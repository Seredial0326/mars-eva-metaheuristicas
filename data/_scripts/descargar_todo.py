#!/usr/bin/env python3
"""Get data/ ready on any machine by downloading the large files straight from their source.

Usage (from the repo root; Linux/macOS/Windows; only standard Python 3):
    python3 data/_scripts/descargar_todo.py --perfil terreno        # DEM + color orthophoto (~4.9 GB)
    python3 data/_scripts/descargar_todo.py --perfil terreno dl     # + BoulderNet (and AI4Mars if it is in the manifest)
    python3 data/_scripts/descargar_todo.py --perfil todo           # + optional files (gray orthophoto 24 GB, raw data 9.4 GB)
    python3 data/_scripts/descargar_todo.py --perfil todo --solo-verificar

- Reads data/_scripts/manifiesto.json. Files that already exist with the right size are skipped.
- Resumable: if it stops, run the same command again.
- Zips marked "descomprimir" are extracted into an extraido/ folder next to the zip (safe_zip.py).
Small files (waypoints, weather, indexes, papers) are NOT downloaded here: they travel in the
light kit (armar_kit_ligero.py).
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import safe_zip  # noqa: E402


def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def extract(zpath):
    """Extract a zip into extraido/<name>/ next to it. Returns the number of failures."""
    out = os.path.join(os.path.dirname(zpath), "extraido", os.path.splitext(os.path.basename(zpath))[0])
    try:
        result = safe_zip.extract(zpath, out)
    except safe_zip.UnsafePath as e:
        sys.exit(f"unsafe path inside {zpath}: {e}")
    if result is None:
        return 0
    safe_zip.report(result, os.path.relpath(out, DATA))
    return len(result.failed)


def main():
    ap = argparse.ArgumentParser(description="Download the large data files listed in manifiesto.json.")
    ap.add_argument("--perfil", nargs="+", default=["terreno"], help="terreno, dl, opcional or todo")
    ap.add_argument("--conns", type=int, default=8, help="parallel segments per file")
    ap.add_argument("--solo-verificar", action="store_true", help="only check sizes and md5; download nothing")
    a = ap.parse_args()
    with open(os.path.join(HERE, "manifiesto.json"), encoding="utf-8") as f:
        items = json.load(f)["archivos"]
    failures = 0
    for it in items:
        if "todo" not in a.perfil and it["perfil"] not in a.perfil:
            continue
        dest = os.path.join(DATA, *it["dest"].split("/"))
        ok = os.path.exists(dest) and os.path.getsize(dest) == it["bytes"]
        print(f"[{it['perfil']}] {it['dest']}  ({it['bytes'] / 1e9:.2f} GB)  ->", "present" if ok else "missing")
        if a.solo_verificar:
            if ok and it.get("md5"):
                good = md5(dest) == it["md5"]
                print("  md5", "OK" if good else "DOES NOT MATCH")
                failures += not good
            failures += not ok
            continue
        if not ok:
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            cmd = [sys.executable, "-I", os.path.join(HERE, "bajar.py"), it["url"], dest, "--conns", str(a.conns)]
            if it.get("md5"):
                cmd += ["--md5", it["md5"]]
            if subprocess.call(cmd) != 0 or not os.path.exists(dest):
                failures += 1
                continue
        if it.get("descomprimir"):
            failures += extract(dest)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
