/* The starting-point blanks for the merch mockup tool, drawn rather than
 * photographed.
 *
 * The real answer is a photograph of the blank the band is actually going to
 * print, which is what js/merch-photo.js is for. These exist because a tool
 * that opens on an empty canvas and demands a photo before it shows you
 * anything is a tool most people close again. They are somewhere to start:
 * pick a product, see the logo on it, and go and photograph the real shirt
 * once you know it is worth doing.
 *
 * Being drawn buys three things worth having for that job. Recolouring is a
 * fill, so every colour is available rather than only the ones that got shot.
 * The silhouettes scale to any export size. And a drum head and a pair of
 * sticks cost the same to add as a t-shirt, which matters here -- nobody
 * stocks a blank drum head mockup, and a drummer's merch table is half
 * drum-shaped.
 *
 * They go through the same printing engine as a photograph does, so the
 * artwork picks up their shading too.
 *
 * Each blank exposes:
 *   draw(ctx, W, H, colour)   paint the product
 *   print                     {x, y, w, h} in 0..1, where artwork goes
 *   dark                      true if the blank is dark, so light art is offered
 *
 * Shading is deliberately restrained. A drawn garment with heavy fake
 * highlights reads as a bad 3D render; flat with one soft shadow reads as a
 * deliberate illustration, which is what this is.
 */
