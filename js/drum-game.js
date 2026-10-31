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
 * judgement here is made against the playing track's own position, so a
 * dropped frame costs a smooth animation and never a missed note. game.html
 * owns that clock: it reads the audio element and smooths between its ticks,
 * because the element reports its position in steps a quarter of a second
 * wide on some phones and a judgement window is a tenth of that.
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
export function judge(delta, scale = 1) {
  const d = Math.abs(delta);
  for (const w of WINDOWS) if (d <= w.t * scale) return w;
  return null;
}

/* The note a keypress should be judged against: the nearest unhit note in
 * that lane. Nearest rather than next, because pressing slightly early for a
 * note you already hit must not eat the one behind it. */
export function nearestNote(notes, lane, now, from, scale = 1) {
  const miss = MISS_AFTER * scale;
  let best = null, bestD = Infinity, bestI = -1;
  for (let i = from; i < notes.length; i++) {
    const n = notes[i];
    if (n.t - now > miss * 4) break;            // too far ahead to matter
    if (n.lane !== lane || n.done) continue;
    const d = Math.abs(n.t - now);
    if (d < bestD) { bestD = d; best = n; bestI = i; }
  }
  return bestD <= miss ? { note: best, index: bestI, delta: best.t - now } : null;
}

/* ---- difficulty -------------------------------------------------------
 *
 * The full chart is every hit the detector found, often a kick, a snare and
 * a hat on the same instant at 200 BPM. That is the honest drum part and it
 * is a wall of notes for anyone who just wants to play along. The levels
 * below are the same part with the busy bits taken out, not a different
 * chart, so whatever is left still lands on something you can hear:
 *
 *   easy    beats only, one pad at a time, never faster than the pulse,
 *           and the timing windows are wider
 *   medium  eighths, one pad at a time
 *   hard    sixteenths with chords -- what the game used to default to
 *   expert  everything the detector found
 *
 * maxW is the finest metrical position kept (0 downbeat, 1 beat, 2 eighth,
 * 3 sixteenth, 4 anything). gapBeats is the shortest gap allowed between two
 * notes, in beats, so it scales with the song; minGap is a floor in seconds,
 * so at 207 BPM Easy drops to half time -- still on the beat, just every
 * other one -- instead of asking a beginner for three and a half taps a
 * second. scale widens the judgement windows. */
export const LEVELS = {
  easy:   { label: 'Easy',   maxW: 1, single: true,  gapBeats: 0.9,  minGap: 0.4,  scale: 1.45 },
  medium: { label: 'Medium', maxW: 2, single: true,  gapBeats: 0.45, minGap: 0.2,  scale: 1.2 },
  hard:   { label: 'Hard',   maxW: 3, single: false, gapBeats: 0,    minGap: 0,    scale: 1 },
  expert: { label: 'Expert', maxW: 4, single: false, gapBeats: 0,    minGap: 0,    scale: 1 }
};

// When several pads land on the same instant and only one can stay, the one
// that stands out: each hit is measured against how hard that drum is usually
// hit in this song, because a mix that buries the kick still has a kick that
// is loud for a kick. The snare and kick get a nudge over the hat underneath.
const LANE_PULL = { snare: 0.4, kick: 0.45, hat: 0 };
const CHORD = 0.03;   // seconds; hits closer than this are the same instant

/* The median gap between tracked beats, or a guess from the tempo. */
export function beatLength(beats, bpm) {
  if (beats && beats.length > 2) {
    const g = [];
    for (let i = 1; i < beats.length; i++) g.push(beats[i] - beats[i - 1]);
    g.sort((a, b) => a - b);
    const m = g[g.length >> 1];
    if (m > 0.15 && m < 2) return m;
  }
  return bpm > 0 ? 60 / bpm : 0.5;
}

/* The chart for a level. Notes in, notes out, sorted by time. */
export function simplifyChart(notes, level, beats, bpm) {
  const L = LEVELS[level] || LEVELS.easy;
  const kept = notes.filter(n => (n.w == null ? 0 : n.w) <= L.maxW)
                    .slice().sort((a, b) => a.t - b.t);
  if (!L.single) return kept;

  // One note per instant: the one that stands out most.
  const typical = {};
  for (const lane of new Set(kept.map(n => n.lane))) {
    const vs = kept.filter(n => n.lane === lane).map(n => n.v == null ? 0.5 : n.v)
                   .sort((a, b) => a - b);
    typical[lane] = Math.max(0.05, vs[vs.length >> 1]);
  }
  const pull = n => (n.v == null ? 0.5 : n.v) / (typical[n.lane] || 0.5)
                    + (LANE_PULL[n.lane] || 0);
  const single = [];
  for (let i = 0; i < kept.length;) {
    let j = i, best = kept[i];
    while (j < kept.length && kept[j].t - kept[i].t < CHORD) {
      if (pull(kept[j]) > pull(best)) best = kept[j];
      j++;
    }
    single.push(best);
    i = j;
  }

  // Then thin out anything faster than the level allows. Stronger metrical
  // positions win a clash, so what survives is the pulse of the song.
  const gap = Math.max(L.gapBeats * beatLength(beats, bpm), L.minGap || 0);
  if (!(gap > 0)) return single;
  const out = [];
  for (const n of single) {
    const last = out[out.length - 1];
    if (!last || n.t - last.t >= gap) { out.push(n); continue; }
    const wn = n.w == null ? 0 : n.w, wl = last.w == null ? 0 : last.w;
    if (wn < wl || (wn === wl && pull(n) > pull(last) + 0.2)) {
      out.pop();
      const prev = out[out.length - 1];
      if (!prev || n.t - prev.t >= gap) out.push(n);
      else out.push(last);              // swapping would crowd the one before
    }
  }
  return out;
}

