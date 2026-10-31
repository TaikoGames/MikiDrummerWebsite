/* The rules of the drum game.
 *
 *     node tools/drum_game_test.mjs
 *
 * Plain node, no browser, no GPU. This is why the timing lives in a module
 * with no Three.js in it: a rhythm game is its judgement windows, and windows
 * that can only be checked by a person with a keyboard and good ears do not
 * get checked. Everything here is arithmetic that decides whether a hit
 * counts, which is the part players will notice being wrong.
 */
import { judge, nearestNote, hitScore, accuracy, rank, slugify,
         simplifyChart, hypeMoments, beatLength, LEVELS,
         WINDOWS, MISS_AFTER } from '../js/drum-game.js';

let fails = 0;
const ok = (cond, what) => { if (!cond) { console.log('FAIL ' + what); fails++; } };
const eq = (got, want, what) =>
  ok(JSON.stringify(got) === JSON.stringify(want), `${what}: got ${JSON.stringify(got)} want ${JSON.stringify(want)}`);

// --- windows -----------------------------------------------------------
eq(judge(0)?.name, 'Perfect', 'dead on is Perfect');
eq(judge(0.044)?.name, 'Perfect', 'just inside Perfect');
eq(judge(-0.044)?.name, 'Perfect', 'early counts the same as late');
eq(judge(0.046)?.name, 'Good', 'just outside Perfect falls to Good');
eq(judge(0.089)?.name, 'Good', 'just inside Good');
eq(judge(0.13)?.name, 'OK', 'the loose window');
eq(judge(0.2), null, 'well outside is no hit at all');
ok(judge(MISS_AFTER + 0.001) === null, 'nothing is judged past the miss point');

// The windows must be ordered and non-overlapping, or a Good hit could score
// as Perfect depending on array order.
for (let i = 1; i < WINDOWS.length; i++) {
  ok(WINDOWS[i].t > WINDOWS[i - 1].t, `window ${i} is wider than the one before it`);
  ok(WINDOWS[i].score < WINDOWS[i - 1].score, `window ${i} is worth less`);
}
ok(WINDOWS[WINDOWS.length - 1].t <= MISS_AFTER, 'the loosest window is inside the miss point');

// --- combo scoring -----------------------------------------------------
eq(hitScore(300, 0), 300, 'no combo, no bonus');
eq(hitScore(300, 10), 330, 'ten in a row is +10%');
eq(hitScore(300, 50), 450, 'fifty is +50%');
ok(hitScore(300, 500) === hitScore(300, 100),
   'the multiplier caps, so the end of a song is not worth more than the rest of it');

// --- which note a press belongs to -------------------------------------
const chart = () => ([
  { t: 1.00, lane: 'kick',  done: false },
  { t: 1.05, lane: 'snare', done: false },
  { t: 1.30, lane: 'kick',  done: false },
  { t: 5.00, lane: 'kick',  done: false }
]);

{
  const c = chart();
  const hit = nearestNote(c, 'kick', 1.01, 0);
  eq(hit.note.t, 1.00, 'picks the kick, not the snare 50 ms later');
}
{
  const c = chart();
  c[0].done = true;
  const hit = nearestNote(c, 'kick', 1.02, 0);
  // 1.30 is 280 ms away, past the miss point, so there is nothing to hit.
  ok(hit === null, 'a note already hit is not hit twice, and does not fall through to the next');
}
{
  const c = chart();
  // Pressing early for a note that is coming must take that note, not the one
  // behind it -- getting this wrong makes fast passages unplayable.
  const hit = nearestNote(c, 'kick', 1.22, 0);
  eq(hit.note.t, 1.30, 'takes the nearest note, not the first one it walks past');
}
{
  const c = chart();
  ok(nearestNote(c, 'kick', 3.0, 0) === null, 'a press in a gap hits nothing');
  ok(nearestNote(c, 'hat', 1.0, 0) === null, 'a lane with no notes hits nothing');
}
{
  const c = chart();
  const hit = nearestNote(c, 'kick', 1.0, 0);
  ok(Math.abs(hit.delta) < 1e-9, 'delta is zero when dead on');
  ok(nearestNote(c, 'kick', 0.95, 0).delta > 0, 'a positive delta means the note is still coming');
}

// --- accuracy and grade ------------------------------------------------
eq(accuracy({ Perfect: 0, Good: 0, OK: 0, Miss: 0 }), 0, 'nothing played is zero, not NaN');
eq(accuracy({ Perfect: 10, Good: 0, OK: 0, Miss: 0 }), 1, 'all perfect is 100%');
eq(accuracy({ Perfect: 0, Good: 0, OK: 0, Miss: 10 }), 0, 'all missed is 0%');
ok(Math.abs(accuracy({ Perfect: 5, Good: 5, OK: 0, Miss: 0 }) - 0.83) < 0.01,
   'half perfect half good lands between');
eq(rank(1), 'S', 'flawless is S');
eq(rank(0.9), 'A', 'the A boundary is inclusive');
eq(rank(0.899), 'B', 'just under A is B');
eq(rank(0), 'F', 'nothing is F');

// Grades must never go backwards as accuracy climbs.
const order = ['F', 'D', 'C', 'B', 'A', 'S'];
let last = -1;
for (let a = 0; a <= 1.0001; a += 0.01) {
  const i = order.indexOf(rank(Math.min(a, 1)));
  ok(i >= last, `grade goes backwards at ${a.toFixed(2)} (${rank(a)})`);
  last = i;
}

