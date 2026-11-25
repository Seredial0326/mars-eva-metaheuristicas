"""Build the offline Navcam catalogue; never download imagery.

Run ``python -m src.viz3d.build_rover_photos --help`` from the repository root.
All five source/output paths are explicit. The root catalog.json is the atomic
commit pointer: it references an immutable generation's assets and reports.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import tempfile
from collections import Counter, defaultdict
from itertools import combinations

import numpy as np
from PIL import Image
import rasterio


SCHEMA_VERSION = 1
GROUP_RADIUS_M = 10.0
POSITION_TOLERANCE_M = 0.01
# The API rounds quaternion components to 6 decimals: about 2e-6 rad of angle noise.
ATTITUDE_TIE_RAD = 1e-5
CONTRACT = Path(__file__).resolve().parents[2] / "docs/contracts/grid.json"


class RejectedPhoto(ValueError):
    """A source record cannot be used without guessing its meaning."""


def finite(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("nonfinite number")
    return number


def integer(value):
    number = finite(value)
    if number != int(number):
        raise ValueError("nonintegral identifier")
    return int(number)


def quaternion(value):
    if isinstance(value, str):
        value = value.strip().strip("()").split(",")
    q = np.asarray([finite(v) for v in value], dtype=float)
    if q.shape != (4,) or np.linalg.norm(q) < 1e-10:
        raise ValueError("invalid quaternion")
    return q / np.linalg.norm(q)


def row_position(row):
    return tuple(finite(row[k]) for k in ("easting", "northing", "elevation"))


def row_order(row):
    return (integer(row["site"]), integer(row["drive"]), integer(row["pose"]),
            finite(row["sclk"]), row_position(row),
            tuple(str(row.get(k, "")) for k in sorted(row)))


def index_item_order(item):
    """Image ID first, then the full record, so equal inputs always sort equally."""
    image_id = item.get("imageid") if isinstance(item, dict) else None
    return str(image_id), json.dumps(item, sort_keys=True, default=str)


def load_places(path):
    """Only the agreed original PLACES interpolated localization is accepted."""
    path = Path(path)
    if path.name.lower() != "localized_interp.csv":
        raise ValueError("PLACES must be localized_interp.csv; _demv2 is not accepted")
    rows = defaultdict(list)
    counts = Counter()
    with path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if row.get("frame", "").strip() != "ROVER":
                counts["non_rover"] += 1
                continue
            try:
                key = integer(row["site"]), integer(row["drive"])
                row_order(row)
                quaternion([row[k] for k in ("quat_s", "quat_v1", "quat_v2", "quat_v3")])
            except (ValueError, TypeError, KeyError):
                counts["malformed_rover"] += 1
                continue
            rows[key].append(row)
            counts["valid_rover"] += 1
    for key in rows:
        rows[key].sort(key=row_order)
    counts["repeated_rover_keys"] = sum(len(v) > 1 for v in rows.values())
    return rows, dict(counts)


def resolve_place(item, rows):
    """Pick the PLACES pose whose attitude matches the image; never guess a position.

    Rows of one site/drive share their ``sclk`` (the earliest clock of the
    site/drive, pose ignored: PLACES SIS 4.4.1), so the clock cannot separate
    poses. Rows whose attitude ties within the API's 6-decimal rounding must
    agree in position; then the highest pose is kept, the SIS's rule of thumb.
    """
    if not rows:
        raise RejectedPhoto("missing_places_join")
    try:
        q = quaternion(item["attitude"])
        ranked = []
        for row in rows:
            other = quaternion([row[k] for k in ("quat_s", "quat_v1", "quat_v2", "quat_v3")])
            ranked.append((2 * math.acos(float(np.clip(abs(np.dot(q, other)), 0, 1))), row))
    except (ValueError, TypeError, KeyError):
        raise RejectedPhoto("malformed_join_attitude") from None
    best_angle = min(r[0] for r in ranked)
    contenders = [r for r in ranked if r[0] <= best_angle + ATTITUDE_TIE_RAD]
    # Every pair must agree: two rows can each be near a third yet far from each other.
    positions = [row_position(r[1]) for r in contenders]
    spread = max((math.dist(a, b) for a, b in combinations(positions, 2)), default=0.0)
    if spread > POSITION_TOLERANCE_M:
        raise RejectedPhoto("ambiguous_places_positions")
    angle, row = max(contenders, key=lambda r: row_order(r[1]))
    return row, {"candidate_rows": len(rows), "attitude_residual_deg": math.degrees(angle),
                 "tied_rows": len(contenders), "tied_position_spread_m": spread,
                 "method": "attitude_then_highest_colocated_pose"}


def in_bbox(x, y, bbox):
    return bbox["xmin"] <= x < bbox["xmax"] and bbox["ymin"] <= y < bbox["ymax"]


def group_and_select(candidates, radius=GROUP_RADIUS_M):
    """Greedy stable representatives, without transitive/chained clustering."""
    if not math.isfinite(radius) or radius <= 0 or radius > 10:
        raise ValueError("group radius must be in (0, 10] metres")
    groups = []
    for candidate in sorted(candidates, key=lambda c: (row_order(c["_row"]), c["id"])):
        position = row_position(candidate["_row"])
        matches = [(math.dist(position[:2], g["representative"]["xy"]), g) for g in groups]
        matches = [(d, g) for d, g in matches if d <= radius]
        if matches:
            _, group = min(matches, key=lambda pair: (pair[0], pair[1]["id"]))
        else:
            group = {"id": f"stop_{len(groups):04d}",
                     "representative": {"xy": list(position[:2]), "z": position[2],
                                        "site": integer(candidate["_row"]["site"]),
                                        "drive": integer(candidate["_row"]["drive"]),
                                        "places_pose": integer(candidate["_row"]["pose"])},
                     "_candidates": []}
            groups.append(group)
        candidate["group_id"] = group["id"]
        candidate["distance_to_representative_m"] = math.dist(position[:2], group["representative"]["xy"])
        candidate["quadrant"] = int((candidate["pose"]["heading"] % (2 * math.pi)) / (math.pi / 2))
        group["_candidates"].append(candidate)
    selected = []
    for group in groups:
        sectors = defaultdict(list)
        for candidate in group.pop("_candidates"):
            sectors[candidate["quadrant"]].append(candidate)
        chosen = [min(sectors[q], key=lambda c: (abs(c["pose"]["pitch"]),
                                                c["distance_to_representative_m"], c["id"]))
                  for q in sorted(sectors)]
        group.update(photo_ids=[c["id"] for c in chosen], available_quadrants=sorted(sectors),
                     missing_quadrants=sorted(set(range(4)) - sectors.keys()),
                     candidate_count=sum(len(v) for v in sectors.values()))
        selected.extend(chosen)
    return groups, selected


def load_candidates(index_dir, places, bbox):
    from .rover_photo_geometry import camera_pose

    counts = Counter()
    rejected = []
    candidates = []
    seen = set()
    full_keys = set()
    pages = sorted(Path(index_dir).glob("page_*.json"))
    if not pages:
        raise ValueError("index directory contains no page_*.json files")
    items = []
    for page in pages:
        payload = json.loads(page.read_text(encoding="utf-8"))
        if not isinstance(payload.get("items"), list):
            raise ValueError(f"invalid index page: {page.name}")
        items.extend(payload["items"])
    # A canonical order makes the result independent of how items fall on pages,
    # including which copy of a repeated image ID is kept.
    items.sort(key=index_item_order)
    for item in items:
        counts["index_items"] += 1
        if not isinstance(item, dict):
            counts["malformed_item"] += 1
            continue
        if not str(item.get("instrument", "")).startswith("NAV_"):
            counts["not_navcam"] += 1
            continue
        if item.get("is_thumbnail") is not False:
            counts["thumbnail_or_unknown"] += 1
            continue
        if (item.get("extended") or {}).get("sample_type") != "full":
            counts["not_full"] += 1
            continue
        counts["full_navcam"] += 1
        try:
            image_id = item["imageid"]
            if not isinstance(image_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", image_id):
                raise RejectedPhoto("invalid_imageid")
            if image_id in seen:
                raise RejectedPhoto("duplicate_imageid")
            seen.add(image_id)
            key = integer(item["site"]), integer(item["drive"])
            full_keys.add(key)
            if not str(item.get("https_url", "")).startswith("https://"):
                raise RejectedPhoto("missing_https_url")
            row, join = resolve_place(item, places.get(key, []))
            pose = camera_pose(item, row)
            for field in ("x", "y", "z", "heading", "pitch", "fov"):
                finite(pose[field])
            if not in_bbox(pose["x"], pose["y"], bbox):
                raise RejectedPhoto("outside_bbox")
            candidate = {"id": image_id, "source_id": item.get("id"),
                         "sol": integer(item["sol"]), "date_taken": item.get("date_taken"),
                         "lmst": (item.get("extended") or {}).get("lmst"),
                         "site": key[0], "drive": key[1], "places_pose": integer(row["pose"]),
                         "instrument": item["instrument"], "https_url": item["https_url"],
                         "image_credit": item.get("image_credit"), "pose": pose,
                         "places_join": join, "rover_position": dict(zip(("x", "y", "z"), row_position(row))),
                         "validation_status": "pending_visual", "_item": item, "_row": row}
            candidates.append(candidate)
        except (RejectedPhoto, ValueError, KeyError, TypeError) as error:
            reason = str(error) if isinstance(error, RejectedPhoto) else "invalid_geometry_or_metadata"
            counts[reason] += 1
            rejected.append({"id": item.get("imageid"), "reason": reason,
                             "detail": str(error)[:250]})
    counts["full_navcam_keys"] = len(full_keys)
    counts["eligible"] = len(candidates)
    counts["eligible_keys"] = len({(c["site"], c["drive"]) for c in candidates})
    return candidates, dict(counts), rejected


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2, allow_nan=False) + "\n").encode("utf-8")


def atomic_write(path, data):
    """Readers see the old complete file or the new complete file."""
    path = Path(path)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".tmp-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def local_images(images_dir):
    images = {}
    for path in sorted(Path(images_dir).rglob("*")):
        if path.is_file() and path.suffix.lower() in (".jpg", ".jpeg"):
            if path.stem in images:
                raise ValueError(f"duplicate local image filename: {path.name}")
            images[path.stem] = path
    return images


def summary(values):
    values = [float(v) for v in values if v is not None and math.isfinite(v)]
    if not values:
        return {"count": 0, "min": None, "max": None, "mean": None, "p95": None}
    return {"count": len(values), "min": min(values), "max": max(values),
            "mean": float(np.mean(values)), "p95": float(np.percentile(values, 95))}


def process_assets(photo, local, stage):
    from .rover_photo_geometry import rectify_image

    path = local.get(photo["id"])
    photo["assets"] = {"source_available": path is not None,
                       "source_relative_path": None if path is None else path.name,
                       "thumbnail": None, "unwarped": None, "rectified": None,
                       "status": "missing_source" if path is None else "pending"}
    if path is None:
        return
    try:
        with Image.open(path) as source:
            source.load()
            source = source.convert("RGB")
        rectified, metrics = rectify_image(source, photo["_item"], photo["pose"], size=768)
        for name, size, extension in (("thumbnail", 320, "jpg"), ("unwarped", 1024, "jpg")):
            output = source.copy()
            output.thumbnail((size, size), Image.Resampling.LANCZOS)
            relative = f"assets/{photo['id']}_{name}.{extension}"
            output.save(stage / relative, "JPEG", quality=90, optimize=False)
            photo["assets"][name] = relative
        relative = f"assets/{photo['id']}_rectified.png"
        rectified.save(stage / relative, "PNG")
        photo["assets"]["rectified"] = relative
        photo["assets"]["status"] = "available"
        photo["rectification"] = metrics
    # A corrupt header can claim an absurd size; PIL refuses it with a non-OSError.
    except (OSError, ValueError, KeyError, TypeError, Image.DecompressionBombError) as error:
        photo["assets"].update(status="processing_failed", thumbnail=None, unwarped=None, rectified=None,
                                error=str(error)[:250])


def validate_paths(index_dir, places_csv, images_dir, dem, output_dir):
    paths = [Path(p).expanduser().resolve() for p in (index_dir, places_csv, images_dir, dem, output_dir)]
    for p in (paths[0], paths[2]):
        if not p.is_dir():
            raise ValueError(f"missing input directory: {p}")
    for p in (paths[1], paths[3]):
        if not p.is_file():
            raise ValueError(f"missing input file: {p}")
    if paths[1].name.lower() != "localized_interp.csv":
        raise ValueError("PLACES must be localized_interp.csv; _demv2 is not accepted")
    out = paths[4]
    for source in (paths[0], paths[2], paths[1].parent, paths[3].parent):
        if out == source or source in out.parents or out in source.parents:
            raise ValueError("output directory must not overlap an input directory")
    return paths


def build_catalog(index_dir, places_csv, images_dir, dem, output_dir):
    index_dir, places_csv, images_dir, dem, output_dir = validate_paths(
        index_dir, places_csv, images_dir, dem, output_dir)
    contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
    bbox = contract["bbox"]
    places, places_counts = load_places(places_csv)
    candidates, counts, rejected = load_candidates(index_dir, places, bbox)
    groups, photos = group_and_select(candidates)
    local = local_images(images_dir)
    with rasterio.open(dem) as dataset:
        if not np.allclose(tuple(dataset.bounds), (bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]), rtol=0, atol=1e-5):
            raise ValueError("DEM bounds differ from docs/contracts/grid.json")
        if dataset.crs != rasterio.crs.CRS.from_string(contract["crs_proj4"]):
            raise ValueError("DEM CRS differs from docs/contracts/grid.json")
        if dataset.res != (1.0, 1.0) or dataset.transform.b != 0 or dataset.transform.d != 0:
            raise ValueError("DEM must use the unrotated one-metre contract grid")
        for photo in candidates:
            x, y, z = row_position(photo["_row"])
            value = next(dataset.sample([(x, y)], masked=True))[0] if in_bbox(x, y, bbox) else np.ma.masked
            height = None if np.ma.is_masked(value) or not math.isfinite(float(value)) else float(value)
            photo["dem"] = {"elevation_m": height,
                            "places_minus_dem_m": None if height is None else z - height,
                            "camera_minus_dem_m": None if height is None else photo["pose"]["z"] - height,
                            "method": "nearest_dem_cell_at_rover_position; no_vertical_correction"}
    output_dir.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".staging-", dir=output_dir))
    try:
        (stage / "assets").mkdir()
        for photo in photos:
            process_assets(photo, local, stage)
        eligible_ids = {c["id"] for c in candidates}
        sizes = [path.stat().st_size for image_id, path in local.items() if image_id in eligible_ids]
        size_stats = summary(sizes)
        missing = [{"id": p["id"], "https_url": p["https_url"], "filename": p["id"] + ".JPG",
                    "sol": p["sol"], "image_credit": p["image_credit"]}
                   for p in photos if not p["assets"]["source_available"]]
        manifest = {"schema_version": SCHEMA_VERSION, "download_performed": False,
                    "scope": "selected_missing_sources_only", "count": len(missing), "items": missing,
                    "size_estimate": {"is_estimate": True, "method": "local eligible full JPG sample; no HEAD/network requests",
                                      "sample_count": size_stats["count"], "sample_mean_bytes": size_stats["mean"],
                                      "sample_p95_bytes": size_stats["p95"],
                                      "total_mean_bytes": None if not sizes else round(len(missing) * size_stats["mean"]),
                                      "total_p95_bytes": None if not sizes else round(len(missing) * size_stats["p95"])}}
        counts.update(groups=len(groups), selected=len(photos), not_selected=len(candidates) - len(photos),
                      selected_local_available=sum(p["assets"]["status"] == "available" for p in photos),
                      selected_missing=len(missing),
                      selected_processing_failed=sum(p["assets"]["status"] == "processing_failed" for p in photos))
        report = {"schema_version": SCHEMA_VERSION, "counts": counts, "places_rows": places_counts,
                  "rejected": rejected, "selection_discard_reason": "lower_priority_in_same_stop_heading_quadrant",
                  "coverage": [{"group_id": g["id"], "quadrants": g["available_quadrants"],
                                "missing_quadrants": g["missing_quadrants"],
                                "candidate_count": g["candidate_count"]} for g in groups],
                  "places_minus_dem_m": summary(c["dem"]["places_minus_dem_m"] for c in candidates),
                  "camera_minus_dem_m": summary(c["dem"]["camera_minus_dem_m"] for c in candidates),
                  "join_attitude_residual_deg": summary(c["places_join"]["attitude_residual_deg"] for c in candidates),
                  "repeated_join_photos": [{"id": c["id"], **c["places_join"]} for c in candidates
                                           if c["places_join"]["candidate_rows"] > 1],
                  "null_credit_count": sum(c["image_credit"] is None for c in photos),
                  "validation_status": "pending_visual",
                  "geometry_diagnostics": {key: summary(c["pose"].get("diagnostics", {}).get(key) for c in candidates)
                                           for key in ("source_roll_deg", "axis_to_center_deg", "vector_to_center_deg",
                                                       "image_places_attitude_delta_deg", "image_places_yaw_delta_deg")},
                  "source_hfov_deg": summary(c["pose"].get("source_hfov_deg") for c in candidates),
                  "source_vfov_deg": summary(c["pose"].get("source_vfov_deg") for c in candidates),
                  "rectified_supported_fraction": summary(c.get("rectification", {}).get("supported_fraction") for c in photos)}
        public_photos = [{k: v for k, v in p.items() if not k.startswith("_")} for p in photos]
        catalog = {"schema_version": SCHEMA_VERSION, "bbox": bbox, "crs_proj4": contract["crs_proj4"],
                   "units": {"position": "metres; x=easting, y=northing, z=elevation",
                             "heading": "radians clockwise from north", "pitch": "radians positive down from horizon",
                             "fov": "degrees; square rectified viewport", "dates": "UTC ISO 8601"},
                   "provenance": {"index_dir": str(index_dir), "places_csv": str(places_csv),
                                  "images_dir": str(images_dir), "dem": str(dem),
                                  "places_credit": "NASA / JPL / PDS Imaging Node",
                                  "selection": "full non-thumbnail Navcam; PLACES ROVER site/drive; original camera coordinates",
                                  "join": "minimum quaternion angular residual; ties within API rounding must agree within 1 cm, then highest PLACES pose; otherwise rejected"},
                   "selection": {"max_group_radius_m": GROUP_RADIUS_M, "distance_metric": "horizontal Euclidean",
                                 "representative": "first stable actual PLACES position; never chained or averaged",
                                 "quadrants": "0=[0,90), 1=[90,180), 2=[180,270), 3=[270,360) degrees",
                                 "priority": ["absolute_pitch", "distance_to_representative", "imageid"]},
                   "validation_status": "pending_visual", "groups": groups, "photos": public_photos}
        sources = {"schema_version": SCHEMA_VERSION,
                   "items": [{"id": p["id"], "raw_index_item": p["_item"], "places_row": p["_row"]} for p in photos]}
        # Hash the complete logical bundle and image bytes before adding its prefix.
        digest = hashlib.sha256(json_bytes([catalog, report, manifest, sources]))
        for asset in sorted((stage / "assets").iterdir()):
            digest.update(asset.name.encode())
            digest.update(asset.read_bytes())
        generation = digest.hexdigest()[:24]
        prefix = f"generations/{generation}"
        for photo in public_photos:
            for name in ("thumbnail", "unwarped", "rectified"):
                if photo["assets"][name]:
                    photo["assets"][name] = f"{prefix}/{photo['assets'][name]}"
        catalog.update(generation=generation, report=f"{prefix}/report.json",
                       download_manifest=f"{prefix}/download_manifest.json", sources=f"{prefix}/sources.json")
        documents = {"catalog.json": catalog, "report.json": report, "download_manifest.json": manifest,
                     "sources.json": sources}
        for name, document in documents.items():
            (stage / name).write_bytes(json_bytes(document))
        destination = output_dir / prefix
        destination.parent.mkdir(exist_ok=True)
        if not destination.exists():
            os.replace(stage, destination)
        # Immutable report references in catalog keep concurrent readers consistent.
        for name in ("report.json", "download_manifest.json", "catalog.json"):
            atomic_write(output_dir / name, json_bytes(documents[name]))
        return catalog, report, manifest
    finally:
        if stage.exists():
            shutil.rmtree(stage)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for flag in ("index-dir", "places-csv", "images-dir", "dem", "output-dir"):
        parser.add_argument("--" + flag, required=True, type=Path)
    args = parser.parse_args(argv)
    _, report, manifest = build_catalog(**vars(args))
    print(json.dumps({"counts": report["counts"], "download_estimate": manifest["size_estimate"]}, sort_keys=True))


if __name__ == "__main__":
    main()
