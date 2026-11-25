"""Analytic geometry checks plus a small, offline real-metadata fixture."""

import copy
import json
import math
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from src.viz3d.rover_photo_geometry import camera_pose, rectify_image, _model, _project, _unproject


def synthetic(*, q=(1, 0, 0, 0), center=(1, 2, -3), principal=(511.5, 511.5), radial=(0, 0, 0),
              focal=1000):
    # Camera looks along rover +X; source sample increases +Y and line +Z.
    return {
        "imageid": "synthetic", "instrument": "NAV_RIGHT_B", "is_thumbnail": False,
        "extended": {"sample_type": "full"}, "camera_model_type": "CAHVOR",
        "subframe_rect": "(1,1,1024,1024)", "scale_factor": 1, "attitude": q,
        "camera_model_component_list": [center, [1, 0, 0], [principal[0], focal, 0],
                                         [principal[1], 0, focal], [1, 0, 0], radial],
    }


ORIGIN = {"easting": "100", "northing": "200", "elevation": "-4000"}


@pytest.mark.parametrize("degrees,offset", [(0, (2, 1, 3)), (90, (1, -2, 3)),
                                           (180, (-2, -1, 3)), (270, (-1, 2, 3))])
def test_cardinal_heading_and_rotated_camera_center(degrees, offset):
    half = math.radians(degrees) / 2
    pose = camera_pose(synthetic(q=(math.cos(half), 0, 0, math.sin(half))), ORIGIN)
    assert math.degrees(pose["heading"]) == pytest.approx(degrees, abs=1e-10)
    assert pose["pitch"] == pytest.approx(0)
    assert [pose[k] for k in ("x", "y", "z")] == pytest.approx(np.array([100, 200, -4000]) + offset)
    assert pose["fov"] == 40
    assert pose["source_hfov_deg"] == pytest.approx(2 * math.degrees(math.atan(512 / 1000)))


def test_pitch_sign_and_camera_height_use_full_quaternion():
    # Positive rotation about rover +Y tips the nose upward in NED.
    half = math.radians(30) / 2
    pose = camera_pose(synthetic(q=(math.cos(half), 0, math.sin(half), 0)), ORIGIN)
    assert math.degrees(pose["pitch"]) == pytest.approx(-30)
    expected_down = -math.sin(math.radians(30)) - 3*math.cos(math.radians(30))
    assert pose["z"] == pytest.approx(-4000 - expected_down)


def test_center_ray_uses_principal_offset_and_radial_inverse():
    item = synthetic(principal=(501.5, 531.5), radial=(.02, .1, .01))
    pose = camera_pose(item, ORIGIN)
    # Independently solve the scalar odd polynomial with numpy polynomial roots.
    distorted_radius = math.hypot(.01, -.02)
    roots = np.roots([.01, 0, .1, 0, 1.02, -distorted_radius])
    radius = next(r.real for r in roots if abs(r.imag) < 1e-9 and r.real > 0)
    expected = np.array([1, .01*radius/distorted_radius, -.02*radius/distorted_radius])
    expected /= np.linalg.norm(expected)
    assert pose["diagnostics"]["center_ray_rover"] == pytest.approx(expected)
    assert pose["heading"] > 0
    assert pose["pitch"] < 0
    assert pose["diagnostics"]["axis_to_center_deg"] > 1


def test_distortion_forward_projection_matches_analytic_polynomial():
    item = synthetic(radial=(.02, .1, .01))
    u, v, valid = _project(np.array([1., .3, -.2]), _model(item))
    scale = 1.02 + .1*(.3**2 + .2**2) + .01*(.3**2 + .2**2)**2
    assert valid
    assert u == pytest.approx(511.5 + 300*scale)
    assert v == pytest.approx(511.5 - 200*scale)
    assert _unproject(u, v, _model(item)) == pytest.approx(np.array([1, .3, -.2])/math.sqrt(1.13))


