"""Tests for data/_scripts/safe_zip.py: path checks, long paths and zip extraction.

Run with pytest, or without it: python -m unittest discover -s tests/data_scripts
"""
import os
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "data" / "_scripts"))

import safe_zip  # noqa: E402
from safe_zip import UnsafePath  # noqa: E402

WINDOWS = os.name == "nt"


def deep_name(total, root):
    """A relative member name that makes root/<name> longer than `total` characters."""
    parts, length = [], len(str(root)) + 1
    while length <= total:
        part = f"folder_{len(parts):02d}_" + "x" * 40
        parts.append(part)
        length += len(part) + 1
    return "/".join(parts + ["image_0001.png.aux.xml"])


class SplitName(unittest.TestCase):
    def test_normal_names(self):
        self.assertEqual(safe_zip.split_name("a/b/c.txt"), ["a", "b", "c.txt"])
        self.assertEqual(safe_zip.split_name("a\\b\\c.txt"), ["a", "b", "c.txt"])
        self.assertEqual(safe_zip.split_name("./a//b/"), ["a", "b"])
        self.assertEqual(safe_zip.split_name("./"), [])
        self.assertEqual(safe_zip.split_name("a/file.txt:stream"), ["a", "file.txt:stream"])

    def test_names_that_leave_the_folder(self):
        for name in ["/etc/passwd", "\\\\server\\share\\x", "../x", "a/../../x", "a\\..\\..\\x",
                     "C:/x", "C:x", "a/D:/evil.txt", "a/z:evil.txt", "a\x00b"]:
            with self.subTest(name=name), self.assertRaises(UnsafePath):
                safe_zip.split_name(name)


