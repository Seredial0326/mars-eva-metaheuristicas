"""Tests for the offline Navcam catalogue builder (P3, issue #46).

Every input is synthetic and written to tmp_path: raw-image index pages,
PLACES rows, local JPGs and a float32 DEM on the contract grid. A synthetic
Navcam looks along rover +X with a distortion-free 45-degree lens, so its
heading, pitch and roll come only from the attitude quaternion.
"""

import csv
import json
import math
import random
import socket
import zlib
from pathlib import Path

import numpy as np
import pytest
import rasterio
from PIL import Image
from rasterio.crs import CRS
from rasterio.transform import from_origin

from src.viz3d import build_rover_photos as brp

REPO = Path(__file__).resolve().parents[2]
CONTRACT = json.loads((REPO / "docs/contracts/grid.json").read_text(encoding="utf-8"))
BBOX = CONTRACT["bbox"]

# A stop near the middle of the 2 x 2 km box (x=easting, y=northing, metres).
EAST, NORTH, ELEV = 8143500.0, -284500.0, -3720.0
DEM_Z = ELEV - 1.5                        # the synthetic DEM lies 1.5 m below the stops
HOLE = (8144200.0, -284000.0)             # centre of a NaN patch in the DEM
MM = 1e-6                                 # coordinate tolerance; pytest's default rel is metres here

PLACES_FIELDS = ["frame", "site", "drive", "pose", "easting", "northing", "elevation", "roll",
                 "pitch", "yaw", "quat_s", "quat_v1", "quat_v2", "quat_v3", "sclk", "sol"]


def _axis(index, degrees):
    q = [math.cos(math.radians(degrees) / 2), 0.0, 0.0, 0.0]
    q[index] = math.sin(math.radians(degrees) / 2)
    return q


