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

export function buildScene(canvas) {
  // Antialiasing costs a phone GPU more than it gives it, and a small screen
  // hides the jaggies anyway.
  const small = Math.min(innerWidth, innerHeight) < 700;
  const renderer = new THREE.WebGLRenderer({
    canvas, antialias: !small, alpha: false, powerPreference: 'high-performance'
  });

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x0b0c0e);
  scene.fog = new THREE.Fog(0x0b0c0e, 12, 26);

  const camera = new THREE.PerspectiveCamera(BASE_FOV, 1, 0.1, 100);
  camera.position.copy(WIDE_POS);
  camera.lookAt(WIDE_LOOK);

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

  return { renderer, scene, camera, lanes, takeNote, freeNote, resize,
           SPEED, LOOKAHEAD, HIT_Z };
}
