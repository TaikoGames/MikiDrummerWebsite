/* Story Cutter: the parts that decide things.
 *
 * No DOM, no canvas, no MediaRecorder in here, so a test can run it in plain
 * node. The page (story-cutter.html) owns the video, the drawing and the
 * recording; this owns "which bits of the video are worth posting" and
 * "which part of the frame ends up in a 9:16 story".
 */

export const STORY_W = 1080;
export const STORY_H = 1920;
export const HOP = 0.05;                 // seconds per loudness reading

/* Loudness over time: RMS of the mono mix in HOP-second steps.
 * channels is an array of Float32Arrays, as AudioBuffer.getChannelData gives. */
export function loudness(channels, sampleRate, hop = HOP) {
  if (!channels || !channels.length || !channels[0].length) return new Float32Array(0);
  const len = channels[0].length;
  const step = Math.max(1, Math.round(sampleRate * hop));
  const out = new Float32Array(Math.ceil(len / step));
  const nc = channels.length;
  for (let f = 0; f < out.length; f++) {
    const a = f * step, b = Math.min(len, a + step);
    let sum = 0;
    for (let i = a; i < b; i++) {
      let m = 0;
      for (let c = 0; c < nc; c++) m += channels[c][i];
      m /= nc;
      sum += m * m;
    }
    out[f] = Math.sqrt(sum / Math.max(1, b - a));
  }
  return out;
}

/* The best moments for a story.
 *
 * A window scores on how loud it is on average plus how much it moves -- a
 * chorus, a breakdown, the crowd going up -- because a wall of steady noise is
 * loud without being interesting. The best window is taken, everything that
 * overlaps it is ruled out, and so on until there are `count` of them.
 *
 * Then each start is pulled back to the hit just before it, so a clip opens
 * on a downbeat or a scream rather than half a second into one. Stories are
 * swiped past in under a second; the first frame has to land.
 *
 * Returns [{ start, end, score, rank }] in time order. score is 0..1 against
 * the best one; rank 1 is the best. */
