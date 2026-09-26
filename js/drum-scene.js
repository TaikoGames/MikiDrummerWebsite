/* Drawing the game. Everything here needs a GPU; nothing here decides
 * anything. The rules are in drum-game.js, which stays importable by a test.
 *
 * Three is imported by path rather than through an import map. An import map
 * needs Safari 16.4, and a phone one release older does not fail loudly: it
 * ignores the map, cannot resolve the bare specifier 'three', and refuses to
 * run the module at all. Nothing throws, nothing logs, the page simply sits
 * on "Loading the song list" for ever. A path resolves in every browser that
 * has modules at all, and costs nothing.
 */
import * as THREE from '/vendor/three/three.module.js';
import { LANES, LOOKAHEAD, SPEED, HIT_Z } from '/js/drum-game.js';

// The camera has to keep all three lanes on screen. On a laptop that is free;
// in portrait on a phone the viewport is taller than it is wide, and a fixed
// vertical field of view shows a slice narrow enough to slice the outer lanes
// off the edges. These are what resize() works back from.
const PAD_CENTRE = new THREE.Vector3(0, 0.06, 0);
const HALF_WIDTH = 3.7;   // world units either side of centre that must be visible
const BASE_FOV = 58;
const MAX_FOV = 74;

// Two framings, blended by how wide the window is. The low one is the good
// view on a laptop. It is the wrong view on a phone held upright: the
// vanishing point lands a third of the way up and the two thirds above it are
// empty sky, so the runway gets a strip of a screen the player is holding all
// of. Tilting down as the window narrows spends the whole screen on the game.
const WIDE_POS  = new THREE.Vector3(0, 3.4, 7.2);
const WIDE_LOOK = new THREE.Vector3(0, 0.2, -4);
const TALL_POS  = new THREE.Vector3(0, 5.8, 6.2);
const TALL_LOOK = new THREE.Vector3(0, -0.2, -6.5);
const pos = new THREE.Vector3(), look = new THREE.Vector3(), back = new THREE.Vector3();

// How far back the world is drawn. The runway ends where the fog does; the
// background carries on past it so there is somewhere for the song to happen.
const FOG_NEAR = 14, FOG_FAR = 44;
const GRID_STEP = 3.0;        // metres between floor lines
const GRID_BACK = 60;         // how far the floor grid reaches

/* A vertical gradient for the sky, drawn once into a 2-pixel-wide canvas.
 * Cheaper than a shader, cheaper than an image, and it is the difference
 * between a game in a room and a game in a void. */
function makeSky() {
  const c = document.createElement('canvas');
  c.width = 2; c.height = 256;
  const g = c.getContext('2d').createLinearGradient(0, 0, 0, 256);
  g.addColorStop(0.00, '#05060a');
  g.addColorStop(0.55, '#0d0f15');
  g.addColorStop(0.82, '#1b1410');
  g.addColorStop(1.00, '#2a1608');   // the band's orange, buried
  const ctx = c.getContext('2d');
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, 2, 256);
  const tex = new THREE.CanvasTexture(c);
  tex.colorSpace = THREE.SRGBColorSpace;
  return tex;
}