/* ---- the loud parts ---------------------------------------------------
 *
 * Where the song goes off: choruses, blast sections, the bit where the whole
 * band comes back in. Found from the full chart rather than from the audio,
 * because the chart is already a list of how hard and how often the drums
 * were hit, and because it can be worked out before the song starts, so a
 * moment is ready on the exact beat rather than a frame after the analyser
 * noticed.
 *
 * Drum energy is summed into quarter-second bins, smoothed over three
 * seconds, and the runs that sit in the top fifth of the song are the hype
 * sections. Each one starts on the tracked beat nearest to where it begins,
 * so the picture lands with the music. Returns [{ start, end, peak }]. */
const LANE_WEIGHT = { kick: 1, snare: 1, hat: 0.55 };

export function hypeMoments(notes, duration, beats, opts = {}) {
  const BIN = 0.25;
  const smooth = opts.smooth || 3;          // seconds
  const minLen = opts.minLen || 3;          // shortest section worth a moment
  const spacing = opts.spacing || 12;       // seconds between moment starts
  const top = opts.top == null ? 0.8 : opts.top;
  const dur = duration || (notes.length ? notes[notes.length - 1].t + 1 : 0);
  const nb = Math.ceil(dur / BIN);
  if (nb < 8) return [];

  const raw = new Float64Array(nb);
  for (const n of notes) {
    const b = Math.floor(n.t / BIN);
    if (b >= 0 && b < nb) raw[b] += (n.v == null ? 0.5 : n.v) * (LANE_WEIGHT[n.lane] || 0.5);
  }
  const half = Math.max(1, Math.round(smooth / BIN / 2));
  const e = new Float64Array(nb);
  let sum = 0, cnt = 0;
  for (let i = 0; i < Math.min(half, nb); i++) { sum += raw[i]; cnt++; }
  for (let i = 0; i < nb; i++) {
    if (i + half < nb) { sum += raw[i + half]; cnt++; }
    if (i - half - 1 >= 0) { sum -= raw[i - half - 1]; cnt--; }
    e[i] = sum / cnt;
  }

  // Ignore the count-in and the ring-out when deciding what "loud" means.
  const edge = Math.min(Math.floor(nb / 6), Math.round(4 / BIN));
  const body = Array.from(e.slice(edge, nb - edge)).sort((a, b) => a - b);
  if (!body.length) return [];
  const thr = body[Math.min(body.length - 1, Math.floor(body.length * top))];
  const loud = body[body.length - 1];
  if (!(thr > 0) || loud <= 0) return [];

  // Runs above the line, with short dips bridged.
  const runs = [];
  let s = -1;
  for (let i = 0; i <= nb; i++) {
    const on = i < nb && e[i] >= thr;
    if (on && s < 0) s = i;
    if (!on && s >= 0) {
      const prev = runs[runs.length - 1];
      if (prev && (s - prev.e) * BIN < 2) prev.e = i;
      else runs.push({ s, e: i });
      s = -1;
    }
  }

  const snap = (t) => {
    if (!beats || !beats.length) return t;
    let best = t, bd = 0.6;
    for (const b of beats) {
      const d = Math.abs(b - t);
      if (d < bd) { bd = d; best = b; }
      if (b > t + 0.6) break;
    }
    return best;
  };

  const out = [];
  for (const r of runs) {
    if ((r.e - r.s) * BIN < minLen) continue;
    const start = snap(r.s * BIN);
    if (start < 2) continue;                       // not on the first note
    const last = out[out.length - 1];
    if (last && start - last.start < spacing) continue;
    let peak = 0;
    for (let i = r.s; i < r.e; i++) peak = Math.max(peak, e[i]);
    out.push({ start, end: Math.min(dur, r.e * BIN), peak: peak / loud });
  }
  return out;
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