def coordinate_image():
    y, x = np.mgrid[:1024, :1024]
    return Image.fromarray(np.stack((x//4, y//4, np.full_like(x, 80)), axis=-1).astype(np.uint8))


def test_roll_is_removed_by_ray_mapping_instead_of_rotating_pixels():
    # 90-degree roll maps world screen-right to source -line, and screen-down to sample.
    q = (math.sqrt(.5), math.sqrt(.5), 0, 0)
    item = synthetic(q=q)
    pose = camera_pose(item, ORIGIN)
    image, metrics = rectify_image(coordinate_image(), item, pose, size=9)
    pixels = np.asarray(image)
    horizontal = (2*(7+.5)/9 - 1)*math.tan(math.radians(20))
    vertical = (2*(2+.5)/9 - 1)*math.tan(math.radians(20))
    expected_u, expected_v = 511.5 + 1000*vertical, 511.5 - 1000*horizontal
    assert pixels[2, 7, 0] == pytest.approx(expected_u/4, abs=1)
    assert pixels[2, 7, 1] == pytest.approx(expected_v/4, abs=1)
    assert pose["diagnostics"]["source_roll_deg"] == pytest.approx(90)
    assert metrics["supported_fraction"] == 1
    assert image.mode == "RGBA"


def test_rectification_applies_distortion_at_each_output_pixel():
    item = synthetic(radial=(.02, .1, .01))
    pose = camera_pose(item, ORIGIN)
    image, _ = rectify_image(coordinate_image(), item, pose, size=11)
    x, y = 9, 1
    sx = (2*(x+.5)/11 - 1)*math.tan(math.radians(20))
    sy = (2*(y+.5)/11 - 1)*math.tan(math.radians(20))
    tau = sx*sx + sy*sy
    factor = 1.02 + .1*tau + .01*tau*tau
    assert np.asarray(image)[y, x, :2] == pytest.approx([(511.5 + 1000*sx*factor)/4,
                                                       (511.5 + 1000*sy*factor)/4], abs=1)


def test_unsupported_corners_are_transparent_without_edge_fill():
    # A 45-degree roll turns the 40-degree square's corners onto the source's
    # vertical and horizontal axes: tan(20)*sqrt(2)*1100 px > 512 px, so they leave the frame.
    half = math.radians(45)/2
    item = synthetic(q=(math.cos(half), math.sin(half), 0, 0), focal=1100)
    out, metrics = rectify_image(Image.new("RGB", (1024, 1024), (123, 45, 67)),
                                 item, camera_pose(item, ORIGIN), size=129)
    pixels = np.asarray(out)
    assert 0 < metrics["transparent_fraction"] < .1
    assert pixels[0, 0].tolist() == [0, 0, 0, 0]
    assert pixels[64, 64].tolist() == [123, 45, 67, 255]
    assert metrics["supported_fraction"] + metrics["transparent_fraction"] == pytest.approx(1)


@pytest.mark.parametrize("key,value", [("camera_model_type", "CAHVORE"),
    ("instrument", "MAST_LEFT"), ("is_thumbnail", True), ("scale_factor", 2),
    ("subframe_rect", "(2,1,1024,1024)"), ("attitude", [0, 0, 0, 0]),
    ("attitude", [float("nan"), 0, 0, 1]), ("camera_model_component_list", "bad")])
def test_invalid_or_unsupported_metadata_is_rejected(key, value):
    item = synthetic()
    item[key] = value
    with pytest.raises(ValueError):
        camera_pose(item, ORIGIN)


def test_bad_source_dimensions_and_places_match_rejected():
    item = synthetic()
    with pytest.raises(ValueError):
        rectify_image(Image.new("L", (512, 512)), item, camera_pose(item, ORIGIN))
    with pytest.raises(ValueError):
        camera_pose(item, {**ORIGIN, "frame": "SITE"})
    with pytest.raises(ValueError):
        camera_pose(item, {**ORIGIN, "elevation": "nan"})
    with pytest.raises(ValueError):
        camera_pose({**item, "site": 120}, {**ORIGIN, "site": 121})


def test_real_metadata_frame_evidence_and_quaternion_agreement():
    fixture = json.loads((Path(__file__).parent / "fixtures/rover_photo_geometry.json").read_text())
    assert len({sample["item"]["sol"] for sample in fixture["samples"]}) >= 3
    for sample in fixture["samples"]:
        item, row = sample["item"], sample["places_row"]
        pose = camera_pose(item, row)
        diagnostics = pose["diagnostics"]
        assert 45 < pose["source_hfov_deg"] < 46
        assert 45 < pose["source_vfov_deg"] < 46
        assert diagnostics["vector_to_mast_deg"] < .05
        assert diagnostics["image_places_attitude_delta_deg"] < .01
        assert abs(diagnostics["image_places_yaw_delta_deg"]) < .01
        assert .03 < diagnostics["vector_to_center_deg"] < .04
        assert .2 < diagnostics["axis_to_center_deg"] < .6
        assert not diagnostics["visually_registered"]
        # API vector uses (512,512); physical image center is zero-based511.5.
        vector = np.array([float(x) for x in item["camera_vector"].strip("()").split(",")])
        u, v, valid = _project(vector, _model(item))
        assert valid
        assert [u, v] == pytest.approx([512, 512], abs=1e-3)
        flipped = copy.deepcopy(item)
        flipped["attitude"] = [-float(x) for x in item["attitude"].strip("()").split(",")]
        assert camera_pose(flipped, row)["heading"] == pytest.approx(pose["heading"])


REAL = json.loads((Path(__file__).parent / "fixtures/rover_photo_real_checks.json").read_text(encoding="utf-8"))


def test_real_stereo_pair_has_the_navcam_baseline_with_the_right_camera_on_the_right():
    # Physical facts, not the module's formulas: the Navcam pair is 42.4 cm apart across
    # the view, on a mast about 2 m above the rover origin. A swapped axis, a mirrored
    # image or an inverted attitude puts the right camera on the left or the mast below.
    left, right = (camera_pose(s["item"], s["places_row"]) for s in REAL["stereo_pair"])
    assert REAL["stereo_pair"][0]["item"]["instrument"] == "NAV_LEFT_B"
    baseline = np.array([right[k] - left[k] for k in "xyz"])
    heading = left["heading"]
    to_the_right = np.array([math.cos(heading), -math.sin(heading)])   # east, north
    forward = np.array([math.sin(heading), math.cos(heading)])
    assert np.linalg.norm(baseline) == pytest.approx(0.424, abs=0.01)
    assert baseline[:2] @ to_the_right > 0.40
    assert abs(baseline[:2] @ forward) < 0.05
    assert math.degrees(abs(left["heading"] - right["heading"])) < 1
    for pose, sample in zip((left, right), REAL["stereo_pair"]):
        assert 1.7 < pose["z"] - float(sample["places_row"]["elevation"]) < 2.2


def test_real_drives_go_along_the_rover_forward_axis_of_the_attitude():
    # The rover drives forward: the attitude's +X must follow the PLACES track. With the
    # inverse rotation the same drives point 100 degrees or more away.
    def angles(rotate):
        result = []
        for start, end in REAL["drive_hops"]:
            motion = np.array([float(end["easting"]) - float(start["easting"]),
                               float(end["northing"]) - float(start["northing"])])
            ned = sum(rotate([float(r[k]) for k in ("quat_s", "quat_v1", "quat_v2", "quat_v3")]) @ [1, 0, 0]
                      for r in (start, end))
            facing = np.array([ned[1], ned[0]])
            cosine = motion @ facing / np.linalg.norm(motion) / np.linalg.norm(facing)
            result.append(math.degrees(math.acos(np.clip(cosine, -1, 1))))
        return result
    from src.viz3d.rover_photo_geometry import _rotation
    assert len(REAL["drive_hops"]) == 20
    assert sum(angle < 15 for angle in angles(_rotation)) >= 18
    assert sum(angle < 15 for angle in angles(lambda q: _rotation(q).T)) <= 2


def test_image_attitude_is_used_even_when_places_yaw_differs():
    item = synthetic(q=(math.sqrt(.5), 0, 0, math.sqrt(.5)))
    row = {**ORIGIN, "quat_s": 1, "quat_v1": 0, "quat_v2": 0, "quat_v3": 0, "yaw": 0}
    pose = camera_pose(item, row)
    assert math.degrees(pose["heading"]) == pytest.approx(90)
    assert pose["diagnostics"]["image_places_attitude_delta_deg"] == pytest.approx(90)
    assert pose["diagnostics"]["image_places_yaw_delta_deg"] == pytest.approx(90)
