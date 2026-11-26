"""Build editable HyperFrames scenes from the solver source and the GA trace.

Run with Python 3. Optional argument: a JSON file overriding the named cue times
in seconds relative to the beginning of each narration.
"""
import csv
import html
import io
import json
import keyword
from pathlib import Path
import sys
import tokenize


VIDEO = Path(__file__).resolve().parent
REPO = VIDEO.parent
OUT = VIDEO / "composicion" / "compositions"
OUT.mkdir(parents=True, exist_ok=True)
CUES = {
    "2": {"duration": 30.293333, "dp": 5.71, "cpsat": 7.16, "ils": 11,
          "sa": 13.23, "aco": 15.11, "ga": 16.14, "pool": 19.02, "samples": 23.17,
          "sizes": 25.23, "limits": 27.17},
    "4": {"duration": 27.1535, "ils": 0, "sa": 3.54, "aco": 8.64,
          "ga": 15.24, "repair": 16.92, "logging": 20.04, "trace": 24.37},
}
if len(sys.argv) > 1:
    for scene, override in json.loads(Path(sys.argv[1]).read_text(encoding="utf-8")).items():
        if scene in CUES:
            CUES[scene].update(override)

CSS = """
#root { position:absolute; inset:0; overflow:hidden; background:#111b21; color:#f3f1e9;
  font-family:Arial,Helvetica,sans-serif; }
#root * { box-sizing:border-box; }
.source-head {display:flex;justify-content:space-between;align-items:center;
  padding:0 0 24px;border-bottom:2px solid #526267; font-size:28px; color:#cbd7d7}
.source-head strong {font-size:30px;color:#f2a478}
.scene-padding {position:absolute;inset:66px 108px 68px}
.scene-padding h1 {font-weight:600;letter-spacing:-2.6px}
"""


def composition(scene, content, style, script):
    duration = CUES[scene]["duration"]
    return f"""<template>
<style>{CSS}{style}</style>
<div id="root" data-composition-id="escena-{scene}" data-width="1920" data-height="1080" data-duration="{duration}">
{content}
</div>
<script>
(()=>{{
const tl = gsap.timeline({{paused:true}});
{script}
window.__timelines["escena-{scene}"] = tl;
}})();
</script>
</template>
"""


def overview():
    cue = CUES["2"]
    exact = [("dp", "DP", "Programación dinámica"), ("cpsat", "CP-SAT", "CP-SAT de Google OR-Tools")]
    heuristics = [("ils", "ILS", "Búsqueda local iterada"), ("sa", "SA", "Recocido simulado"),
                  ("aco", "ACO", "Colonia de hormigas"), ("ga", "GA", "Algoritmo genético")]
    def column(heading, rows):
        content = "".join(f'<div class="algorithm" id="alg-{key}"><b>{symbol}</b><span>{name}</span></div>'
                          for key, symbol, name in rows)
        return f'<section><h2>{heading}</h2>{content}</section>'
    body = f"""
<div class="scene-padding">
  <header class="source-head"><strong>Mars EVA Planner</strong><span>Diseño del experimento</span></header>
  <h1>Seis algoritmos para planear la ruta</h1>
  <div class="families">{column('Exactos',exact)}{column('Metaheurísticas',heuristics)}</div>
  <div class="sampling">
    <div id="alg-pool"><small>Conjunto completo</small><strong>120 estaciones</strong></div>
    <div id="alg-sizes"><small id="alg-samples">16 instancias experimentales</small><strong>20, 50, 80 y 100 nodos</strong><p>El hábitat cuenta como un nodo.</p></div>
    <div id="alg-limits"><small>Diseño de las corridas</small><strong>120 y 180 min</strong><p>3 semillas aleatorias</p></div>
  </div>
</div>"""
    style = """
.scene-padding h1 {margin:43px 0 47px;font-size:78px}
.families {display:grid;grid-template-columns:1fr 1fr;gap:86px}
.families h2 {margin:0 0 15px;font-size:44px;color:#79dfd7;font-weight:600}
.families section:first-child h2 {color:#ffac83}
.algorithm {display:flex;align-items:center;gap:24px;height:82px;border-top:1px solid #42565c;font-size:39px}
.algorithm b {font:600 30px Consolas,monospace;color:#b9cdce;min-width:128px}
.sampling {position:absolute;bottom:0;left:0;right:0;border-top:3px solid #93a4a6;
 display:grid;grid-template-columns:1fr 1.42fr 1fr;padding:30px 0 0;gap:42px}
.sampling>div+div {border-left:1px solid #46595d;padding-left:36px}
.sampling small {color:#b9cbcb;font-size:28px}
.sampling strong {display:block;font-size:47px;margin-top:14px;font-weight:600;letter-spacing:-1.6px}
.sampling p {font-size:27px;margin:12px 0 0;color:#c4d5d5}
"""
    animation = [f'''tl.fromTo("#alg-samples",{{color:"#b9cbcb"}},{{color:"#89ebe3",duration:0.18}}, {cue["samples"]});''']
    keys = [row[0] for row in exact + heuristics] + ["pool", "sizes", "limits"]
    for index, key in enumerate(keys):
        start = cue[key]
        end = cue[keys[index+1]] if index+1 < len(keys) else cue["duration"]
        color = "#ffb18c" if key in ("dp", "cpsat") else "#89ebe3"
        selector = f"#alg-{key} " + ("span" if index < 6 else "strong")
        animation.append(f'''tl.to("{selector}",{{color:"{color}",duration:0.18}}, {start});''')
        animation.append(f'''tl.to("{selector}",{{color:"#f3f1e9",duration:0.18}}, {max(start+.18,end-.2):.3f});''')
    return composition("2", body, style, "\n".join(animation))