export function pickHighlights(rms, duration, clipLen, count, opts = {}) {
  const hop = opts.hop || HOP;
  const gap = opts.gap == null ? 1 : opts.gap;
  if (!(duration > 0) || !(clipLen > 0) || !(count > 0)) return [];
  if (duration <= clipLen) return [{ start: 0, end: duration, score: 1, rank: 1 }];
  if (!rms || rms.length < 4) return evenly(duration, clipLen, count);

  const n = rms.length;
  const pre = new Float64Array(n + 1), pre2 = new Float64Array(n + 1);
  for (let i = 0; i < n; i++) { pre[i + 1] = pre[i] + rms[i]; pre2[i + 1] = pre2[i] + rms[i] * rms[i]; }
  const W = Math.max(1, Math.round(clipLen / hop));
  const lastStart = Math.max(0, Math.min(n - W, Math.floor((duration - clipLen) / hop)));

  const scores = new Float64Array(lastStart + 1);
  let peak = 0;
  for (let s = 0; s <= lastStart; s++) {
    const e = Math.min(n, s + W), k = e - s;
    const mean = (pre[e] - pre[s]) / k;
    const sd = Math.sqrt(Math.max(0, (pre2[e] - pre2[s]) / k - mean * mean));
    scores[s] = mean + 0.5 * sd;
    if (scores[s] > peak) peak = scores[s];
  }
  if (!(peak > 0)) return evenly(duration, clipLen, count);

  const picked = [];
  const taken = new Uint8Array(lastStart + 1);
  const block = Math.round((clipLen + gap) / hop);
  while (picked.length < count) {
    let best = -1, bv = -1;
    for (let s = 0; s <= lastStart; s++) if (!taken[s] && scores[s] > bv) { bv = scores[s]; best = s; }
    if (best < 0) break;
    picked.push({ s: best, score: bv / peak });
    for (let s = Math.max(0, best - block + 1); s <= Math.min(lastStart, best + block - 1); s++) taken[s] = 1;
  }

  // Greedy takes the very best moment first, which is what matters most,
  // but it can strand the rest: a second pick in the wrong place leaves gaps
  // too short for a third. If it fell short of what fits, keep the best
  // moment exactly where it is and plan everything either side of it at once
  // -- the most total "goes off" across as many clips as there is room for.
  const fits = Math.min(count, Math.floor((duration + gap) / (clipLen + gap)));
  if (picked.length < fits && picked.length) {
    const top = picked[0].s;
    let bestPlan = null;
    for (let kl = 0; kl < fits; kl++) {
      const kr = fits - 1 - kl;
      const left = top - block >= 0 ? planAll(scores.subarray(0, top - block + 1), kl, block) : planAll(new Float64Array(0), kl, block);
      const right = top + block <= lastStart ? planAll(scores.subarray(top + block), kr, block) : planAll(new Float64Array(0), kr, block);
      const n = left.starts.length + right.starts.length;
      const total = left.total + right.total;
      if (!bestPlan || n > bestPlan.n || (n === bestPlan.n && total > bestPlan.total)) {
        bestPlan = { n, total, starts: left.starts.concat(right.starts.map(x => x + top + block)) };
      }
    }
    if (bestPlan && bestPlan.n + 1 > picked.length) {
      picked.length = 1;
      bestPlan.starts.sort((a, b) => scores[b] - scores[a])
        .forEach(st => picked.push({ s: st, score: scores[st] / peak }));
    }
    // Still short of what fits -- the best moment sits in the middle of a
    // short video and leaves no room either side. Plan the whole timeline
    // freely, and take that if its best clip is still nearly as good as the
    // best moment: a second clip is worth a small shift, not a lost chorus.
    if (picked.length < fits) {
      const free = planAll(scores, fits, block);
      const top = free.starts.reduce((m, st) => Math.max(m, scores[st]), 0);
      if (free.starts.length > picked.length && top >= 0.9 * peak) {
        picked.length = 0;
        free.starts.sort((a, b) => scores[b] - scores[a])
          .forEach(st => picked.push({ s: st, score: scores[st] / peak }));
      }
    }
  }

  const maxStart = duration - clipLen;
  const out = picked.map((p, i) => {
    const start = Math.max(0, Math.min(maxStart, snapToHit(rms, p.s * hop, hop)));
    return { start: round2(start), end: round2(start + clipLen), score: round2(p.score), rank: i + 1 };
  });
  return out.sort((a, b) => a.start - b.start);
}

/* Up to k windows over these scores, at least `block` steps apart, as many
 * as fit and then the highest total. f[j][s] is the best total of exactly j
 * windows all starting at or after s. Returns { starts, total }. */
function planAll(scores, k, block) {
  const L = scores.length, NEG = -Infinity;
  if (!L || k <= 0) return { starts: [], total: 0 };
  const f = [];
  for (let j = 0; j <= k; j++) f.push(new Float64Array(L + 1).fill(j === 0 ? 0 : NEG));
  for (let j = 1; j <= k; j++) {
    for (let s = L - 1; s >= 0; s--) {
      const next = Math.min(s + block, L);
      f[j][s] = Math.max(f[j][s + 1], scores[s] + f[j - 1][next]);
    }
  }
  let j = k;
  while (j > 0 && f[j][0] === NEG) j--;
  const starts = [], total = f[j][0];
  for (let s = 0; j > 0 && s < L;) {
    if (f[j][s] === f[j][s + 1]) { s++; continue; }
    starts.push(s);
    s += block; j--;
  }
  return { starts, total: starts.length ? total : 0 };
}

/* The sharpest rise in loudness from a second before t to a quarter second
 * after it, minus a hair so the attack itself is in the clip. If nothing in
 * there is a real hit, t is left alone. */
export function snapToHit(rms, t, hop = HOP) {
  const at = Math.round(t / hop);
  const from = Math.max(3, at - Math.round(1 / hop)), to = Math.min(rms.length - 1, at + Math.round(0.25 / hop));
  let best = -1, bj = 0, level = 0;
  for (let i = from; i <= to; i++) level = Math.max(level, rms[i]);
  for (let i = from; i <= to; i++) {
    const jump = rms[i] - rms[i - 3];
    if (jump > bj) { bj = jump; best = i; }
  }
  if (best < 0 || bj < level * 0.25) return t;
  return Math.max(0, (best - 2) * hop);
}

