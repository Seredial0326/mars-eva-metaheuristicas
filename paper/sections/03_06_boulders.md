<!-- Owner: Aaron · Sources: E9_boulders.md · Status: drafted by JB's Claude; confirmed with corrections by the owner (Aaron), 2026-11-15 -->

### 3.6 Boulders (BoulderNet, distillation and uncertainty)

**Teacher.** BoulderNet, a Mask R-CNN [@He2017] in Detectron2 [@Wu2019] with the authors' weights [@Prieur2023], is run over the 0.25 m grey orthophoto in 500 px windows every 250 px. Each detection is owned by the window whose central block contains its box centre, so no boulder is counted twice. On the authors' Mars patches it reaches precision 0.74 and recall 0.59 (score ≥ 0.5, mask IoU ≥ 0.5). None of its training patches is from Gale. Over the box it finds 8,380 boulders with score ≥ 0.10 (median equivalent diameter 1.7 m, 95th percentile 3.8 m), covering 0.37 % of the box (score-weighted), mostly in debris at the foot of scarps.

**Student.** A 3-level U-Net [@Ronneberger2015] is trained by distillation [@Hinton2015] on the teacher's per-pixel score. It has 47 times fewer parameters (0.93 M against 43.9 M) and runs over the box 42 times faster (8.6 s against 362 s). Validation uses 250 m blocks never seen in training (Figure @fig:e9-student):
- **Density:** its 1 m rock cover correlates with the teacher's at r = 0.66, with a calibrated mean cover (0.35 % against 0.33 %).
- **Ranking:** it ranks rock well (pixel AUC 0.986, average precision 0.47 against 0.003 for chance).
- **Single boulders:** its F1 against human labels is 0.27, against 0.66 for the teacher, so it is a density map, not a detector.
- **Longer training:** 60 epochs instead of 30 raise that F1 to 0.41 but lower the mean cover to 0.24 %. The delivered layer keeps the calibrated 30-epoch student.

The product, `rocas.tif`, is a density of boulders visible from orbit; boulders below about 1 m are not detected.

**Uncertainty (X1).** A Gaussian process (Matérn, on √cover) on 20 m blocks gives a mean and a predictive standard deviation of rock cover. It is checked by spatial cross-validation against the training mean and a Gaussian smoothing:
- **Mean:** it is no better than a 20 m smoothing when interpolating (RMSE 1.154 against 1.142 % cover), and only 2–3 % better when extrapolating into held-out 400 m tiles.
- **Intervals:** its 90 % intervals hold 92–93 % of held-out blocks overall, but only about 80 % of rocky blocks. The standard deviation grows with the mean.
- **What the std leaves out:** BoulderNet's own undercount (recall 0.59) and boulders below 1 m.
- **Use:** it is presented as the confidence of the orbital map, not as a guarantee.

The optional rock-risk term in the route cost, 1 + k · (mean + λ · std), stays off, because no price was validated (E1, Section 3.2).

![Rock cover in 10 m windows from (a) the teacher (BoulderNet) and (b) the distilled student (`rocas.tif`); cyan squares are validation blocks. (c) Student against teacher on validation blocks only (r = 0.66).](../figures/e9_fig2_student.png){#fig:e9-student}
