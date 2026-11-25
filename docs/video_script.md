# Mars EVA Planner: 30-second video script (#123)

Owner: Diana (`@dianagrz`) · Last update: 2026-11-15

The final, word-for-word script: 9 scenes, 29.8 s, 72 words of English voice-over, burned-in English subtitles and real screen captures of the HUD, guide mode and 3D view. Anything over 30 s makes the project ineligible for Global Judging.

## Script

Nine scenes follow the Space Apps order: who we are, the challenge, the name, the idea, and the future. Every picture is a real capture of our software; the only replacement still open is **[TEAM NAME]**. The product is called **Mars EVA Planner**, the name every view of the app shows; *Martian Map* is the challenge's name.

### Scene 1 · Title · 0:00–0:03
- **Picture:** HiRISE orthophoto of the boxwork, full frame, slow push-in (100 % → 108 %).
- **On screen:** "[TEAM NAME]" (large) · "Aaron · Diana · Javier · Juan · Sebastian" · "NASA Space Apps 2026 — Martian Map challenge" (small).
- **Voice-over:** "We're team [TEAM NAME]: Aaron, Diana, Javier, Juan and Sebastian."
- **Sound:** music fades in under the voice.

### Scene 2 · The challenge · 0:03–0:08.5
- **Picture:** 3D view, low camera gliding forward over the ridges in sunlight and shadow (sol 4711, about 11:00).
- **On screen (0:04–0:08, centred):** "How far can you walk on Mars… and still get home?"
- **Voice-over:** "Our challenge: how far can an astronaut walk on Mars and still get home?"

### Scene 3 · Name and tagline · 0:08.5–0:12
- **Picture:** the 3D glide continues, darkened 40 %.
- **On screen:** "MARS EVA PLANNER" (large) · "Learn from the rover. Guarantee the human."
- **Voice-over:** "Mars EVA Planner: learn from the rover, guarantee the human."

### Scene 4 · The idea: data · 0:12–0:15
- **Picture:** HUD, tab *1 Terrain*: orthophoto; at 0:13 *Slope* switches on; the cursor rests on the chip *7 data types from 4 missions*.
- **On screen (lower third):** "NASA HiRISE · MSL Curiosity · ESA Mars Express"
- **Voice-over:** "On NASA HiRISE terrain, we price every step in Mars gravity,"

### Scene 5 · The idea: the plan · 0:15–0:18
- **Picture:** HUD, tab *3 Plan* (*EVA length* 120 min, *Energy budget* 1,000 Wh): click *Plan the walk*; the map zooms in and numbers the stations 1–8 along the route.
- **On screen (lower third):** "8 science stations · exact optimum"
- **Voice-over:** "pick the best science stations exactly,"

### Scene 6 · The idea: the way home · 0:18–0:22
- **Picture:** HUD, tab *4 Walk*: the red 30-minute line and the dashed fixed-distance circles; the route plays.
- **On screen (lower third):** "≈ 1/3 of the classic 'safe' circle can't get back in 30 min"
- **Voice-over:** "and draw the real 30-minute line home."

### Scene 7 · The future: guidance · 0:22–0:25
- **Picture:** 3D view, *Rehearse* at eye height, with the next manoeuvre and the energy and time-back meters visible.
- **On screen (lower third):** "Runs offline — no waiting for Earth"
- **Voice-over:** "Offline, on an arm tablet, it guides the walk"

### Scene 8 · The future: safety · 0:25–0:28.5
- **Picture:** guide mode in a tablet frame: *Solar storm* fires, the storm alert takes the top of the screen and the guide turns home on its own.
- **On screen:** none (the alert is the text).
- **Voice-over:** "and turns back for solar storms."

### Scene 9 · End card · 0:28.5–0:29.8
- **Picture:** orthophoto, darkened 60 %.
- **On screen:** "MARS EVA PLANNER — built for the first human walks on Mars" · "Data: NASA MRO HiRISE · USGS Gale 1 m DEM · MSL Curiosity (PLACES, RAD, REMS) · MRO CRISM · Mars Odyssey THEMIS · ESA Mars Express OMEGA" · repo link, only if the repo is public.
- **Voice-over:** none.
- **Sound:** music out by 29.8 s.

## Voice-over read-through

Record it in one take, then cut it to the scene times; at 2.5 words per second it fits with room to breathe.

```text
We're team [TEAM NAME]: Aaron, Diana, Javier, Juan and Sebastian.
Our challenge: how far can an astronaut walk on Mars and still get home?
Mars EVA Planner: learn from the rover, guarantee the human.
On NASA HiRISE terrain, we price every step in Mars gravity,
pick the best science stations exactly,
and draw the real 30-minute line home.
Offline, on an arm tablet, it guides the walk
and turns back for solar storms.
```

- **Pace:** calm and even; a short pause after "get home?" and after "the human."
- **Stress:** "get home", "exactly", "real 30-minute line", "solar storms".
- **Say:** "EVA" as the letters *E-V-A*; "HiRISE" as *HIGH-rise*; "Mars gravity", not "Martian gravity" (fewer syllables).
- **If the take runs long:** drop "the best" in line 5 first, then "on Mars" in line 2. Never speed up the voice.

## English subtitles (SRT)

Burn these into the video and upload the same file to YouTube; nudge the times to the recorded voice.