export function buildScene(canvas) {
  // Antialiasing costs a phone GPU more than it gives it, and a small screen
  // hides the jaggies anyway.
  const small = Math.min(innerWidth, innerHeight) < 700;
  const renderer = new THREE.WebGLRenderer({
    canvas, antialias: !small, alpha: false, powerPreference: 'high-performance'
  });

  const scene = new THREE.Scene();
  scene.background = makeSky();
  scene.fog = new THREE.Fog(0x0b0c0e, FOG_NEAR, FOG_FAR);

  const camera = new THREE.PerspectiveCamera(BASE_FOV, 1, 0.1, 100);
  camera.position.copy(WIDE_POS);
  camera.lookAt(WIDE_LOOK);

  scene.add(new THREE.AmbientLight(0xffffff, 0.55));
  const key = new THREE.DirectionalLight(0xffffff, 0.9);
  key.position.set(3, 8, 6);
  scene.add(key);

  // The runway. One plane per lane, dark, with the lane colour bled in at the
  // near end so you can tell which is which without reading the labels.
  // The runway runs all the way back to where the fog swallows it. It used to
  // stop at the lookahead distance, which was fine when the fog closed in at
  // 26 and the end was never visible -- once the background opened the view
  // up, the lanes ended in a hard horizontal seam across the middle of the
  // screen with the floor grid showing through beyond it.
  const RUN = GRID_BACK;
  const lanes = LANES.map((lane) => {
    const g = new THREE.PlaneGeometry(1.9, RUN);
    const m = new THREE.MeshBasicMaterial({ color: 0x14161a, fog: true });
    const mesh = new THREE.Mesh(g, m);
    mesh.rotation.x = -Math.PI / 2;
    mesh.position.set(lane.x, -0.02, HIT_Z - RUN / 2 + 3);
    scene.add(mesh);

    // A lit edge down each side, in the lane's colour, so which lane is which
    // reads from the far end of the runway instead of only at the pads.
    const rail = new THREE.Mesh(
      new THREE.PlaneGeometry(0.06, RUN),
      new THREE.MeshBasicMaterial({ color: lane.colour, transparent: true,
                                    opacity: 0.30, fog: true })
    );
    rail.rotation.x = -Math.PI / 2;
    rail.position.set(lane.x - 0.97, -0.015, mesh.position.z);
    scene.add(rail);
    const rail2 = rail.clone();
    rail2.position.x = lane.x + 0.97;
    scene.add(rail2);

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
    //
    // (The moment itself is marked by the judgement line below, which runs
    // across all three lanes. Without it there is nothing on screen that says
    // "now" -- the pads are round, the notes land on top of them and cover
    // them, and the eye has no edge to line anything up against. A rhythm
    // game that does not draw its own hit line is asking the player to
    // estimate where it is.)
    const ring = new THREE.Mesh(
      new THREE.RingGeometry(0.9, 1.15, 48),
      new THREE.MeshBasicMaterial({ color: lane.colour, transparent: true, opacity: 0 })
    );
    ring.rotation.x = -Math.PI / 2;
    ring.position.set(lane.x, 0.08, HIT_Z);
    scene.add(ring);

    return { ...lane, mesh, pad, ring, rails: [rail, rail2], flash: 0 };
  });

  /* ---- the world the runway sits in --------------------------------- */
  /* All of this is three draw calls and no per-frame allocation, because it
   * has to survive a five-year-old phone that is already doing the actual
   * game. Everything moves toward the camera at the same rate the notes do,
   * which is what sells the runway as motion rather than as a dark rectangle
   * with dots sliding down it. */

  // A floor grid, receding into the fog. Lines along the run and across it.
  const gridPts = [];
  for (let x = -30; x <= 30; x += GRID_STEP) {
    gridPts.push(x, -1.2, 6, x, -1.2, -GRID_BACK);
  }
  for (let z = 6; z >= -GRID_BACK; z -= GRID_STEP) {
    gridPts.push(-30, -1.2, z, 30, -1.2, z);
  }
  const grid = new THREE.LineSegments(
    new THREE.BufferGeometry().setAttribute(
      'position', new THREE.Float32BufferAttribute(gridPts, 3)),
    new THREE.LineBasicMaterial({ color: 0x2a3138, transparent: true, opacity: 0.55, fog: true })
  );
  scene.add(grid);

  // Sparks drifting up out of the floor. One Points object, one draw call.
  const STARS = small ? 240 : 650;
  const sp = new Float32Array(STARS * 3);
  const drift = new Float32Array(STARS);
  for (let i = 0; i < STARS; i++) {
    sp[i * 3]     = (Math.random() - 0.5) * 56;
    sp[i * 3 + 1] = Math.random() * 16 - 1;
    sp[i * 3 + 2] = 6 - Math.random() * GRID_BACK;
    drift[i] = 0.25 + Math.random() * 0.9;
  }
  const starGeo = new THREE.BufferGeometry();
  starGeo.setAttribute('position', new THREE.BufferAttribute(sp, 3));
  const stars = new THREE.Points(starGeo, new THREE.PointsMaterial({
    color: 0xe8672a, size: small ? 0.13 : 0.1, transparent: true,
    opacity: 0.5, sizeAttenuation: true, fog: true, depthWrite: false
  }));
  scene.add(stars);

  // THE JUDGEMENT LINE. Where "now" is. Bright, hard-edged and across all
  // three lanes, so a note arriving is a note crossing something rather than
  // a note being vaguely near a circle.
  const hitLine = new THREE.Mesh(
    new THREE.PlaneGeometry(7.4, 0.13),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true,
                                  opacity: 0.82, fog: false, depthWrite: false })
  );
  hitLine.rotation.x = -Math.PI / 2;
  hitLine.position.set(0, 0.17, HIT_Z);
  scene.add(hitLine);

  // A soft glow under it, so it reads on a bright phone screen outdoors.
  const hitGlow = new THREE.Mesh(
    new THREE.PlaneGeometry(7.4, 1.5),
    new THREE.MeshBasicMaterial({ color: 0xffffff, transparent: true,
                                  opacity: 0.07, fog: false, depthWrite: false })
  );
  hitGlow.rotation.x = -Math.PI / 2;
  hitGlow.position.set(0, 0.03, HIT_Z);
  scene.add(hitGlow);

  // A bar across the far end that flares on every beat of the song. The
  // charts carry the beats the tracker found, so this is in time with the
  // record rather than with a guess at its tempo.
  const horizon = new THREE.Mesh(
    new THREE.PlaneGeometry(64, 0.9),
    new THREE.MeshBasicMaterial({ color: 0xe8672a, transparent: true, opacity: 0.12,
                                  fog: false, depthWrite: false })
  );
  horizon.position.set(0, 0.4, -GRID_BACK * 0.55);
  scene.add(horizon);

  // Notes are pooled. A three minute song is a couple of thousand notes and
  // thirty of them are on screen; allocating a mesh per note would spend the
  // whole frame budget in the garbage collector.
  const pool = [];
  function takeNote(colour) {
    const n = pool.pop() || new THREE.Mesh(
      new THREE.CylinderGeometry(0.62, 0.62, 0.16, small ? 18 : 28),
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

  /* Move the world. dt is seconds since the last frame, pulse is 0..1 and
   * decays from 1 on each beat of the song.
   *
   * Driven by real elapsed time rather than by frame count, so it runs at the
   * same speed on a 60 Hz phone and a 120 Hz one -- and, unlike the notes,
   * nothing here is judged, so the frame clock is the right clock for it. */
  const starPos = starGeo.attributes.position;
  function update(dt, pulse) {
    if (!(dt > 0)) return;
    const d = Math.min(dt, 0.1);            // a tab coming back from sleep

    grid.position.z = (grid.position.z + d * SPEED * 0.55) % GRID_STEP;

    const a = starPos.array;
    for (let i = 0; i < STARS; i++) {
      const k = i * 3;
      a[k + 2] += d * SPEED * drift[i];
      a[k + 1] += d * 0.35;
      if (a[k + 2] > 8) {                   // wrap round the back
        a[k + 2] -= GRID_BACK + 8;
        a[k + 1] = Math.random() * 6 - 1;
        a[k]     = (Math.random() - 0.5) * 56;
      }
      if (a[k + 1] > 15) a[k + 1] = -1;
    }
    starPos.needsUpdate = true;

    const p = pulse || 0;
    // The judgement line breathes on the beat too, so the moment the eye is
    // watching is the moment the music is marking.
    hitLine.material.opacity = 0.72 + p * 0.28;
    hitGlow.material.opacity = 0.06 + p * 0.14;
    horizon.material.opacity = 0.10 + p * 0.5;
    horizon.scale.y = 1 + p * 2.6;
    stars.material.opacity = 0.42 + p * 0.3;
    grid.material.opacity = 0.45 + p * 0.35;
  }

  function resize() {
    const w = canvas.clientWidth || 960;
    const h = canvas.clientHeight || 540;
    const aspect = w / h;

    // Retina on a phone means drawing four times the pixels for a frame the
    // player cannot see the difference in, and a frame rate they can.
    const cap = w < 700 ? 1.5 : 2;
    renderer.setPixelRatio(Math.min(devicePixelRatio || 1, cap));
    renderer.setSize(w, h, false);

    // 0 on a laptop, 1 on a phone held upright.
    const tall = Math.min(1, Math.max(0, (1.35 - aspect) / 0.6));
    pos.copy(WIDE_POS).lerp(TALL_POS, tall);
    look.copy(WIDE_LOOK).lerp(TALL_LOOK, tall);

    // Widen the lens until the outer lanes fit, and if the lens runs out of
    // room -- a very tall, very narrow window -- step the camera back instead.
    const fov = aspect < 1.35 ? Math.min(MAX_FOV, BASE_FOV * (1.35 / aspect)) : BASE_FOV;
    const reach = HALF_WIDTH / (Math.tan(fov * Math.PI / 360) * aspect);
    camera.fov = fov;
    camera.position.copy(pos);
    const have = pos.distanceTo(PAD_CENTRE);
    if (reach > have) {
      back.copy(pos).sub(look).normalize();
      camera.position.addScaledVector(back, reach - have);
    }
    camera.lookAt(look);
    camera.aspect = aspect;
    camera.updateProjectionMatrix();
  }

  return { renderer, scene, camera, lanes, takeNote, freeNote, resize, update,
           SPEED, LOOKAHEAD, HIT_Z };
}