def excerpt(name, first, last, emphasized):
    filename = REPO / "src" / "orienteering" / "solvers" / f"{name}.py"
    source = filename.read_text(encoding="utf-8")
    lines = source.splitlines()
    def find(needle, offset=0):
        matches = [index for index, line in enumerate(lines) if index >= offset and needle in line]
        if len(matches) != 1:
            raise ValueError(f"Expected one matching line in {filename}: {needle!r}")
        return matches[0]
    start = find(first)
    end = find(last, start)
    indent = min(len(line)-len(line.lstrip()) for line in lines[start:end+1] if line.strip())
    spans = {}
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        row, col = token.start
        if token.end[0] != row:
            continue
        color = {tokenize.NUMBER:"num",tokenize.COMMENT:"comment",tokenize.STRING:"str"}.get(token.type)
        if token.type == tokenize.NAME and keyword.iskeyword(token.string):
            color = "kw"
        if color:
            spans.setdefault(row - 1, []).append((col,token.end[1],color))
    rendered = []
    for pos in range(start, end+1):
        line = lines[pos]
        cursor = indent
        pieces = []
        for col, stop, color in spans.get(pos, []):
            pieces.append(html.escape(line[cursor:col]))
            pieces.append(f'<i class="{color}">{html.escape(line[col:stop])}</i>')
            cursor = stop
        pieces.append(html.escape(line[cursor:]))
        cls = "line active" if any(needle in line for needle in emphasized) else "line"
        rendered.append(f'<div class="{cls}"><span class="ln">{pos+1}</span><code>{"".join(pieces)}</code></div>')
    return '<div class="snippet">' + "\n".join(rendered) + '</div>'


def trace_table():
    filename = REPO / "data/lab/runs/final/traces/trace_ga.csv"
    with filename.open(encoding="utf-8",newline="") as stream:
        reader = csv.DictReader(stream)
        rows = [next(reader) for _ in range(5)]
    columns = ["iter","pop_best","pop_mean","pop_worst","diversity"]
    headings = "".join(f"<th>{k}</th>" for k in columns)
    rendered = "".join("<tr>"+"".join(f"<td>{html.escape(row[k])}</td>" for k in columns)+"</tr>" for row in rows)
    return f'<p class="instance">{rows[0]["instance"]} &nbsp;·&nbsp; Semilla {rows[0]["seed"]}</p><table><thead><tr>{headings}</tr></thead><tbody>{rendered}</tbody></table>'