class Inside(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def test_joins_under_root(self):
        root = os.path.join(self.tmp, "dest")
        self.assertEqual(safe_zip.inside(root, ["a", "b.txt"]), os.path.join(os.path.abspath(root), "a", "b.txt"))

    def test_same_answer_whether_folders_exist_or_not(self):
        root = os.path.join(self.tmp, "dest")
        parts = ["06_bouldernet", "zenodo", "file.zip"]
        before = safe_zip.inside(root, parts)
        os.makedirs(os.path.join(root, *parts[:-1]))
        self.assertEqual(safe_zip.inside(root, parts), before)
        self.assertEqual(safe_zip.inside(safe_zip.long_path(root), parts), before)

    def test_root_itself_is_refused(self):
        with self.assertRaises(UnsafePath):
            safe_zip.inside(self.tmp, [])

    @unittest.skipUnless(WINDOWS, "drive letters only mean something on Windows")
    def test_other_drive_is_refused(self):
        # os.path.join would give D:x here; split_name refuses it first, this is the second line.
        with self.assertRaises(UnsafePath):
            safe_zip.inside(self.tmp, ["a", "D:", "x"])


class NameProblem(unittest.TestCase):
    def test_windows_names(self):
        self.assertIsNone(safe_zip.name_problem(["a", "b.txt"], windows=True))
        self.assertIsNone(safe_zip.name_problem(["console.txt", "nullable"], windows=True))
        for parts in (["a", "x."], ["a ", "b"], ["CON"], ["nul.txt"], ["COM1.log"], ["a?b"],
                      ["file.txt:stream"], ["tab\there"]):
            with self.subTest(parts=parts):
                self.assertIsNotNone(safe_zip.name_problem(parts, windows=True))

    def test_no_restrictions_elsewhere(self):
        self.assertIsNone(safe_zip.name_problem(["CON", "x."], windows=False))


class LongPath(unittest.TestCase):
    def test_prefix(self):
        path = os.path.abspath("some/file.txt")
        if WINDOWS:
            self.assertEqual(safe_zip.long_path(path), "\\\\?\\" + path)
            self.assertEqual(safe_zip.long_path("\\\\host\\share\\f"), "\\\\?\\UNC\\host\\share\\f")
            self.assertEqual(safe_zip.plain_path("\\\\?\\UNC\\host\\share\\f"), "\\\\host\\share\\f")
        else:
            self.assertEqual(safe_zip.long_path(path), path)
        self.assertEqual(safe_zip.long_path(safe_zip.long_path(path)), safe_zip.long_path(path))
        self.assertEqual(safe_zip.plain_path(safe_zip.long_path(path)), path)


class Extract(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(safe_zip.long_path(self.tmp), True))
        self.out = os.path.join(self.tmp, "extraido", "dataset")
        self.long = deep_name(300, self.out)
        self.zpath = os.path.join(self.tmp, "dataset.zip")

    def make_zip(self, members):
        with zipfile.ZipFile(self.zpath, "w") as z:
            for name, data in members:
                z.writestr(name, data)

    def test_long_paths_junk_and_resume(self):
        self.make_zip([("boulder2024/", b""), ("boulder2024/labels/a.txt", b"0 0.5 0.5"),
                       (self.long, b"<xml/>"),
                       ("boulder2024/jupyter-notebooks/.ipynb_checkpoints/", b""),
                       ("boulder2024/jupyter-notebooks/.ipynb_checkpoints/nb-checkpoint.ipynb", b"{}"),
                       ("__MACOSX/boulder2024/._a.txt", b"junk")])
        self.assertGreater(len(os.path.join(self.out, *self.long.split("/"))), 260)
        r = safe_zip.extract(self.zpath, self.out)
        self.assertEqual((r.files, r.failed), (2, []))
        self.assertEqual(sorted(n for n, _ in r.skipped),
                         ["__MACOSX/boulder2024/._a.txt",
                          "boulder2024/jupyter-notebooks/.ipynb_checkpoints/nb-checkpoint.ipynb"])
        with open(safe_zip.long_path(os.path.join(self.out, *self.long.split("/"))), "rb") as f:
            self.assertEqual(f.read(), b"<xml/>")
        self.assertFalse(os.path.exists(os.path.join(self.out, "__MACOSX")))
        self.assertIsNone(safe_zip.extract(self.zpath, self.out))  # finished: nothing to do

        # Resume: an interrupted run left no marker and lost one file.
        os.remove(os.path.join(self.out, safe_zip.DONE_MARKER))
        os.remove(os.path.join(self.out, "boulder2024", "labels", "a.txt"))
        r = safe_zip.extract(self.zpath, self.out)
        self.assertEqual((r.files, r.failed), (2, []))
        with open(os.path.join(self.out, "boulder2024", "labels", "a.txt"), "rb") as f:
            self.assertEqual(f.read(), b"0 0.5 0.5")

    def test_unsafe_member_extracts_nothing(self):
        for bad in ("../evil.txt", "ok/../../evil.txt", "a/D:/evil.txt", "/abs.txt"):
            with self.subTest(member=bad):
                self.make_zip([("first.txt", b"1"), (bad, b"x")])
                with self.assertRaises(UnsafePath):
                    safe_zip.extract(self.zpath, self.out)
                self.assertFalse(os.path.exists(self.out))
                self.assertFalse(os.path.exists(os.path.join(self.tmp, "evil.txt")))

    @unittest.skipUnless(WINDOWS, "only Windows refuses these names")
    def test_names_windows_cannot_store_are_skipped(self):
        self.make_zip([("ok.txt", b"1"), ("dir./x.txt", b"2"), ("a/b?.txt", b"3"), ("a/CON", b"4")])
        r = safe_zip.extract(self.zpath, self.out)
        self.assertEqual((r.files, r.failed), (1, []))
        self.assertEqual(sorted(n for n, _ in r.skipped), ["a/CON", "a/b?.txt", "dir./x.txt"])
        self.assertEqual(sorted(os.listdir(self.out)), [safe_zip.DONE_MARKER, "ok.txt"])


if __name__ == "__main__":
    unittest.main()
