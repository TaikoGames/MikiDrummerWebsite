/* The rules of the Story Cutter.
 *
 *     node tools/story_cutter_test.mjs
 */
import { loudness, pickHighlights, snapToHit, evenly, fillRect, fitRect,
         clock, clipName, autoLength, keepSize, crc32, zipParts, HOP } from '../js/story-cutter.js';
import { writeFileSync, mkdtempSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

let fails = 0;
const ok = (cond, what) => { if (!cond) { console.log('FAIL ' + what); fails++; } };
const near = (a, b, tol, what) => ok(Math.abs(a - b) <= tol, `${what}: got ${a} want ${b}±${tol}`);

// --- loudness ----------------------------------------------------------
{
  const sr = 1000, a = new Float32Array(2000), b = new Float32Array(2000);
  for (let i = 1000; i < 2000; i++) { a[i] = 0.5; b[i] = 0.5; }
  const r = loudness([a, b], sr);
  ok(r.length === 40, `40 readings for 2 s at 50 ms (${r.length})`);
  near(r[5], 0, 1e-9, 'silence is zero');
  near(r[30], 0.5, 1e-6, 'a steady level reads as that level');
  ok(loudness([], 1000).length === 0, 'no channels, no readings');
}

// --- highlights --------------------------------------------------------
// Two minutes, quiet, with a loud stretch from 40 to 60 s and a louder one
// from 90 to 105 s. Each loud stretch starts with a hit.
function song() {
  const n = Math.round(120 / HOP), r = new Float32Array(n);
  for (let i = 0; i < n; i++) {
    const t = i * HOP;
    r[i] = 0.05 + 0.01 * Math.sin(i);
    if (t >= 40 && t < 60) r[i] = 0.4 + 0.1 * Math.sin(i * 0.9);
    if (t >= 90 && t < 105) r[i] = 0.6 + 0.15 * Math.sin(i * 0.7);
  }
  return r;
}
{
  const h = pickHighlights(song(), 120, 15, 2);
  ok(h.length === 2, 'two clips');
  ok(h[0].start < h[1].start, 'returned in time order');
  const best = h.find(c => c.rank === 1);
  ok(best && best.start >= 88 && best.start <= 91, `the best clip starts at the loudest part (${best && best.start})`);
  const second = h.find(c => c.rank === 2);
  ok(second && second.start >= 38 && second.start <= 46, `the second clip is in the other loud part (${second && second.start})`);
  ok(h.every(c => Math.abs(c.end - c.start - 15) < 0.011), 'every clip is the length asked for');
  ok(h.every(c => c.start >= 0 && c.end <= 120), 'every clip is inside the video');
  ok(best.score === 1, 'the best clip scores 1');
}
{
  const h = pickHighlights(song(), 120, 15, 8);
  for (let i = 1; i < h.length; i++) ok(h[i].start >= h[i - 1].end - 1e-9, 'clips never overlap');
  ok(h.length >= 5, `asking for eight in two minutes gets most of them (${h.length})`);
}
{
  const h = pickHighlights(song(), 10, 15, 3);
  ok(h.length === 1 && h[0].start === 0 && h[0].end === 10, 'a video shorter than a clip is one clip of the whole thing');
  ok(pickHighlights(new Float32Array(2400), 120, 15, 3).length === 3, 'silence falls back to spreading them out');
  ok(pickHighlights(song(), 120, 15, 0).length === 0, 'zero asked for, zero given');
}

// Ninety seconds with one loud stretch from 30 to 42 s. Asking for five 15 s
// clips has to give as many as fit around the best one, not two stranded
// ones -- the greedy pass alone managed two.
{
  const n = Math.round(90 / HOP), r = new Float32Array(n);
  for (let i = 0; i < n; i++) r[i] = (i * HOP >= 30 && i * HOP < 42) ? 0.8 : 0.05 + 0.01 * Math.sin(i);
  const h = pickHighlights(r, 90, 15, 5);
  ok(h.length >= 4, `fills the timeline (${h.length} clips)`);
  for (let i = 1; i < h.length; i++) ok(h[i].start >= h[i - 1].end - 1e-9, 'filled clips never overlap');
  const best = h.find(c => c.rank === 1);
  ok(best && best.start <= 30.01 && best.end >= 42, `the best clip still covers the loud part (${best && best.start})`);
}

// --- snapping to a hit -------------------------------------------------
{
  const r = new Float32Array(400).fill(0.05);
  for (let i = 200; i < 400; i++) r[i] = 0.8;           // a hit at 10.0 s
  const t = snapToHit(r, 10.6);
  ok(t > 9.85 && t <= 10.0, `pulled back onto the hit (${t})`);
  const flat = new Float32Array(400).fill(0.3);
  ok(snapToHit(flat, 10.6) === 10.6, 'no hit, no move');
}

// --- evenly ------------------------------------------------------------
{
  const e = evenly(100, 10, 5);
  ok(e.length === 5 && e[0].start === 0 && e[4].end === 100, 'spread from the start to the end');
  ok(evenly(25, 10, 5).length === 2, 'no more clips than fit');
}

// --- framing -----------------------------------------------------------
{
  const r = fillRect(1920, 1080, 1080, 1920, 0);
  near(r.sw / r.sh, 1080 / 1920, 1e-9, 'the crop is 9:16');
  near(r.sx + r.sw / 2, 960, 1e-9, 'centred by default');
  ok(fillRect(1920, 1080, 1080, 1920, -1).sx === 0, 'pan -1 is the left edge');
  near(fillRect(1920, 1080, 1080, 1920, 1).sx + r.sw, 1920, 1e-9, 'pan 1 is the right edge');
  const tall = fillRect(1080, 2400, 1080, 1920, 0);
  ok(tall.sw === 1080 && Math.abs(tall.sh - 1920) < 1e-9, 'a taller-than-story video crops top and bottom');
  const f = fitRect(1920, 1080);
  ok(f.dw === 1080 && Math.abs(f.dy - (1920 - f.dh) / 2) < 1e-9, 'fit is full width and centred');
}

// --- keeping the shape -------------------------------------------------
{
  const a = keepSize(1920, 1080);
  ok(a.w === 1920 && a.h === 1080, 'a 1080p landscape video stays 1920×1080');
  const b = keepSize(3840, 2160);
  ok(b.w === 1920 && b.h === 1080, '4K comes down to 1920×1080, same shape');
  const c = keepSize(1080, 1920);
  ok(c.w === 1080 && c.h === 1920, 'portrait stays portrait');
  const d = keepSize(640, 360);
  ok(d.w === 640 && d.h === 360, 'a small video is not blown up');
  const e = keepSize(1441, 1081);
  ok(e.w % 2 === 0 && e.h % 2 === 0, 'both sides even for H.264');
  ok(Math.abs(e.w / e.h - 1441 / 1081) < 0.005, 'and the shape is kept');
  const f = keepSize(1440, 1440);
  ok(f.w === 1440 && f.h === 1440, 'square stays square');
}

// --- auto length -------------------------------------------------------
ok(autoLength(600) === 15, 'a long video gets 15 s clips');
ok(autoLength(40) === 15, `a 40 s video gets full 15 s clips (${autoLength(40)})`);
ok(autoLength(12) === 12, 'a video of 15 s or less is one clip of the whole thing');
ok(autoLength(20) >= 7 && autoLength(20) <= 10, `a 20 s video gets two clips' worth (${autoLength(20)})`);
for (let d = 15.5; d < 400; d += 0.5) ok(autoLength(d) >= 7, `never under 7 s (${d})`);
for (const d of [20, 40, 50]) {
  const n = Math.round(d / HOP), r = new Float32Array(n);
  for (let i = 0; i < n; i++) r[i] = 0.1 + 0.05 * Math.sin(i * 0.3);
  ok(pickHighlights(r, d, autoLength(d), 5).length >= 2, `a ${d} s video gives more than one clip`);
}

// --- names -------------------------------------------------------------
ok(clock(75.4) === '1:15', 'clock');
ok(clipName('gig.mov', 2, 61, 'mp4', 'short') === 'gig-short-03-1m01s.mp4', 'Shorts are named as shorts');
ok(clipName('Live at Bully’s (2026).MOV', 0, 92.3, 'mp4') === 'Live-at-Bully-s-2026-story-01-1m32s.mp4', 'clip names are safe and sortable: ' + clipName('Live at Bully’s (2026).MOV', 0, 92.3, 'mp4'));

// --- the ZIP ---------------------------------------------------------------
ok(crc32(new TextEncoder().encode('123456789')) === 0xCBF43926, 'crc32 matches the standard check value');
{
  const a = new Uint8Array(5000).map((_, i) => (i * 7) & 255);
  const b = new TextEncoder().encode('second clip');
  const parts = zipParts([{ name: 'clip-01.mp4', data: a }, { name: 'clip-01.mp4', data: b },
                          { name: 'Café-story.mp4', data: new Uint8Array(0) }]);
  const total = parts.reduce((n, p) => n + p.length, 0);
  const buf = new Uint8Array(total);
  let o = 0; for (const p of parts) { buf.set(p, o); o += p.length; }
  const dir = mkdtempSync(join(tmpdir(), 'zip-'));
  const file = join(dir, 'clips.zip');
  writeFileSync(file, buf);
  // Read it back with Python's zipfile, which checks every CRC.
  const out = execFileSync('python3', ['-I', '-c', `
import zipfile, sys, json
z = zipfile.ZipFile(sys.argv[1])
bad = z.testzip()
print(json.dumps({"bad": bad, "names": z.namelist(), "sizes": [i.file_size for i in z.infolist()],
                  "second": z.read(z.namelist()[1]).decode()}))
`, file]).toString();
  const r = JSON.parse(out);
  ok(r.bad === null, 'every file in the zip passes its CRC');
  ok(JSON.stringify(r.names) === JSON.stringify(['clip-01.mp4', 'clip-01-2.mp4', 'Café-story.mp4']),
     'names kept, a clash renamed rather than overwritten, accents survive: ' + JSON.stringify(r.names));
  ok(JSON.stringify(r.sizes) === JSON.stringify([5000, 11, 0]), 'sizes are right');
  ok(r.second === 'second clip', 'contents are right');
}

console.log(fails ? `${fails} check(s) FAILED` : 'story cutter rules: all checks passed');
process.exit(fails ? 1 : 0);
