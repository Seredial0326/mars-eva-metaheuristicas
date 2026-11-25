<!-- Owner: JB · Sources: - · Status: drafted from the notes by JB's Claude; owner to confirm -->

## 1. Introduction

A Mars surface EVA is limited by the suit's consumables and by the walk back to the habitat. On Apollo, return distances were planned with fixed radii and constant consumption rates, and they were recomputed from the real consumption during the walk. On Mars, with no help from Earth during the EVA (a radio signal takes 3–22 min each way [@NASA-MarsFact]), the plan has to answer on site, and at every point: can the astronaut still get home?

The boxwork of Gale crater, a network of mineralised ridges a few metres wide enclosing sandy hollows [@Siebach2014], was Curiosity's target in 2025–2026 and is a natural target for human exploration. It is also a hard place to walk: scarps and knolls make the cost of moving strongly direction-dependent, and the features that matter (ridges, sand, boulders) are near or below the resolution of the orbital DEM.

We contribute:

1. a planner on a 1 m grid with directed metabolic costs under Mars gravity (Section 3.3), an exact return-energy layer and walkback-safe round trips (3.4), and a station tour solved exactly (3.5);
2. a test against Curiosity's traverse, with a learned terrain price that turns out to be small (3.2), and layers mapped from the 0.25 m orthophoto: sand (3.1) and boulders (3.6);
3. operational layers: radiation dose and a solar-storm alert (3.7), radio line of sight and an adaptive walkback that learns the astronaut's consumption (3.8), and the best time to leave (3.9);
4. a product that runs offline: an API, a planning HUD, an arm-tablet guide and a 3D rehearsal (3.10).

We report negative results as well as positive ones, and we state what is validated only in simulation.