def implementation():
    cue = CUES["4"]
    title = {"sa":"Aceptar una ruta peor", "aco":"Elegir la siguiente estación", "ga":"Cruzar rutas y reparar el hijo",
             "ils":"Perturbar la ruta", "logging":"Registrar cada generación", "trace":"Leer la traza de búsqueda"}
    code = {
        "sa": excerpt("sa","cand_score = score(cand)","best = list(current)",["math.exp(delta / temp)"]),
        "aco":excerpt("aco","weight = tau[at, cand]","tau[at, nxt] = (1 - RHO)",["weight = tau","< Q0","tau[at, nxt] ="]),
        "ga":excerpt("ga","segment = inner_a[i:j]","return [a[0], *segment",["segment =","return [a[0]"])
            + excerpt("ga","child = crossover(a, b, rng)","children.append(ev.insert_greedy(child))",["ev.repair(child)"]),
        "ils":excerpt("ils","shake_at = (shake_at - 1)","shake_size += 1",["removed = set","shake_at +=","shake_size +="]),
        "logging":excerpt("ga","points = [ev.points(r) for r in pop]","diversity=len({tuple",["trace(iter=","pop_best=max(points)","diversity=len"]),
        "trace":trace_table(),
    }
    order = sorted(title, key=cue.__getitem__)
    panels = []
    for i, key in enumerate(order):
        start = cue[key]
        end = cue[order[i+1]] if i+1<len(order) else cue["duration"]
        if end <= start:
            raise ValueError(f"Scene 4 cues out of order at {key}.")
        filename = {"logging":"ga.py","trace":"trace_ga.csv"}.get(key, key+".py")
        folder = "src/orienteering/solvers/" if key != "trace" else "data/lab/runs/final/traces/"
        panels.append(f"""
<div id="source-{key}" class="clip sheet" data-track-index="0" data-start="{start}" data-duration="{end-start:.5f}">
 <div class="scene-padding">
  <header class="source-head"><strong>Mars EVA Planner</strong><span>{'Código fuente' if key!='trace' else 'Datos de la corrida'}</span></header>
  <h1>{title[key]}</h1>
  <div class="listing"><div class="filepath">{folder}<b>{filename}</b></div>{code[key]}</div>
 </div></div>""")
    style = """
.sheet {position:absolute;inset:0;background:#111b21}
.sheet h1 {margin:38px 0 35px;font-size:73px}
.listing {border:1px solid #455b65;background:#18262d;padding-bottom:19px}
.filepath {background:#223239;color:#b5c5c9;padding:22px 34px;font:30px Consolas,monospace}
.filepath b {color:#8de9e1}
.snippet {margin:23px 0 0}
.snippet+.snippet {border-top:1px dashed #52646a;padding-top:14px;margin-top:14px}
.line {display:flex;align-items:center;min-height:54px;border-left:4px solid transparent}
.line.active {background:#233b40;border-left-color:#6fd5cf}
.ln {text-align:right;color:#94a8af;min-width:100px;padding-right:32px;font:25px Consolas,monospace}
.line code {white-space:pre;font:32px Consolas,'Courier New',monospace;color:#eff4ec}
.line i {font-style:normal}
.kw {color:#ffa985}.num {color:#b9e79c}.str {color:#f2d49e}.comment {color:#acc0c3}
.listing table {width:calc(100% - 68px);margin:22px 34px;border-collapse:collapse;font:31px Consolas,monospace}
.listing th,.listing td {padding:18px 10px;text-align:left;border-bottom:1px solid #41535a}
.listing th {color:#7bddda}.listing td {color:#eff4ec}.listing td:first-child {color:#ffbb92}
.instance {font:29px Consolas,monospace;color:#d3e1df;margin:26px 44px 12px}
"""
    animate = f'''tl.fromTo("#source-ga .snippet + .snippet",{{opacity:0.48}},{{opacity:1,duration:0.18}}, {cue["repair"]});'''
    return composition("4","\n".join(panels),style,animate)


for number, build in [(2,overview),(4,implementation)]:
    (OUT / f"escena-{number}.html").write_text(build(),encoding="utf-8")
