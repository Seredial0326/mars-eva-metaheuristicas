"""Download the Navcam photographs listed in a P3 download manifest.

The catalogue builder never downloads. This script is run by hand, after the
count and size in ``download_manifest.json`` have been approved:

    python -m src.viz3d.fetch_rover_photos --manifest <photos>/download_manifest.json \
        --dest <data>/03_curiosity/imagenes_crudas/navcam_p3

Only full 1024 x 1024 JPEGs from the NASA raw-image server are accepted. Files
already present and valid are skipped, so an interrupted run can be repeated.
Each file is written as ``<dest>/sol_<sol>/<imageid>.JPG`` and logged with its
size and SHA-256 in ``<dest>/_download_log.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

ALLOWED_PREFIX = "https://mars.nasa.gov/msl-raw-images/"
IMAGE_ID = re.compile(r"[A-Za-z0-9_-]+")
USER_AGENT = "martian-map-p3/1.0"
SOURCE_SIZE = (1024, 1024)


def check_item(item):
    """Return (image id, url, sol) or raise ValueError for an unusable entry."""
    image_id, url = item.get("id"), item.get("https_url")
    if not isinstance(image_id, str) or not IMAGE_ID.fullmatch(image_id):
        raise ValueError(f"invalid image id: {image_id!r}")
    if not isinstance(url, str) or not url.startswith(ALLOWED_PREFIX):
        raise ValueError(f"URL outside {ALLOWED_PREFIX}: {url!r}")
    if not url.rsplit("/", 1)[-1].upper() == f"{image_id}.JPG".upper():
        raise ValueError(f"URL file name does not match image id {image_id}")
    sol = item.get("sol")
    if isinstance(sol, bool) or not isinstance(sol, int) or sol < 0:
        raise ValueError(f"invalid sol for {image_id}: {sol!r}")
    return image_id, url, sol


def check_jpeg(data):
    """A full Navcam frame: a decodable 1024 x 1024 JPEG."""
    with Image.open(io.BytesIO(data)) as image:
        if image.format != "JPEG":
            raise ValueError(f"not a JPEG ({image.format})")
        if image.size != SOURCE_SIZE:
            raise ValueError(f"size {image.size} is not {SOURCE_SIZE}")
        image.load()


def fetch(url, timeout=60):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def download(manifest_path, dest, pause=0.3, attempts=3, limit=None, opener=fetch):
    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    if manifest.get("download_performed") is not False or not isinstance(manifest.get("items"), list):
        raise ValueError("not a P3 download manifest")
    items = [check_item(item) for item in manifest["items"]]
    if len({image_id for image_id, _, _ in items}) != len(items):
        raise ValueError("manifest repeats an image id")
    if limit is not None:
        items = items[:limit]
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    log = []
    for number, (image_id, url, sol) in enumerate(items, 1):
        path = dest / f"sol_{sol}" / f"{image_id}.JPG"
        entry = {"id": image_id, "sol": sol, "https_url": url, "path": path.relative_to(dest).as_posix()}
        if path.exists():
            try:
                data = path.read_bytes()
                check_jpeg(data)
                log.append({**entry, "status": "already_present", "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest()})
                continue
            except (OSError, ValueError) as error:
                print(f"replacing invalid local file {path.name}: {error}", flush=True)
        error = None
        for attempt in range(1, attempts + 1):
            try:
                data = opener(url)
                check_jpeg(data)
                path.parent.mkdir(exist_ok=True)
                partial = path.with_suffix(".part")
                partial.write_bytes(data)
                partial.replace(path)
                log.append({**entry, "status": "downloaded", "bytes": len(data),
                            "sha256": hashlib.sha256(data).hexdigest(),
                            "downloaded_at": datetime.now(timezone.utc).isoformat(timespec="seconds")})
                error = None
                break
            except Exception as exc:  # network, HTTP or image errors are all retried, then logged
                error = f"{type(exc).__name__}: {exc}"[:250]
                time.sleep(pause * 4 * attempt)
        if error is not None:
            log.append({**entry, "status": "failed", "error": error})
        print(f"[{number}/{len(items)}] {image_id}: {log[-1]['status']}", flush=True)
        time.sleep(pause)
    counts = {status: sum(e["status"] == status for e in log)
              for status in ("downloaded", "already_present", "failed")}
    summary = {"manifest": str(manifest_path), "source": ALLOWED_PREFIX, "counts": counts,
               "bytes": sum(e.get("bytes", 0) for e in log), "items": log}
    (dest / "_download_log.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--dest", required=True, type=Path)
    parser.add_argument("--pause", type=float, default=0.3, help="seconds between requests")
    parser.add_argument("--limit", type=int, help="download only the first N entries")
    args = parser.parse_args(argv)
    summary = download(args.manifest, args.dest, pause=args.pause, limit=args.limit)
    print(json.dumps({"counts": summary["counts"], "bytes": summary["bytes"]}))
    return 1 if summary["counts"]["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
