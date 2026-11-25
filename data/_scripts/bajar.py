#!/usr/bin/env python3
"""Descarga reanudable por segmentos en paralelo (solo biblioteca estándar).

Uso:  python3 data/_scripts/bajar.py URL DESTINO [--conns 8] [--md5 HEX]
- Parte el archivo en segmentos y baja varios a la vez (cada conexión rinde ~1 MB/s en S3 de USGS).
- Si se interrumpe, volver a ejecutar el mismo comando continúa donde quedó.
- Al final une los segmentos, comprueba el tamaño y, si se da --md5, el checksum.
"""
import argparse, hashlib, os, sys, threading, time, urllib.request

def head(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": "curl/8"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return int(r.headers["Content-Length"]), r.url

def seg(url, path, a, b, prog, i):
    while True:
        have = os.path.getsize(path) if os.path.exists(path) else 0
        if have >= b - a + 1:
            prog[i] = have; return
        try:
            req = urllib.request.Request(url, headers={"Range": f"bytes={a+have}-{b}", "User-Agent": "curl/8"})
            with urllib.request.urlopen(req, timeout=90) as r, open(path, "ab") as f:
                if r.status != 206: raise RuntimeError(f"status {r.status}")
                while True:
                    chunk = r.read(1 << 18)
                    if not chunk: break
                    f.write(chunk); have += len(chunk); prog[i] = have
        except Exception as e:
            print(f"  seg {i}: reintento ({e})", flush=True); time.sleep(5)

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("url"); ap.add_argument("dest")
    ap.add_argument("--conns", type=int, default=8); ap.add_argument("--md5")
    a = ap.parse_args()
    if os.path.exists(a.dest):
        print("ya existe:", a.dest); return check(a)
    size, url = head(a.url)
    n = max(1, min(a.conns, size // (8 << 20) or 1)); step = -(-size // n)
    parts = [(i * step, min(size, (i + 1) * step) - 1) for i in range(n)]
    prog = [0] * n; ths = []
    for i, (s, e) in enumerate(parts):
        t = threading.Thread(target=seg, args=(url, f"{a.dest}.part{i}", s, e, prog, i), daemon=True); t.start(); ths.append(t)
    t0 = time.time(); last = sum(os.path.getsize(f"{a.dest}.part{i}") if os.path.exists(f"{a.dest}.part{i}") else 0 for i in range(n))
    tick = time.time()
    while any(t.is_alive() for t in ths):
        time.sleep(0.5)
        if time.time() - tick < 30: continue
        tick = time.time(); done = sum(prog)
        print(f"[{time.strftime('%H:%M:%S')}] {done/1e6:,.0f}/{size/1e6:,.0f} MB ({100*done/size:.1f}%)  {(done-last)/30/1e6:.2f} MB/s", flush=True); last = done
    with open(a.dest + ".tmp", "wb") as out:
        for i in range(n):
            with open(f"{a.dest}.part{i}", "rb") as f:
                while True:
                    c = f.read(1 << 22)
                    if not c: break
                    out.write(c)
    if os.path.getsize(a.dest + ".tmp") != size:
        sys.exit(f"ERROR: tamaño {os.path.getsize(a.dest + '.tmp')} != {size}")
    os.replace(a.dest + ".tmp", a.dest)
    for i in range(n): os.remove(f"{a.dest}.part{i}")
    print(f"OK {a.dest} {size} bytes en {time.time()-t0:.0f}s", flush=True); check(a)

def check(a):
    if a.md5:
        h = hashlib.md5()
        with open(a.dest, "rb") as f:
            for c in iter(lambda: f.read(1 << 22), b""): h.update(c)
        print("md5", "OK" if h.hexdigest() == a.md5 else f"NO COINCIDE ({h.hexdigest()})", flush=True)

main()