/* The clip length when nobody has picked one: 15 seconds, the classic story
 * length. A video of 15 seconds or less is one clip of the whole thing. In
 * between, short enough for two clips -- but never under 7 seconds. It used
 * to aim for three clips and go down to 5 seconds, and a 15 second video came
 * back as a handful of snippets too short to be worth posting. */
export function autoLength(duration) {
  if (!(duration > 0)) return 15;
  if (duration <= 15) return duration;
  return Math.max(7, Math.min(15, Math.floor((duration + 1) / 2 - 1)));
}

/* No audio to listen to: spread the clips out across the video. */
export function evenly(duration, clipLen, count) {
  if (!(duration > 0) || !(clipLen > 0) || !(count > 0)) return [];
  if (duration <= clipLen) return [{ start: 0, end: duration, score: 1, rank: 1 }];
  const room = duration - clipLen;
  const n = Math.max(1, Math.min(count, Math.floor(duration / clipLen)));
  const out = [];
  for (let i = 0; i < n; i++) {
    const start = n === 1 ? room / 2 : room * i / (n - 1);
    out.push({ start: round2(start), end: round2(start + clipLen), score: 1, rank: i + 1 });
  }
  return out;
}

/* The part of the source frame that fills a 9:16 story. pan runs -1 (left
 * or top edge) to 1 (right or bottom edge), 0 is the middle. */
export function fillRect(vw, vh, outW = STORY_W, outH = STORY_H, pan = 0) {
  const want = outW / outH;
  const p = Math.max(-1, Math.min(1, pan || 0));
  if (vw / vh > want) {                     // wider than a story: crop the sides
    const sw = vh * want;
    return { sx: (vw - sw) / 2 * (1 + p), sy: 0, sw, sh: vh };
  }
  const sh = vw / want;                     // taller: crop top and bottom
  return { sx: 0, sy: (vh - sh) / 2 * (1 + p), sw: vw, sh };
}

/* The output size that keeps the video's own shape: the same aspect ratio,
 * the long side at most `maxLong` (never scaled up past the source), and
 * both sides even, because H.264 will not encode an odd width or height. */
export function keepSize(vw, vh, maxLong = 1920) {
  if (!(vw > 0) || !(vh > 0)) return { w: STORY_W, h: STORY_H };
  const s = Math.min(1, maxLong / Math.max(vw, vh));
  const even = (x) => Math.max(2, Math.round(x / 2) * 2);
  return { w: even(vw * s), h: even(vh * s) };
}

/* Where the whole frame sits inside the story when it is fitted, not cropped. */
export function fitRect(vw, vh, outW = STORY_W, outH = STORY_H) {
  const s = Math.min(outW / vw, outH / vh);
  const w = vw * s, h = vh * s;
  return { dx: (outW - w) / 2, dy: (outH - h) / 2, dw: w, dh: h };
}

export function clock(t) {
  t = Math.max(0, t || 0);
  const m = Math.floor(t / 60), s = Math.floor(t % 60);
  return m + ':' + String(s).padStart(2, '0');
}

/* A filename that sorts and says where in the video it came from. */
export function clipName(base, i, start, ext, kind = 'story') {
  const stem = String(base || 'video').replace(/\.[^.]+$/, '')
    .normalize('NFKD').replace(/[̀-ͯ]/g, '')
    .replace(/[^A-Za-z0-9]+/g, '-').replace(/^-|-$/g, '').slice(0, 40) || 'video';
  const m = Math.floor(start / 60), s = Math.floor(start % 60);
  return `${stem}-${kind}-${String(i + 1).padStart(2, '0')}-${m}m${String(s).padStart(2, '0')}s.${ext}`;
}

const round2 = (x) => Math.round(x * 100) / 100;

