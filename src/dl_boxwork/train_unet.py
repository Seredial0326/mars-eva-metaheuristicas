import argparse
import json
import time
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import segmentation_models_pytorch as smp
import torch
from torch.utils.data import DataLoader, Dataset, WeightedRandomSampler

IGNORE, N_CLASSES = 255, 3
NAMES = ["background", "ridge", "trough"]
OUT = Path("e8")
MEAN = np.array([0.485, 0.456, 0.406], dtype="float32")
STD = np.array([0.229, 0.224, 0.225], dtype="float32")

parser = argparse.ArgumentParser()
parser.add_argument("--epochs", type=int, default=15)
parser.add_argument("--batch", type=int, default=8)
parser.add_argument("--lr", type=float, default=3e-4)
parser.add_argument("--weights", default="imagenet", help="encoder weights ('imagenet' or 'none')")
parser.add_argument("--out", default="unet_v1.pt")
parser.add_argument("--seed", type=int, default=0)
parser.add_argument("--no-amp", action="store_true", help="train in float32 (slower, for debugging)")
args = parser.parse_args()
torch.manual_seed(args.seed)
rng = np.random.default_rng(args.seed)
device = "cuda" if torch.cuda.is_available() else "cpu"


class Patches(Dataset):
    def __init__(self, X, Y, augment):
        self.X, self.Y, self.augment = X, Y, augment

    def __len__(self):
        return len(self.X)

    def __getitem__(self, i):
        x = self.X[i].astype("float32") / 255.0
        y = self.Y[i].astype("int64")
        if self.augment:  # orientation is arbitrary from orbit: flips + 90 degree turns
            k = rng.integers(4)
            x, y = np.rot90(x, k), np.rot90(y, k)
            if rng.random() < 0.5:
                x, y = x[:, ::-1], y[:, ::-1]
            x = x * rng.uniform(0.9, 1.1) + rng.uniform(-0.05, 0.05)  # mild brightness / contrast
        x = (x - MEAN) / STD
        return torch.from_numpy(np.ascontiguousarray(x.transpose(2, 0, 1))), torch.from_numpy(np.ascontiguousarray(y))


tr, va = np.load(OUT / "patches_train.npz"), np.load(OUT / "patches_val.npz")
Xt, Yt, Xv, Yv = tr["X"], tr["Y"], va["X"], va["Y"]

# Class weights: inverse frequency of labelled pixels, normalised, capped at 10
counts = np.array([(Yt == c).sum() for c in range(N_CLASSES)], dtype="float64")
cw = counts.sum() / np.maximum(counts, 1) / N_CLASSES
cw = np.clip(cw / cw.min(), 1, 10)
# Patch sampling weights: rare classes appear more often
has_ridge = (Yt == 1).any(axis=(1, 2))
has_sand = (Yt == 2).any(axis=(1, 2))
pw = 1.0 + 4.0 * has_ridge + 2.0 * has_sand
sampler = WeightedRandomSampler(torch.as_tensor(pw, dtype=torch.double), num_samples=len(Xt), replacement=True)

train_dl = DataLoader(Patches(Xt, Yt, True), batch_size=args.batch, sampler=sampler, num_workers=0, drop_last=True)
val_dl = DataLoader(Patches(Xv, Yv, False), batch_size=args.batch, shuffle=False, num_workers=0)

model = smp.Unet("efficientnet-b0", encoder_weights=None if args.weights == "none" else args.weights,
                 in_channels=3, classes=N_CLASSES).to(device)
ce = torch.nn.CrossEntropyLoss(weight=torch.as_tensor(cw, dtype=torch.float32, device=device), ignore_index=IGNORE)
dice = smp.losses.DiceLoss(mode="multiclass", ignore_index=IGNORE)
opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, T_max=args.epochs)
use_amp = device == "cuda" and not args.no_amp
scaler = torch.amp.GradScaler("cuda", enabled=use_amp)


def evaluate():
    model.eval()
    conf = np.zeros((N_CLASSES, N_CLASSES), dtype="int64")
    with torch.no_grad():
        for x, y in val_dl:
            with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
                p = model(x.to(device)).argmax(1).cpu().numpy()
            y = y.numpy()
            m = y != IGNORE
            conf += np.bincount(N_CLASSES * y[m] + p[m], minlength=N_CLASSES ** 2).reshape(N_CLASSES, N_CLASSES)
    iou = np.diag(conf) / np.maximum(conf.sum(0) + conf.sum(1) - np.diag(conf), 1)
    return {n: round(float(v), 4) for n, v in zip(NAMES, iou)}


log, best, best_epoch = [], -1.0, -1
print(f"device {device} | train {len(Xt)} patches, val {len(Xv)} | class weights {np.round(cw, 2).tolist()}")
for epoch in range(1, args.epochs + 1):
    model.train()
    t0, total, n, skipped = time.time(), 0.0, 0, 0
    for x, y in train_dl:
        x, y = x.to(device), y.to(device)
        opt.zero_grad(set_to_none=True)
        with torch.autocast(device_type="cuda", dtype=torch.float16, enabled=use_amp):
            out = model(x)
        out = out.float()  # losses in float32: softmax/log in float16 can overflow to NaN
        loss = ce(out, y) + dice(out, y)
        if not torch.isfinite(loss):
            skipped += 1
            continue
        scaler.scale(loss).backward()
        scaler.unscale_(opt)
        torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
        scaler.step(opt)
        scaler.update()
        total, n = total + loss.item() * len(x), n + len(x)
    sched.step()
    iou = evaluate()
    score = (iou["ridge"] + iou["trough"]) / 2  # the classes we care about
    mean_loss = total / max(n, 1)
    log.append({"epoch": epoch, "loss": round(mean_loss, 4), "val_iou_weak": iou, "score": round(score, 4),
                "skipped_batches": skipped, "sec": round(time.time() - t0, 1)})
    print(f"epoch {epoch:2d}  loss {mean_loss:.4f}  skipped {skipped}  IoU(weak) {iou}  {time.time() - t0:.0f}s")
    if score > best:
        best, best_epoch = score, epoch
        torch.save({"state_dict": model.state_dict(), "epoch": epoch, "args": vars(args),
                    "class_weights": cw.tolist()}, OUT / args.out)

(OUT / "train_log.json").write_text(json.dumps({"best_epoch": best_epoch, "best_score_weak": round(best, 4),
                                                "class_weights": cw.tolist(), "log": log}, indent=2))
fig, ax = plt.subplots(1, 2, figsize=(11, 4))
ax[0].plot([r["loss"] for r in log])
ax[0].set_title("training loss")
for n_ in NAMES:
    ax[1].plot([r["val_iou_weak"][n_] for r in log], label=n_)
ax[1].set_title("IoU vs weak labels (held-out region)")
ax[1].legend()
for a in ax:
    a.set_xlabel("epoch")
fig.tight_layout()
fig.savefig(OUT / "train_curve.png", dpi=100)
print(f"best epoch {best_epoch} (score {best:.4f}) saved to e8/{args.out}")
