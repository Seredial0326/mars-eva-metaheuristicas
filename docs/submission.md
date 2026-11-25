# Space Apps submission: text to paste into the form

Draft (Sebastian's Claude, 2026-11-15). The field names follow the usual Space Apps project form. **Check them against the live form when submitting.** The official submission guide could not be fetched from here (certificate error), so the limits marked *(check)* are the ones known from past editions and from other teams. Every number below comes from [`results/registry.csv`](../results/registry.csv) and matches the README and the paper.

Before submitting:
- [ ] The repository is **public**, and the data releases download without signing in (Juan).
- [x] The 30 s video is on YouTube and opens without signing in: https://www.youtube.com/watch?v=7LSQqSFdU6c (29.8 s).
- [ ] Replace every `[…]` below. Submit well before **11:59 p.m. local time, Sunday 15 November**. The form cannot be edited afterwards.

---

## Project name

Mars EVA Planner · Gale boxwork

## Team

Pense Em Mim · Aaron, Diana, Javier, Juan and Sebastian

## Challenge

Interplanetary Survival Guide: Martian Map

## High-level project summary *(check: about 200 words)*

Mars EVA Planner plans a walk on Mars that the astronaut can come back from, checked at every step. It covers 2 × 2 km of the boxwork ridges on Mount Sharp, Gale crater, where Curiosity is driving now.

From a 1 m terrain model and 25 cm HiRISE photos, it computes the metabolic energy of every step under Mars gravity, and the exact energy and time to walk home from every cell. Coming back can cost half or 1.7 times the way out. Simple rules (a fixed radius, a slope-only route, a constant oxygen rate) call 21–46 % of goals safe when their own route cannot complete them. The planner never does.

An exact solver picks the science stations that fit the time, energy and oxygen limits. The walk is rehearsed in 2D, on an arm-tablet guide with voice, and in 3D at eye height. The guide warns about radio shadows and solar storms, and learns how hard this astronaut is working: in simulation, oxygen run-outs drop from 90 % to 4.7 % of walks at 1.5 times the predicted energy use.

We tested the terrain model against Curiosity's real drive, negative results included. It runs offline, on site.

## Link to project demo *(check: one link; a video of at most 30 s, or slides)*

https://www.youtube.com/watch?v=7LSQqSFdU6c

No hosted demo: the planner runs locally (one command), and the deploy is future work.

## Final project link *(check)*

https://github.com/JuanCorredor2023/martian-map

## Detailed project description *(check: what it does, how it works, benefits, tools)*

**What it does.**
- **Planner (HUD):** layers, science stations, time/energy/O₂ limits, the best station tour, and a rehearsal with the safety lines on the map: the 30 min emergency-oxygen line and the area out of reach with the energy left.
- **Arm tablet guide:** turn-by-turn voice; "can I get back?" meters; a way home that checks energy, time and oxygen on the same path; re-routing when off route; solar-storm return; plan-against-the-walk summary.
- **3D rehearsal:** the 1 m terrain at eye height under the Sun of the EVA's sol, the map layers, and 383 Curiosity Navcam photos at their real camera poses.
- **Wrist card:** a printable step list with turn-back rules.

**How it works.**
1. Metabolic cost of each move on a directed graph of 4 million cells: Santee et al. 2001, a 124.2 kg suited astronaut, g = 3.71 m/s².
2. One reversed shortest-path search gives the return cost from every cell. Every plan is checked at every vertex: energy used plus energy to get home must fit the budget.
3. An exact orienteering solver (dynamic programming / CP-SAT) chooses the stations; it reached the optimum in 100 % of the benchmark.
4. During the walk, a Bayesian filter learns the astronaut's own consumption factor.
5. Validation against Curiosity's traverse (5,247 localized poses):
   - terrain explains the valley the rover chose (AUC 0.73) but not its path inside the boxwork (0.53);
   - only sand mapped from the orthophoto earns a small, learned price (up to +11.5 % energy).

**Benefits.**
- A return guarantee that follows the terrain, not a circle. The fixed radius would need a 4× safety factor to be safe in 99 % of cases.
- Decisions on site, without Earth (3–22 min light delay).
- Every reported figure is traceable: a registry of 68 results with script, output file and checksum, plus a checker.

**Tools.** Python (NumPy, SciPy, rasterio/GDAL, FastAPI, OR-Tools, PyTorch), JavaScript (deck.gl, three.js), all running on a local server. Code under MIT; paper and docs under CC BY 4.0.

**Limitations, stated plainly.**
- The guarantee is exact on the model's costs, not on a real astronaut.
- The adaptive reserve is tested only in simulation.
- The 1 m terrain model does not resolve the 1–3 m ridges.
- The sand map finds about one in nine sand pixels.

## Use of artificial intelligence *(check)*

- **The app itself calls no AI model.** Every layer, route and check is computed by ordinary code, and the planner never invents a route.
- **Neural networks used offline as detectors on the orbital photo:** a U-Net trained by the team for sand (E8), and BoulderNet (Prieur et al. 2023, published weights) distilled into a small network for boulders (E9). Their outputs are validated against blind labels and reported with their errors.
- **Development:** the team used AI coding agents (Anthropic Claude Code and OpenAI Codex) to write and review code, tests, notes, the paper draft and this text. Each member ran their own agent. The agents coordinated on a shared message board in the repository's issues. Humans chose the approach, reviewed the results and approved every merge.
- **Video:** no AI-generated voice, image or music. The voice is a team member's recording; every picture is a real screen capture of the app. The captures were recorded and edited (cuts, titles, subtitles) with a coding agent (Claude Code).

## NASA data *(check)*

- **HiRISE** 1 m DTM and 25 cm orthophoto of Gale (MRO): NASA/JPL-Caltech/University of Arizona, via USGS Astrogeology (Calef & Parker 2016).
- **Curiosity (MSL):**
  - PLACES localized poses (Planetary Data System);
  - Navcam raw images;
  - RAD dose rates (PDS / SPDF);
  - REMS weather, from Centro de Astrobiología (CAB, CSIC-INTA) and NASA PDS.
- **THEMIS** night infrared (Mars Odyssey) and **CRISM** mineral detections (MRO), via NASA Mars Trek.

## Space agency partner data *(check)*

- **ESA Mars Express:**
  - OMEGA mineral detections (ESA/CNES/CNRS/IAS), via NASA Mars Trek;
  - HRSC stereo, part of the USGS Gale DEM mosaic.

## References *(check)*

The full list, with links, is in [`paper/references.md`](../paper/references.md) and [`THIRD_PARTY.md`](../THIRD_PARTY.md). Main ones:
- Santee et al. (2001); Carr, Newman & Hodges (2003); Johnson et al. (2010).
- Calef & Parker (2016), the USGS Gale DEM.
- Hassler et al. (2014), RAD.
- Prieur et al. (2023), BoulderNet.
- Ziebart et al. (2008), maximum-entropy inverse RL.
- Vansteenwegen et al. (2011), orienteering.
- Allison & McEwen (2000), Mars24.
- Software: NumPy, SciPy, GDAL, OR-Tools, PyTorch, deck.gl, three.js (licenses in THIRD_PARTY.md).

## Tags *(check)*

Mars · EVA · path planning · walkback · metabolic cost · Gale crater · Curiosity · HiRISE · orienteering · safety
