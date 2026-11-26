import { execFileSync } from 'node:child_process';
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { chromium } from 'playwright';

const video = path.dirname(fileURLToPath(import.meta.url));
const project = path.join(video, 'composicion');
const assets = path.join(project, 'assets');
const target = path.join(video, 'mars-eva-planner.mp4');
const fps = 30;
const round = n => Number(n.toFixed(6));
const native = {stdio: 'inherit', windowsHide: true};
const ff = args => execFileSync('ffmpeg',['-nostdin','-v','error','-y',...args],native);
const probe = file => Number(execFileSync('ffprobe',['-v','error','-show_entries','format=duration','-of','csv=p=0',file],{encoding:'utf8'}));
const sceneName = s => 'escena-'+s;
function cli(...args) {
  execFileSync(process.execPath,[path.resolve(video,'../.agents/skills/hyperframes/scripts/plugin-cli.mjs'),'--cli-version','0.9.96',...args],{
    ...native,cwd:project,env:{...process.env,HYPERFRAMES_BROWSER_PATH:chromium.executablePath()}
  });
}

// Approved take, in seconds. Cut on the words spoken in scene 3. A repeated
// frame holds the result while the speaker describes the route on the map.
function editPlanner(length) {
  const approved = path.join(video,'escena-03-prueba.mp4');
  const cuts = [
    [0,4.4,5.7], [4.4,10.95,8.65], [10.95,13.78,17.0],
    [13.78,17.65,20.12], [28.92,31.45,22.6],
    [17.65,24.05,24.23], [24.05,26.35,length]
  ];
  let previous = 0;
  const graph = cuts.map(([a,b,until],i) => {
    const stop = Math.round(until*fps);
    const frames = stop-previous;
    previous = stop;
    const speedFactor = Math.min(1,(frames/fps)/(b-a));
    // Isolate the original warning panel so the finished ACO route is first
    // shown when the voice introduces the result.
    const detail = i===4 ? ',crop=370:286:0:622,scale=1110:858,pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=0x111b21,setsar=1' : '';
    return `[0:v]trim=start=${a}:end=${b}${detail},setpts=(PTS-STARTPTS)*${speedFactor},fps=30,tpad=stop_mode=clone:stop_duration=12,trim=end_frame=${frames},setpts=PTS-STARTPTS[v${i}]`;
  });
  graph.push(cuts.map((_,i)=>`[v${i}]`).join('')+`concat=n=${cuts.length}:v=1:a=0[out]`);
  ff(['-i',approved,'-filter_complex',graph.join(';'),'-map','[out]','-an','-c:v','libx264','-preset','fast','-crf','16','-pix_fmt','yuv420p',path.join(assets,'plan-sincronizado.mp4')]);
  ff(['-ss','25','-i',approved,'-frames:v','1','-q:v','2',path.join(assets,'regreso-ruta.jpg')]);
}

function prepare() {
  mkdirSync(assets,{recursive:true});
  const voices = readdirSync(path.join(video,'audio'));
  const timing = [];
  let elapsed = 0;
  for (let n=1;n<=7;n++) {
    const files=voices.filter(f=>new RegExp(`^(?:escena[ _-]*0?${n}\\b|0${n}[-_. ])`,'i').test(f));
    if (files.length !== 1) throw Error('Se necesita un audio para la escena '+n+'. Encontrados: '+files);
    const source=files[0];
    const wav=path.join(assets,'voz-'+n+'.wav');
    ff(['-i',path.join(video,'audio',source),'-map','0:a:0','-vn','-ar','48000','-c:a','pcm_s16le',wav]);
    const seconds=probe(wav);
    const end=elapsed+seconds;
    timing.push({scene:n,source,start:round(elapsed),duration:seconds,end:round(end)});
    elapsed=end;
  }
  editPlanner(timing[2].duration);
  const tags=[];
  for (const {scene:n,start,duration,source} of timing) {
    const id=sceneName(n);
    const attrs=`class="clip" data-start="${start}" data-duration="${duration}" data-track-index="0"`;
    if ([2,4,5,6].includes(n)) {
      tags.push(`<div id="${id}" ${attrs} data-width="1920" data-height="1080" data-composition-id="${id}" data-composition-src="compositions/${id}.html" data-track-kind="graphics"></div>`);
    } else if (n===7) {
      const cut=7.0;
      tags.push(`<video id="laboratorio" class="clip" data-start="${start}" data-duration="${cut}" data-track-index="0" src="assets/lab-final.mp4" muted playsinline></video>`);
      tags.push(`<img id="regreso" class="clip" data-start="${round(start+cut)}" data-duration="${round(duration-cut)}" data-track-index="0" src="assets/regreso-ruta.jpg" alt="Ruta ACO de vuelta al hábitat">`);
    } else {
      const file=n===1?'mapa-inicio':'plan-sincronizado';
      tags.push(`<video id="${id}" ${attrs} src="assets/${file}.mp4" muted playsinline></video>`);
    }
    if (source) tags.push(`<audio id="voz-${n}" class="clip" data-start="${start}" data-duration="${duration}" data-track-index="2" src="assets/voz-${n}.wav"></audio>`);
  }
  const total=round(Math.ceil(elapsed*fps)/fps);
  writeFileSync(path.join(project,'tiempos.json'),JSON.stringify({fps,total,scenes:timing},null,2)+'\n');
  writeFileSync(path.join(project,'index.html'),`<!doctype html>
<html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=1920,height=1080">
<title>Mars EVA Planner · Laboratorio de metaheurísticas</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>html,body{margin:0;background:#111b21}#pelicula{position:relative;width:1920px;height:1080px;overflow:hidden}#pelicula>.clip{position:absolute;inset:0;width:100%;height:100%}</style></head><body>
<main id="pelicula" data-composition-id="main" data-start="0" data-duration="${total}" data-width="1920" data-height="1080" data-fps="30">
${tags.join('\n')}
</main><script>window.__timelines ||= {};window.__timelines.main=gsap.timeline({paused:true});</script></body></html>\n`);
  console.table(timing);
}

const action=process.argv[2];
if(action==='preparar') prepare();
else if(action==='preview') cli('preview','--background');
else if(action==='check') cli('check','--json');
else if(action==='revision') cli('snapshot','--review');
else if(action==='render') cli('render','--fps','30','--output',target);
else if(action==='verificar') {
  const {scenes,total}=JSON.parse(readFileSync(path.join(project,'tiempos.json'),'utf8'));
  const report=JSON.parse(execFileSync('ffprobe',['-v','error','-show_streams','-show_format','-of','json',target],{encoding:'utf8'}));
  const v=report.streams.find(s=>s.codec_type==='video');
  if(v?.width!==1920||v?.height!==1080||v?.avg_frame_rate!=='30/1'||!report.streams.some(s=>s.codec_type==='audio')||Math.abs(probe(target)-total)>.06) throw Error('Formato o duración inesperados');
  const dir=path.join(video,'revision');mkdirSync(dir,{recursive:true});
  const offsets=[4,20,11,11.5,11.5,17.8,5.5];
  for(const {scene,start} of scenes) ff(['-ss',String(start+offsets[scene-1]),'-i',target,'-frames:v','1','-q:v','2',path.join(dir,'escena-'+scene+'.jpg')]);
  ff(['-xerror','-i',target,'-map','0:v','-map','0:a','-f','null','-']);
  console.log(target,v.codec_name,v.width,v.height,v.avg_frame_rate,probe(target),report.streams.find(s=>s.codec_type==='audio').codec_name);
} else throw Error('Uso: node video/pelicula.mjs preparar|preview|check|revision|render|verificar');
