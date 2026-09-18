/* Printing artwork onto a photograph.
 *
 * The first cut of the merch tool drew its blanks as vectors, and they read as
 * vectors. A mockup exists to answer one question -- what will this actually
 * look like -- and a drawing cannot answer it.
 *
 * There is no stock library to reach for. Public-domain photography is
 * pre-1930 and museum holdings; nobody was shooting blank t-shirt flat lays
 * then, and everything modern carries either an attribution condition or a
 * share-alike one. A share-alike condition on a mockup would attach itself to
 * the band's own artwork, which is not ours to give away.
 *
 * So the photograph comes from the band. They own a shirt, a hoodie, a drum
 * head; they photograph it and the artwork goes onto that. Better than stock
 * anyway -- it is the actual garment, in the actual colour, that they will
 * actually order.
 *
 * Two things have to be right for that to look real:
 *
 *   1. Perspective. Nobody photographs a shirt perfectly square-on, and a drum
 *      head almost always sits at an angle. Artwork pasted into an upright
 *      rectangle on a tilted surface reads as a sticker every time. So the
 *      print area is four draggable corners, and the artwork is mapped through
 *      a real projective transform -- foreshortening and all.
 *
 *   2. Shading. Cloth has folds and the light falls unevenly across it. Ink
 *      printed on cloth goes dark in the creases with the cloth. This reads
 *      the surface's own brightness under the print area and multiplies the
 *      artwork by it, which is what a mockup PSD's multiply layer does, and
 *      it is why the result sits in the fabric instead of on top of it.
 *
 * Both work the same way on a drawn blank as on a photograph, so the built-in
 * blanks go through this too.
 */
