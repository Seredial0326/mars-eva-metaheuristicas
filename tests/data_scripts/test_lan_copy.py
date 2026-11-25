"""End-to-end test of the LAN copy: servir_lan.py serves a small data/ folder on 127.0.0.1
and clonar_desde_lan.py copies it, into a git checkout and into a plain folder.

Run with pytest, or without it: python -m unittest discover -s tests/data_scripts
"""
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import zipfile
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "data" / "_scripts"
sys.path.insert(0, str(SCRIPTS))

import safe_zip  # noqa: E402
from clonar_desde_lan import in_git_checkout  # noqa: E402

ZIP_DIR = "06_bouldernet/zenodo_14250874_ampliado_2024"
CHECKPOINT = "boulder2024/jupyter-notebooks/.ipynb_checkpoints/nb-checkpoint.ipynb"
LARGE_BYTES = (32 << 20) + 123  # just over the size that clonar_desde_lan.py hands to bajar.py


def write(root, rel, data):
    path = safe_zip.long_path(os.path.join(root, *rel.split("/")))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(data)


def read(root, rel):
    with open(safe_zip.long_path(os.path.join(root, *rel.split("/"))), "rb") as f:
        return f.read()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class LanCopy(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.mkdtemp()
        cls.src = os.path.join(cls.tmp, "src", "data")
        write(cls.src, "_scripts/servir_lan.py", (SCRIPTS / "servir_lan.py").read_bytes())
        write(cls.src, "_scripts/extra.py", b"print('only on the source')\n")
        write(cls.src, "README.md", b"# data\nLF line endings, as on macOS\n")
        cls.small = {f"01_terreno/d{k % 12}/sub{k % 5}/f{k}.txt": bytes([65 + k % 26]) * k for k in range(150)}
        for rel, data in cls.small.items():
            write(cls.src, rel, data)
        cls.large = os.urandom(1 << 16) * (LARGE_BYTES >> 16) + b"x" * (LARGE_BYTES % (1 << 16))
        write(cls.src, "01_terreno/dem_big.tif", cls.large)
        # Member deep enough that <destination>/.../extraido/dataset/<member> passes 260 characters.
        cls.deep = "boulder2024/" + "/".join(f"level_{k}_" + "y" * 40 for k in range(5)) + "/image.png.aux.xml"
        os.makedirs(os.path.join(cls.src, *ZIP_DIR.split("/"), "extraido"))  # marks the zip to be extracted
        with zipfile.ZipFile(os.path.join(cls.src, *ZIP_DIR.split("/"), "dataset.zip"), "w") as z:
            z.writestr("boulder2024/labels/a.txt", b"0 0.5 0.5")
            z.writestr(cls.deep, b"<xml/>")
            z.writestr(CHECKPOINT, b"{}")
        cls.port = free_port()
        cls.url = f"http://127.0.0.1:{cls.port}"
        cls.server = subprocess.Popen([sys.executable, "-I", os.path.join(cls.src, "_scripts", "servir_lan.py"),
                                       str(cls.port), "127.0.0.1"],
                                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + "/_indice.json", timeout=1).close()
                break
            except OSError:
                time.sleep(0.1)
        else:
            cls.tearDownClass()
            raise RuntimeError("servir_lan.py did not start")

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(10)
        shutil.rmtree(safe_zip.long_path(cls.tmp), ignore_errors=True)

    def clone(self, dest):
        p = subprocess.run([sys.executable, "-I", str(SCRIPTS / "clonar_desde_lan.py"), self.url, "--destino", dest],
                           capture_output=True, text=True, timeout=300)
        return p.returncode, p.stdout + p.stderr

    def check_data(self, dest):
        for rel, data in self.small.items():
            self.assertEqual(read(dest, rel), data, rel)
        self.assertEqual(read(dest, "01_terreno/dem_big.tif"), self.large)
        out = os.path.join(dest, *ZIP_DIR.split("/"), "extraido", "dataset")
        self.assertGreater(len(os.path.join(out, *self.deep.split("/"))), 260)
        self.assertEqual(read(out, self.deep), b"<xml/>")
        self.assertEqual(read(out, "boulder2024/labels/a.txt"), b"0 0.5 0.5")
        self.assertFalse(os.path.exists(safe_zip.long_path(os.path.join(out, *CHECKPOINT.split("/")))))

    def test_into_git_checkout_keeps_repo_files(self):
        repo = os.path.join(self.tmp, "checkout")
        os.makedirs(os.path.join(repo, ".git"))
        dest = os.path.join(repo, "data")
        write(dest, "README.md", b"# data\r\nCRLF line endings, as git writes them on Windows\r\n")
        before = read(dest, "README.md")
        code, log = self.clone(dest)
        self.assertEqual(code, 0, log)
        self.assertIn("3 files not copied because they come from git", log)
        self.assertIn("skipped: " + CHECKPOINT, log)
        self.check_data(dest)
        self.assertEqual(read(dest, "README.md"), before)
        self.assertFalse(os.path.exists(os.path.join(dest, "_scripts")))

        code, log = self.clone(dest)  # second run: nothing left to do
        self.assertEqual(code, 0, log)
        self.assertIn("0 missing", log)
        self.assertNotIn("extracted into", log)

    def test_into_plain_folder_copies_byte_for_byte(self):
        # Deep destination: the files copied over the LAN pass 260 characters too.
        dest = os.path.join(self.tmp, "plain", *("z" * 50 for _ in range(4)), "data")
        if in_git_checkout(dest):
            self.skipTest("the temporary folder is inside a git checkout")
        if safe_zip.IS_WINDOWS:
            self.assertGreater(len(os.path.join(dest, "01_terreno", "d0", "sub0", "f0.txt")), 260)
        code, log = self.clone(dest)
        self.assertEqual(code, 0, log)
        self.check_data(dest)
        self.assertEqual(read(dest, "README.md"), read(self.src, "README.md"))
        self.assertEqual(read(dest, "_scripts/extra.py"), read(self.src, "_scripts/extra.py"))


if __name__ == "__main__":
    unittest.main()