// --- slugs -------------------------------------------------------------
// The same table appears in tools/build_beatmaps.py's self-test. One side
// writes the chart file, the other fetches it, and testing either against a
// reimplementation of the other is what let "Sebastopol García" 404 while
// both tests passed.
const SLUGS = {
  'Sebastopol García.mp3': 'sebastopol-garcia',
  'Per mi.mp3': 'per-mi',
  '04 - Skamen.mp3': '04-skamen',
  'Bajo el nivel del mal.mp3': 'bajo-el-nivel-del-mal',
  'LandSea.mp3': 'landsea',
  'Café Über.mp3': 'cafe-uber'
};
for (const [name, want] of Object.entries(SLUGS)) {
  eq(slugify(name), want, `slug for ${name}`);
  ok(/^[a-z0-9-]+$/.test(slugify(name)), `slug for ${name} is url-safe ascii`);
}

// --- difficulty --------------------------------------------------------
// A two-bar rock beat at 120 BPM: kick on 1 and 3, snare on 2 and 4, hats on
// every eighth, all hit at once on the beats.
{
  const notes = [];
  for (let i = 0; i < 64; i++) {
    const t = 1 + i * 0.25, onBeat = i % 2 === 0;
    notes.push({ t, lane: 'hat', w: onBeat ? (i % 8 === 0 ? 0 : 1) : 2, v: 0.4 });
    if (onBeat) notes.push({ t, lane: (i / 2) % 2 ? 'snare' : 'kick', w: i % 8 === 0 ? 0 : 1, v: 0.8 });
  }
  const beats = notes.filter(n => n.lane !== 'hat').map(n => n.t);
  eq(beatLength(beats, 0), 0.5, 'beat length from the tracked beats');
  eq(beatLength([], 120), 0.5, 'beat length from the tempo when there are no beats');

  const easy = simplifyChart(notes, 'easy', beats, 120);
  const times = easy.map(n => n.t);
  ok(new Set(times).size === times.length, 'easy never asks for two pads at once');
  for (let i = 1; i < easy.length; i++) {
    ok(easy[i].t - easy[i - 1].t >= 0.4 - 1e-9, `easy keeps a gap at ${easy[i].t}`);
  }
  ok(easy.every(n => n.lane !== 'hat'), 'easy plays the kick and snare you hear, not the hat under them');
  ok(easy.every(n => n.w <= 1), 'easy stays on the beat');
  eq(easy.length, 32, 'easy at 120 BPM keeps every beat');

  const med = simplifyChart(notes, 'medium', beats, 120);
  ok(med.length > easy.length, 'medium has more than easy');
  ok(new Set(med.map(n => n.t)).size === med.length, 'medium is one pad at a time too');
  eq(simplifyChart(notes, 'expert', beats, 120).length, notes.length, 'expert is the whole chart');
  ok(simplifyChart(notes, 'hard', beats, 120).length >= med.length, 'hard is at least medium');
  eq(simplifyChart(notes, 'nonsense', beats, 120).length, easy.length, 'an unknown level is easy');
  ok(notes.length === 96, 'the chart it was given is left alone');
  for (const k of Object.keys(LEVELS)) ok(LEVELS[k].scale >= 1, `${k} never narrows the windows`);

  // Faster than the floor allows: at 240 BPM easy goes half time.
  const fast = notes.map(n => ({ ...n, t: 1 + (n.t - 1) / 2 }));
  const fe = simplifyChart(fast, 'easy', fast.filter(n => n.lane !== 'hat').map(n => n.t), 240);
  for (let i = 1; i < fe.length; i++) ok(fe[i].t - fe[i - 1].t >= 0.4 - 1e-9, 'fast easy keeps its floor');
}

// Wider windows on the easier levels, and the default is unchanged.
eq(judge(0.06, 1.45)?.name, 'Perfect', 'easy timing is more forgiving');
eq(judge(0.06)?.name, 'Good', 'normal timing is unchanged');
ok(nearestNote([{ t: 1, lane: 'kick', done: false }], 'kick', 1.2, 0, 1.45) !== null,
   'easy reaches a little further for a note');

// --- hype moments ------------------------------------------------------
// Sixty seconds: quiet verse, a loud chorus from 20 to 32, quiet, loud again
// from 44 to 52.
{
  const notes = [], beats = [];
  for (let t = 0.5; t < 60; t += 0.5) beats.push(t);
  for (let t = 0.5; t < 60; t += 0.125) {
    const loud = (t >= 20 && t < 32) || (t >= 44 && t < 52);
    if (loud) notes.push({ t, lane: 'snare', v: 0.9 }, { t, lane: 'kick', v: 0.9 });
    else if (Math.abs(t * 2 - Math.round(t * 2)) < 1e-9) notes.push({ t, lane: 'hat', v: 0.3 });
  }
  const h = hypeMoments(notes, 60, beats);
  eq(h.length, 2, 'finds both loud sections');
  ok(h[0] && Math.abs(h[0].start - 20) < 2, `first starts at the chorus (${h[0] && h[0].start})`);
  ok(h[1] && Math.abs(h[1].start - 44) < 2, `second starts at the second chorus (${h[1] && h[1].start})`);
  ok(h.every(m => beats.includes(m.start)), 'every moment lands on a tracked beat');
  ok(h.every(m => m.end > m.start), 'every section has a length');
  eq(hypeMoments([], 60, beats), [], 'no notes, no moments');
  eq(hypeMoments(notes, 1, beats), [], 'a one-second clip is too short to have a chorus');
}

console.log(fails ? `${fails} check(s) FAILED` : 'drum game rules: all checks passed');
process.exit(fails ? 1 : 0);
