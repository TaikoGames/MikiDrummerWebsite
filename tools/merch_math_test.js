/* Checks on the geometry behind the merch mockups.
 *
 *     node tools/merch_math_test.js
 *
 * Plain node, no browser and no dependencies -- these are the parts of
 * js/merch-photo.js that are arithmetic rather than canvas, and they are the
 * parts that fail silently. A warp that is slightly wrong still produces a
 * picture; it just produces one where the artwork does not sit on the
 * garment, and nobody notices until a band has ordered a hundred shirts.
 *
 * The shading side is checked in a real browser, since it needs getImageData.
 * Measured on cloth at luma 46 with a crease and a lit ridge cut through it,
 * printing mid-grey (180) ink:
 *
 *     flat ink    180 on fabric, 180 in the crease, 180 on the ridge
 *     printed     174 on fabric,  77 in the crease, 255 on the ridge
 *
 * which is the whole point: flat ignores the cloth, printed goes dark in the
 * crease with it.
 */
'use strict';

global.window = {};
global.document = { createElement: function () { return { getContext: function () { return {}; } }; } };
require('../js/merch-photo.js');
const M = global.window.MerchPhoto;

let fails = 0;
const near = (a, b, t) => Math.abs(a - b) <= (t === undefined ? 1e-6 : t);
function ok(cond, msg) { if (!cond) { console.log('FAIL ' + msg); fails++; } }

// Whatever else it does, the mapping has to put the corners on the corners.
// If it does not, the artwork does not line up with the area the person
// dragged, and every other thing here is beside the point.
[
  [[0, 0], [100, 0], [100, 100], [0, 100]],        // rectangle
  [[10, 5], [100, 0], [80, 100], [20, 90]],        // irregular
  [[0, 0], [100, 0], [80, 100], [20, 100]],        // trapezoid
  [[0, 0], [100, 20], [120, 120], [20, 100]]       // parallelogram: affine path
].forEach(q => {
  const f = M.homography(q);
  [[0, 0], [1, 0], [1, 1], [0, 1]].forEach(([u, v], i) => {
    const p = f(u, v);
    ok(near(p.x, q[i][0], 1e-9) && near(p.y, q[i][1], 1e-9),
       `corner ${i} of ${JSON.stringify(q)} landed at ${p.x},${p.y}`);
  });
});

// A rectangle has no perspective in it, so the middle is the middle.
{
  const p = M.homography([[0, 0], [100, 0], [100, 100], [0, 100]])(0.5, 0.5);
  ok(near(p.x, 50) && near(p.y, 50), `rectangle centre came out at ${p.x},${p.y}`);
}

// A trapezoid does have perspective, and this is the check that distinguishes
// a real projective map from the bilinear one it is tempting to write instead.
// Bilinear would put the texture's midpoint at y=50; a receding plane puts it
// further away than that, because the near half of the surface takes up more
// of the picture than the far half.
{
  const p = M.homography([[0, 0], [100, 0], [80, 100], [20, 100]])(0.5, 0.5);
  ok(near(p.x, 50, 1e-9), `trapezoid drifted sideways to x=${p.x}`);
  ok(p.y > 55, `no foreshortening: midpoint y=${p.y.toFixed(2)}, bilinear would be 50`);
}

// The median is what "unshaded cloth" means, so it has to be the cloth and not
// whatever extreme happens to be in frame. A photograph of a black shirt will
// have a specular highlight somewhere in it; anchoring to a mean would let
// that one blowout set the exposure for the whole print.
{
  const px = [];
  const push = (v, n) => { for (let i = 0; i < n; i++) px.push(v, v, v, 255); };
  push(46, 300);          // fabric
  push(12, 20);           // a deep crease
  push(250, 60);          // a highlight, big enough to drag a mean well off
  const med = M.medianLuma(new Uint8ClampedArray(px));
  const mean = px.filter((_, i) => i % 4 === 0).reduce((a, b) => a + b, 0) / 380;
  ok(med === 46, `median should be the fabric's 46, got ${med}`);
  ok(mean > 70, `test is pointless unless the mean is skewed; it is ${mean.toFixed(1)}`);
  console.log(`   median ${med} (the fabric) vs mean ${mean.toFixed(1)} (the highlight)`);
}

// Nothing to measure: better neutral than a divide by zero further down.
ok(M.medianLuma(new Uint8ClampedArray(200)) === 128, 'empty surface should read neutral');

// Corners can be dragged off the edge of the picture, so the read-back
// rectangle has to stay inside the canvas or getImageData throws.
{
  const b = M.bounds([[-50, -50], [100, 0], [120, 200], [0, 180]], 200, 150);
  ok(b.x >= 0 && b.y >= 0 && b.x + b.w <= 200 && b.y + b.h <= 150,
     `bounds escaped the canvas: ${JSON.stringify(b)}`);
}
// A quad entirely off-canvas must come back empty rather than negative.
{
  const b = M.bounds([[-90, -90], [-50, -90], [-50, -50], [-90, -50]], 200, 150);
  ok(b.w === 0 || b.h === 0, `off-canvas quad should be empty: ${JSON.stringify(b)}`);
}

console.log(fails ? `${fails} check(s) FAILED` : 'merch geometry: all checks passed');
process.exit(fails ? 1 : 0);
