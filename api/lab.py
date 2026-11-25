"""Metaheuristics lab endpoints (/lab/*): browse runs of the experiment runner, list
instances and solve one instance live. Reads LAB_DIR at request time (tests patch it)."""

import csv
import json
import math
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import List

import numpy as np
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, field_validator

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "src") not in sys.path:
    sys.path.insert(0, str(REPO / "src"))

from orienteering.lab import datasets  # noqa: E402
from orienteering.lab.run import ALGORITHMS, run_instance  # noqa: E402

LAB_DIR = REPO / "data" / "lab"
SOLVE_CPSAT_LIMIT_S = 30.0
SOLVE_DP_MAX = 18
_SAFE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_MEDIA = {".csv": "text/csv", ".png": "image/png", ".json": "application/json",
          ".geojson": "application/geo+json"}

router = APIRouter(prefix="/lab", tags=["lab"])
_meta_cache = {}


def _instances_dir():
    return Path(LAB_DIR) / "instances"


def _runs_dir():
    return Path(LAB_DIR) / "runs"


def _json_safe(x):
    """NaN and inf become null so the response is valid JSON."""
    if isinstance(x, float):
        return x if math.isfinite(x) else None
    if isinstance(x, dict):
        return {k: _json_safe(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_json_safe(v) for v in x]
    if isinstance(x, np.generic):
        return _json_safe(x.item())
    return x


def _instance_exists(name):
    return bool(_SAFE.match(name)) and all(
        (_instances_dir() / f"{name}.{e}").exists() for e in ("npz", "csv"))


class SolveRequest(BaseModel):
    instance: str
    algorithms: List[str] = Field(min_length=1, max_length=6)
    seeds: List[int] = [0]

    @field_validator("algorithms")
    @classmethod
    def known_algorithms(cls, algs):
        bad = [a for a in algs if a not in ALGORITHMS]
        if bad:
            raise ValueError(f"unknown algorithm {bad}; valid: {list(ALGORITHMS)}")
        return algs

    @field_validator("seeds")
    @classmethod
    def seeds_ok(cls, seeds):
        if not 1 <= len(seeds) <= 5:
            raise ValueError("between 1 and 5 seeds")
        if any(not 0 <= s <= 999 for s in seeds):
            raise ValueError("seeds must be in 0..999")
        return seeds

    @field_validator("instance")
    @classmethod
    def instance_exists(cls, name):
        if not _instance_exists(name):
            raise ValueError(f"unknown instance {name!r}")
        return name


def _num(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None


@router.post("/solve")
def solve(req: SolveRequest):
    """Run the chosen algorithms on one stored instance (exact reference included)."""
    inst = datasets.load(req.instance, root=_instances_dir())
    rows, traces = run_instance(inst, req.algorithms, req.seeds, dp_max=SOLVE_DP_MAX,
                                cpsat_limit_s=SOLVE_CPSAT_LIMIT_S)
    first = rows[0] if rows else {}
    reference = {"prize": _num(first.get("reference_prize")), "kind": first.get("reference_kind") or None,
                 "upper_bound": _num(first.get("upper_bound"))}
    return _json_safe({"instance": inst.name, "n": inst.problem.n, "set": inst.set,
                       "reference": reference, "runs": rows, "traces": traces,
                       "stations": inst.stations})


def _count_lines(path):
    try:
        with open(path, encoding="utf-8") as f:
            return max(sum(1 for _ in f) - 1, 0)
    except OSError:
        return 0


def _run_dir(run_id):
    if not _SAFE.match(run_id):
        raise HTTPException(status_code=404, detail="run not found")
    d = _runs_dir() / run_id
    if not d.is_dir():
        raise HTTPException(status_code=404, detail="run not found")
    return d


@router.get("/runs")
def runs():
    root = _runs_dir()
    if not root.is_dir():
        return []
    out = []
    for d in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        cfg = d / "config.json"
        created = (datetime.fromtimestamp(cfg.stat().st_mtime).isoformat(timespec="seconds")
                   if cfg.exists() else d.name)
        figs = sorted(p.name for p in (d / "analysis").glob("*.png")) if (d / "analysis").is_dir() else []
        out.append({"id": d.name, "created": created,
                    "instances": _count_lines(d / "instances.csv"), "rows": _count_lines(d / "runs.csv"),
                    "has_analysis": (d / "analysis" / "summary.csv").exists(), "figures": figs})
    return out


@router.get("/runs/{run_id}/summary")
def run_summary(run_id: str):
    path = _run_dir(run_id) / "analysis" / "summary.csv"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no analysis for this run: run orienteering.lab.analyze")
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


@router.get("/runs/{run_id}/files/{path:path}")
def run_file(run_id: str, path: str):
    base = _run_dir(run_id).resolve()
    if not path or path.startswith(("/", "\\")) or ".." in Path(path.replace("\\", "/")).parts:
        raise HTTPException(status_code=404, detail="file not found")
    target = (base / path).resolve()
    if not target.is_relative_to(base) or not target.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return FileResponse(target, media_type=_MEDIA.get(target.suffix.lower(), "application/octet-stream"))


def _instance_meta(npz):
    key, mtime = str(npz), npz.stat().st_mtime
    hit = _meta_cache.get(key)
    if hit and hit[0] == mtime:
        return hit[1]
    with np.load(npz, allow_pickle=False) as z:
        meta = {"name": npz.stem, "set": str(z["set"]), "kind": str(z["kind"]), "n": int(z["energy"].shape[0])}
    _meta_cache[key] = (mtime, meta)
    return meta


_CASE = re.compile(r"^real-n(\d+)-(\d+)$")


def _read_stations(path):
    """Rows of an instance or pool CSV (habitat first) -> (habitat, stations for the HUD)."""
    with open(path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    habitat = {"x": float(rows[0]["x"]), "y": float(rows[0]["y"])}
    stations = [{"id": r["id"], "type": r["type"], "x": float(r["x"]), "y": float(r["y"]),
                 "score": float(r["prize"]), "service_time_min": float(r["service_s"]) / 60.0}
                for r in rows[1:]]
    return habitat, stations


def _dataset_path(ds_id):
    """CSV with the stations of a dataset id, or None. A case's two scenarios share stations,
    so the 120min file stands for both."""
    if not _SAFE.match(ds_id):
        return None
    if ds_id == "pool":
        path = _instances_dir() / "pool.csv"
    elif _CASE.match(ds_id):
        path = _instances_dir() / f"{ds_id}-120min.csv"
    else:
        return None
    return path if path.is_file() else None


def _dataset_label(ds_id, n_stations):
    m = _CASE.match(ds_id)
    if m:
        return f"{m.group(1)} nodes · case {m.group(2)} ({n_stations} stations)"
    return f"Full pool ({n_stations} stations)"


@router.get("/datasets")
def lab_datasets():
    """Station sets the HUD can load: one per experiment case, then the full pool."""
    root = _instances_dir()
    if not root.is_dir():
        return []
    ids = sorted({p.name[:-len("-120min.csv")] for p in root.glob("real-n*-*-120min.csv")},
                 key=lambda i: tuple(int(v) for v in _CASE.match(i).groups())
                 if _CASE.match(i) else (10**9, 0))
    out = []
    for ds_id in [i for i in ids if _CASE.match(i)] + ["pool"]:
        path = _dataset_path(ds_id)
        if path is None:
            continue
        _, st = _read_stations(path)
        m = _CASE.match(ds_id)
        out.append({"id": ds_id, "label": _dataset_label(ds_id, len(st)),
                    "n": int(m.group(1)) if m else len(st) + 1, "stations": len(st)})
    return out


@router.get("/datasets/{ds_id}")
def lab_dataset(ds_id: str):
    path = _dataset_path(ds_id)
    if path is None:
        raise HTTPException(status_code=404, detail="dataset not found")
    habitat, st = _read_stations(path)
    return {"id": ds_id, "label": _dataset_label(ds_id, len(st)), "habitat": habitat,
            "stations": st}


@router.get("/instances")
def instances():
    root = _instances_dir()
    if not root.is_dir():
        return []
    return [_instance_meta(p) for p in sorted(root.glob("*.npz")) if (root / f"{p.stem}.csv").exists()]


@router.get("/instances/{name}")
def instance(name: str):
    if not _instance_exists(name):
        raise HTTPException(status_code=404, detail="instance not found")
    inst = datasets.load(name, root=_instances_dir())
    gj = _instances_dir() / f"{name}.geojson"
    p = inst.problem
    return _json_safe({"name": inst.name, "set": inst.set, "kind": inst.kind, "n": p.n,
                       "budget": float(p.budget), "max_duration_s": p.max_duration_s,
                       "stations": inst.stations,
                       "geojson": json.loads(gj.read_text(encoding="utf-8")) if gj.exists() else None})