(function (global) {
  'use strict';

  function shade(ctx, x, y, w, h, colour, strength) {
    var g = ctx.createLinearGradient(x, y, x + w, y + h);
    g.addColorStop(0, 'rgba(255,255,255,' + (strength * 0.5) + ')');
    g.addColorStop(0.45, 'rgba(255,255,255,0)');
    g.addColorStop(1, 'rgba(0,0,0,' + strength + ')');
    ctx.fillStyle = g;
    ctx.fill();
  }

  function seam(ctx, strength) {
    ctx.strokeStyle = 'rgba(0,0,0,' + strength + ')';
    ctx.lineWidth = 2;
    ctx.stroke();
  }

  // ---- apparel -----------------------------------------------------------

  function tee(ctx, W, H, colour, opts) {
    opts = opts || {};
    var long = !!opts.longSleeve, hood = !!opts.hood;
    var cx = W / 2;
    var shoulder = H * 0.17, hem = H * 0.92;
    var halfBody = W * 0.275, halfShoulder = W * 0.315;

    ctx.beginPath();
    // left shoulder down to hem, across, and back up the right
    ctx.moveTo(cx - halfShoulder, shoulder);
    ctx.lineTo(cx - halfBody, H * 0.34);
    ctx.lineTo(cx - halfBody * 1.06, hem);
    ctx.quadraticCurveTo(cx, hem + H * 0.025, cx + halfBody * 1.06, hem);
    ctx.lineTo(cx + halfBody, H * 0.34);
    ctx.lineTo(cx + halfShoulder, shoulder);
    // neckline
    ctx.quadraticCurveTo(cx, shoulder + H * 0.085, cx - halfShoulder, shoulder);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
    shade(ctx, cx - halfShoulder, shoulder, halfShoulder * 2, hem - shoulder, colour, 0.16);
    seam(ctx, 0.18);

    // sleeves
    var sleeveEnd = long ? H * 0.62 : H * 0.38;
    [-1, 1].forEach(function (s) {
      ctx.beginPath();
      ctx.moveTo(cx + s * halfShoulder, shoulder);
      ctx.lineTo(cx + s * (halfShoulder + W * 0.115), shoulder + H * 0.06);
      ctx.lineTo(cx + s * (halfShoulder + W * (long ? 0.085 : 0.105)), sleeveEnd);
      ctx.lineTo(cx + s * halfBody, sleeveEnd - H * (long ? 0.20 : 0.035));
      ctx.closePath();
      ctx.fillStyle = colour;
      ctx.fill();
      shade(ctx, cx + s * halfShoulder, shoulder, s * W * 0.12, sleeveEnd - shoulder, colour, 0.2);
      seam(ctx, 0.16);
    });

    // collar ribbing
    ctx.beginPath();
    ctx.moveTo(cx - halfShoulder * 0.62, shoulder + H * 0.004);
    ctx.quadraticCurveTo(cx, shoulder + H * 0.072, cx + halfShoulder * 0.62, shoulder + H * 0.004);
    ctx.quadraticCurveTo(cx, shoulder + H * 0.105, cx - halfShoulder * 0.62, shoulder + H * 0.004);
    ctx.closePath();
    ctx.fillStyle = 'rgba(0,0,0,0.16)';
    ctx.fill();

    if (hood) {
      ctx.beginPath();
      ctx.moveTo(cx - halfShoulder * 0.86, shoulder + H * 0.01);
      ctx.quadraticCurveTo(cx, shoulder - H * 0.105, cx + halfShoulder * 0.86, shoulder + H * 0.01);
      ctx.quadraticCurveTo(cx, shoulder + H * 0.10, cx - halfShoulder * 0.86, shoulder + H * 0.01);
      ctx.closePath();
      ctx.fillStyle = colour;
      ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.13)';
      ctx.fill();
      seam(ctx, 0.16);
      // drawstrings
      ctx.strokeStyle = 'rgba(0,0,0,0.3)';
      ctx.lineWidth = 3;
      [-1, 1].forEach(function (s) {
        ctx.beginPath();
        ctx.moveTo(cx + s * W * 0.03, shoulder + H * 0.055);
        ctx.lineTo(cx + s * W * 0.045, shoulder + H * 0.135);
        ctx.stroke();
      });
      // pocket
      ctx.beginPath();
      ctx.moveTo(cx - halfBody * 0.82, H * 0.66);
      ctx.lineTo(cx + halfBody * 0.82, H * 0.66);
      ctx.lineTo(cx + halfBody * 0.72, H * 0.80);
      ctx.lineTo(cx - halfBody * 0.72, H * 0.80);
      ctx.closePath();
      ctx.strokeStyle = 'rgba(0,0,0,0.22)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
  }

  function tote(ctx, W, H, colour) {
    var cx = W / 2, top = H * 0.26, bot = H * 0.90, half = W * 0.295;
    // handles first, so the bag sits over their roots
    ctx.strokeStyle = colour;
    ctx.lineWidth = W * 0.022;
    ctx.lineCap = 'round';
    [-1, 1].forEach(function (s) {
      ctx.beginPath();
      ctx.moveTo(cx + s * half * 0.55, top + 4);
      ctx.quadraticCurveTo(cx + s * half * 0.72, H * 0.10, cx + s * half * 0.12, H * 0.115);
      ctx.stroke();
    });
    ctx.beginPath();
    ctx.rect(cx - half, top, half * 2, bot - top);
    ctx.fillStyle = colour;
    ctx.fill();
    shade(ctx, cx - half, top, half * 2, bot - top, colour, 0.15);
    seam(ctx, 0.18);
  }

  function cap(ctx, W, H, colour) {
    var cx = W / 2, cy = H * 0.58, r = W * 0.31;
    ctx.beginPath();
    ctx.arc(cx, cy, r, Math.PI, 0);
    ctx.lineTo(cx + r, cy + H * 0.02);
    ctx.lineTo(cx - r, cy + H * 0.02);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
    shade(ctx, cx - r, cy - r, r * 2, r, colour, 0.18);
    seam(ctx, 0.18);
    // peak
    ctx.beginPath();
    ctx.ellipse(cx + r * 0.30, cy + H * 0.016, r * 1.00, H * 0.052, 0.06, 0, Math.PI);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
    ctx.fillStyle = 'rgba(0,0,0,0.18)';
    ctx.fill();
    seam(ctx, 0.2);
    // button
    ctx.beginPath();
    ctx.arc(cx, cy - r, W * 0.012, 0, Math.PI * 2);
    ctx.fillStyle = 'rgba(0,0,0,0.3)';
    ctx.fill();
  }

  // ---- the drummer's half ------------------------------------------------

  function drumhead(ctx, W, H, colour) {
    var cx = W / 2, cy = H * 0.50, r = W * 0.38;
    // hoop
    ctx.beginPath();
    ctx.arc(cx, cy, r * 1.09, 0, Math.PI * 2);
    ctx.fillStyle = '#c9ccd1';
    ctx.fill();
    var g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    g.addColorStop(0, 'rgba(255,255,255,0.55)');
    g.addColorStop(0.5, 'rgba(0,0,0,0.12)');
    g.addColorStop(1, 'rgba(0,0,0,0.35)');
    ctx.fillStyle = g; ctx.fill();
    // lugs
    for (var i = 0; i < 10; i++) {
      var a = (i / 10) * Math.PI * 2 - Math.PI / 2;
      ctx.beginPath();
      ctx.arc(cx + Math.cos(a) * r * 1.09, cy + Math.sin(a) * r * 1.09, W * 0.017, 0, Math.PI * 2);
      ctx.fillStyle = '#8f949b'; ctx.fill();
    }
    // head
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = colour;
    ctx.fill();
    var gg = ctx.createRadialGradient(cx - r * 0.35, cy - r * 0.4, r * 0.1, cx, cy, r);
    gg.addColorStop(0, 'rgba(255,255,255,0.18)');
    gg.addColorStop(1, 'rgba(0,0,0,0.22)');
    ctx.fillStyle = gg; ctx.fill();
  }

  function sticks(ctx, W, H, colour) {
    // Two sticks lying at a slight angle, tips up. The print area is the shaft
    // of the upper one, which is where a maker's logo goes.
    [[-1, 0.60], [1, 0.46]].forEach(function (s, i) {
      ctx.save();
      ctx.translate(W / 2, H * s[1]);
      ctx.rotate((i ? -1 : 1) * 0.055);
      var len = W * 0.86, w = W * 0.044;
      ctx.beginPath();
      ctx.moveTo(-len / 2, -w / 2);
      ctx.lineTo(len / 2 - w * 2.2, -w / 2);
      ctx.quadraticCurveTo(len / 2, -w * 0.62, len / 2, 0);        // taper to the tip
      ctx.quadraticCurveTo(len / 2, w * 0.62, len / 2 - w * 2.2, w / 2);
      ctx.lineTo(-len / 2, w / 2);
      ctx.quadraticCurveTo(-len / 2 - w * 0.3, 0, -len / 2, -w / 2);
      ctx.closePath();
      ctx.fillStyle = colour;
      ctx.fill();
      var g = ctx.createLinearGradient(0, -w / 2, 0, w / 2);
      g.addColorStop(0, 'rgba(255,255,255,0.32)');
      g.addColorStop(0.5, 'rgba(255,255,255,0)');
      g.addColorStop(1, 'rgba(0,0,0,0.30)');
      ctx.fillStyle = g; ctx.fill();
      // tip
      ctx.beginPath();
      ctx.ellipse(len / 2 - w * 0.5, 0, w * 0.62, w * 0.55, 0, 0, Math.PI * 2);
      ctx.fillStyle = colour; ctx.fill();
      ctx.fillStyle = 'rgba(0,0,0,0.16)'; ctx.fill();
      ctx.restore();
    });
  }

  function sticker(ctx, W, H, colour) {
    var cx = W / 2, cy = H * 0.5, r = W * 0.36;
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.45)';
    ctx.shadowBlur = W * 0.03;
    ctx.shadowOffsetY = W * 0.012;
    ctx.beginPath();
    // die-cut square with generous radius
    var s = r * 1.6, x = cx - s / 2, y = cy - s / 2, rad = s * 0.12;
    ctx.moveTo(x + rad, y);
    ctx.arcTo(x + s, y, x + s, y + s, rad);
    ctx.arcTo(x + s, y + s, x, y + s, rad);
    ctx.arcTo(x, y + s, x, y, rad);
    ctx.arcTo(x, y, x + s, y, rad);
    ctx.closePath();
    ctx.fillStyle = colour;
    ctx.fill();
    ctx.restore();
    ctx.strokeStyle = 'rgba(255,255,255,0.5)';
    ctx.lineWidth = W * 0.008;
    ctx.stroke();
  }

  function pin(ctx, W, H, colour) {
    var cx = W / 2, cy = H * 0.5, r = W * 0.30;
    ctx.save();
    ctx.shadowColor = 'rgba(0,0,0,0.5)';
    ctx.shadowBlur = W * 0.035;
    ctx.shadowOffsetY = W * 0.014;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = colour;
    ctx.fill();
    ctx.restore();
    // metal rim
    ctx.lineWidth = W * 0.016;
    var g = ctx.createLinearGradient(cx - r, cy - r, cx + r, cy + r);
    g.addColorStop(0, '#f2e9c9'); g.addColorStop(0.5, '#a9935c'); g.addColorStop(1, '#f2e9c9');
    ctx.strokeStyle = g;
    ctx.beginPath();
    ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.stroke();
    var gg = ctx.createRadialGradient(cx - r * 0.4, cy - r * 0.45, r * 0.05, cx, cy, r);
    gg.addColorStop(0, 'rgba(255,255,255,0.22)');
    gg.addColorStop(1, 'rgba(0,0,0,0.20)');
    ctx.beginPath(); ctx.arc(cx, cy, r, 0, Math.PI * 2);
    ctx.fillStyle = gg; ctx.fill();
  }

  function flag(ctx, W, H, colour) {
    // A backdrop banner -- the thing behind the drum riser.
    var x = W * 0.08, y = H * 0.22, w = W * 0.84, h = H * 0.54;
    ctx.beginPath();
    ctx.rect(x, y, w, h);
    ctx.fillStyle = colour;
    ctx.fill();
    shade(ctx, x, y, w, h, colour, 0.14);
    seam(ctx, 0.2);
    // grommets
    [[x, y], [x + w, y], [x, y + h], [x + w, y + h]].forEach(function (p) {
      ctx.beginPath();
      ctx.arc(p[0], p[1], W * 0.011, 0, Math.PI * 2);
      ctx.fillStyle = '#b9bec5'; ctx.fill();
    });
  }

  global.MerchBlanks = {
    tee: { name: 'T-shirt', draw: function (c, W, H, col) { tee(c, W, H, col); },
           print: { x: 0.355, y: 0.28, w: 0.29, h: 0.30 } },
    longsleeve: { name: 'Long sleeve', draw: function (c, W, H, col) { tee(c, W, H, col, { longSleeve: true }); },
           print: { x: 0.355, y: 0.28, w: 0.29, h: 0.30 } },
    hoodie: { name: 'Hoodie', draw: function (c, W, H, col) { tee(c, W, H, col, { longSleeve: true, hood: true }); },
           print: { x: 0.365, y: 0.33, w: 0.27, h: 0.26 } },
    tote: { name: 'Tote bag', draw: tote, print: { x: 0.295, y: 0.38, w: 0.41, h: 0.34 } },
    cap: { name: 'Cap', draw: cap, print: { x: 0.375, y: 0.40, w: 0.25, h: 0.13 } },
    drumhead: { name: 'Drum head', draw: drumhead, print: { x: 0.28, y: 0.32, w: 0.44, h: 0.38 } },
    sticks: { name: 'Drumsticks', draw: sticks, print: { x: 0.24, y: 0.408, w: 0.34, h: 0.05 } },
    sticker: { name: 'Sticker', draw: sticker, print: { x: 0.26, y: 0.26, w: 0.48, h: 0.48 } },
    pin: { name: 'Enamel pin', draw: pin, print: { x: 0.30, y: 0.30, w: 0.40, h: 0.40 } },
    banner: { name: 'Stage banner', draw: flag, print: { x: 0.14, y: 0.28, w: 0.72, h: 0.42 } }
  };
})(window);
