"""Calibrated full-resolution MSL Navcam geometry, without image registration.

The API's CAHVOR vectors are in rover navigation coordinates (forward, right,
down), supported by mast-angle/vector agreement and the MSL camera SIS. Image
attitude is scalar-first and rotates rover vectors into site north/east/down.
PLACES supplies the localized rover origin; image telemetry supplies attitude.
Only full 1024-square images at scale 1 are supported. No guessed crop scaling.

References: NASA-AMMOS/VICAR vos/p2/sub/cahvor/cmod_cahvor.c (CAHVOR equations);
PLACES_PDS_SIS.pdf sections 2.1 and 6 (frames and quaternion direction).
"""

from __future__ import annotations

import math
from collections.abc import Mapping

import numpy as np
from PIL import Image

RECTIFIED_FOV_DEG = 40.0
SOURCE_SIZE = 1024
SOURCES = {
    "cahvor": "https://github.com/NASA-AMMOS/VICAR/blob/master/vos/p2/sub/cahvor/cmod_cahvor.c",
    "places": "https://planetarydata.jpl.nasa.gov/img/data/msl/msl_places/document/PLACES_PDS_SIS.pdf",
    "camera_sis": "https://planetarydata.jpl.nasa.gov/img/data/msl/MSLHAZ_0XXX/DOCUMENT/MSL_CAMERA_SIS_latest.PDF",
}


def _vector(value, count, name):
    try:
        if isinstance(value, str):
            value = value.strip().strip("()[]").split(",")
        vector = np.asarray(value, dtype=float)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid {name}") from exc
    if vector.shape != (count,) or not np.all(np.isfinite(vector)):
        raise ValueError(f"Invalid {name}: expected {count} finite components")
    return vector


def _unit(vector):
    norm = np.linalg.norm(vector, axis=-1, keepdims=True)
    if np.any(norm < 1e-12):
        raise ValueError("Degenerate vector")
    return vector / norm


def _angle(a, b):
    return float(np.degrees(np.arccos(np.clip(_unit(a) @ _unit(b), -1, 1))))


def _rotation(value):
    q = _vector(value, 4, "attitude")
    norm = np.linalg.norm(q)
    if abs(norm - 1) > 0.01:
        raise ValueError("Attitude quaternion is not unit length")
    w, x, y, z = q / norm
    return np.array([
        [1 - 2*(y*y + z*z), 2*(x*y - z*w), 2*(x*z + y*w)],
        [2*(x*y + z*w), 1 - 2*(x*x + z*z), 2*(y*z - x*w)],
        [2*(x*z - y*w), 2*(y*z + x*w), 1 - 2*(x*x + y*y)],
    ])


