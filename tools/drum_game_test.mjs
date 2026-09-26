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
import { judge, nearestNote, hitScore, accuracy, rank,
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

console.log(fails ? `${fails} check(s) FAILED` : 'drum game rules: all checks passed');
process.exit(fails ? 1 : 0);