/* ---- one ZIP for every clip -----------------------------------------
 *
 * "Download all" used to mean one download per clip, which browsers treat
 * as a page spraying files: Chrome asks permission or quietly keeps only
 * the first, and a phone has no good answer at all. One ZIP is one
 * download everywhere.
 *
 * Stored, not compressed: the clips are already H.264 or VP9, so deflate
 * would spend seconds on a phone to save a few bytes. This is the plain
 * ZIP layout -- a local header and the data for each file, then a central
 * directory, then the end record -- which every unzipper reads, including
 * the Files app on an iPhone. Returns the pieces in order, ready for
 * new Blob(parts), so the clips are never copied into one big buffer. */

let CRC_TABLE = null;
export function crc32(bytes, crc = 0) {
  if (!CRC_TABLE) {
    CRC_TABLE = new Uint32Array(256);
    for (let n = 0; n < 256; n++) {
      let c = n;
      for (let k = 0; k < 8; k++) c = c & 1 ? 0xEDB88320 ^ (c >>> 1) : c >>> 1;
      CRC_TABLE[n] = c >>> 0;
    }
  }
  crc = ~crc >>> 0;
  for (let i = 0; i < bytes.length; i++) crc = CRC_TABLE[(crc ^ bytes[i]) & 0xFF] ^ (crc >>> 8);
  return ~crc >>> 0;
}

function dosTime(d) {
  return {
    time: (d.getHours() << 11) | (d.getMinutes() << 5) | (d.getSeconds() >> 1),
    date: ((Math.max(1980, d.getFullYear()) - 1980) << 9) | ((d.getMonth() + 1) << 5) | d.getDate()
  };
}

/* files: [{ name, data: Uint8Array }], or [{ name, body, size, crc }] where
 * body is a Blob -- the page passes the clips themselves that way, with the
 * CRC worked out once, so a ZIP of five clips is not five clips' worth of
 * extra memory on a phone. */
export function zipParts(files, when = new Date()) {
  const enc = new TextEncoder();
  const { time, date } = dosTime(when);
  const parts = [], central = [];
  let offset = 0;
  const used = new Set();
  for (const f of files) {
    // Two clips must never share a name, or one silently replaces the other.
    let name = f.name, n = 2;
    while (used.has(name)) name = f.name.replace(/(\.[^.]+)?$/, `-${n++}$1`);
    used.add(name);
    const nameBytes = enc.encode(name);
    const crc = f.crc != null ? f.crc : crc32(f.data);
    const size = f.size != null ? f.size : f.data.length;

    const local = new DataView(new ArrayBuffer(30));
    local.setUint32(0, 0x04034b50, true);
    local.setUint16(4, 20, true);              // version needed
    local.setUint16(6, 0x0800, true);          // names are UTF-8
    local.setUint16(8, 0, true);               // stored
    local.setUint16(10, time, true);
    local.setUint16(12, date, true);
    local.setUint32(14, crc, true);
    local.setUint32(18, size, true);
    local.setUint32(22, size, true);
    local.setUint16(26, nameBytes.length, true);
    local.setUint16(28, 0, true);
    parts.push(new Uint8Array(local.buffer), nameBytes, f.body || f.data);

    const cd = new DataView(new ArrayBuffer(46));
    cd.setUint32(0, 0x02014b50, true);
    cd.setUint16(4, 20, true);                 // made by
    cd.setUint16(6, 20, true);                 // needed
    cd.setUint16(8, 0x0800, true);
    cd.setUint16(10, 0, true);
    cd.setUint16(12, time, true);
    cd.setUint16(14, date, true);
    cd.setUint32(16, crc, true);
    cd.setUint32(20, size, true);
    cd.setUint32(24, size, true);
    cd.setUint16(28, nameBytes.length, true);
    cd.setUint32(42, offset, true);            // where its local header starts
    central.push(new Uint8Array(cd.buffer), nameBytes);

    offset += 30 + nameBytes.length + size;
  }
  const cdSize = central.reduce((n, p) => n + p.length, 0);
  const end = new DataView(new ArrayBuffer(22));
  end.setUint32(0, 0x06054b50, true);
  end.setUint16(8, files.length, true);
  end.setUint16(10, files.length, true);
  end.setUint32(12, cdSize, true);
  end.setUint32(16, offset, true);
  return parts.concat(central, [new Uint8Array(end.buffer)]);
}