def _model(item):
    if not isinstance(item, Mapping):
        raise ValueError("Expected an image metadata mapping")
    if item.get("camera_model_type") != "CAHVOR":
        raise ValueError("Only CAHVOR camera models are supported")
    if item.get("instrument") not in ("NAV_LEFT_B", "NAV_RIGHT_B"):
        raise ValueError("Only MSL Navcam B images are supported")
    if item.get("is_thumbnail") is not False or item.get("extended", {}).get("sample_type") != "full":
        raise ValueError("Only full images are supported")
    try:
        scale = float(item.get("scale_factor"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Invalid scale factor") from exc
    if scale != 1 or not np.array_equal(_vector(item.get("subframe_rect"), 4, "subframe_rect"), [1, 1, 1024, 1024]):
        raise ValueError("Only uncropped 1024 x 1024 images at scale 1 are supported")
    components = item.get("camera_model_component_list")
    if isinstance(components, str):
        components = components.split(";")
    if not isinstance(components, (list, tuple)) or len(components) != 6:
        raise ValueError("Expected six CAHVOR vectors")
    model = tuple(_vector(value, 3, name) for name, value in zip("CAHVOR", components))
    c, a, h, v, o, r = model
    if abs(np.linalg.norm(a) - 1) > 1e-4 or abs(np.linalg.norm(o) - 1) > 1e-4:
        raise ValueError("CAHVOR A/O must be unit vectors")
    if abs(np.linalg.det(np.array([a, h, v]))) < 1e-6:
        raise ValueError("Degenerate camera calibration")
    # Rounded metadata are retained for A/H/V; only O is normalized for radial math.
    return c, a, h, v, _unit(o), r


def _project(rays, model):
    """Rover-frame rays to zero-based source sample/line and forward validity."""
    _, a, h, v, o, r = model
    omega = rays @ o
    safe = np.where(np.abs(omega) > 1e-12, omega, np.nan)
    transverse = rays - omega[..., None] * o
    tau = np.sum(transverse * transverse, axis=-1) / (safe * safe)
    mu = r[0] + r[1] * tau + r[2] * tau * tau
    distorted = rays + mu[..., None] * transverse
    depth = distorted @ a
    with np.errstate(invalid="ignore", divide="ignore"):
        u, v = (distorted @ h) / depth, (distorted @ v) / depth
    valid = (omega > 0) & (depth > 0) & np.isfinite(u) & np.isfinite(v)
    return u, v, valid


def _unproject(u, v, model):
    """Invert CAHVOR radial distortion, rejecting a nonmonotonic solution."""
    _, a, h, vertical, o, r = model
    distorted = _unit(np.cross(vertical - v*a, h - u*a))
    if distorted @ a < 0:
        distorted = -distorted
    omega = distorted @ o
    if omega <= 1e-12:
        raise ValueError("Image ray is behind the optical axis")
    transverse = distorted / omega - o
    observed = np.linalg.norm(transverse)
    radius = observed
    for _ in range(40):
        tau = radius * radius
        derivative = 1 + r[0] + 3*r[1]*tau + 5*r[2]*tau*tau
        if derivative <= 0:
            raise ValueError("Nonmonotonic CAHVOR distortion")
        step = (radius*(1 + r[0] + r[1]*tau + r[2]*tau*tau) - observed) / derivative
        radius -= step
        if abs(step) < 1e-13:
            break
    else:
        raise ValueError("CAHVOR inversion did not converge")
    ray = _unit(o + transverse * (radius / observed if observed > 1e-14 else 1))
    pu, pv, valid = _project(ray, model)
    if not valid or max(abs(pu-u), abs(pv-v)) > 1e-6:
        raise ValueError("CAHVOR inversion failed its pixel residual check")
    return ray


def _basis(heading, pitch):
    """Forward, screen-right and screen-down in site north/east/down."""
    sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
    return np.array([ch*cp, sh*cp, sp]), np.array([-sh, ch, 0]), np.array([-ch*sp, -sh*sp, cp])


def camera_pose(item, places_row):
    """Return map x=east,y=north,z=elevation; heading/pitch radians, FOV degrees.

    ``places_row`` is a matched PLACES ROVER row: easting/northing/elevation
    (or explicit x/y/z). Optional quat_s/quat_v1/quat_v2/quat_v3 and yaw produce
    independent consistency diagnostics. Position is rover origin + rotated C.
    """
    model = _model(item)
    rotation = _rotation(item.get("attitude"))
    if places_row.get("frame", "ROVER") != "ROVER":
        raise ValueError("Expected a PLACES ROVER frame")
    for key in ("site", "drive"):
        if key in places_row and int(places_row[key]) != int(item.get(key, -1)):
            raise ValueError(f"PLACES {key} does not match image metadata")
    try:
        origin = np.array([float(places_row.get(k, places_row.get(raw))) for k, raw in
                           (("x", "easting"), ("y", "northing"), ("z", "elevation"))])
    except (TypeError, ValueError) as exc:
        raise ValueError("PLACES position must contain finite map coordinates") from exc
    if not np.all(np.isfinite(origin)):
        raise ValueError("PLACES position must contain finite map coordinates")
    center = _unproject(511.5, 511.5, model)
    forward = rotation @ center
    heading = math.atan2(forward[1], forward[0]) % (2*math.pi)
    pitch = math.atan2(forward[2], math.hypot(forward[0], forward[1]))
    if math.hypot(forward[0], forward[1]) < 1e-6:
        raise ValueError("Horizon-level orientation is undefined at the pole")
    offset = rotation @ model[0]
    position = origin + [offset[1], offset[0], -offset[2]]
    # FOV is measured between physical image boundaries at the center line.
    hfov = _angle(_unproject(-0.5, 511.5, model), _unproject(1023.5, 511.5, model))
    vfov = _angle(_unproject(511.5, -0.5, model), _unproject(511.5, 1023.5, model))
    right = rotation @ _unit(_unproject(512.5, 511.5, model) - center)
    _, level_right, level_down = _basis(heading, pitch)
    diagnostics = {
        "image_id": item.get("imageid"), "metadata_id": item.get("id"),
        "model_frame": "ROVER_NAV_FRAME", "world_frame": "site_north_east_down",
        "frame_evidence": "MSL camera SIS; raw camera_vector versus mast angles",
        "attitude_source": "image.attitude (w,x,y,z)", "sources": dict(SOURCES),
        "center_pixel": [511.5, 511.5], "center_ray_rover": center.tolist(),
        "center_ray_ned": forward.tolist(), "camera_offset_ned_m": offset.tolist(),
        "axis_to_center_deg": _angle(model[1], center),
        "source_roll_deg": math.degrees(math.atan2(right @ level_down, right @ level_right)),
        "image_rover_yaw_deg": math.degrees(math.atan2(rotation[1, 0], rotation[0, 0])) % 360,
        "visually_registered": False,
    }
    if item.get("camera_vector") is not None:
        vector = _unit(_vector(item["camera_vector"], 3, "camera_vector"))
        diagnostics["vector_to_center_deg"] = _angle(vector, center)
        extended = item.get("extended", {})
        if extended.get("mast_az") is not None and extended.get("mast_el") is not None:
            az, el = math.radians(float(extended["mast_az"])), math.radians(float(extended["mast_el"]))
            mast = np.array([math.cos(az)*math.cos(el), math.sin(az)*math.cos(el), -math.sin(el)])
            diagnostics["vector_to_mast_deg"] = _angle(vector, mast)
    qkeys = ("quat_s", "quat_v1", "quat_v2", "quat_v3")
    if all(key in places_row for key in qkeys):
        places_rotation = _rotation([places_row[key] for key in qkeys])
        cosine = np.clip((np.trace(rotation.T @ places_rotation) - 1) / 2, -1, 1)
        diagnostics["image_places_attitude_delta_deg"] = float(np.degrees(np.arccos(cosine)))
    if "yaw" in places_row:
        delta = diagnostics["image_rover_yaw_deg"] - float(places_row["yaw"])
        diagnostics["image_places_yaw_delta_deg"] = (delta + 180) % 360 - 180
    return {"x": float(position[0]), "y": float(position[1]), "z": float(position[2]),
            "heading": heading, "pitch": pitch, "fov": RECTIFIED_FOV_DEG,
            "source_hfov_deg": hfov, "source_vfov_deg": vfov, "diagnostics": diagnostics}


def rectify_image(image: Image.Image, item, pose, size=768):
    """Resample a 40-degree square with zero roll and transparent missing pixels.

    Each output pixel center defines a horizon-level pinhole ray. Its inverse
    attitude rotation and CAHVOR forward projection locate the original pixel.
    Bilinear interpolation only; no sharpening, colour adjustment or inpainting.
    """
    model = _model(item)
    rotation = _rotation(item.get("attitude"))
    if image.size != (SOURCE_SIZE, SOURCE_SIZE):
        raise ValueError("Source pixels must be 1024 x 1024")
    if isinstance(size, bool) or not isinstance(size, int) or not 1 <= size <= 4096:
        raise ValueError("Output size must be an integer from 1 to 4096")
    try:
        heading, pitch, fov = (float(pose[k]) for k in ("heading", "pitch", "fov"))
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError("Invalid rectification pose") from exc
    if not all(math.isfinite(x) for x in (heading, pitch, fov)) or fov != RECTIFIED_FOV_DEG:
        raise ValueError("Rectification requires finite angles and a 40-degree FOV")
    forward, right, down = _basis(heading, pitch)
    source = np.asarray(image.convert("RGBA"), dtype=float)
    source[..., :3] *= source[..., 3:4] / 255  # interpolate premultiplied alpha
    result = np.zeros((size, size, 4), dtype=np.uint8)
    axis = (2*(np.arange(size) + .5)/size - 1) * math.tan(math.radians(fov)/2)
    valid_count = 0
    for start in range(0, size, 128):
        stop = min(start + 128, size)
        world = forward + axis[None, :, None]*right + axis[start:stop, None, None]*down
        u, v, valid = _project(world @ rotation, model)
        valid &= (u >= 0) & (u <= 1023) & (v >= 0) & (v <= 1023)
        # All bilinear taps must be inside source support; no clamped edge fill.
        safe_u, safe_v = np.where(valid, u, 0), np.where(valid, v, 0)
        x0, y0 = np.floor(safe_u).astype(int), np.floor(safe_v).astype(int)
        x1, y1 = np.minimum(x0+1, 1023), np.minimum(y0+1, 1023)
        dx, dy = (safe_u-x0)[..., None], (safe_v-y0)[..., None]
        pixels = ((1-dy)*((1-dx)*source[y0, x0] + dx*source[y0, x1])
                  + dy*((1-dx)*source[y1, x0] + dx*source[y1, x1]))
        pixels[~valid] = 0
        alpha = pixels[..., 3:4]
        pixels[..., :3] = np.divide(pixels[..., :3]*255, alpha,
                                    out=np.zeros_like(pixels[..., :3]), where=alpha > 0)
        result[start:stop] = np.rint(np.clip(pixels, 0, 255)).astype(np.uint8)
        valid_count += int(valid.sum())
    return Image.fromarray(result), {
        "method": "CAHVOR ray projection; bilinear; zero roll", "output_size": [size, size],
        "source_size": list(image.size), "fov_deg": fov,
        "supported_fraction": valid_count / (size*size),
        "transparent_fraction": float(np.mean(result[..., 3] == 0)),
        "source_roll_deg": pose.get("diagnostics", {}).get("source_roll_deg"),
        "visually_registered": False,
    }