```text
1
00:00:00,000 --> 00:00:03,000
We're team [TEAM NAME]:
Aaron, Diana, Javier, Juan and Sebastian.

2
00:00:03,000 --> 00:00:08,500
Our challenge: how far can an astronaut
walk on Mars and still get home?

3
00:00:08,500 --> 00:00:12,000
Mars EVA Planner: learn from the rover,
guarantee the human.

4
00:00:12,000 --> 00:00:15,000
On NASA HiRISE terrain, we price
every step in Mars gravity,

5
00:00:15,000 --> 00:00:18,000
pick the best science stations exactly,

6
00:00:18,000 --> 00:00:22,000
and draw the real 30-minute line home.

7
00:00:22,000 --> 00:00:25,000
Offline, on an arm tablet,
it guides the walk

8
00:00:25,000 --> 00:00:28,500
and turns back for solar storms.
```

## Capture steps

Record every clip from the local demo, 8–10 s long, and cut it down in the editor; the clicks follow `docs/demo.md`.

**Set up once:**
1. `git checkout main; git pull`, then `python -m api.check_data` (all green) and `python -m uvicorn api.main:app --port 8000`.
2. Open `http://localhost:8000/?tips=off` (the in-context tips stay off in every clip), press Ctrl+F5, and plan once with the nominal limits so the cache is warm (the first plan takes 10–30 s).
3. Screen 1920 × 1080, browser full screen (F11), zoom 100 %, no bookmarks bar; OBS at 30 fps, no desktop audio.

**Clips:**

| Clip | Scene | Page | Exact actions |
|---|---|---|---|
| A | 2, 3 | `/3d/` | Set the Sun to sol 4711, about 11:00. Fly low and slowly along the ridges for 10 s, no sharp turns. |
| B | 1, 9 | HUD, *1 Terrain* | All layers off (*Slope* is on by default: switch it off), whole area in view. Hold 5 s (background for the title and end cards). |
| C | 4 | HUD, *1 Terrain* | Start on the orthophoto, with *Slope* off. Wait 1 s, switch on *Slope*, wait 1 s, move the cursor onto the chip *7 data types from 4 missions* and hold. |
| D | 5 | HUD, *3 Plan* | Habitat at the box centre, *EVA length* 120 min, *Energy budget* 1,000 Wh. Click *Plan the walk*; keep recording until the zoom ends and the numbers appear. |
| E | 6 | HUD, *4 Walk* | Keep *Compare with a fixed-distance rule* on (the default). Let the route play (Space). The red line, the dark shade and the dashed circles must all be in view, with the panel line on the falsely safe share. |
| F | 7 | `/3d/` | Press *Rehearse*; record from the first turn, with the meters visible. |
| G | 8 | `/guide.html` (or *Tablet* in the HUD's *4 Walk*) | Browser DevTools → device mode (tablet, landscape). Press ▶ *Walk*, wait 2 s, open *Demo controls (for the presenter)* → *Solar storm*; record until the guide has turned home. |

**Check before editing:** the numbers in clip D (8 stations) and clip E (the falsely safe share) must match what the script says. If the plan shows a different number, change the on-screen text, not the capture.

## Edit specs and upload checklist

Export 1920 × 1080, 30 fps, H.264 MP4, total length 29.8 s; check the length in the player, not on the editor timeline.

- **Subtitles:** white sans-serif on a 60 % black box, bottom centre, at least 48 px tall at 1080p, so they read on a phone.
- **On-screen text:** same font as the subtitles; lower thirds above the subtitle box, never on top of it.
- **Audio:** voice at about −14 LUFS; royalty-free music about 20 dB under the voice, or no music.
- **Transitions:** straight cuts only; one quick fade into the end card.

**Before upload (Space Apps rules):**
- [ ] [TEAM NAME] replaced in the script, the SRT and the title card.
- [ ] Length ≤ 30.0 s, end card included.
- [ ] English subtitles burned in and the SRT uploaded.
- [ ] Human voice and real captures. Anything AI-generated must be declared (and AI images or video carry a visible watermark).
- [ ] No NASA or other agency logos or branding; data named in text only.
- [ ] Music licence noted, or no music.
- [ ] Repo link on the end card only if the repo is public (still private on 15 November; Juan is making it public with the licence, #179). The landing page (`/home/`) is not online, since there is no deploy (#122), so it is not linked.
- [ ] Uploaded to YouTube as Public, and the link opens in an incognito window with no sign-in.
- [ ] Project form: one link in "Link to Project Demo"; "Use of Artificial Intelligence" says the code was written with coding agents (Claude Code, Codex) and where; all third-party code, data and images listed.
- [ ] Submitted well before 11:59 p.m. on Sunday 15 November, local event time; the submission cannot be edited afterwards.
- [ ] The 2026 submission guide checked for any change to these limits (the online guide still shows 2025 dates).

**Sources:** [Space Apps Project Submission Guide](https://www.spaceappschallenge.org/resources/project-submission-guide/) (demo limits, suggested timeline, subtitles, hosting, AI and copyright rules, deadline); [Participant FAQs](https://www.spaceappschallenge.org/resources/participant-faqs/) (2026 dates); `docs/demo.md` and `README.md` (screens, clicks and numbers).