def _product(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return [w1*w2 - x1*x2 - y1*y2 - z1*z2, w1*x2 + x1*w2 + y1*z2 - z1*y2,
            w1*y2 - x1*z2 + y1*w2 + z1*x2, w1*z2 + x1*y2 - y1*x2 + z1*w2]


def attitude(heading=0.0, pitch=0.0, roll=0.0):
    """Scalar-first rover-to-site quaternion from yaw, pitch (positive down) and roll in degrees."""
    # A positive turn about rover +Y raises the nose, so looking down is a negative turn.
    return _product(_product(_axis(3, heading), _axis(2, -pitch)), _axis(1, roll))


def navcam(image_id, *, site=10, drive=100, heading=0.0, pitch=0.0, roll=0.0, clock=1000.0,
           center=(0, 0, 0), **changes):
    """A valid full-frame Navcam index item, shaped like the raw-image API's."""
    focal = 1236.0
    item = {
        "id": zlib.crc32(image_id.encode()), "imageid": image_id, "instrument": "NAV_LEFT_B",
        "is_thumbnail": False, "extended": {"sample_type": "full", "lmst": "Sol-04450M13:38:27.231"},
        "camera_model_type": "CAHVOR", "subframe_rect": "(1,1,1024,1024)", "scale_factor": 1,
        "camera_model_component_list": [list(center), [1, 0, 0], [511.5, focal, 0],
                                         [511.5, 0, focal], [1, 0, 0], [0, 0, 0]],
        "attitude": "(" + ",".join(repr(v) for v in attitude(heading, pitch, roll)) + ")",
        "site": site, "drive": drive, "sol": 4450, "spacecraft_clock": clock,
        "date_taken": "2025-02-11T11:54:53.000Z", "image_credit": "NASA/JPL-Caltech",
        "https_url": "https://mars.nasa.gov/msl-raw-images/proj/msl/redops/ods/surface/sol/"
                     f"04450/opgs/edr/ncam/{image_id}.JPG",
    }
    item.update(changes)
    return item


def places(*, site=10, drive=100, pose=-1, east=EAST, north=NORTH, elev=ELEV, heading=0.0,
           sclk=1000, frame="ROVER"):
    """One PLACES localized_interp row, with the same text precision as the real file."""
    q = attitude(heading)
    return {"frame": frame, "site": str(site), "drive": str(drive), "pose": str(pose),
            "easting": f"{east:.3f}", "northing": f"{north:.3f}", "elevation": f"{elev:.3f}",
            "roll": "0.000", "pitch": "0.000", "yaw": f"{heading:.3f}",
            **{key: f"{v:.9f}" for key, v in zip(PLACES_FIELDS[10:14], q)},
            "sclk": str(sclk), "sol": "4450"}


def write_pages(index_dir, items, per_page=3):
    index_dir.mkdir(parents=True, exist_ok=True)
    for old in index_dir.glob("page_*.json"):
        old.unlink()
    for number, start in enumerate(range(0, len(items), per_page)):
        page = {"items": items[start:start + per_page], "more": start + per_page < len(items)}
        (index_dir / f"page_{number:03d}.json").write_text(json.dumps(page), encoding="utf-8")


def write_places(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=PLACES_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def write_jpeg(path, size=(1024, 1024)):
    """A grayscale Navcam-like JPG with a diagonal gradient."""
    path.parent.mkdir(parents=True, exist_ok=True)
    y, x = np.mgrid[:size[1], :size[0]]
    Image.fromarray(((x + y) // 8 % 256).astype(np.uint8), "L").save(path, "JPEG", quality=90)


@pytest.fixture(scope="module")
def dem(tmp_path_factory):
    """Float32 DEM on the contract grid: 1 m cells, DEM_Z everywhere except a NaN patch."""
    path = tmp_path_factory.mktemp("base") / "dem_1m.tif"
    width, height = round(BBOX["xmax"] - BBOX["xmin"]), round(BBOX["ymax"] - BBOX["ymin"])
    z = np.full((height, width), DEM_Z, dtype="float32")
    col, row = int(HOLE[0] - BBOX["xmin"]), int(BBOX["ymax"] - HOLE[1])
    z[row - 5:row + 5, col - 5:col + 5] = np.nan
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1,
                       dtype="float32", crs=CRS.from_string(CONTRACT["crs_proj4"]),
                       transform=from_origin(BBOX["xmin"], BBOX["ymax"], 1.0, 1.0),
                       nodata=float("nan")) as dst:
        dst.write(z, 1)
    return path


def layout(root):
    """Input folders and the output folder, all siblings under root."""
    return {"index_dir": root / "index", "places_csv": root / "places" / "localized_interp.csv",
            "images_dir": root / "images", "output_dir": root / "out"}


def prepare(root, items, rows, images=(), per_page=3):
    paths = layout(root)
    write_pages(paths["index_dir"], items, per_page)
    write_places(paths["places_csv"], rows)
    paths["images_dir"].mkdir(parents=True, exist_ok=True)
    for image_id in images:
        write_jpeg(paths["images_dir"] / f"{image_id}.JPG")


def run(root, dem):
    return brp.build_catalog(dem=dem, **layout(root))


def build(root, dem, items, rows, images=(), per_page=3):
    prepare(root, items, rows, images, per_page)
    return run(root, dem)


def by_id(catalog):
    return {photo["id"]: photo for photo in catalog["photos"]}


def test_only_localized_interp_csv_is_accepted(tmp_path, dem):
    rows = [places(), places(frame="SITE")]
    demv2 = tmp_path / "places" / "localized_interp_demv2.csv"
    original = tmp_path / "places" / "localized_interp.csv"
    write_places(demv2, rows)
    write_places(original, rows)
    with pytest.raises(ValueError):
        brp.load_places(demv2)
    loaded, _ = brp.load_places(original)
    assert list(loaded) == [(10, 100)] and len(loaded[(10, 100)]) == 1   # SITE frame dropped

    paths = layout(tmp_path)
    write_pages(paths["index_dir"], [navcam("NLB_a")])
    paths["images_dir"].mkdir()
    # Same folder and same content: only the file name decides.
    brp.validate_paths(paths["index_dir"], original, paths["images_dir"], dem, paths["output_dir"])
    with pytest.raises(ValueError):
        brp.validate_paths(paths["index_dir"], demv2, paths["images_dir"], dem, paths["output_dir"])
    with pytest.raises(ValueError):
        brp.build_catalog(paths["index_dir"], demv2, paths["images_dir"], dem, paths["output_dir"])
    assert not paths["output_dir"].exists()


def test_repeated_places_rows_give_each_image_exactly_one_row(tmp_path, dem):
    rows = [
        # Drive 100: matching attitude beats a matching clock.
        places(drive=100, pose=1, east=EAST, heading=30, sclk=9000),
        places(drive=100, pose=2, east=EAST + 2, heading=40, sclk=1000),
        # Drive 101: same attitude and place; the highest pose is kept (PLACES SIS rule
        # of thumb), and the clock, shared by a site/drive, does not decide.
        places(drive=101, pose=3, east=EAST + 50, heading=200, sclk=1300),
        places(drive=101, pose=1, east=EAST + 50.003, heading=200, sclk=900),
        # Drive 102: fully tied rows 4 mm apart are one place.
        places(drive=102, pose=1, east=EAST + 100),
        places(drive=102, pose=2, east=EAST + 100.004),
        # Drive 103: fully tied rows 5 m apart; nothing says which is right.
        places(drive=103, pose=1, east=EAST + 150, sclk=900),
        places(drive=103, pose=2, east=EAST + 155, sclk=1100),
        # Drive 104: both outer rows are within 6 mm of the first row, but 12 mm from each other.
        places(drive=104, pose=1, east=EAST + 200),
        places(drive=104, pose=2, east=EAST + 199.994),
        places(drive=104, pose=3, east=EAST + 200.006),
    ]
    items = [navcam("NLB_attitude", drive=100, heading=30), navcam("NLB_highest_pose", drive=101, heading=200),
             navcam("NLB_colocated", drive=102), navcam("NLB_ambiguous", drive=103),
             navcam("NLB_spread", drive=104)]
    items.append(dict(items[0]))                         # the same record again on a later page
    catalog, report, _ = build(tmp_path, dem, items, rows, per_page=2)

    ids = [photo["id"] for photo in catalog["photos"]]
    assert len(ids) == len(set(ids))
    assert set(ids) == {"NLB_attitude", "NLB_highest_pose", "NLB_colocated"}
    photos = by_id(catalog)
    assert photos["NLB_attitude"]["places_pose"] == 1
    assert photos["NLB_attitude"]["rover_position"]["x"] == pytest.approx(EAST, abs=MM)
    assert photos["NLB_highest_pose"]["places_pose"] == 3
    assert photos["NLB_highest_pose"]["rover_position"]["x"] == pytest.approx(EAST + 50, abs=MM)
    assert photos["NLB_colocated"]["places_pose"] == 2
    assert photos["NLB_colocated"]["places_join"]["tied_position_spread_m"] == pytest.approx(0.004, abs=MM)
    rejected = {(entry["id"], entry["reason"]) for entry in report["rejected"]}
    assert ("NLB_ambiguous", "ambiguous_places_positions") in rejected
    assert ("NLB_spread", "ambiguous_places_positions") in rejected
    assert report["counts"]["ambiguous_places_positions"] == 2


def test_only_full_navcam_inside_the_box_is_eligible(tmp_path, dem):
    rows = [places(drive=100), places(drive=101, east=BBOX["xmin"] - 40)]
    items = [navcam("NLB_keep"),
             navcam("NLB_thumb", is_thumbnail=True),
             navcam("NLB_subframe", extended={"sample_type": "subframe"}),
             navcam("NLB_cropped", subframe_rect="(1,1,512,512)"),    # labelled full, but cropped
             navcam("FLB_hazcam", instrument="FHAZ_LEFT_B"),
             navcam("NLB_outside", drive=101)]
    catalog, report, manifest = build(tmp_path, dem, items, rows)

    assert [photo["id"] for photo in catalog["photos"]] == ["NLB_keep"]
    assert [entry["id"] for entry in manifest["items"]] == ["NLB_keep"]
    counts = report["counts"]
    assert counts["index_items"] == 6 and counts["eligible"] == 1
    assert counts["thumbnail_or_unknown"] == 1
    assert counts["not_full"] == 1
    assert counts["not_navcam"] == 1
    assert counts["outside_bbox"] == 1
    assert counts["invalid_geometry_or_metadata"] == 1
    assert {entry["id"] for entry in report["rejected"]} == {"NLB_cropped", "NLB_outside"}


def test_groups_keep_a_real_places_position_and_never_chain(tmp_path, dem):
    # A-B 8 m and B-C 8 m, but A-C 16 m: C cannot join A's stop through B.
    rows = [places(drive=100, east=EAST), places(drive=101, east=EAST + 8),
            places(drive=102, east=EAST + 16)]
    items = [navcam("NLB_a", drive=100, heading=45), navcam("NLB_b", drive=101, heading=135),
             navcam("NLB_c", drive=102, heading=225)]
    catalog, _, _ = build(tmp_path, dem, items, rows)

    photos = by_id(catalog)
    assert photos["NLB_a"]["group_id"] == photos["NLB_b"]["group_id"] != photos["NLB_c"]["group_id"]
    groups = {group["id"]: group for group in catalog["groups"]}
    first = groups[photos["NLB_a"]["group_id"]]["representative"]
    assert first["xy"] == pytest.approx([EAST, NORTH], abs=MM)    # A itself, not the A-B midpoint
    assert first["z"] == pytest.approx(ELEV, abs=MM)
    actual = {(float(row["easting"]), float(row["northing"])) for row in rows}
    for group in catalog["groups"]:
        assert tuple(group["representative"]["xy"]) in actual
        for image_id in group["photo_ids"]:
            rover = photos[image_id]["rover_position"]
            assert math.dist((rover["x"], rover["y"]), group["representative"]["xy"]) <= 10


def test_one_photo_per_heading_sector_by_pitch_then_distance_then_id(tmp_path, dem):
    # One stop: drive 100 is the representative and drive 101 stands 3 m east of it.
    rows = [places(drive=100), places(drive=101, east=EAST + 3)]
    items = [
        # North-east sector: the smaller |pitch| wins although it is farther away.
        navcam("NLB_ne_steep", drive=100, heading=10, pitch=20),
        navcam("NLB_ne_level", drive=101, heading=80, pitch=-5),
        # South-east: equal pitch, so the photo nearer the representative beats the smaller id.
        navcam("NLB_se_a", drive=101, heading=100),
        navcam("NLB_se_z", drive=100, heading=170),
        # South-west: equal pitch and distance, so the smaller image id wins.
        navcam("NLB_sw_b", drive=100, heading=200),
        navcam("NLB_sw_a", drive=100, heading=250),
        # North-west: the less steep of two downward views.
        navcam("NLB_nw_steep", drive=100, heading=359.9, pitch=40),
        navcam("NLB_nw", drive=101, heading=300, pitch=30),
    ]
    catalog, report, _ = build(tmp_path, dem, items, rows)

    assert len(catalog["groups"]) == 1
    group = catalog["groups"][0]
    assert sorted(group["photo_ids"]) == ["NLB_ne_level", "NLB_nw", "NLB_se_z", "NLB_sw_a"]
    assert sorted(photo["id"] for photo in catalog["photos"]) == sorted(group["photo_ids"])
    sectors = sorted(int(math.degrees(photo["pose"]["heading"]) // 90) for photo in catalog["photos"])
    assert sectors == [0, 1, 2, 3]
    assert report["counts"]["not_selected"] == 4


def test_result_does_not_depend_on_page_or_item_order(tmp_path, dem):
    rng = random.Random(46)
    # Stops 6 m apart, so which stop a photo joins depends on who represents each group.
    rows = [places(drive=100 + n, east=EAST + 6 * n, north=NORTH + n % 3) for n in range(8)]
    rows += [places(drive=150, east=EAST + 300), places(drive=150, east=EAST + 310)]   # ambiguous
    items = [navcam(f"NLB_{n:03d}", drive=100 + rng.randrange(8), heading=rng.uniform(0, 360),
                    pitch=rng.choice([0, 0, 5, -5, 12]), clock=1000 + n) for n in range(40)]
    items += [navcam("NLB_ambiguous_1", drive=150), navcam("NLB_ambiguous_2", drive=150),
              navcam("NLB_no_places", drive=999), navcam("NLB_thumb", is_thumbnail=True)]
    # The same image fetched twice, its metadata touched between the two page requests.
    items[3]["updated_at"] = "2025-02-11T12:00:00Z"
    items.append(dict(items[3], updated_at="2025-02-12T12:00:00Z"))
    paths = layout(tmp_path)
    write_places(paths["places_csv"], rows)
    paths["images_dir"].mkdir()

    shuffled = items[:]
    random.Random(7).shuffle(shuffled)
    results = []
    for number, (order, per_page) in enumerate([(items, 5), (items[::-1], 7), (shuffled, 3)]):
        write_pages(paths["index_dir"], order, per_page)
        results.append(brp.build_catalog(paths["index_dir"], paths["places_csv"], paths["images_dir"],
                                         dem, tmp_path / f"out{number}"))

    catalog, report, manifest = results[0]
    assert len(catalog["groups"]) > 1 and report["counts"]["not_selected"] > 0
    assert len(report["rejected"]) == 4
    for other_catalog, other_report, other_manifest in results[1:]:
        assert other_catalog["groups"] == catalog["groups"]
        assert other_catalog["photos"] == catalog["photos"]
        assert other_catalog["generation"] == catalog["generation"]
        assert other_report == report
        assert other_manifest == manifest


def test_selected_photos_keep_their_own_camera_position(tmp_path, dem):
    rows = [places(drive=100), places(drive=101, east=EAST + 4, north=NORTH + 3, elev=ELEV + 0.5)]
    # The camera sits 1 m forward, 2 m right and 3 m above the rover origin.
    items = [navcam("NLB_here", drive=100, heading=0, center=(1, 2, -3)),
             navcam("NLB_there", drive=101, heading=180, center=(1, 2, -3))]
    catalog, _, _ = build(tmp_path, dem, items, rows)

    photos = by_id(catalog)
    assert photos["NLB_here"]["group_id"] == photos["NLB_there"]["group_id"]
    # Facing north, forward is +northing and right is +easting; facing south both flip.
    here = [photos["NLB_here"]["pose"][k] for k in "xyz"]
    there = [photos["NLB_there"]["pose"][k] for k in "xyz"]
    assert here == pytest.approx([EAST + 2, NORTH + 1, ELEV + 3], abs=MM)
    assert there == pytest.approx([EAST + 4 - 2, NORTH + 3 - 1, ELEV + 0.5 + 3], abs=MM)
    assert photos["NLB_there"]["rover_position"] == pytest.approx(
        {"x": EAST + 4, "y": NORTH + 3, "z": ELEV + 0.5}, abs=MM)
    assert catalog["groups"][0]["representative"]["xy"] == pytest.approx([EAST, NORTH], abs=MM)


def test_each_group_reports_its_missing_heading_sectors(tmp_path, dem):
    rows = [places(drive=100), places(drive=101, east=EAST + 100)]
    items = [navcam("NLB_a_ne", drive=100, heading=45), navcam("NLB_a_se", drive=100, heading=135),
             navcam("NLB_b_nw", drive=101, heading=315)]
    catalog, report, _ = build(tmp_path, dem, items, rows)

    group_of = {photo["id"]: photo["group_id"] for photo in catalog["photos"]}
    groups = {group["id"]: group for group in catalog["groups"]}
    assert groups[group_of["NLB_a_ne"]]["missing_quadrants"] == [2, 3]
    assert groups[group_of["NLB_b_nw"]]["missing_quadrants"] == [0, 1, 2]
    coverage = {entry["group_id"]: entry["missing_quadrants"] for entry in report["coverage"]}
    assert coverage == {key: group["missing_quadrants"] for key, group in groups.items()}


def test_download_manifest_lists_selected_photos_missing_locally_and_never_connects(
        tmp_path, dem, monkeypatch):
    attempts = []

    def no_network(*args, **kwargs):
        attempts.append(args)
        raise OSError("network disabled by the test")

    monkeypatch.setattr(socket.socket, "connect", no_network)
    monkeypatch.setattr(socket.socket, "connect_ex", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    monkeypatch.setattr(socket, "getaddrinfo", no_network)
    rows = [places(drive=100), places(drive=101, east=EAST + 100), places(drive=102, east=EAST + 200)]
    items = [navcam("NLB_local", drive=100, heading=45),
             navcam("NLB_remote_a", drive=101, heading=45),
             navcam("NLB_remote_a_steep", drive=101, heading=60, pitch=25),   # loses its sector
             navcam("NLB_remote_b", drive=102, heading=225)]
    catalog, _, manifest = build(tmp_path, dem, items, rows, images=["NLB_local"])

    urls = {item["imageid"]: item["https_url"] for item in items}
    assert sorted(entry["id"] for entry in manifest["items"]) == ["NLB_remote_a", "NLB_remote_b"]
    assert manifest["count"] == 2 and manifest["download_performed"] is False
    for entry in manifest["items"]:
        assert entry["https_url"] == urls[entry["id"]]
        assert entry["filename"]
    assert manifest["size_estimate"]["is_estimate"] is True

    # A file saved under its manifest filename is found as the local source next time.
    entry = next(entry for entry in manifest["items"] if entry["id"] == "NLB_remote_b")
    write_jpeg(layout(tmp_path)["images_dir"] / entry["filename"])
    catalog, _, manifest = run(tmp_path, dem)
    assert [entry["id"] for entry in manifest["items"]] == ["NLB_remote_a"]
    assert by_id(catalog)["NLB_remote_b"]["assets"]["status"] == "available"
    assert attempts == []


def test_local_image_gives_thumbnail_card_and_transparent_comparison(tmp_path, dem):
    # A 30-degree roll puts the corners of the level 40-degree view outside the source frame.
    catalog, report, manifest = build(tmp_path, dem, [navcam("NLB_local", heading=45, roll=30)],
                                      [places()], images=["NLB_local"])
    out = layout(tmp_path)["output_dir"]
    assets = catalog["photos"][0]["assets"]
    assert assets["status"] == "available"
    assert manifest["items"] == [] and report["counts"]["selected_local_available"] == 1
    with Image.open(out / assets["thumbnail"]) as thumbnail:
        assert max(thumbnail.size) <= 320
    with Image.open(out / assets["unwarped"]) as card:
        assert card.format == "JPEG" and 320 < max(card.size) <= 1024
    with Image.open(out / assets["rectified"]) as comparison:
        assert comparison.format == "PNG" and comparison.mode == "RGBA"
        assert comparison.size == (768, 768)
        alpha = np.asarray(comparison)[..., 3]
    assert [alpha[0, 0], alpha[0, -1], alpha[-1, 0], alpha[-1, -1]] == [0, 0, 0, 0]
    assert alpha[384, 384] == 255


def corrupt(kind, path):
    write_jpeg(path)
    data = path.read_bytes()
    if kind == "not_an_image":
        path.write_bytes(b"this is not a JPEG " * 100)
    elif kind == "truncated":
        path.write_bytes(data[:len(data) // 3])
    elif kind == "absurd_header_size":
        # The baseline frame header claims 65535 x 65535 pixels.
        frame = data.index(b"\xff\xc0")
        path.write_bytes(data[:frame + 5] + b"\xff\xff\xff\xff" + data[frame + 9:])
    elif kind == "wrong_dimensions":
        write_jpeg(path, size=(512, 512))


@pytest.mark.parametrize("kind", ["not_an_image", "truncated", "absurd_header_size", "wrong_dimensions"])
def test_corrupt_local_image_is_recorded_and_the_build_continues(tmp_path, dem, kind):
    rows = [places(drive=100), places(drive=101, east=EAST + 100)]
    prepare(tmp_path, [navcam("NLB_bad", drive=100), navcam("NLB_remote", drive=101)], rows)
    corrupt(kind, layout(tmp_path)["images_dir"] / "NLB_bad.JPG")
    catalog, report, manifest = run(tmp_path, dem)

    assets = by_id(catalog)["NLB_bad"]["assets"]
    assert assets["status"] == "processing_failed" and assets["error"]
    assert assets["thumbnail"] is None and assets["unwarped"] is None and assets["rectified"] is None
    assert report["counts"]["selected_processing_failed"] == 1
    assert [entry["id"] for entry in manifest["items"]] == ["NLB_remote"]
    out = layout(tmp_path)["output_dir"]
    assert json.loads((out / "catalog.json").read_text(encoding="utf-8"))["generation"] == catalog["generation"]
    assert not list(out.rglob("NLB_bad*"))


def test_build_writes_only_inside_the_output_dir(tmp_path, dem):
    rows = [places(drive=100), places(drive=101, east=EAST + 100)]
    prepare(tmp_path, [navcam("NLB_local", drive=100), navcam("NLB_remote", drive=101)], rows,
            images=["NLB_local"])

    def snapshot():
        roots = (tmp_path, dem.parent)
        return {path: (path.is_dir(), None if path.is_dir() else path.stat().st_size,
                       None if path.is_dir() else path.stat().st_mtime_ns)
                for root in roots for path in root.rglob("*")}

    before = snapshot()
    catalog, _, _ = run(tmp_path, dem)
    after = snapshot()

    out = layout(tmp_path)["output_dir"]
    changed = {path for path in before.keys() | after.keys() if before.get(path) != after.get(path)}
    assert changed and all(path == out or out in path.parents for path in changed)
    assert not list(out.glob(".staging-*")) and not list(out.glob(".tmp-*"))
    referenced = [catalog[key] for key in ("report", "download_manifest", "sources")]
    referenced += [path for photo in catalog["photos"] for path in photo["assets"].values()
                   if isinstance(path, str) and path.startswith("generations/")]
    assert len(referenced) == 6
    for relative in referenced:
        assert out.resolve() in (out / relative).resolve().parents and (out / relative).is_file()


@pytest.mark.parametrize("where", ["inside_index", "same_as_images", "inside_images",
                                   "holds_places_csv", "holds_dem", "holds_everything"])
def test_output_dir_overlapping_an_input_is_refused(tmp_path, where):
    paths = layout(tmp_path)
    write_pages(paths["index_dir"], [navcam("NLB_a")])
    write_places(paths["places_csv"], [places()])
    paths["images_dir"].mkdir()
    dem = tmp_path / "base" / "dem_1m.tif"
    dem.parent.mkdir()
    dem.write_bytes(b"")                    # refusal must come before the DEM is read
    output = {"inside_index": paths["index_dir"] / "photos", "same_as_images": paths["images_dir"],
              "inside_images": paths["images_dir"] / "photos",
              "holds_places_csv": paths["places_csv"].parent, "holds_dem": dem.parent,
              "holds_everything": tmp_path}[where]
    before = sorted(tmp_path.rglob("*"))
    with pytest.raises(ValueError, match="overlap"):
        brp.build_catalog(paths["index_dir"], paths["places_csv"], paths["images_dir"], dem, output)
    assert sorted(tmp_path.rglob("*")) == before


def test_catalog_json_is_strict_and_keeps_each_photo_credit(tmp_path, dem):
    rows = [places(drive=100), places(drive=101, east=EAST + 100),
            places(drive=102, east=HOLE[0], north=HOLE[1])]
    items = [navcam("NLB_jpl", drive=100, heading=45),
             navcam("NLB_msss", drive=101, heading=45, image_credit="NASA/JPL-Caltech/MSSS"),
             navcam("NLB_uncredited", drive=102, heading=45, image_credit=None)]   # over the NaN patch
    catalog, report, _ = build(tmp_path, dem, items, rows)
    out = layout(tmp_path)["output_dir"]

    def reject_constant(name):
        raise AssertionError(f"non-standard JSON constant {name}")

    saved = {name: json.loads((out / name).read_text(encoding="utf-8"), parse_constant=reject_constant)
             for name in ("catalog.json", "report.json", "download_manifest.json")}
    assert saved["catalog.json"] == catalog
    assert isinstance(catalog["schema_version"], int)
    assert {"position", "heading", "pitch", "fov"} <= set(catalog["units"])
    credits = {photo["id"]: photo["image_credit"] for photo in catalog["photos"]}
    assert credits == {"NLB_jpl": "NASA/JPL-Caltech", "NLB_msss": "NASA/JPL-Caltech/MSSS",
                       "NLB_uncredited": None}
    assert {entry["id"]: entry["image_credit"] for entry in saved["download_manifest.json"]["items"]} == credits
    assert report["null_credit_count"] == 1
    photos = by_id(catalog)
    assert photos["NLB_uncredited"]["dem"]["elevation_m"] is None
    assert photos["NLB_jpl"]["dem"]["elevation_m"] == pytest.approx(DEM_Z, abs=1e-3)
