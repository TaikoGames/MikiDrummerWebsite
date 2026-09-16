/* Raining pumpkins.
 *
 * Decoration on a page people actually work on, so the rules are: never take a
 * click, never cost anything while nobody is looking, and get out of the way
 * entirely for anyone who has asked their machine to stop animating things.
 *
 *   Pumpkins.start()         turn it on
 *   Pumpkins.stop()          turn it off
 *   Pumpkins.toggle()        ... and back
 *   Pumpkins.inSeason()      true in the week before Halloween
 *
 * One canvas, not a heap of DOM nodes: forty falling elements each with their
 * own transform is forty style recalculations a frame, and on a phone that is
 * felt.
 */
(function (global) {
  'use strict';

  var CHARS = ['🎃', '🎃', '🎃', '👻', '🦇'];   // mostly pumpkins, the odd friend
  var MAX = 34;
  var canvas = null, ctx = null, bits = [], raf = 0, last = 0, dpr = 1;

  function reduced() {
    return global.matchMedia &&
           global.matchMedia('(prefers-reduced-motion: reduce)').matches;
  }

  function make(seedTop) {
    var size = 18 + Math.random() * 30;
    return {
      x: Math.random() * canvas.clientWidth,
      // On the first frame they are spread down the screen, so it looks like
      // it has been raining a while. Seeding them all above the top edge — the
      // first attempt — meant staring at an empty page for several seconds
      // while they trickled in. After that, new ones come in from above.
      y: seedTop ? Math.random() * canvas.clientHeight
                 : -size - Math.random() * 200,
      size: size,
      speed: 26 + Math.random() * 54,          // px per second, not per frame
      drift: (Math.random() - 0.5) * 26,
      spin: (Math.random() - 0.5) * 40,
      angle: Math.random() * 360,
      alpha: 0.35 + Math.random() * 0.4,
      char: CHARS[(Math.random() * CHARS.length) | 0],
      sway: Math.random() * Math.PI * 2
    };
  }

  function size() {
    if (!canvas) return;
    dpr = Math.min(global.devicePixelRatio || 1, 2);
    canvas.width = Math.floor(canvas.clientWidth * dpr);
    canvas.height = Math.floor(canvas.clientHeight * dpr);
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  }

  function frame(now) {
    raf = global.requestAnimationFrame(frame);
    // Seconds since the last frame, so a 120Hz screen does not rain twice as
    // fast as a 60Hz one, and a background tab catching up does not teleport
    // everything to the bottom.
    var dt = Math.min((now - last) / 1000, 0.05);
    last = now;

    var w = canvas.clientWidth, h = canvas.clientHeight;
    ctx.clearRect(0, 0, w, h);

    for (var i = 0; i < bits.length; i++) {
      var p = bits[i];
      p.sway += dt * 1.6;
      p.y += p.speed * dt;
      p.x += (p.drift + Math.sin(p.sway) * 14) * dt;
      p.angle += p.spin * dt;

      if (p.y > h + p.size) { bits[i] = make(false); continue; }
      if (p.x < -60) p.x = w + 40;
      if (p.x > w + 60) p.x = -40;

      ctx.save();
      ctx.globalAlpha = p.alpha;
      ctx.translate(p.x, p.y);
      ctx.rotate(p.angle * Math.PI / 180);
      ctx.font = p.size + 'px serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(p.char, 0, 0);
      ctx.restore();
    }
  }

  function start() {
    if (canvas || reduced()) return false;
    canvas = document.createElement('canvas');
    canvas.id = 'pumpkin-rain';
    canvas.setAttribute('aria-hidden', 'true');
    // In front of the page, not behind it. Behind was the first attempt and it
    // may as well have been off: the admin page is opaque cards nearly all the
    // way down, so the rain only showed in the gaps. Deaf to the mouse either
    // way — this must never eat a click on a page whose whole job is buttons —
    // and under the save bar, which has to stay readable.
    canvas.style.cssText = 'position:fixed;inset:0;width:100%;height:100%;' +
      'pointer-events:none;z-index:40';
    document.body.appendChild(canvas);
    ctx = canvas.getContext('2d');
    size();

    bits = [];
    for (var i = 0; i < MAX; i++) bits.push(make(true));

    global.addEventListener('resize', size);
    document.addEventListener('visibilitychange', visible);
    last = global.performance.now();
    raf = global.requestAnimationFrame(frame);
    return true;
  }

  function visible() {
    // A hidden tab still gets rAF on some browsers, and there is no reason to
    // paint pumpkins nobody can see.
    if (document.hidden) {
      global.cancelAnimationFrame(raf);
      raf = 0;
    } else if (canvas && !raf) {
      last = global.performance.now();
      raf = global.requestAnimationFrame(frame);
    }
  }

  function stop() {
    if (!canvas) return false;
    global.cancelAnimationFrame(raf);
    global.removeEventListener('resize', size);
    document.removeEventListener('visibilitychange', visible);
    canvas.remove();
    canvas = null; ctx = null; bits = []; raf = 0;
    return true;
  }

  function inSeason(d) {
    d = d || new Date();
    var m = d.getMonth(), day = d.getDate();
    return (m === 9 && day >= 24) || (m === 10 && day === 1);   // Oct 24 – Nov 1
  }

  global.Pumpkins = {
    start: start,
    stop: stop,
    toggle: function () { return canvas ? (stop(), false) : start(); },
    running: function () { return !!canvas; },
    reduced: reduced,
    inSeason: inSeason
  };
})(window);
