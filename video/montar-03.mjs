import { execFileSync } from 'node:child_process';
import { mkdirSync, readdirSync, writeFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { chromium } from 'playwright';

const video = fileURLToPath(new URL('.', import.meta.url));
const project = path.join(video, 'composicion');
const assets = path.join(project, 'assets');
mkdirSync(assets, {recursive:true});
const source = path.join(video, 'grabaciones', 'escena-03.webm');
const duration = file => Number(execFileSync('ffprobe', ['-v','error','-show_entries','format=duration','-of','csv=p=0',file], {encoding:'utf8'}).trim());
const audioFiles = readdirSync(path.join(video, 'audio'));
const voice = audioFiles.find(name => /^03-/.test(name)) ?? audioFiles.find(name => /^escena 3\.mp4$/i.test(name));
const voiceFile = voice && path.join(video, 'audio', voice);
const spoken = voiceFile ? duration(voiceFile) : 0;
const raw = duration(source);
const length = Math.ceil((spoken ? spoken + 4 : raw) * 30) / 30;
function ffmpeg(args) { execFileSync('ffmpeg', ['-hide_banner','-loglevel','error','-y',...args], {stdio:'inherit'}); }
ffmpeg(['-i',source,'-vf',`setpts=${length/raw}*PTS,fps=30,tpad=stop_mode=clone:stop_duration=1`,'-t',String(length),'-an','-c:v','libx264','-crf','15','-preset','fast','-pix_fmt','yuv420p',path.join(assets,'planificador.mp4')]);
if (voiceFile) ffmpeg(['-i',voiceFile,'-vn','-c:a','aac','-b:a','192k',path.join(assets,'voz.m4a')]);
writeFileSync(path.join(project,'index.html'), `<!doctype html>
<html lang="es"><head><meta charset="utf-8"><title>Mars EVA Planner · Escena 3</title>
<script src="https://cdn.jsdelivr.net/npm/gsap@3.15.0/dist/gsap.min.js"></script>
<style>*{margin:0} html,body,#root,video{width:1920px;height:1080px;overflow:hidden;background:#12171b} video{display:block}</style></head>
<body><main id="root" data-composition-id="main" data-start="0" data-duration="${length}" data-width="1920" data-height="1080">
<video id="planificador" class="clip" data-start="0" data-duration="${length}" data-track-index="0" src="assets/planificador.mp4" muted playsinline></video>
${voice ? `<audio id="voz" class="clip" data-start="0" data-duration="${spoken}" data-track-index="1" src="assets/voz.m4a"></audio>` : ''}
</main><script>window.__timelines ||= {}; window.__timelines.main = gsap.timeline({paused:true});</script></body></html>\n`);
const launcher = path.resolve(video,'../.agents/skills/hyperframes/scripts/plugin-cli.mjs');
const settings = {cwd:project,stdio:'inherit',env:{...process.env,HYPERFRAMES_BROWSER_PATH:chromium.executablePath()}};
function hf(args) {execFileSync(process.execPath,[launcher,'--cli-version','0.9.96',...args],settings);}
hf(['check','--json']);
hf(['preview','--background']);
hf(['render','--fps','30','--output',path.join(video,'escena-03-prueba.mp4')]);
