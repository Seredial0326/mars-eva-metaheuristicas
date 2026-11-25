"""Path checks and zip extraction shared by clonar_desde_lan.py and descargar_todo.py.

- Paths are checked as text, never against the disk, so the answer does not depend on which
  folders exist yet (clonar_desde_lan.py creates folders from 8 threads at once).
- A name that would land outside the destination raises UnsafePath: absolute paths, "..",
  and drive letters anywhere in the name. On Windows "a/D:/x" would otherwise resolve to D:\\x.
- On Windows, names the file system cannot store as they are (characters such as ":" or "?",
  a trailing dot or space, device names such as CON or NUL) are skipped and reported.
- On Windows every path gets the extended-length prefix (\\\\?\\), so paths longer than
  260 characters work even when LongPathsEnabled is off.
- Extraction skips junk that is never needed (.ipynb_checkpoints, __MACOSX) and reports it.
- Extraction is resumable: files already in place with the right size are kept, and a zip
  only counts as done once the marker file .extraccion_completa exists.
"""
import collections
import os
import re
import shutil
import zipfile

IS_WINDOWS = os.name == "nt"
JUNK_DIRS = {".ipynb_checkpoints", "__MACOSX"}
# Same marker name as the first version of this module, so finished folders stay finished.
DONE_MARKER = ".extraccion_completa"

_DRIVE = re.compile(r"^[A-Za-z]:")
_WINDOWS_BAD_CHARS = set('<>:"|?*').union(chr(c) for c in range(32))
_WINDOWS_DEVICES = {"CON", "PRN", "AUX", "NUL", "CONIN$", "CONOUT$"} | {
    f"{kind}{n}" for kind in ("COM", "LPT") for n in "123456789"}

# files: files written or already in place. skipped, failed: lists of (member name, reason).
Result = collections.namedtuple("Result", "files skipped failed")


class UnsafePath(ValueError):
    """A path that would land outside the destination folder."""


def plain_path(path):
    """Absolute path without the Windows extended-length prefix (for checks and messages)."""
    if IS_WINDOWS and path.startswith("\\\\?\\"):
        path = "\\\\" + path[8:] if path.upper().startswith("\\\\?\\UNC\\") else path[4:]
    return os.path.abspath(path)


def long_path(path):
    """Absolute path; on Windows, with the prefix that allows more than 260 characters."""
    path = plain_path(path)
    if IS_WINDOWS:
        return "\\\\?\\UNC\\" + path[2:] if path.startswith("\\\\") else "\\\\?\\" + path
    return path


def split_name(name):
    """Split a relative name (zip member or LAN index entry) into its components.

    Raises UnsafePath for absolute names, "..", NUL characters, or a drive letter in any
    component. Returns [] for the root itself ("", ".", "./").
    """
    text = name.replace("\\", "/")
    parts = [p for p in text.split("/") if p not in ("", ".")]
    if text.startswith("/") or "\x00" in text or any(p == ".." or _DRIVE.match(p) for p in parts):
        raise UnsafePath(name)
    return parts


def inside(root, parts):
    """Join parts under root and check, as text, that the result stays inside root.

    Raises UnsafePath otherwise. Returns the plain absolute path.
    """
    root = plain_path(root)
    path = os.path.normpath(os.path.join(root, *parts))
    try:
        common = os.path.commonpath([root, path])
    except ValueError:  # different drives on Windows
        common = None
    if not parts or common is None or os.path.normcase(common) != os.path.normcase(root):
        raise UnsafePath("/".join(parts))
    return path


def windows_problem(part):
    """Why Windows cannot store this file or folder name as it is, or None."""
    if any(c in _WINDOWS_BAD_CHARS for c in part):
        return "character not allowed on Windows"
    if part[-1] in ". ":
        return "ends with a dot or a space"
    if part.split(".")[0].rstrip(" ").upper() in _WINDOWS_DEVICES:
        return "reserved device name on Windows"
    return None


def name_problem(parts, windows=IS_WINDOWS):
    """Why this system cannot store the path as it is (the caller skips it), or None."""
    if windows:
        for part in parts:
            why = windows_problem(part)
            if why:
                return f"{why}: {part!r}"
    return None


def extract(zpath, out):
    """Extract zpath into out. Returns None if an earlier run already finished, else a Result.

    Every member name is checked before anything is written. Raises UnsafePath if one
    would land outside out; nothing is extracted in that case.
    """
    root = plain_path(out)
    marker = long_path(os.path.join(root, DONE_MARKER))
    if os.path.exists(marker):
        return None
    todo, skipped, failed, files = [], [], [], 0
    with zipfile.ZipFile(long_path(zpath)) as z:
        for m in z.infolist():
            parts = split_name(m.filename)
            if not parts:
                continue
            path = inside(root, parts)
            why = ("notebook checkpoint or macOS metadata" if JUNK_DIRS.intersection(parts)
                   else name_problem(parts))
            if why:
                if not m.is_dir():  # report files only; their folder is implied
                    skipped.append((m.filename, why))
                continue
            todo.append((m, long_path(path)))
        for m, target in todo:
            try:
                if m.is_dir():
                    os.makedirs(target, exist_ok=True)
                    continue
                if os.path.isfile(target) and os.path.getsize(target) == m.file_size:
                    files += 1
                    continue
                os.makedirs(os.path.dirname(target), exist_ok=True)
                with z.open(m) as src, open(target + ".tmp", "wb") as dst:
                    shutil.copyfileobj(src, dst, 1 << 20)
                os.replace(target + ".tmp", target)
                files += 1
            except (OSError, zipfile.BadZipFile) as e:
                failed.append((m.filename, str(e)))
    if not failed:
        os.makedirs(long_path(root), exist_ok=True)
        open(marker, "w").close()
    return Result(files, skipped, failed)


def report(result, out, limit=10):
    """Print a summary of one extraction, naming the skipped and failed members."""
    print(f"  extracted into {out}: {result.files} files, "
          f"{len(result.skipped)} skipped, {len(result.failed)} failed")
    for label, items in (("skipped", result.skipped), ("FAILED", result.failed)):
        for name, why in items[:limit]:
            print(f"    {label}: {name} ({why})")
        if len(items) > limit:
            print(f"    ... and {len(items) - limit} more {label}")
