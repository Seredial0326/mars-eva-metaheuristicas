"""E9 distillation: BoulderNet (teacher, src/dl_rocas/teacher.py) -> a tiny U-Net
(student) that maps the gray orthophoto to a per-pixel boulder probability, and
from it rocas.tif: the fraction of each 1 m cell covered by boulders.

  python src/dl_rocas/distill.py targets   # teacher polygons -> soft target rasters
  python src/dl_rocas/distill.py train     # student on spatial blocks (train / val)
  python src/dl_rocas/distill.py predict   # student on the whole box -> data/e9/rocas.tif

Soft target (knowledge distillation, Hinton et al. 2015): each 0.25 m pixel gets the
score of the teacher's boulder mask that covers it (the highest if several), 0
elsewhere. The student learns the teacher's confidence, not a hard 0/1 mask.

Split: the box is cut in 8 x 8 blocks of 250 m; every 5th block in a fixed
checkerboard-like pattern is validation (13 of 64 blocks, ~20 %), never seen in
training. Metrics on validation: pixel BCE, per-cell (1 m) MAE and correlation of
rock cover against the teacher, and boulder counts.

Runs in the `bouldernet` env (torch with CUDA) or any env with torch + rasterio.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

REPO = Path(__file__).resolve().parents[2]
BASE = REPO / "data" / "base"
ORTHO = BASE / "ortho_gray_025.tif"
OUT = REPO / "data" / "e9"
TEACHER = OUT / "boulders_teacher.gpkg"
SOFT = OUT / "teacher_soft_025.tif"        # uint8, score x 255, 0.25 m
COVER_T = OUT / "teacher_cover_1m.tif"     # float32, teacher rock cover per 1 m cell
STUDENT = OUT / "student.pt"
ROCAS = OUT / "rocas.tif"

UP = 4                                     # 0.25 m pixels per 1 m cell
BLOCK_PX = 1000                            # 250 m blocks
CROP = 256
MEAN, STD = 98.22, 30.0                    # teacher's pixel mean; std set from the box


# ---------------------------------------------------------------- targets

def rasterise_soft(gpkg, ortho_path):
    import geopandas as gpd
    import rasterio
    from rasterio import features
    g = gpd.read_file(gpkg).sort_values("score")       # higher scores drawn last
    with rasterio.open(ortho_path) as src:
        prof, shape, tr = src.profile, (src.height, src.width), src.transform
    soft = features.rasterize(((geom, int(round(s * 255))) for geom, s in zip(g.geometry, g.score)),
                              out_shape=shape, transform=tr, fill=0, dtype="uint8",
                              all_touched=False)
    return soft, prof


def block_mean(a, k=UP):
    h, w = a.shape[0] // k, a.shape[1] // k
    return a[:h * k, :w * k].reshape(h, k, w, k).mean(axis=(1, 3))


def base_profile():
    import rasterio
    with rasterio.open(BASE / "dem_1m.tif") as src:
        p = src.profile.copy()
    p.update(dtype="float32", nodata=np.nan, count=1, compress="deflate")
    return p


def targets(args):
    import rasterio
    soft, prof = rasterise_soft(args.teacher, args.ortho)
    OUT.mkdir(parents=True, exist_ok=True)
    p = prof.copy()
    p.update(dtype="uint8", nodata=None, count=1, compress="deflate")
    with rasterio.open(SOFT, "w", **p) as dst:
        dst.write(soft, 1)
    with rasterio.open(args.ortho) as src:
        valid = src.read(1) != 0
    cover = block_mean(soft.astype(np.float32) / 255.0).astype(np.float32)
    cover[block_mean(valid.astype(np.float32)) < 1.0] = np.nan
    with rasterio.open(COVER_T, "w", **base_profile()) as dst:
        dst.write(cover, 1)
    print(f"soft target: {(soft > 0).mean():.4f} of pixels inside a boulder; "
          f"mean cover {np.nanmean(cover):.4f}; wrote {SOFT.name}, {COVER_T.name}")


# ---------------------------------------------------------------- student

def conv(cin, cout):
    return nn.Sequential(nn.Conv2d(cin, cout, 3, padding=1, bias=False), 
                         nn.BatchNorm2d(cout),
                         nn.ReLU(inplace=True),
                         nn.Conv2d(cout, cout, 3, padding=1, bias=False), 
                         nn.BatchNorm2d(cout),
                         nn.ReLU(inplace=True))


class TinyUNet(nn.Module):
    """3-level U-Net, widths w, 2w, 4w (w=16 -> 0.23 M parameters, w=32 -> 0.93 M). Receptive field
    ~ 40 px = 10 m, enough for boulders of a few metres and their shadows."""

    def __init__(self, w=16):
        super().__init__()
        self.e1, self.e2, self.e3 = conv(1, w), conv(w, 2 * w), conv(2 * w, 4 * w)
        self.mid = conv(4 * w, 4 * w)
        self.u3, self.d3 = nn.ConvTranspose2d(4 * w, 4 * w, 2, 2), conv(8 * w, 2 * w)
        self.u2, self.d2 = nn.ConvTranspose2d(2 * w, 2 * w, 2, 2), conv(4 * w, w)
        self.u1, self.d1 = nn.ConvTranspose2d(w, w, 2, 2), conv(2 * w, w)
        self.head = nn.Conv2d(w, 1, 1)

    def forward(self, x):
        e1 = self.e1(x)
        e2 = self.e2(F.max_pool2d(e1, 2))
        e3 = self.e3(F.max_pool2d(e2, 2))
        m = self.mid(F.max_pool2d(e3, 2))
        d3 = self.d3(torch.cat([self.u3(m), e3], 1))
        d2 = self.d2(torch.cat([self.u2(d3), e2], 1))
        d1 = self.d1(torch.cat([self.u1(d2), e1], 1))
        return self.head(d1)                              # logits


def n_params(m):
    return sum(p.numel() for p in m.parameters())


def val_blocks(n_blocks):
    """(by, bx) block indices held out for validation: a fixed 1-in-5 diagonal
    pattern, so validation is spread over the whole box."""
    return {(by, bx) for by in range(n_blocks) for bx in range(n_blocks) if (by * 2 + bx) % 5 == 0}


def load_arrays(ortho_path):
    import rasterio
    with rasterio.open(ortho_path) as src:
        img = src.read(1)
    with rasterio.open(SOFT) as src:
        soft = src.read(1)
    return img, soft


def sample_crops(img, soft, blocks, n, rng):
    """n random CROP x CROP crops whose window lies inside one of `blocks`
    (so a crop never straddles train and validation) and is >= 95 % valid."""
    xs, ys = [], []
    blocks = list(blocks)
    while len(xs) < n:
        by, bx = blocks[rng.integers(len(blocks))]
        r = by * BLOCK_PX + rng.integers(0, BLOCK_PX - CROP + 1)
        c = bx * BLOCK_PX + rng.integers(0, BLOCK_PX - CROP + 1)
        im = img[r:r + CROP, c:c + CROP]
        if (im != 0).mean() < 0.95:
            continue
        xs.append(im)
        ys.append(soft[r:r + CROP, c:c + CROP])
    return np.stack(xs), np.stack(ys)


def to_tensor(x, device):
    return ((torch.from_numpy(x).float() - MEAN) / STD).unsqueeze(1).to(device)


def augment(x, y):
    k = int(torch.randint(0, 4, (1,)))
    x, y = torch.rot90(x, k, (2, 3)), torch.rot90(y, k, (2, 3))
    if torch.rand(1) < 0.5:
        x, y = x.flip(3), y.flip(3)
    return x, y


@torch.no_grad()
def predict_image(model, img, device, tile=1024, pad=32):
    """Per-pixel probability over a whole image, tiled with a `pad` px overlap that
    is discarded (no seams)."""
    model.eval()
    H, W = img.shape
    out = np.zeros((H, W), np.float32)
    for r in range(0, H, tile):
        for c in range(0, W, tile):
            r0, c0 = max(r - pad, 0), max(c - pad, 0)
            r1, c1 = min(r + tile + pad, H), min(c + tile + pad, W)
            sub = img[r0:r1, c0:c1]
            ph, pw = (-sub.shape[0]) % 8, (-sub.shape[1]) % 8      # 3 poolings
            x = to_tensor(np.pad(sub, ((0, ph), (0, pw)), mode="reflect")[None], device)
            p = torch.sigmoid(model(x))[0, 0].cpu().numpy()[:sub.shape[0], :sub.shape[1]]
            out[r:min(r + tile, H), c:min(c + tile, W)] = \
                p[r - r0:r - r0 + min(tile, H - r), c - c0:c - c0 + min(tile, W - c)]
    return out


def block_mask(shape, blocks):
    m = np.zeros(shape, bool)
    for by, bx in blocks:
        m[by * BLOCK_PX:(by + 1) * BLOCK_PX, bx * BLOCK_PX:(bx + 1) * BLOCK_PX] = True
    return m


def cover_metrics(p_student, soft, valid, region):
    """Per 1 m cell rock cover: student vs teacher on `region` (bool, 0.25 m)."""
    t = block_mean(soft.astype(np.float32) / 255.0)
    s = block_mean(p_student)
    ok = block_mean((valid & region).astype(np.float32)) == 1.0
    # 10 m windows (what a route planner feels); NaN where any cell is outside
    t10 = block_mean(np.where(ok, t, np.nan), 10).ravel()
    s10 = block_mean(np.where(ok, s, np.nan), 10).ravel()
    k = ~np.isnan(t10)
    t, s = t[ok], s[ok]
    return dict(cells=int(ok.sum()), teacher_mean_cover=float(t.mean()),
                student_mean_cover=float(s.mean()), mae=float(np.abs(s - t).mean()),
                pearson_r=float(np.corrcoef(s, t)[0, 1]),
                windows_10m=int(k.sum()), mae_10m=float(np.abs(s10[k] - t10[k]).mean()),
                pearson_r_10m=float(np.corrcoef(s10[k], t10[k])[0, 1]))


def train(args):
    device = "cuda" if torch.cuda.is_available() else "cpu"
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    img, soft = load_arrays(args.ortho)
    nb = img.shape[0] // BLOCK_PX
    val = val_blocks(nb)
    trn = {(by, bx) for by in range(nb) for bx in range(nb)} - val
    xv, yv = sample_crops(img, soft, val, 64, np.random.default_rng(0))
    xv, yv = to_tensor(xv, device), torch.from_numpy(yv).float().unsqueeze(1).to(device) / 255
    model = TinyUNet(args.width).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps = args.epochs * args.steps
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, args.lr, total_steps=steps)
    # pos_weight 1 keeps the student calibrated: with soft targets the BCE optimum
    # is the teacher's expected value, so the mean cover is not inflated
    pos_w = torch.tensor(args.pos_weight, device=device)
    log, best, t0 = [], np.inf, time.time()
    for ep in range(args.epochs):
        model.train()
        tl = 0.0
        for _ in range(args.steps):
            xb, yb = sample_crops(img, soft, trn, args.batch, rng)
            xb = to_tensor(xb, device)
            yb = torch.from_numpy(yb).float().unsqueeze(1).to(device) / 255
            xb, yb = augment(xb, yb)
            loss = F.binary_cross_entropy_with_logits(model(xb), yb, pos_weight=pos_w)
            opt.zero_grad()
            loss.backward()
            opt.step()
            sched.step()
            tl += loss.item()
        model.eval()
        with torch.no_grad():
            vl = float(np.mean([F.binary_cross_entropy_with_logits(
                model(xv[i:i + 16]), yv[i:i + 16], pos_weight=pos_w).item()
                for i in range(0, len(xv), 16)]))
        log.append(dict(epoch=ep + 1, train_loss=tl / args.steps, val_loss=vl))
        print(f"epoch {ep + 1:2d}  train {tl / args.steps:.4f}  val {vl:.4f}  "
              f"{time.time() - t0:.0f} s", flush=True)
        if vl < best:
            best = vl
            torch.save(dict(state=model.state_dict(), width=args.width), STUDENT)

    ck = torch.load(STUDENT, map_location=device, weights_only=True)
    model.load_state_dict(ck["state"])
    p = predict_image(model, img, device)
    valid = img != 0
    metrics = dict(params=n_params(model), width=args.width, epochs=args.epochs,
                   steps_per_epoch=args.steps, batch=args.batch, crop=CROP, lr=args.lr,
                   pos_weight=args.pos_weight, seed=args.seed, best_val_loss=best,
                   train_seconds=round(time.time() - t0, 1),
                   val_blocks=sorted(map(list, val)), n_blocks=nb * nb,
                   cover_val=cover_metrics(p, soft, valid, block_mask(img.shape, val)),
                   cover_train=cover_metrics(p, soft, valid, block_mask(img.shape, trn)),
                   log=log)
    (OUT / "student_metrics.json").write_text(json.dumps(metrics, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in metrics.items() if k != "log"}, indent=1))


def predict(args):
    import rasterio
    device = "cuda" if torch.cuda.is_available() else "cpu"
    ck = torch.load(STUDENT, map_location=device, weights_only=True)
    model = TinyUNet(ck["width"]).to(device)
    model.load_state_dict(ck["state"])
    with rasterio.open(args.ortho) as src:
        img = src.read(1)
    if device == "cuda":
        torch.cuda.synchronize()
    t0 = time.time()
    p = predict_image(model, img, device)
    if device == "cuda":
        torch.cuda.synchronize()
    secs = time.time() - t0
    cover = block_mean(p).astype(np.float32)
    cover[block_mean((img != 0).astype(np.float32)) < 1.0] = np.nan
    with rasterio.open(args.out, "w", **base_profile()) as dst:
        dst.write(cover, 1)
        dst.update_tags(units="fraction of the 1 m cell covered by boulders (0-1)",
                        source="E9 student (TinyUNet distilled from BoulderNet), src/dl_rocas/distill.py",
                        caveat="boulders below ~1 m (4 px at 0.25 m) are not detected")
    meta = dict(seconds_whole_box=round(secs, 2), device=device, params=n_params(model),
                mean_cover=float(np.nanmean(cover)),
                cover_quantiles={str(q): float(np.nanquantile(cover, q))
                                 for q in (0.5, 0.9, 0.99, 0.999)})
    Path(args.out).with_suffix(".json").write_text(json.dumps(meta, indent=1), encoding="utf-8")
    print(json.dumps(meta, indent=1), "\nwrote", args.out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ortho", default=str(ORTHO))
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("targets")
    t.add_argument("--teacher", default=str(TEACHER))
    t.set_defaults(func=targets)
    tr = sub.add_parser("train")
    tr.add_argument("--width", type=int, default=32)
    tr.add_argument("--epochs", type=int, default=30)
    tr.add_argument("--steps", type=int, default=100)
    tr.add_argument("--batch", type=int, default=16)
    tr.add_argument("--lr", type=float, default=3e-3)
    tr.add_argument("--pos-weight", type=float, default=1.0)
    tr.add_argument("--seed", type=int, default=9)
    tr.set_defaults(func=train)
    pr = sub.add_parser("predict")
    pr.add_argument("--out", default=str(ROCAS))
    pr.set_defaults(func=predict)
    args = ap.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
