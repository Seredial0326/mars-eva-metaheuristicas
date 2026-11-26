import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdir, readdir, writeFile } from 'node:fs/promises';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const video = fileURLToPath(new URL('.', import.meta.url));
const assets = path.join(video, 'composicion/assets');
const recordings = path.join(video, 'grabaciones');
const size = { width: 1920, height: 1080 };
const base = process.env.PLANNER_URL || 'http://127.0.0.1:8000';
await mkdir(assets, {recursive:true});
await mkdir(recordings, {recursive:true});

function duration(file) {
  return Number(execFileSync('ffprobe',['-v','error','-show_entries','format=duration','-of','csv=p=0',file],{encoding:'utf8'}));
}
function encode(input, filters, seconds, output) {
  execFileSync('ffmpeg',['-v','error','-y','-i',input,...filters,'-an','-t',String(seconds),
    '-c:v','libx264','-crf','16','-preset','fast','-pix_fmt','yuv420p','-movflags','+faststart',path.join(assets,output)],{stdio:'inherit'});
}
async function capture(page,name) {
  const file = path.join(recordings,name + '.webm');
  await page.screencast.start({path:file,size,fps:30});
  return file;
}
async function terrain(page) {
  await page.waitForFunction(() => {
    const ortho = window.eval('deckgl')?.layerManager?.getLayers().find(layer => layer.id === 'ortho');
    const tiles = ortho?.state.tileset?.selectedTiles;
    return ortho?.isLoaded && tiles?.length && tiles.every(tile => tile.content);
  },null,{timeout:90000});
  await page.waitForLoadState('networkidle');
}
async function mapa(browser) {
  const names = await readdir(path.join(video,'audio'));
  const voice = names.find(name => /^(?:escena\s*0?1\.|01-)/i.test(name));
  if (!voice) throw new Error('Falta la narración de la escena 1');
  const seconds = Math.ceil(duration(path.join(video,'audio',voice))*30)/30;
  const page = await browser.newPage({viewport:size, deviceScaleFactor:1});
  await page.goto(base + '/?tips=off');
  await terrain(page);
  await page.locator('#fit-all').click();
  await page.mouse.move(1900,1016);
  await page.waitForTimeout(800);
  await terrain(page);
  const raw = await capture(page,'escena-01-mapa');
  await page.waitForTimeout(1600);
  const move = Math.min(15,seconds * 0.72);
  await page.evaluate(ms => {
    const [x,y] = habitatXY();
    fitBounds(x-390,y-390,x+390,y+390,ms);
  },move*1000);
  await page.waitForTimeout((seconds-1.6)*1000+400);
  await page.screencast.stop();
  await page.close();
  encode(raw,['-vf','fps=30,tpad=stop_mode=clone:stop_duration=1'],seconds,'mapa-inicio.mp4');
  console.log('mapa-inicio.mp4',seconds);
}
async function laboratorio(browser) {
  const page = await browser.newPage({viewport:size,deviceScaleFactor:1});
  await page.goto(base + '/lab.html');
  await page.waitForSelector('#instance option[value="real-n50-0-120min"]',{state:'attached'});
  // Focus the execution section. The real form, solver restrictions and results remain intact.
  await page.addStyleTag({content:'html{zoom:1.52}section[aria-labelledby="h-runs"]{display:none}'});
  await page.locator('#instance').selectOption('real-n50-0-120min');
  await page.locator('#seeds').fill('1');
  for (const option of await page.locator('#algs input:enabled').all()) await option.check();
  const limits = await page.locator('#alg-note').innerText();
  await page.screencast.showActions({cursor:'pointer',style:{title:'display:none'}});
  const raw = await capture(page,'escena-07-laboratorio');
  const start = performance.now();
  await page.waitForTimeout(1400);
  const [response] = await Promise.all([
    page.waitForResponse(r => new URL(r.url()).pathname === '/lab/solve',{timeout:240000}),
    page.locator('#run-btn').click()
  ]);
  if(!response.ok()) throw new Error(await response.text());
  const result = await response.json();
  await page.locator('#conv polyline').first().waitFor();
  const displayed = (performance.now()-start)/1000;
  await page.waitForTimeout(1300);
  await page.locator('#conv').evaluate(el => el.scrollIntoView({block:'center',behavior:'smooth'}));
  await page.waitForTimeout(4900);
  await page.screencast.stop();
  await page.close();
  await writeFile(path.join(recordings,'ejecucion-07.json'),JSON.stringify({instance:result.instance,
    limits,reference:result.reference,runs:result.runs.map(({algorithm,seed,prize,status,runtime_s}) =>
    ({algorithm,seed,prize,status,runtime_s})),resultAppearsAt:displayed},null,2));
  // Keep the click, the results and the convergence chart; trim the wait for the server.
  const resultStart = Math.max(2.5,displayed-0.2);
  encode(raw,['-filter_complex',`[0:v]trim=end=2.5,setpts=PTS-STARTPTS[a];[0:v]trim=start=${resultStart}:duration=5.0,setpts=PTS-STARTPTS[b];[a][b]concat=n=2:v=1:a=0,fps=30,tpad=stop_mode=clone:stop_duration=1`],7.5,'lab-final.mp4');
  console.log('lab-final.mp4',limits);
}

const browser = await chromium.launch({args:['--enable-unsafe-swiftshader']});
try {
  const scene = process.argv[2] || 'ambas';
  if (!['mapa','lab','ambas'].includes(scene)) throw Error('Usa mapa, lab o ambas');
  if (scene !== 'lab') await mapa(browser);
  if (scene !== 'mapa') await laboratorio(browser);
} finally { await browser.close(); }
