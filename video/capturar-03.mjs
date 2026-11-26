import { chromium } from 'playwright';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const folder = fileURLToPath(new URL('./grabaciones/', import.meta.url));
await mkdir(folder, { recursive: true });
const size = { width: 1920, height: 1080 };
const browser = await chromium.launch({ args: ['--enable-unsafe-swiftshader'] });
const results = {};

async function terrain(page) {
  await page.waitForFunction(() => {
    const ortho = window.eval('deckgl')?.layerManager?.getLayers().find(layer => layer.id === 'ortho');
    return ortho?.isLoaded && ortho.state.tileset?.selectedTiles?.some(tile => tile.content);
  }, null, { timeout: 90000 });
}

async function run(record) {
  const page = await browser.newPage({ viewport: size, deviceScaleFactor: 1 });
  const hold = ms => page.waitForTimeout(record ? ms : 50);
  await page.goto('http://127.0.0.1:8000/?tips=off');
  await terrain(page);
  if (record) {
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(750);
    await page.screencast.showActions({ cursor: 'pointer', style: {title: 'display:none'} });
    await page.screencast.start({ path: path.join(folder, 'escena-03.webm'), size, fps: 30 });
  }
  const start = performance.now();
  for (const [dataset, solver, minutes] of [['real-n20-0', 'dp', '120'], ['pool', 'aco', '180']]) {
    await hold(500);
    await page.locator('#tab-stations').click();
    await page.locator('#lab-dataset').selectOption(dataset);
    await hold(700);
    await page.locator('#load-lab').click();
    await page.waitForFunction(id => window.eval('labDataset')?.id === id, dataset);
    await hold(1150);
    await page.locator('#tab-plan').click();
    await options(page);
    await page.locator('#solver').selectOption(solver);
    await hold(450);
    await page.locator('#max-min').fill(minutes);
    await hold(550);
    const t = performance.now();
    const [res] = await Promise.all([page.waitForResponse(r => new URL(r.url()).pathname === '/plan', {timeout:180000}), page.locator('#plan-btn').click()]);
    if (!res.ok()) throw Error(await res.text());
    await page.waitForFunction(() => !document.querySelector('#plan-btn').hasAttribute('aria-busy'));
    const seconds = (performance.now() - t) / 1000;
    await page.waitForTimeout(800);
    await terrain(page);
    const stats = await page.locator('#plan-info .stats').innerText();
    const result = {stats, solver: await page.locator('#plan-solver').innerText(), seconds, at: (performance.now()-start)/1000};
    console.log(record ? 'Grabación' : 'Calentamiento', solver, result);
    if (record) results[solver] = result;
    await hold(3400);
  }
  if (record) {
    await options(page);
    await page.locator('#solver').selectOption('cpsat');
    await hold(650);
    await page.locator('#plan-btn').click();
    const warning = page.getByText(/supports up to 59 plus the habitat/i).first();
    await warning.waitFor();
    await warning.scrollIntoViewIfNeeded();
    results.warning = await warning.innerText();
    await hold(3800);
    await page.screencast.stop();
    await writeFile(path.join(folder, 'resultados-03.json'), JSON.stringify(results, null, 2));
  }
  await page.close();
}

async function options(page) {
  for (const selector of ['#plan-inputs', '#plan-inputs .more']) {
    const details = page.locator(selector);
    if (!await details.evaluate(el => el.open)) await details.locator('summary').first().click();
  }
}

try { await run(false); await run(true); }
finally { await browser.close(); }
