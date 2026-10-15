// node graphics/render_overlay.mjs --dir work/v1/B --out out/v1/B.mp4      full render
// node graphics/render_overlay.mjs --dir work/v1/B --stills 2,10,40          stills + contact sheet for review
// Renders graphics/overlay.html frame by frame (transparent PNG via seek(t)) and composites it over
// <dir>/base.mov from pipeline/build.py, mixes synthesized SFX, normalizes to -14 LUFS.
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import { existsSync, mkdirSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const flag = (k, d) => { const i = process.argv.indexOf('--' + k); return i > 0 ? process.argv[i + 1] : d; };
const DIR = resolve(flag('dir')), OUT = flag('out'), STILLS = flag('stills');
const tl = JSON.parse(readFileSync(join(DIR, 'timeline.json'), 'utf8'));
const base = join(DIR, 'base.mov');

// CHROME_PATH overrides Playwright's bundled browser (offline installs / version mismatch)
let browser;
try { browser = await chromium.launch(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}); }
catch (e) {
  // fall back to any chromium already in the Playwright cache
  const cache = join(process.env.HOME || '', '.cache/ms-playwright');
  const found = existsSync(cache) && readdirSync(cache).filter((d) => /^chromium-\d+$/.test(d)).sort().reverse()
    .map((d) => join(cache, d, 'chrome-linux/chrome')).find(existsSync);
  if (!found) throw e;
  browser = await chromium.launch({ executablePath: found });
}
const page = await browser.newPage({ viewport: { width: tl.W, height: tl.H }, deviceScaleFactor: 1 });
await page.addInitScript((t) => { window.TIMELINE = t; }, tl);
await page.goto('file://' + join(HERE, 'overlay.html'));
await page.evaluate(() => window.READY);
const shot = async (t) => { await page.evaluate((x) => window.seek(x), t); return page.screenshot({ type: 'png', omitBackground: true }); };

const run = (args) => { const r = spawnSync('ffmpeg', ['-v', 'error', '-y', ...args], { stdio: 'inherit' }); if (r.status) process.exit(r.status); };

if (STILLS) {
  // each still = base frame + overlay at t; then a contact sheet at phone-ish size
  const sdir = join(DIR, 'stills'); mkdirSync(sdir, { recursive: true });
  const ts = STILLS === 'auto' ? Array.from({ length: 15 }, (_, i) => +(tl.dur * (i + 0.5) / 15).toFixed(2)) : STILLS.split(',').map(Number);
  const files = [];
  for (const t of ts) {
    const png = await shot(t), o = join(sdir, `ov_${t}.png`), f = join(sdir, `s_${String(t).padStart(6, '0')}.png`);
    (await import('node:fs')).writeFileSync(o, png);
    run(['-ss', String(t), '-i', base, '-i', o, '-filter_complex', `[0:v][1:v]overlay=0:0,drawtext=text='${t.toFixed(1)}s':x=20:y=20:fontsize=40:fontcolor=yellow:box=1:boxcolor=black@0.5`, '-frames:v', '1', f]);
    files.push(f);
  }
  const cols = Math.min(files.length, 5), rows = Math.ceil(files.length / cols);
  run([...files.flatMap((f) => ['-i', f]), '-filter_complex',
    files.map((_, i) => `[${i}:v]scale=360:-1[s${i}]`).join(';') + ';' + files.map((_, i) => `[s${i}]`).join('') +
    `xstack=inputs=${files.length}:layout=${files.map((_, i) => `${(i % cols) * 360}_${Math.floor(i / cols) * 640}`).join('|')}:fill=black`,
    '-frames:v', '1', join(DIR, 'contact.png')]);
  console.log(`stills -> ${join(DIR, 'contact.png')}`);
  await browser.close();
  process.exit(0);
}

// SFX bed from cues (graphics/sfx.mjs)
const cues = JSON.parse(readFileSync(join(DIR, 'sfx_cues.json'), 'utf8'));
const sfx = join(DIR, 'sfx.wav');
if (cues.length) spawnSync('node', [join(HERE, 'sfx.mjs'), join(DIR, 'sfx_cues.json'), sfx], { stdio: 'inherit' });

mkdirSync(dirname(OUT), { recursive: true });
const audio = cues.length
  ? `[0:a][2:a]amix=inputs=2:duration=first:normalize=0:weights='1 ${flag('sfx-gain', '0.45')}',loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000[a]`
  : `[0:a]loudnorm=I=-14:TP=-1.5:LRA=9,aresample=48000[a]`;
const ff = spawn('ffmpeg', ['-y', '-loglevel', 'error', '-i', base, '-f', 'image2pipe', '-framerate', String(tl.fps), '-i', '-',
  ...(cues.length ? ['-i', sfx] : []),
  '-filter_complex', `[0:v][1:v]overlay=0:0:format=auto:eof_action=pass,format=yuv420p[v];${audio}`,
  '-map', '[v]', '-map', '[a]', '-c:v', 'libx264', '-crf', '19', '-maxrate', '12M', '-bufsize', '24M', '-preset', 'medium', '-profile:v', 'high', '-r', String(tl.fps),
  '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', OUT], { stdio: ['pipe', 'inherit', 'inherit'] });

const total = Math.round(tl.dur * tl.fps), t0 = Date.now();
for (let i = 0; i < total; i++) {
  const png = await shot(i / tl.fps);
  if (!ff.stdin.write(png)) await new Promise((r) => ff.stdin.once('drain', r));
  if (i % (tl.fps * 10) === 0) console.log(`${(i / tl.fps).toFixed(0)}s / ${tl.dur.toFixed(0)}s  (${((Date.now() - t0) / 1000).toFixed(0)}s elapsed)`);
}
ff.stdin.end();
await new Promise((r) => ff.on('close', r));
await browser.close();
console.log(`wrote ${OUT}`);
