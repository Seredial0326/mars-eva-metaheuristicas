# Third-party software, data and models

Everything this project uses that the team did not write, and the license or terms each
one comes under. The team's own work is under MIT (code, [`LICENSE`](LICENSE)) and
CC BY 4.0 (paper and docs, [`LICENSE-CC-BY-4.0.txt`](LICENSE-CC-BY-4.0.txt)); see
[License](README.md#license) in the README. Nothing below is relicensed by this project:
each item keeps its own license. Licenses are as declared by each project for the
versions used; check upstream before reusing.

## 1. Code shipped in this repository

These files are copied into the repo so the pages work offline. Each keeps its license
file next to it.

| Library | Version | License | Where | License file |
|---|---|---|---|---|
| [three.js](https://threejs.org) | 0.187.0 | MIT, © 2010-2026 three.js authors | `web/3d/vendor/three/` | `web/3d/vendor/three/LICENSE` |
| [deck.gl](https://deck.gl) | 9.1.14 | MIT, © Vis.gl contributors | `web/vendor/deck.gl-9.1.14.min.js` | `web/vendor/LICENSE.deck.gl.txt` |
| [qrcode-generator](https://github.com/kazuhikoarase/qrcode-generator) | 1.4.4 | MIT, © 2009 Kazuhiko Arase | `web/vendor/qrcode-generator-1.4.4.min.js` | `web/vendor/LICENSE.qrcode-generator.txt` |

## 2. Libraries the code depends on (installed, not shipped)

Installed with pip or conda (`api/requirements.txt`, `src/dl_rocas/requirements_bouldernet.txt`).

| Library | Used for | License |
|---|---|---|
| NumPy, SciPy, pandas | arrays, sparse graphs, tables | BSD-3-Clause |
| GDAL (`osgeo`), rasterio, pyogrio | rasters, GeoPackages, line of sight (E11) | MIT (GDAL), BSD-3-Clause (rasterio), MIT (pyogrio) |
| GeoPandas, Shapely | vector data | BSD-3-Clause |
| contourpy, Matplotlib | contours, paper figures | BSD-3-Clause, Matplotlib license (PSF-based) |
| Pillow | images | MIT-CMU (HPND) |
| scikit-learn, scikit-image, threadpoolctl | baselines, image processing | BSD-3-Clause |
| OpenCV (`opencv-python-headless`) | image processing (E9) | Apache-2.0 |
| Google OR-Tools | CP-SAT solver (E5, E6) | Apache-2.0 |
| FastAPI, Pydantic | the API | MIT |
| Uvicorn, HTTPX | server, tests | BSD-3-Clause |
| pytest | tests | MIT |
| PyTorch, torchvision | U-Net (E8), distillation (E9) | BSD-3-Clause |
| segmentation_models_pytorch | U-Net (E8) | MIT |
| Detectron2, fvcore | running BoulderNet (E9) | Apache-2.0 |
| pycocotools | BoulderNet masks (E9) | BSD-2-Clause |

## 3. Models

| Model | Used for | License / terms |
|---|---|---|
| BoulderNet (Prieur et al. 2023), Mask R-CNN R50-FPN, weights `model_0055999.pth` ([Zenodo 8171052](https://zenodo.org/records/8171052)) | teacher for the boulder map (E9, `src/dl_rocas/teacher.py`) | weights and data CC BY 4.0; the authors' code MIT. **The weights are not in this repository**; only the boulder maps derived from them are published (releases `e9-rocks-v1` and `x1-rocks-gp-v1`, which must credit BoulderNet). Review the license before uploading the weights anywhere. |
| EfficientNet-B0 encoder pre-trained on ImageNet, as distributed by segmentation_models_pytorch | starting point of the sand U-Net (E8, `src/dl_boxwork/train_unet.py`) | Apache-2.0 (EfficientNet-PyTorch weights) |

The other models (the sand U-Net, the distilled TinyUNet, the learned terrain price,
the Gaussian process) were trained by the team and are under MIT with the code.

## 4. Data

All inputs are public. Our processed products (the GitHub releases listed below) add no
restriction of their own; each one stays under the terms of the source it was derived
from, and must credit it. Download details, versions and checksums:
[`data/README.md`](data/README.md) (section 9, credits and licenses).

| Data | Credit | Terms | Releases derived from it |
|---|---|---|---|
| HiRISE 1 m DTM and 25 cm orthophoto of Gale (Calef & Parker 2016) | NASA/JPL-Caltech/University of Arizona, USGS Astrogeology | public domain (USGS); HiRISE products free to use with credit | `base-grid-v2`, `tiles-v2`, `e8-v0`, `e8-v0.1`, `e9-rocks-v1`, `x1-rocks-gp-v1`, `stations-e8-v0` |
| Curiosity waypoints and localized poses (PLACES) | NASA/JPL-Caltech, Planetary Data System | public domain, credit NASA/JPL-Caltech | `e2-trajectory-v1`, `e1-sand-v1` |
| Curiosity Navcam images | NASA/JPL-Caltech | public domain, credit NASA/JPL-Caltech | 3D photo catalogue (`src/viz3d/`), screenshots |
| MSL RAD dose rate (Hassler et al. 2014) | NASA/JPL-Caltech, SwRI, PDS | public domain, credit the RAD team | `e12-dose-v1` |
| MSL REMS weather | Centro de Astrobiología (CAB, CSIC-INTA), NASA PDS | free to use with credit to CAB and the REMS team | `rems-v1` |
| THEMIS night infrared (Mars Odyssey) | NASA/JPL-Caltech/Arizona State University | public domain, credit NASA/JPL-Caltech/ASU | `themis-v1` |
| CRISM mineral detections (MRO) | NASA/JPL-Caltech/JHU-APL, via NASA Mars Trek | public domain, credit NASA/JPL-Caltech/JHU-APL | `minerals-v1` |
| OMEGA mineral detections (Mars Express) | ESA/CNES/CNRS/IAS, via NASA Mars Trek | free use with credit to ESA and the OMEGA team | `minerals-v1` |
| NASA Mars Trek tiles and services | NASA/JPL-Caltech | public, credit NASA/JPL-Caltech | none (read at run time) |
| Orienteering benchmark instances (Tsiligirides 1984) | KU Leuven (CIB), from the published literature | research benchmark, no license declared; **not redistributed** (downloaded from KU Leuven into `data/08_instancias_orienteering/`, outside git) | none |
| USGS geologic map of Mars, SIM 3292 (Tanaka et al. 2014) | USGS | public domain | none (context only) |
| AI4Mars v0.1 | NASA/JPL-Caltech | v0.1 declares no license (v0.6 is CC BY 4.0) | **downloaded but not used** by any code |

Station values, science tasks and the walking model use published results, cited in
[`paper/references.md`](paper/references.md). The Sun's position follows the Mars24
algorithm (Allison & McEwen 2000), implemented from the paper (`web/3d/mars_sun.js`,
`src/orienteering/departure.py`); the rover camera model follows the CAHVOR equations
documented in NASA-AMMOS VICAR (`src/viz3d/rover_photo_geometry.py`). No code was copied
from either.

## 5. Images in this repository

Screenshots and figures (`web/home/assets/`, `docs/img/`, `docs/user_guide/img/`,
`paper/figures/`) are the team's work under CC BY 4.0, but many show NASA imagery
(HiRISE orthophoto, Curiosity Navcam photos). Reusing them should keep the credit
*NASA/JPL-Caltech/University of Arizona* (HiRISE) or *NASA/JPL-Caltech* (Navcam).