window.MerchPhoto = (function () {
  'use strict';

  /* Maps the unit square onto four corners, given in the order top-left,
   * top-right, bottom-right, bottom-left.
   *
   * Returns a function (u,v) -> {x,y}. Genuinely projective rather than
   * bilinear: bilinear is a couple of lines shorter and looks identical on a
   * near-square-on shot, then falls apart on exactly the angled shots that
   * need the help, because it has no foreshortening -- the far edge of the
   * quad stays as tall as the near one.
   */
  function homography(q) {
    var x0 = q[0][0], y0 = q[0][1], x1 = q[1][0], y1 = q[1][1];
    var x2 = q[2][0], y2 = q[2][1], x3 = q[3][0], y3 = q[3][1];
    var dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3;
    var dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3;
    var a, b, c, d, e, f, g, h;

    var den = dx1 * dy2 - dy1 * dx2;
    if ((dx3 === 0 && dy3 === 0) || den === 0) {
      // A parallelogram: no perspective in it, so the affine case is exact.
      g = 0; h = 0;
      a = x1 - x0; b = x3 - x0; c = x0;
      d = y1 - y0; e = y3 - y0; f = y0;
    } else {
      g = (dx3 * dy2 - dy3 * dx2) / den;
      h = (dx1 * dy3 - dy1 * dx3) / den;
      a = x1 - x0 + g * x1; b = x3 - x0 + h * x3; c = x0;
      d = y1 - y0 + g * y1; e = y3 - y0 + h * y3; f = y0;
    }
    return function (u, v) {
      var w = g * u + h * v + 1;
      return { x: (a * u + b * v + c) / w, y: (d * u + e * v + f) / w };
    };
  }

  /* One affine-textured triangle. Canvas has no textured-triangle call, so:
   * clip to the destination triangle, then set the transform that carries the
   * source triangle onto it and draw the whole image through it.
   */
  function triangle(ctx, img, s, d) {
    var sx0 = s[0][0], sy0 = s[0][1];
    var m00 = s[1][0] - sx0, m10 = s[2][0] - sx0;
    var m01 = s[1][1] - sy0, m11 = s[2][1] - sy0;
    var det = m00 * m11 - m10 * m01;
    if (!det) return;                       // degenerate: nothing to fill

    var dx0 = d[0][0], dy0 = d[0][1];
    var n00 = d[1][0] - dx0, n10 = d[2][0] - dx0;
    var n01 = d[1][1] - dy0, n11 = d[2][1] - dy0;

    // inverse(source) then destination, composed
    var i00 = m11 / det, i10 = -m10 / det, i01 = -m01 / det, i11 = m00 / det;
    var a = i00 * n00 + i01 * n10, b = i00 * n01 + i01 * n11;
    var c = i10 * n00 + i11 * n10, e = i10 * n01 + i11 * n11;

    ctx.save();
    ctx.beginPath();
    ctx.moveTo(d[0][0], d[0][1]);
    ctx.lineTo(d[1][0], d[1][1]);
    ctx.lineTo(d[2][0], d[2][1]);
    ctx.closePath();
    ctx.clip();
    ctx.transform(a, b, c, e, dx0 - (a * sx0 + c * sy0), dy0 - (b * sx0 + e * sy0));
    ctx.drawImage(img, 0, 0);
    ctx.restore();
  }

  /* Draws img into the quad, subdividing so the projective mapping is followed
   * rather than approximated by one affine pass over the whole rectangle.
   *
   * `fit` is how the image sits inside the quad: 'contain' keeps its aspect
   * ratio (what you want for a logo), 'fill' stretches to the corners.
   */
  function warp(ctx, img, quad, opts) {
    opts = opts || {};
    var n = opts.steps || 12;
    var map = homography(quad);

    // Where the artwork lands inside the unit square.
    var u0 = 0, v0 = 0, u1 = 1, v1 = 1;
    if (opts.fit !== 'fill') {
      var qw = Math.hypot(quad[1][0] - quad[0][0], quad[1][1] - quad[0][1]);
      var qh = Math.hypot(quad[3][0] - quad[0][0], quad[3][1] - quad[0][1]);
      var s = Math.min(qw / img.width, qh / img.height);
      var du = (img.width * s) / qw, dv = (img.height * s) / qh;
      u0 = (1 - du) / 2; u1 = u0 + du;
      v0 = (1 - dv) / 2; v1 = v0 + dv;
    }
    // Scale and offset are applied in unit space so they survive the warp:
    // nudging stays parallel to the garment, not to the screen.
    var sc = opts.scale == null ? 1 : opts.scale;
    var cu = (u0 + u1) / 2 + (opts.du || 0), cv = (v0 + v1) / 2 + (opts.dv || 0);
    var hu = (u1 - u0) / 2 * sc, hv = (v1 - v0) / 2 * sc;
    u0 = cu - hu; u1 = cu + hu; v0 = cv - hv; v1 = cv + hv;

    for (var i = 0; i < n; i++) {
      for (var j = 0; j < n; j++) {
        var ua = u0 + (u1 - u0) * i / n, ub = u0 + (u1 - u0) * (i + 1) / n;
        var va = v0 + (v1 - v0) * j / n, vb = v0 + (v1 - v0) * (j + 1) / n;
        var sa = [[img.width * i / n, img.height * j / n],
                  [img.width * (i + 1) / n, img.height * j / n],
                  [img.width * (i + 1) / n, img.height * (j + 1) / n],
                  [img.width * i / n, img.height * (j + 1) / n]];
        var p00 = map(ua, va), p10 = map(ub, va);
        var p11 = map(ub, vb), p01 = map(ua, vb);
        // A hairline of overlap. Adjacent clipped triangles otherwise leave a
        // seam where their antialiased edges each cover half a pixel.
        var da = [[p00.x, p00.y], [p10.x, p10.y], [p11.x, p11.y], [p01.x, p01.y]];
        triangle(ctx, img, [sa[0], sa[1], sa[2]], [da[0], da[1], da[2]]);
        triangle(ctx, img, [sa[0], sa[2], sa[3]], [da[0], da[2], da[3]]);
      }
    }
  }

  function bounds(quad, W, H) {
    var xs = quad.map(function (p) { return p[0]; });
    var ys = quad.map(function (p) { return p[1]; });
    var x = Math.max(0, Math.floor(Math.min.apply(null, xs)) - 2);
    var y = Math.max(0, Math.floor(Math.min.apply(null, ys)) - 2);
    var r = Math.min(W, Math.ceil(Math.max.apply(null, xs)) + 2);
    var b = Math.min(H, Math.ceil(Math.max.apply(null, ys)) + 2);
    return { x: x, y: y, w: Math.max(0, r - x), h: Math.max(0, b - y) };
  }

  /* The median brightness of the surface under the print area.
   *
   * Median rather than mean, and that is the whole trick. A mean is dragged
   * around by a highlight blowout or a deep crease, and then every pixel of
   * the artwork is scaled by a number set by the least representative part of
   * the cloth. The median is the brightness of the fabric itself, which is
   * what "unshaded" has to mean for the ratio to sit around 1.
   */
  function medianLuma(data) {
    var hist = new Uint32Array(256), n = 0, i;
    for (i = 0; i < data.length; i += 4) {
      if (data[i + 3] < 8) continue;
      var l = (0.2126 * data[i] + 0.7152 * data[i + 1] + 0.0722 * data[i + 2]) | 0;
      hist[l > 255 ? 255 : l]++; n++;
    }
    if (!n) return 128;
    var half = n / 2, run = 0;
    for (i = 0; i < 256; i++) { run += hist[i]; if (run >= half) return i; }
    return 128;
  }

  /* Print artwork onto whatever is already on the canvas inside `quad`.
   *
   * The surface is read back before the artwork goes down, so its folds and
   * lighting are known; the artwork is warped into the quad on its own layer;
   * then each printed pixel is multiplied by how bright the cloth under it is
   * relative to the cloth's own median. Creases darken the ink, lit ridges
   * lift it, flat fabric leaves it alone.
   *
   * opts.ink: 'print' (into the weave) or 'flat' (sits on top -- vinyl,
   * enamel, a sticker, where the surface genuinely is flat and the ink
   * genuinely does not sink into it).
   */
  function print(ctx, art, quad, opts) {
    opts = opts || {};
    var W = ctx.canvas.width, H = ctx.canvas.height;
    var box = bounds(quad, W, H);
    if (!box.w || !box.h) return;

    // Warp the artwork onto its own transparent layer first. Compositing it
    // straight onto the canvas would leave nothing to multiply afterwards --
    // the surface underneath would already be gone.
    var layer = document.createElement('canvas');
    layer.width = W; layer.height = H;
    warp(layer.getContext('2d'), art, quad, opts);

    if (opts.ink === 'flat') {
      ctx.drawImage(layer, 0, 0);
      return;
    }

    var surface = ctx.getImageData(box.x, box.y, box.w, box.h);
    var ink = layer.getContext('2d').getImageData(box.x, box.y, box.w, box.h);
    var mid = medianLuma(surface.data) || 128;
    var sd = surface.data, id = ink.data;

    for (var i = 0; i < id.length; i += 4) {
      var a = id[i + 3];
      if (!a) continue;
      var luma = 0.2126 * sd[i] + 0.7152 * sd[i + 1] + 0.0722 * sd[i + 2];
      // Clamped, because a photograph's specular highlight can be eight times
      // the fabric's brightness and unclamped that turns a black logo white.
      var k = luma / mid;
      if (k < 0.45) k = 0.45; else if (k > 1.55) k = 1.55;
      // Ink is not paint: a little of the cloth reads through even a heavy
      // screen print, and on cloth the weave never covers completely.
      var op = (opts.opacity == null ? 0.94 : opts.opacity) * (a / 255);
      var r = id[i] * k, g = id[i + 1] * k, b = id[i + 2] * k;
      sd[i]     = sd[i]     + (r - sd[i]) * op;
      sd[i + 1] = sd[i + 1] + (g - sd[i + 1]) * op;
      sd[i + 2] = sd[i + 2] + (b - sd[i + 2]) * op;
    }
    ctx.putImageData(surface, box.x, box.y);
  }

  return {
    homography: homography,
    warp: warp,
    print: print,
    medianLuma: medianLuma,
    bounds: bounds
  };
})();
