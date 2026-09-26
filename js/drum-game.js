/* The drum game.
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
import * as THREE from 'three';

export const LANES = [
  { id: 'hat',   label: 'Hi-hat', key: 'a',   colour: 0x7ee7c7, x: -2.3 },
  { id: 'snare', label: 'Snare',  key: 's',   colour: 0xf4b400, x:  0.0 },
  { id: 'kick',  label: 'Kick',   key: ' ',   colour: 0xe8672a, x:  2.3 }
];

// How far ahead a note is visible, in seconds of music. Long enough to read a
// pattern coming, short enough that the runway is not a wall of dots.
const LOOKAHEAD = 1.9;
const SPEED = 9.0;              // world units per second of music
const HIT_Z = 0;                // where the pads are

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

/* ---- the scene -------------------------------------------------------- */

export function buildScene(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: false });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0c0e);
  scene.fog = new THREE.Fog(0x0b0c0e, 12, 26);

  const camera = new THREE.PerspectiveCamera(58, 1, 0.1, 100);
  camera.position.set(0, 3.4, 7.2);
  camera.lookAt(0, 0.2, -4);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(3, 8, 6);
  scene.add(key);

  // The runway. One plane per lane, dark, with the lane colour bled in at the
  // near end so you can tell which is which without reading the labels.
  const lanes = LANES.map((lane) => {
    const g = new THREE.PlaneGeometry(1.9, LOOKAHEAD * SPEED + 6);
    const m = new THREE.MeshBasicMaterial({ color: 0x14161a });
    const mesh = new THREE.Mesh(g, m);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(lane.x, -0.02, HIT_Z - (LOOKAHEAD * SPEED + 6) / 2 + 3);
    scene.add(mesh);

    // The pad: a squat cylinder, lit from inside when struck.
    const pad = new THREE.Mesh(
      new THREE.CylinderGeometry(0.82, 0.86, 0.22, 40),
      new THREE.MeshStandardMaterial({
        color: lane.colour, emissive: lane.colour,
        emissiveIntensity: 0.12, roughness: 0.5, metalness: 0.1
      })
    );
    pad.position.set(lane.x, 0.06, HIT_Z);
    scene.add(pad);

    // A ring that flares on a hit, so the feedback reads even when the pad is
    // covered by the note that just landed on it.
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.9, 1.15, 48),
      new THREE.MeshBasicMaterial({ color: lane.colour, transparent: true, opacity: 0 })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(lane.x, 0.08, HIT_Z);
    scene.add(ring);

    return { ...lane, mesh, pad, ring, flash: 0 };
  });

  // Notes are pooled. A three minute song is a couple of thousand notes and
  // thirty of them are on screen; allocating a mesh per note would spend the
  // whole frame budget in the garbage collector.
  const pool = [];
  function takeNote(colour) {
    const n = pool.pop() || new THREE.Mesh(
      new THREE.CylinderGeometry(0.62, 0.62, 0.16, 28),
      new THREE.MeshStandardMaterial({ roughness: 0.35, metalness: 0.15 })
    );
    n.material.color.setHex(colour);
    n.material.emissive.setHex(colour);
    n.material.emissiveIntensity = 0.45;
    n.visible = true;
    scene.add(n);
    return n;
  }
  function freeNote(mesh) {
    scene.remove(mesh);
    mesh.visible = false;
    pool.push(mesh);
  }

  function resize() {
    const w = canvas.clientWidth || 960;
    const h = canvas.clientHeight || 540;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
  }

  return { renderer, scene, camera, lanes, takeNote, freeNote, resize,
           SPEED, LOOKAHEAD, HIT_Z };
}
