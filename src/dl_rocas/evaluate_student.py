"""E9 student as a classifier: how well does rocas.tif's network separate boulder from
ground, against the teacher in the box and against human labels on Mars?

  python src/dl_rocas/evaluate_student.py      (bouldernet env) -> data/e9/student_classification.json
  python src/dl_rocas/evaluate_student.py --student data/e9/w32_e60/student.pt       --out data/e9/w32_e60/student_classification.json     (another student)

A. Pixels (0.25 m), validation blocks of the box. Positive = teacher score >= 0.5
   on that pixel. ROC-AUC, average precision (area under precision-recall), and
   the threshold with the best F1 (with its precision, recall and IoU).
B. Objects, validation blocks. Student boulders = connected regions of
   probability >= t (t from A) with >= 4 px (1 m^2 at 0.25 m: below the detection
   floor). Matched one-to-one to teacher boulders (score >= 0.5) at mask IoU >= 0.5.
C. Objects against the authors' HUMAN labels on their 49 Mars patches (HiRISE,
   none from Gale), for the teacher (score >= 0.5, teacher.py check) and the
   student (same rule as B). The student never saw these images: it was trained
   only on the box. This measures what distillation loses against ground truth.
D. Per 1 m cell: "rocky cell" = teacher cover >= 0.25; ROC-AUC and AP of the
   student's cover.
"""

import json
import os
import sys
from pathlib import Path

import numpy as np
import torch
from skimage.measure import label

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from dl_rocas.distill import (BLOCK_PX, OUT, SOFT, STUDENT, TinyUNet, block_mean,  # noqa: E402
                              predict_image, val_blocks)
from dl_rocas.teacher import DATASET, match  # noqa: E402

MIN_PX = 4
POS = 0.5


def roc_ap(scores, labels):
    """ROC-AUC (rank formula) and average precision, without sklearn."""
    order = np.argsort(-scores, kind="stable")
    y = labels[order].astype(np.float64)
    tp = np.cumsum(y)
    fp = np.cumsum(1 - y)
    P, N = tp[-1], fp[-1]
    # AUC by trapezoids on the ROC curve
    tpr = np.concatenate([[0], tp / P])
    fpr = np.concatenate([[0], fp / N])
    auc = float(np.trapezoid(tpr, fpr))
    prec = tp / (tp + fp)
    ap = float(np.sum(prec * y) / P)
    return auc, ap


def best_f1(scores, labels, grid=np.linspace(0.05, 0.95, 19)):
    rows = []
    for t in grid:
        p = scores >= t
        tp = float((p & labels).sum())
        fp = float((p & ~labels).sum())
        fn = float((~p & labels).sum())
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn)
        f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
        rows.append(dict(threshold=round(float(t), 2), precision=prec, recall=rec, f1=f1,
                         iou=tp / (tp + fp + fn)))
    return max(rows, key=lambda r: r["f1"]), rows


def objects(prob, t):
    lab = label(prob >= t, connectivity=2)
    sizes = np.bincount(lab.ravel())
    small = np.flatnonzero(sizes < MIN_PX)
    lab[np.isin(lab, small)] = 0
    return lab


def rle_list(lab):
    from pycocotools import mask as mask_util
    ids = np.unique(lab)
    ids = ids[ids > 0]
    return [mask_util.encode(np.asfortranarray((lab == i).astype(np.uint8))) for i in ids]


def object_scores(pred_lab, true_rles):
    pm = rle_list(pred_lab)
    tp = match(pm, true_rles)
    prec = tp / len(pm) if pm else 0.0
    rec = tp / len(true_rles) if true_rles else 0.0
    return dict(true=len(true_rles), predicted=len(pm), tp=tp, precision=prec, recall=rec,
                f1=2 * prec * rec / (prec + rec) if prec + rec else 0.0)


def load_student(device, path=STUDENT):
    ck = torch.load(path, map_location=device, weights_only=True)
    m = TinyUNet(ck["width"]).to(device)
    m.load_state_dict(ck["state"])
    return m.eval()


