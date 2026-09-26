/* The drum game.
 *
 * The rules, with no Three.js in them on purpose: the timing is the game,
 * and a module that imports a renderer cannot be run by a test harness. The
 * drawing lives in drum-scene.js.
 *
 * Three lanes, one per piece of the kit, and the charts come from the songs
 * themselves — tools/build_beatmaps.py detects what Miki actually played, so
 * hitting the notes is playing along with the record rather than with
 * somebody's approximation of it.
 *
 * The one thing a rhythm game has to get right is time, and the one way to
 * get it wrong is to measure it with requestAnimationFrame. Frames drift,
 * stall behind a garbage collection and lie on a 120 Hz display. Every
 * judgement here is made against AudioContext.currentTime, which is the same
 * clock that is playing the music, so a dropped frame costs a smooth
 * animation and never a missed note.
 */

export const LANES = [
  { id: 'hat',   label: 'Hi-hat', key: 'a',   colour: 0x7ee7c7, x: -2.3 },
  { id: 'snare', label: 'Snare',  key: 's',   colour: 0xf4b400, x:  0.0 },
  { id: 'kick',  label: 'Kick',   key: ' ',   colour: 0xe8672a, x:  2.3 }
];

// How far ahead a note is visible, in seconds of music. Long enough to read a
// pattern coming, short enough that the runway is not a wall of dots.
export const LOOKAHEAD = 1.9;
export const SPEED = 9.0;              // world units per second of music
export const HIT_Z = 0;                // where the pads are

// Judgement windows, in seconds either side. Measured against the audio
// clock, so these are the real numbers rather than frame counts.
export const WINDOWS = [
  { name: 'Perfect', t: 0.045, score: 300 },
  { name: 'Good',    t: 0.090, score: 200 },
  { name: 'OK',      t: 0.135, score: 100 }
];
export const MISS_AFTER = 0.150;   // past this, the note is gone

/* Score for one hit. Combo multiplies, but caps -- otherwise the last third
 * of a song is worth more than the first two thirds put together and the
 * number stops meaning anything. */
export function hitScore(base, combo) {
  return Math.round(base * Math.min(1 + Math.floor(combo / 10) * 0.1, 2));
}

/* Which window a hit falls in, or null for no hit at all. Exported because
 * the timing rules are the game, and rules that cannot be tested without a
 * browser and a keyboard do not get tested. */
export function judge(delta) {
  const d = Math.abs(delta);
  for (const w of WINDOWS) if (d <= w.t) return w;
  return null;
}

/* The note a keypress should be judged against: the nearest unhit note in
 * that lane. Nearest rather than next, because pressing slightly early for a
 * note you already hit must not eat the one behind it. */
export function nearestNote(notes, lane, now, from) {
  let best = null, bestD = Infinity, bestI = -1;
  for (let i = from; i < notes.length; i++) {
    const n = notes[i];
    if (n.t - now > MISS_AFTER * 4) break;      // too far ahead to matter
    if (n.lane !== lane || n.done) continue;
    const d = Math.abs(n.t - now);
    if (d < bestD) { bestD = d; best = n; bestI = i; }
  }
  return bestD <= MISS_AFTER ? { note: best, index: bestI, delta: best.t - now } : null;
}

export function accuracy(counts) {
  const judged = counts.Perfect + counts.Good + counts.OK + counts.Miss;
  if (!judged) return 0;
  const weighted = counts.Perfect * 1 + counts.Good * 0.66 + counts.OK * 0.33;
  return weighted / judged;
}

export function rank(acc) {
  if (acc >= 0.95) return 'S';
  if (acc >= 0.90) return 'A';
  if (acc >= 0.80) return 'B';
  if (acc >= 0.70) return 'C';
  if (acc >= 0.55) return 'D';
  return 'F';
}

/* The chart filename for a track.
 *
 * Must agree, character for character, with slugify() in
 * tools/build_beatmaps.py, because one writes the file and the other fetches
 * it. They disagreed once: Python kept the accent in "Sebastopol García" and
 * this dropped it to "garc-a", so the fetch 404'd and the song quietly
 * vanished from the menu -- no error, just eleven songs where there were
 * twelve. Folding to ASCII first is what makes them the same function.
 *
 * tools/drum_game_test.mjs and the Python self-test check the same names
 * against the same expected slugs. Testing one side against a reimplementation
 * of the other is how the bug survived being "covered" the first time.
 */
export function slugify(name) {
  return name
    .replace(/\.[^.]+$/, '')
    .normalize('NFKD').replace(/[\u0300-\u036f]/g, '')   // García -> Garcia
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-|-$/g, '');
}
