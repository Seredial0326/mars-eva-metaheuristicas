import { copyFileSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const video = dirname(fileURLToPath(import.meta.url));
const repo = dirname(video);
const project = join(video, 'composicion');
const destination = join(project, 'assets', 'resultados');
const scenes = join(project, 'compositions');
const figures = ['fig1_convergence', 'fig7_performance_profile', 'fig6_routes', 'fig5_internal_dynamics'];
const round = n => Number(n.toFixed(6));
const decimal = text => text.replace(/(\d)\.(\d)/g, '$1,$2');

function graph(name, description) {
  return `<img class="research-figure" src="assets/resultados/${name}.png" alt="${description}">`;
}
function clip(id, start, end, html, className = '', track = 1) {
  return `<section id="${id}" class="clip ${className}" data-start="${round(start)}" data-duration="${round(end-start)}" data-track-index="${track}" data-layout-allow-overlap>${html}</section>`;
}
function template(number, duration, css, content, animation='') {
  const id = `escena-${number}`;
  return `<template>
<style>
#root {position:absolute;inset:0;overflow:hidden;background:#111b21;color:#f3f1e9;font:32px/1.28 "Segoe UI",Arial,sans-serif}
#root * {box-sizing:border-box}
${css}
</style>
<div id="root" data-composition-id="${id}" data-width="1920" data-height="1080" data-duration="${duration}">
${content}
</div>
<script>
{
 const tl = gsap.timeline({paused:true});
${animation}
 window.__timelines["${id}"] = tl;
}
</script>
</template>
`;
}

function sourceTable() {
  const readme = readFileSync(join(repo, 'docs/lab/README.md'), 'utf8');
  const section = readme.split('## 7. Resultados de la corrida final')[1].split('## 8.')[0];
  const rows = section.split('| Algoritmo | n = 20')[1].split('\n').slice(2,6);
  const summary = section.match(/el gap medio es (GA[\s\S]*?)\s*;/)[1];
  const global = Object.fromEntries([...summary.matchAll(/(GA|ACO|SA|ILS)\s+(\d+\.\d+)\s*%/g)].map(m=>[m[1],m[2]]));
  return rows.map(row => {
    const [algorithm, ...cells] = row.split('|').slice(1,-1).map(s => s.trim());
    if (!global[algorithm] || cells.length !== 5) throw Error(`Fila de resultados inesperada: ${row}`);
    const rates = cells.slice(0,4).map(cell => {
      const match = cell.match(/^([\d.]+) \(([\d.]+)\)$/);
      if (!match) throw Error(`Celda inesperada: ${cell}`);
      return `<td>${decimal(match[1])}<small>${Math.round(+match[2]*100)} %</small></td>`;
    });
    return `<tr class="row-${algorithm}"><th scope="row">${algorithm}</th><td class="global">${decimal(global[algorithm])} %</td>${rates.join('')}<td>${decimal(cells[4])}</td></tr>`;
  }).join('\n');
}
function table(highlight) {
  return `<div class="s5-table ${highlight}"><h2>Calidad de las metaheurísticas</h2>
<p class="s5-description">Brecha media frente a la referencia, en %. Debajo, corridas que alcanzan la referencia.</p>
<table><thead><tr><th>Método</th><th>Brecha global</th><th>20 nodos</th><th>50 nodos</th><th>80 nodos</th><th>100 nodos</th><th>Mediana de tiempo</th></tr></thead><tbody>${sourceTable()}</tbody></table>
<div class="s5-reference"><span>Corrida final · 16 instancias</span><span>docs/lab/README.md · §7</span></div></div>`;
}

function scene5(t) {
  const style = `
.s5-shot {position:absolute;inset:0;padding:72px 96px 58px}
.s5-kicker,.s5-reference {color:#77dfdb;font-size:27px;letter-spacing:.06em;font-weight:600}
.s5-shot h2 {font-size:66px;line-height:1.1;letter-spacing:-.032em;margin:14px 0 26px;font-weight:650}
.s5-shot .research-figure {display:block;object-fit:contain;background:#fffdfa;max-width:100%;max-height:100%}
.s5-wide {width:100%;margin:52px 0 30px}
.s5-compare {display:flex;align-items:baseline;gap:36px;font-size:34px;margin-top:38px}
.s5-compare strong {font-size:53px;font-weight:600;color:#ff9a66}
.s5-limit {font-size:27px;color:#c6d0ce;margin-top:16px}
.s5-table table {width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;text-align:left;margin-top:52px}
.s5-table .s5-description {font-size:30px;color:#c6d0ce;margin:0}
.s5-table th,.s5-table td {padding:20px 20px;border-bottom:1px solid #49565d;vertical-align:middle}
.s5-table thead th {font-size:25px;font-weight:500;color:#c6d0ce}
.s5-table tbody th,.s5-table tbody td {font-size:39px;font-weight:500}
.s5-table .global {font-weight:650}
.s5-table small {display:block;font-size:22px;color:#bdcbc9;font-weight:400}
.s5-table.ga .row-GA,.s5-table.aco .row-ACO {background:#28393e;box-shadow:inset 5px 0 #77dfdb}
.s5-table.ga .row-GA .global,.s5-table.aco .row-ACO .global {color:#77dfdb}
.s5-reference {display:flex;justify-content:space-between;margin-top:34px;font-size:23px;letter-spacing:.015em}
.s5-split {display:grid;grid-template-columns:505px minmax(0,1fr);align-items:center;gap:55px;height:820px}
.s5-split .s5-display {font-size:99px;font-weight:600;letter-spacing:-.055em;line-height:1.05;color:#77dfdb}
.s5-split h2 {font-size:59px}
.s5-split p {font-size:31px;color:#d6dddd}
.s5-split img {width:auto;max-height:790px;margin:auto}
`;
  const header = '<div class="s5-kicker">Resultados sin ventanas</div>';
  const cmp = `<h2>Convergencia hacia la referencia</h2><div class="s5-wide">${graph(figures[0],'Convergencia por tamaño de instancia')}</div>
<div class="s5-compare"><span>20 nodos</span><strong>0,93 s</strong><span>DP</span><strong>0,61 s</strong><span>CP-SAT</span></div>
<div class="s5-limit">Mediana de tiempo de los métodos exactos. En 80 y 100 nodos se usa la mejor solución conocida.</div>`;
  const profile = `<div class="s5-split"><div><h2>Perfil de desempeño</h2><div class="s5-display">90 %</div><p>de las corridas del GA llegan a la referencia.</p></div>${graph(figures[1],'Fracción de corridas frente al umbral de brecha')}</div>`;
  const routes = `<h2>Rutas sobre una misma instancia</h2><div class="s5-wide">${graph(figures[2],'Rutas de los seis algoritmos en real-n20-1-180min')}</div>
<div class="s5-compare"><span>ILS</span><strong>34,26</strong><span>puntos de 40</span></div>
<p class="s5-limit">Friedman · p = 0,086 · 16 instancias</p>`;
  const conclusion = `<div class="s5-split"><div><h2>Prueba de Friedman</h2><div class="s5-display">p = 0,086</div><p>16 instancias · α = 0,05</p><p>Se necesita más evidencia para distinguir el rendimiento de los cuatro métodos.</p></div>${graph(figures[3],'Dinámica interna de los algoritmos en la corrida final')}</div>`;
  const segments = [
    [0, t.ga, 'convergencia', cmp], [t.ga, t.profile, 'tabla-ga', table('ga')],
    [t.profile, t.aco, 'perfil', profile], [t.aco, t.friedman, 'tabla-aco', table('aco')],
    [t.friedman, t.routes, 'dinamica', conclusion], [t.routes, t.duration, 'rutas', routes],
  ];
  for (const [start,end,name] of segments) if (!(end > start)) throw Error(`Revisar tiempos de ${name}: ${start} → ${end}`);
  return template(5,t.duration,style,segments.map(([s,e,name,html])=>clip('s5-'+name,s,e,header+html,'s5-shot')).join('\n'));
}

function scene6(t) {
  const style = `
.s6-base {position:absolute;inset:0;padding:56px 60px}
.s6-base h2 {font-size:62px;font-weight:650;letter-spacing:-.035em;line-height:1.1;margin:0 0 42px 36px}
.s6-figure {position:absolute;left:60px;top:165px;width:1800px;height:720px;background:#fcfcfa}
.s6-figure img {display:block;width:100%;height:100%}
.s6-ring {position:absolute;left:905px;width:865px;height:63px;border:4px solid #304e50;border-radius:12px;background:rgba(119,223,219,.1);pointer-events:none;opacity:0}
.s6-readout {position:absolute;left:96px;right:96px;bottom:71px;display:flex;align-items:baseline;gap:38px;color:#f3f1e9;font-size:38px}
.s6-readout strong {color:#77dfdb;font-size:61px;letter-spacing:-.03em;font-weight:600;line-height:1}
`;
  const base = `<div class="s6-base"><h2>¿Qué cambia con las ventanas de horario?</h2><div class="s6-figure">
${graph('comparacion-ventanas','Brecha y porcentaje de corridas en la referencia, con y sin ventanas')}
<div id="s6-marcador" class="s6-ring" style="top:247px" data-layout-allow-overlap></div></div></div>`;
  const beats = [
    [0,t.stats,'leyenda','○ Sin ventanas','● Con ventanas'],
    [t.stats,t.p,'friedman','Prueba de Friedman','Diferencias significativas con ventanas'],
    [t.p,t.ga,'probabilidad','p = 0,0002','Prueba de Friedman con ventanas · 16 instancias'],
    [t.ga,t.aco,'ga','GA · 90 % → 94 %','Corridas que alcanzan la referencia'],
    [t.aco,t.close,'aco','ACO · 73 % → 29 %','Corridas que alcanzan la referencia'],
    [t.close,t.duration,'cierre','GA · 90 % → 94 %','Corridas que alcanzan la referencia'],
  ];
  for (const [s,e,n] of beats) if (!(e>s)) throw Error(`Revisar tiempos de ${n}: ${s} → ${e}`);
  const captions = beats.map(([s,e,n,a,b])=>clip('s6-'+n,s,e,`<strong>${a}</strong><span>${b}</span>`,'s6-readout',2)).join('\n');
  const animate = `tl.fromTo('#s6-marcador',{opacity:0},{opacity:1,duration:.22},${t.ga});
 tl.fromTo('#s6-marcador',{y:0},{y:270,duration:.37,ease:'power2.inOut',immediateRender:false},${t.aco});
 tl.fromTo('#s6-marcador',{y:270},{y:0,duration:.45,ease:'power2.inOut',immediateRender:false},${t.close});`;
  return template(6,t.duration,style,base+captions,animate);
}

// Local offsets are seconds from the first audio sample of each scene.
// An alternate timing file uses the same s5 / s6 keys as the supplied map.
const mapFile = process.argv[2] || join(video,'tiempos-graficas.json');
const timing = JSON.parse(readFileSync(mapFile,'utf8'));
mkdirSync(destination,{recursive:true}); mkdirSync(scenes,{recursive:true});
for (const figure of figures) copyFileSync(join(repo,'data/lab/runs/final/analysis',figure+'.png'),join(destination,figure+'.png'));
copyFileSync(join(repo,'data/lab/comparacion-ventanas.png'),join(destination,'comparacion-ventanas.png'));
writeFileSync(join(scenes,'escena-5.html'),scene5(timing.s5));
writeFileSync(join(scenes,'escena-6.html'),scene6(timing.s6));