def main():
    import argparse
    import rasterio
    from pycocotools import mask as mask_util
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--student", default=str(STUDENT))
    ap.add_argument("--out", default=str(OUT / "student_classification.json"))
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = load_student(device, args.student)
    out = {}

    with rasterio.open(REPO / "data" / "base" / "ortho_gray_025.tif") as src:
        img = src.read(1)
    with rasterio.open(SOFT) as src:
        soft = src.read(1)
    prob = predict_image(model, img, device)
    nb = img.shape[0] // BLOCK_PX
    vb = sorted(val_blocks(nb))

    # A. pixels on validation blocks
    s_parts, y_parts = [], []
    for by, bx in vb:
        sl = np.s_[by * BLOCK_PX:(by + 1) * BLOCK_PX, bx * BLOCK_PX:(bx + 1) * BLOCK_PX]
        ok = img[sl] != 0
        s_parts.append(prob[sl][ok])
        y_parts.append(soft[sl][ok] >= POS * 255)
    s, y = np.concatenate(s_parts), np.concatenate(y_parts)
    auc, ap = roc_ap(s, y)
    best, curve = best_f1(s, y)
    out["A_pixels_vs_teacher"] = dict(pixels=int(s.size), positive_share=float(y.mean()),
                                      roc_auc=auc, average_precision=ap,
                                      ap_random_baseline=float(y.mean()),
                                      best_f1=best, curve=curve)
    t = best["threshold"]
    print(f"A pixels: AUC {auc:.3f}  AP {ap:.3f} (random {y.mean():.4f})  best F1 {best['f1']:.3f} "
          f"at t={t} (P {best['precision']:.3f} R {best['recall']:.3f} IoU {best['iou']:.3f})")

    # B. objects on validation blocks vs teacher boulders (score >= 0.5)
    agg = dict(true=0, predicted=0, tp=0)
    for by, bx in vb:
        sl = np.s_[by * BLOCK_PX:(by + 1) * BLOCK_PX, bx * BLOCK_PX:(bx + 1) * BLOCK_PX]
        tl = objects(soft[sl] / 255.0, POS)
        r = object_scores(objects(prob[sl], t), rle_list(tl))
        for k in agg:
            agg[k] += r[k]
    p = agg["tp"] / agg["predicted"]
    rc = agg["tp"] / agg["true"]
    out["B_objects_vs_teacher"] = dict(agg, precision=p, recall=rc, f1=2 * p * rc / (p + rc),
                                       threshold=t, min_px=MIN_PX)
    print(f"B objects vs teacher: {agg['true']} teacher, {agg['predicted']} student, "
          f"P {p:.3f} R {rc:.3f} F1 {2 * p * rc / (p + rc):.3f}")

    # C. objects vs human labels on the authors' Mars patches
    import cv2
    records = json.loads((DATASET / "json" / "Apr2023-Mars-Moon-Earth-mask-5px.json")
                         .read_text(encoding="utf-8"))
    teacher_check = json.loads((OUT / "teacher_check_mars.json").read_text(encoding="utf-8"))
    tc = {r["file"]: r for r in teacher_check["patches"]}
    rows = []
    for r in records:
        if not r["file_name"].startswith("ESP_"):
            continue
        gray = cv2.imread(str(DATASET / "preprocessing" / r["dataset"] / "images" / r["file_name"]),
                          cv2.IMREAD_GRAYSCALE)
        if gray is None:
            continue
        tm = []
        for a in r["annotations"]:
            seg = a["segmentation"]
            if isinstance(seg, dict):
                if isinstance(seg["counts"], str):
                    seg = dict(seg, counts=seg["counts"].encode())
                tm.append(seg)
            else:
                tm += mask_util.frPyObjects(seg, r["height"], r["width"])
        sp = predict_image(model, gray, device, tile=512)
        st = object_scores(objects(sp, t), tm)
        te = tc[r["file_name"]]
        rows.append(dict(file=r["file_name"], split=r["dataset"], true=len(tm),
                         student_pred=st["predicted"], student_tp=st["tp"],
                         teacher_pred=te["n_pred"], teacher_tp=te["tp"]))
    summ = {}
    for who in ("teacher", "student"):
        tp = sum(x[f"{who}_tp"] for x in rows)
        npred = sum(x[f"{who}_pred"] for x in rows)
        ntrue = sum(x["true"] for x in rows)
        p, rc = tp / npred, tp / ntrue
        summ[who] = dict(true=ntrue, predicted=npred, tp=tp, precision=p, recall=rc,
                         f1=2 * p * rc / (p + rc))
        print(f"C {who:7s} vs human labels (49 Mars patches): P {p:.3f} R {rc:.3f} "
              f"F1 {2 * p * rc / (p + rc):.3f}")
    out["C_objects_vs_human_mars"] = dict(summ, patches=len(rows), student_threshold=t,
                                          teacher_score=teacher_check["score_thresh"],
                                          per_patch=rows)

    # D. 1 m cells: rocky cell = teacher cover >= 0.25
    tc1 = block_mean(soft.astype(np.float32) / 255.0)
    sc1 = block_mean(prob)
    okc = block_mean((img != 0).astype(np.float32)) == 1.0
    vmask = np.zeros(tc1.shape, bool)
    cb = BLOCK_PX // 4
    for by, bx in vb:
        vmask[by * cb:(by + 1) * cb, bx * cb:(bx + 1) * cb] = True
    k = okc & vmask
    yc = tc1[k] >= 0.25
    auc_c, ap_c = roc_ap(sc1[k], yc)
    out["D_cells_vs_teacher"] = dict(cells=int(k.sum()), rocky_share=float(yc.mean()),
                                     rocky_cover_threshold=0.25, roc_auc=auc_c,
                                     average_precision=ap_c)
    print(f"D 1 m cells (rocky = teacher cover >= 0.25, {yc.mean():.4f} of cells): "
          f"AUC {auc_c:.3f} AP {ap_c:.3f}")

    path = Path(args.out)
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
