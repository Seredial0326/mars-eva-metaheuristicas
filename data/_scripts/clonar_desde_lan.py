#!/usr/bin/env python3
"""Copy data/ from another machine on the local network that is running servir_lan.py.

Usage:  python3 data/_scripts/clonar_desde_lan.py http://IP:8000 [--solo 01_terreno 03_curiosity]
            [--excluir 02_imagenes_orbitales/ortofoto_gris_25cm] [--destino PATH]
- Needs only Python 3 (Linux/macOS/Windows). Files already there with the right size are
  skipped, so running the same command again resumes.
- Large files are downloaded in parallel segments (bajar.py); small ones 8 at a time.
- Zips that were extracted on the source are extracted here too, into extraido/<name>/.
- Every path in the source's index is checked once, as text, before any download starts.
- Inside a git checkout, data/README.md and data/_scripts/ are never copied: they come from
  git, and the source's copies may have another version or other line endings. Anywhere
  else they are copied byte for byte like every other file.
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import safe_zip  # noqa: E402

LARGE = 32 << 20  # from this size on, bajar.py downloads the file in parallel segments


def url_for(base, rel):
    return base.rstrip("/") + "/" + "/".join(urllib.parse.quote(s) for s in rel.split("/"))


def fetch_small(base, item, dest):
    """Download one small file to dest through a .tmp file. True if it worked."""
    error = None
    for _ in range(5):
        try:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            with urllib.request.urlopen(url_for(base, item["ruta"]), timeout=60) as r, \
                    open(dest + ".tmp", "wb") as f:
                shutil.copyfileobj(r, f, 1 << 18)
            if os.path.getsize(dest + ".tmp") == item["bytes"]:
                os.replace(dest + ".tmp", dest)
                return True
            error = "size does not match the source"
        except Exception as e:  # network or disk error: try again
            error = e
    print(f"  FAILED {item['ruta']}: {error}")
    return False


def in_git_checkout(path):
    """True if path is inside a git working tree (a .git folder or file in it or a parent)."""
    path = os.path.abspath(path)
    while True:
        if os.path.exists(os.path.join(path, ".git")):
            return True
        parent = os.path.dirname(path)
        if parent == path:
            return False
        path = parent


def from_git(rel):
    """The only paths under data/ that the repository tracks (see .gitignore)."""
    return rel == "README.md" or rel.startswith("_scripts/")


def extract(zpath):
    """Extract a downloaded zip into extraido/<name>/ next to it. Returns the number of failures."""
    out = os.path.join(os.path.dirname(zpath), "extraido", os.path.splitext(os.path.basename(zpath))[0])
    try:
        result = safe_zip.extract(zpath, out)
    except safe_zip.UnsafePath as e:
        sys.exit(f"unsafe path inside {zpath}: {e}")
    if result is None:
        return 0
    safe_zip.report(result, out)
    return len(result.failed)


def main():
    ap = argparse.ArgumentParser(description="Copy data/ from a machine running servir_lan.py.")
    ap.add_argument("base", help="the URL that servir_lan.py printed, e.g. http://192.168.1.20:8000")
    ap.add_argument("--solo", nargs="*", default=[], help="copy only paths that start with these prefixes")
    ap.add_argument("--excluir", nargs="*", default=[], help="skip paths that start with these prefixes")
    ap.add_argument("--destino", default=os.path.dirname(HERE), help="where to copy (default: this repo's data/)")
    ap.add_argument("--conns", type=int, default=8, help="parallel segments per large file")
    a = ap.parse_args()

    with urllib.request.urlopen(a.base.rstrip("/") + "/_indice.json", timeout=60) as r:
        items = json.load(r)["archivos"]
    items = [i for i in items if (not a.solo or any(i["ruta"].startswith(p) for p in a.solo))
             and not any(i["ruta"].startswith(p) for p in a.excluir)]

    root = os.path.abspath(a.destino)
    if in_git_checkout(root):
        n = sum(from_git(i["ruta"]) for i in items)
        items = [i for i in items if not from_git(i["ruta"])]
        if n:
            print(f"{n} files not copied because they come from git (README.md, _scripts/)")

    # Every path is checked here, once and as text, before any thread starts. The threads
    # only look up the result, so folders being created meanwhile cannot change the answer.
    dest = {}
    for i in items:
        try:
            parts = safe_zip.split_name(i["ruta"])
            path = safe_zip.inside(root, parts)
        except safe_zip.UnsafePath:
            sys.exit("unsafe path in the source's index: " + i["ruta"])
        why = safe_zip.name_problem(parts)
        if why:
            print(f"  skipped {i['ruta']} ({why})")
            continue
        dest[i["ruta"]] = safe_zip.long_path(path)
    items = [i for i in items if i["ruta"] in dest]

    def done(i):
        d = dest[i["ruta"]]
        return os.path.isfile(d) and os.path.getsize(d) == i["bytes"]

    missing = [i for i in items if not done(i)]
    print(f"{len(items)} files on the source ({sum(i['bytes'] for i in items) / 1e9:.2f} GB); "
          f"{len(missing)} missing ({sum(i['bytes'] for i in missing) / 1e9:.2f} GB)")
    failures = 0
    small = [i for i in missing if i["bytes"] < LARGE]
    with ThreadPoolExecutor(8) as ex:
        failures += sum(not ok for ok in ex.map(lambda i: fetch_small(a.base, i, dest[i["ruta"]]), small))
    for i in [i for i in missing if i["bytes"] >= LARGE]:
        os.makedirs(os.path.dirname(dest[i["ruta"]]), exist_ok=True)
        print("large:", i["ruta"], flush=True)
        cmd = [sys.executable, "-I", os.path.join(HERE, "bajar.py"), url_for(a.base, i["ruta"]),
               dest[i["ruta"]], "--conns", str(a.conns)]
        if subprocess.call(cmd) != 0:
            failures += 1
    for i in items:
        if i.get("extraer") and os.path.exists(dest[i["ruta"]]):
            failures += extract(safe_zip.plain_path(dest[i["ruta"]]))
    print("DONE" if not failures else f"FINISHED WITH {failures} FAILURES (run the same command again)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
