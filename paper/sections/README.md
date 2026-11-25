# paper/sections/ · the article, one file per section

The paper is written here in Markdown (#127). It is assembled from the notes in `../notes/`, and converted to LaTeX with Pandoc only at the end. **Deadline (internal):** the hackathon delivery. **Coordinator:** JB.

## Who writes what

Each owner drafts only **areas that are already finished** (note in "done"). Pieces still in progress (the #120 experiments: C2 in #156 and C5 in #161, not merged; C4 not started) are added when they land. E6's ACO and GA (#94) and E12 on E5's tours (#147) are in. Each file starts with a comment giving its owner, its source notes and its status (`to draft` → `drafted` → `reviewed`).

| File | Section | Owner |
|---|---|---|
| `00_abstract.md` | Abstract (last) | JB |
| `01_introduction.md` | 1. Introduction | JB |
| `02_study_area_data.md` | 2. Study area and data | JB, Juan, Aaron |
| `03_01_grid_terrain_sand.md` | 3.1 Base grid, terrain, boxwork sand (E8) | JB |
| `03_02_traverse_learned_cost.md` | 3.2 Curiosity's traverse (E2) and learned price (E1) | Juan |
| `03_03_metabolic_cost.md` | 3.3 Metabolic and O2 cost (E3) | Sebas |
| `03_04_graph_walkback.md` | 3.4 Graph, R(v), walkback, baselines (E4) | Aaron |
| `03_05_orienteering.md` | 3.5 Orienteering (E5) and benchmark (E6) | Diana |
| `03_06_boulders.md` | 3.6 Boulders (E9, X1) | Aaron |
| `03_07_radiation.md` | 3.7 Radiation dose (E12) | Juan |
| `03_08_radio_adaptive_walkback.md` | 3.8 Radio (E11) and adaptive walkback (X2) | JB |
| `03_09_departure_time.md` | 3.9 Best time to leave (P6) | Diana |
| `03_10_product.md` | 3.10 Product: API, HUD, guide, 3D, photos | Sebas, Juan |
| `04_results.md` | 4. Results | JB assembles; owners give 1–3 key results |
| `05_discussion.md` | 5. Discussion | JB assembles from the Limitations |
| `06_conclusions.md` | 6. Conclusions | JB |

## How to write (so the LaTeX step is automatic)

- **English, paper style.** Short and dense: a Methods subsection is about half a page. Copy facts from your note; the note keeps the detail.
- **Numbers** come from your note, which cites the script and the output. Do not retype them from memory.
- **Citations:** `[@Parker2016]`, with the keys of `../references.md`. A new source first goes into `references.md`.
- **Figures:** `![Caption in one or two sentences.](../figures/e4_fig1_rv_map.png){#fig:e4-rv}`. In the text, write `Figure @fig:e4-rv`. Pick at most 1–2 figures per piece.
- **Equations:** `$E = M\,\Delta t$` inline, `$$...$$` on its own line.
- **Tables:** pipe tables, no merged cells.
- **One file per section,** and edit only yours, so there are no merge conflicts. Small PRs (`<issue>-paper-<piece>`), with "Refs #127".

## Build (at the end)

```bash
cd paper/sections
pandoc 0*.md -o ../paper.pdf --citeproc --number-sections   # or -o ../paper.tex
```

Pandoc is not installed in the team environment yet, and `--citeproc` needs a `.bib`: `references.md` will be converted to `references.bib` (same keys) in that step. The conversion is the last step; until then the Markdown reads on GitHub as is.
