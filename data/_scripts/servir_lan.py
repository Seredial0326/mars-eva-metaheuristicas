#!/usr/bin/env python3
"""Sirve data/ por la red local (solo lectura) para que las otras máquinas la copien rápido.

En la máquina que YA tiene los datos:   python3 data/_scripts/servir_lan.py            (puerto 8000)
En cada máquina que los necesita:       python3 data/_scripts/clonar_desde_lan.py http://IP:8000

Soporta descargas por rangos (reanudables y en paralelo). Cualquiera en la misma red puede leer
data/ mientras esté encendido: son datos públicos de NASA, pero apágalo (Ctrl+C) al terminar.
"""
import json, os, re, socket, sys
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

DATA = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OMITIR_DIRS = {"_logs", "extraido", ".git", "__pycache__"}

def indice():
    out = []
    for raiz, dirs, files in os.walk(DATA):
        dirs[:] = sorted(d for d in dirs if d not in OMITIR_DIRS)
        for f in sorted(files):
            if f.endswith((".tmp", ".DS_Store")) or re.search(r"\.part\d+$", f): continue
            p = os.path.join(raiz, f); rel = os.path.relpath(p, DATA).replace(os.sep, "/")
            item = {"ruta": rel, "bytes": os.path.getsize(p)}
            if f.endswith(".zip") and os.path.isdir(os.path.join(raiz, "extraido")): item["extraer"] = True
            out.append(item)
    return json.dumps({"archivos": out}).encode()

class H(SimpleHTTPRequestHandler):
    def log_message(self, *a): pass
    def send_head(self):
        self._resto = None
        if self.path.split("?")[0] == "/_indice.json":
            import io; b = indice()
            self.send_response(200); self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(b))); self.end_headers(); return io.BytesIO(b)
        ruta = self.translate_path(self.path); rng = self.headers.get("Range")
        if not rng or not os.path.isfile(ruta): return super().send_head()
        m = re.match(r"bytes=(\d+)-(\d*)$", rng.strip()); size = os.path.getsize(ruta)
        if not m or int(m[1]) >= size:
            self.send_error(416, "Rango no válido"); return None
        a = int(m[1]); b = min(int(m[2]) if m[2] else size - 1, size - 1)
        f = open(ruta, "rb"); f.seek(a)
        self.send_response(206); self.send_header("Content-Type", "application/octet-stream")
        self.send_header("Accept-Ranges", "bytes"); self.send_header("Content-Range", f"bytes {a}-{b}/{size}")
        self.send_header("Content-Length", str(b - a + 1)); self.end_headers(); self._resto = b - a + 1
        return f
    def copyfile(self, src, out):
        if getattr(self, "_resto", None) is None: return super().copyfile(src, out)
        n = self._resto
        while n > 0:
            c = src.read(min(1 << 20, n))
            if not c: break
            out.write(c); n -= len(c)

def main():
    puerto = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    host = sys.argv[2] if len(sys.argv) > 2 else "0.0.0.0"
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM); s.connect(("10.255.255.255", 1)); ip = s.getsockname()[0]; s.close()
    except OSError: ip = "IP-de-esta-maquina"
    srv = ThreadingHTTPServer((host, puerto), lambda *a, **k: H(*a, directory=DATA, **k))
    print(f"Sirviendo {DATA}\nEn las otras máquinas:  python3 data/_scripts/clonar_desde_lan.py http://{ip}:{puerto}\nCtrl+C para apagar.", flush=True)
    try: srv.serve_forever()
    except KeyboardInterrupt: pass

main()
