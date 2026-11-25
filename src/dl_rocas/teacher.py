"""E9 teacher: BoulderNet (Prieur et al. 2023, Mask R-CNN R50-FPN, Detectron2) on the
gray HiRISE orthophoto of the study box.

Runs in the separate conda env `bouldernet` (Detectron2 does not install in the API
env); see paper/notes/E9_boulders.md for the setup.

  python src/dl_rocas/teacher.py check     # precision / recall on BoulderNet's Mars patches
  python src/dl_rocas/teacher.py run       # whole box -> data/e9/boulders_teacher.gpkg

Tiling: 500 px windows (the patch size the model was trained on) every 250 px. A
detection is kept only by the tile whose central 250 x 250 px block contains its
box centre, so every boulder belongs to exactly one tile and no boulder is cut by
a tile edge (it is at least 125 px = 31 m from the edge of the tile that keeps it;
the largest boulders here are a few metres). A final mask-free NMS on boxes removes
the rare duplicates across block borders.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch

REPO = Path(__file__).resolve().parents[2]
BN = REPO / "data" / "06_bouldernet"
MODEL_DIR = BN / "zenodo_8171052_original_2023" / "extraido" / "best_model"
WEIGHTS = "model_0055999.pth"            # the one the authors recommend
DATASET = (BN / "zenodo_8171052_original_2023" / "extraido" / "Apr2023-Mars-Moon-Earth-mask-5px"
           / "Apr2023-Mars-Moon-Earth-mask-5px")
ORTHO = REPO / "data" / "base" / "ortho_gray_025.tif"
OUT_DIR = REPO / "data" / "e9"

TILE = 500
STRIDE = 250
# Inference settings from MLtools.inference.predict's docstring (the authors' values)
SCORE_THRESH = 0.10
NMS_THRESH = 0.30
SIZE_TEST = 1024
PRE_NMS_TOPK = 2000
POST_NMS_TOPK = 1000
DETECTIONS_PER_IMAGE = 2000

def load_predictor(model_dir=MODEL_DIR, weights=WEIGHTS, device=None, score_thresh=SCORE_THRESH):
    """DefaultPredictor with BoulderNet's config and weights; fails if any weight is
    missing or left over (a silent partial load would give a random head)."""
    from detectron2.config import get_cfg
    from detectron2.engine import DefaultPredictor

    cfg = get_cfg()
    cfg.set_new_allowed(True)                     # the authors' config adds custom keys
    cfg.merge_from_file(str(Path(model_dir) / "config.yaml"))
    cfg.MODEL.WEIGHTS = str(Path(model_dir) / weights)
    cfg.MODEL.DEVICE = device or ("cuda" if torch.cuda.is_available() else "cpu")
    cfg.MODEL.ROI_HEADS.SCORE_THRESH_TEST = score_thresh
    cfg.MODEL.ROI_HEADS.NMS_THRESH_TEST = NMS_THRESH
    cfg.INPUT.MIN_SIZE_TEST = SIZE_TEST
    cfg.INPUT.MAX_SIZE_TEST = SIZE_TEST
    cfg.MODEL.RPN.PRE_NMS_TOPK_TEST = PRE_NMS_TOPK
    cfg.MODEL.RPN.POST_NMS_TOPK_TEST = POST_NMS_TOPK
    cfg.TEST.DETECTIONS_PER_IMAGE = DETECTIONS_PER_IMAGE
    pred = DefaultPredictor(cfg)

    ckpt = torch.load(cfg.MODEL.WEIGHTS, map_location="cpu", weights_only=False)
    stored = set(ckpt.get("model", ckpt))
    wanted = set(pred.model.state_dict())
    missing, extra = wanted - stored, stored - wanted
    if missing or extra:
        raise RuntimeError(f"weights do not match the model: missing {sorted(missing)[:5]}, "
                           f"unexpected {sorted(extra)[:5]}")
    return pred, cfg


def to_bgr(gray):
    """uint8 gray -> the 3-channel BGR image the model was trained on."""
    return np.repeat(gray[..., None], 3, axis=2)


# ---------------------------------------------------------------- check on Mars patches

def box_iou(a, b):
    """IoU matrix between two (n, 4) / (m, 4) XYXY box arrays."""
    if len(a) == 0 or len(b) == 0:
        return np.zeros((len(a), len(b)))
    lt = np.maximum(a[:, None, :2], b[None, :, :2])
    rb = np.minimum(a[:, None, 2:], b[None, :, 2:])
    inter = np.clip(rb - lt, 0, None).prod(axis=2)
    area = lambda x: (x[:, 2] - x[:, 0]) * (x[:, 3] - x[:, 1])
    return inter / (area(a)[:, None] + area(b)[None, :] - inter)


def match(pred_masks, true_masks, thresh=0.5):
    """Greedy one-to-one matching on mask IoU (predictions in score order).
    Returns the number of true positives."""
    from pycocotools import mask as mask_util
    if len(pred_masks) == 0 or len(true_masks) == 0:
        return 0
    iou = mask_util.iou(pred_masks, true_masks, [0] * len(true_masks))
    used, tp = set(), 0
    for i in range(iou.shape[0]):
        j = int(np.argmax(np.where([k in used for k in range(iou.shape[1])], -1, iou[i])))
        if iou[i, j] >= thresh and j not in used:
            used.add(j)
            tp += 1
    return tp


def check(args):
    """Precision and recall at mask IoU 0.5 on every Mars (HiRISE, ESP_*) patch of the
    authors' dataset, by split. The model was trained on the train split, so only
    validation and test say how it generalises."""
    import cv2
    from pycocotools import mask as mask_util

    pred, _ = load_predictor(score_thresh=args.score)
    records = json.loads((DATASET / "json" / "Apr2023-Mars-Moon-Earth-mask-5px.json")
                         .read_text(encoding="utf-8"))
    mars = [r for r in records if r["file_name"].startswith("ESP_")]
    rows = []
    for r in mars:
        img = DATASET / "preprocessing" / r["dataset"] / "images" / r["file_name"]
        im = cv2.imread(str(img))
        if im is None:
            continue
        inst = pred(im)["instances"].to("cpu")
        pm = [mask_util.encode(np.asfortranarray(m.numpy().astype(np.uint8)))
              for m in inst.pred_masks]
        tm = []
        for a in r["annotations"]:
            seg = a["segmentation"]
            if isinstance(seg, dict):
                if isinstance(seg["counts"], str):
                    seg = dict(seg, counts=seg["counts"].encode())
                tm.append(seg)
            else:                                 # polygon
                tm += mask_util.frPyObjects(seg, r["height"], r["width"])
        tp = match(pm, tm)
        rows.append(dict(file=r["file_name"], split=r["dataset"], n_true=len(tm),
                         n_pred=len(pm), tp=tp))
    out = {}
    for split in ("train", "validation", "test", "all"):
        sel = [x for x in rows if split == "all" or x["split"] == split]
        if not sel:
            continue
        tp = sum(x["tp"] for x in sel)
        npred = sum(x["n_pred"] for x in sel)
        ntrue = sum(x["n_true"] for x in sel)
        out[split] = dict(patches=len(sel), boulders=ntrue, detections=npred, tp=tp,
                          precision=tp / npred if npred else None,
                          recall=tp / ntrue if ntrue else None)
        print(f"{split:10s} {len(sel):3d} patches  {ntrue:5d} boulders  {npred:5d} det  "
              f"P {out[split]['precision']:.3f}  R {out[split]['recall']:.3f}")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "teacher_check_mars.json"
    params = sum(x.numel() for x in pred.model.parameters())
    path.write_text(json.dumps(dict(score_thresh=args.score, iou=0.5, params=params, splits=out,
                                    patches=rows), indent=1), encoding="utf-8")
    print("wrote", path)


# ---------------------------------------------------------------- whole-box inference

def tile_origins(n, tile=TILE, stride=STRIDE):
    """Window starts covering [0, n) with the last window flush with the edge."""
    starts = list(range(0, max(n - tile, 0) + 1, stride))
    if starts[-1] + tile < n:
        starts.append(n - tile)
    return starts


def own_block(start, n, tile=TILE, stride=STRIDE):
    """Pixel range [lo, hi) that the window starting at `start` keeps. Neighbouring
    windows split their overlap in the middle, so the kept ranges partition [0, n)
    (also when the last window is pulled back flush with the edge). With a regular
    stride this is the central `stride` px block, (tile - stride) / 2 px from each
    inner edge."""
    starts = tile_origins(n, tile, stride)
    i = starts.index(start)
    lo = 0 if i == 0 else (starts[i - 1] + tile + start) // 2
    hi = n if i == len(starts) - 1 else (start + tile + starts[i + 1]) // 2
    return lo, hi


def mask_polygon(mask, transform):
    """Largest polygon of a boolean mask, in map coordinates."""
    from rasterio import features
    from shapely.geometry import shape
    polys = [shape(g) for g, v in features.shapes(mask.astype(np.uint8), mask=mask,
                                                    transform=transform) if v == 1]
    return max(polys, key=lambda p: p.area) if polys else None


def run(args):
    import geopandas as gpd
    import rasterio
    from rasterio.windows import Window
    from torchvision.ops import nms

    pred, _ = load_predictor(score_thresh=args.score)
    src = rasterio.open(args.ortho)
    H, W = src.height, src.width
    rows_, cols_ = tile_origins(H), tile_origins(W)
    if args.limit:
        rows_, cols_ = rows_[:args.limit], cols_[:args.limit]
    recs, t0, n_tiles = [], time.time(), len(rows_) * len(cols_)
    for i, r0 in enumerate(rows_):
        for c0 in cols_:
            win = Window(c0, r0, TILE, TILE)
            img = src.read(1, window=win)
            valid = img != (src.nodata if src.nodata is not None else -1)
            if valid.mean() < 0.5:
                continue
            inst = pred(to_bgr(img))["instances"].to("cpu")
            if len(inst) == 0:
                continue
            rlo, rhi = own_block(r0, H)
            clo, chi = own_block(c0, W)
            boxes = inst.pred_boxes.tensor.numpy()
            cx = c0 + (boxes[:, 0] + boxes[:, 2]) / 2
            cy = r0 + (boxes[:, 1] + boxes[:, 3]) / 2
            keep = (cy >= rlo) & (cy < rhi) & (cx >= clo) & (cx < chi)
            tr = src.window_transform(win)
            for k in np.flatnonzero(keep):
                m = inst.pred_masks[k].numpy() & valid
                poly = mask_polygon(m, tr)
                if poly is None:
                    continue
                b = boxes[k]
                recs.append(dict(geometry=poly, score=float(inst.scores[k]),
                                 area_m2=float(m.sum()) * abs(src.res[0] * src.res[1]),
                                 box_px=(c0 + b[0], r0 + b[1], c0 + b[2], r0 + b[3]),
                                 tile_row=r0, tile_col=c0))
        done = (i + 1) * len(cols_)
        print(f"rows {i + 1}/{len(rows_)}  tiles {done}/{n_tiles}  boulders {len(recs)}  "
              f"{time.time() - t0:.0f} s", flush=True)

    if recs:
        boxes = torch.tensor([r["box_px"] for r in recs], dtype=torch.float32)
        scores = torch.tensor([r["score"] for r in recs])
        kept = set(nms(boxes, scores, NMS_THRESH).tolist())
        recs = [r for i, r in enumerate(recs) if i in kept]
    for r in recs:
        r["diameter_m"] = 2.0 * np.sqrt(r["area_m2"] / np.pi)
        r.pop("box_px")
    gdf = gpd.GeoDataFrame(recs, geometry="geometry", crs=src.crs)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = Path(args.out)
    gdf.to_file(out, layer="boulders", driver="GPKG")
    meta = dict(model="BoulderNet (Prieur et al. 2023) Mask R-CNN R50-FPN", weights=WEIGHTS,
                ortho=str(Path(args.ortho).name), tile_px=TILE, stride_px=STRIDE,
                score_thresh=args.score, nms_thresh=NMS_THRESH, size_test=SIZE_TEST,
                params=sum(x.numel() for x in pred.model.parameters()),
                tiles=n_tiles, boulders=len(gdf), seconds=round(time.time() - t0, 1),
                device=str(pred.model.device),
                diameter_m_quantiles={str(q): float(gdf.diameter_m.quantile(q))
                                      for q in (0.05, 0.25, 0.5, 0.75, 0.95)} if len(gdf) else {})
    out.with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1))
    print("wrote", out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("check", help="precision / recall on the authors' Mars patches")
    c.add_argument("--score", type=float, default=0.5,
                   help="score threshold for the check (default 0.5)")
    c.set_defaults(func=check)
    r = sub.add_parser("run", help="whole orthophoto -> boulders GeoPackage")
    r.add_argument("--ortho", default=str(ORTHO))
    r.add_argument("--out", default=str(OUT_DIR / "boulders_teacher.gpkg"))
    r.add_argument("--score", type=float, default=SCORE_THRESH,
                   help="keep detections above this score (authors: 0.10); filter later")
    r.add_argument("--limit", type=int, default=0, help="only the first N x N tiles (test)")
    r.set_defaults(func=run)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
