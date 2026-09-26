/* Drawing the game. Everything here needs a GPU; nothing here decides
 * anything. The rules are in drum-game.js, which stays importable by a test.
 */
import * as THREE from 'three';
import { LANES } from './drum-game.js';

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
