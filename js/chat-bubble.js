/* A floating chat bubble.
 *
 * Drops a round button in the corner of whatever page includes this file, and
 * opens the site chat in a panel above it.
 *
 * WHY AN IFRAME RATHER THAN A SECOND COPY OF THE CHAT. The matcher in
 * chat.html is about eight hundred lines of tuned behaviour -- typo budgets,
 * intent tests that stop "drum lessons vancouver" returning fifty gig
 * listings, pronoun carry-over so "when do they play next" has a subject. A
 * compact widget version of that would be a second implementation to keep in
 * step with the first, and it would drift the first time either is tuned.
 * The bubble therefore runs the real page in ?embed=1 mode, which hides the
 * page chrome and lets the log fill the frame. One brain, one place to fix it.
 *
 * The cost is an iframe's isolation: the panel cannot read the conversation,
 * and the chat cannot resize its own panel. Neither matters here. What it buys
 * is that the chat keeps working exactly as it already does, including the
 * teaching panel and the key panel, with no refactor of working code.
 *
 * Currently only on admin.html, as a trial before it goes anywhere public.
 */
(function () {
  'use strict';

  var SRC = '/chat.html?embed=1';
  var POS = 'chatBubble:pos';      // where it was dragged to
  var OPEN = 'chatBubble:open';    // whether it was left open

  // Drag has to be told apart from click: a bubble you cannot move is
  // annoying, and a bubble that opens every time you finish dragging it is
  // worse. Anything under this many pixels of travel counts as a tap.
  var DRAG_SLOP = 4;
  var EDGE = 10;                   // keep it this far inside the window

  function store(k, v) { try { v === null ? localStorage.removeItem(k) : localStorage.setItem(k, v); } catch (e) {} }
  function read(k) { try { return localStorage.getItem(k); } catch (e) { return null; } }

  function build() {
    var css = document.createElement('style');
    css.textContent = [
      '.cbub-btn{position:fixed;right:18px;bottom:18px;width:56px;height:56px;border-radius:50%;',
      '  border:1px solid #2c2023;background:linear-gradient(180deg,#e8372a,#b4251b);color:#fff;',
      '  font-size:25px;line-height:1;cursor:grab;z-index:2147483000;display:flex;',
      '  align-items:center;justify-content:center;box-shadow:0 10px 26px rgba(0,0,0,.45);',
      '  touch-action:none;transition:transform .16s ease,box-shadow .16s ease;padding:0}',
      '.cbub-btn:hover{transform:scale(1.06);box-shadow:0 14px 32px rgba(0,0,0,.55)}',
      '.cbub-btn:active{cursor:grabbing}',
      '.cbub-btn.dragging{transition:none;cursor:grabbing}',
      '.cbub-panel{position:fixed;right:18px;bottom:86px;width:min(400px,calc(100vw - 32px));',
      '  height:min(560px,calc(100vh - 120px));background:#0d0b0c;border:1px solid #2c2023;',
      '  border-radius:16px;overflow:hidden;z-index:2147483000;display:none;flex-direction:column;',
      '  box-shadow:0 20px 50px rgba(0,0,0,.6)}',
      '.cbub-panel.open{display:flex}',
      '.cbub-head{display:flex;align-items:center;justify-content:space-between;gap:8px;',
      '  padding:10px 8px 10px 14px;border-bottom:1px solid #2c2023;background:#171113;',
      '  color:#f4efe6;font:600 13.5px system-ui,-apple-system,"Segoe UI",Arial,sans-serif}',
      '.cbub-head a,.cbub-head button{background:none;border:0;color:#a2938c;cursor:pointer;',
      '  font:inherit;font-weight:500;padding:4px 8px;border-radius:8px;text-decoration:none}',
      '.cbub-head a:hover,.cbub-head button:hover{color:#f4efe6;background:#2c2023}',
      '.cbub-panel iframe{flex:1;width:100%;border:0;background:#0d0b0c}',
      '@media (prefers-reduced-motion:reduce){.cbub-btn{transition:none}}'
    ].join('');
    document.head.appendChild(css);

    var btn = document.createElement('button');
    btn.className = 'cbub-btn';
    btn.type = 'button';
    btn.setAttribute('aria-label', 'Ask the site');
    btn.title = 'Ask the site — drag to move';
    btn.textContent = '💬';

    var panel = document.createElement('div');
    panel.className = 'cbub-panel';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'Ask the site');

    var head = document.createElement('div');
    head.className = 'cbub-head';
    var title = document.createElement('span');
    title.textContent = '🤖 Ask the site';
    var right = document.createElement('span');
    var full = document.createElement('a');
    full.href = '/chat.html';
    full.textContent = 'Open full';
    var close = document.createElement('button');
    close.type = 'button';
    close.setAttribute('aria-label', 'Close');
    close.textContent = '✕';
    right.appendChild(full); right.appendChild(close);
    head.appendChild(title); head.appendChild(right);

    // The frame is created empty and only given its src on first open, so a
    // page carrying the bubble does not pay for the chat, its knowledge base
    // and the whole shows board on every load.
    var frame = document.createElement('iframe');
    frame.title = 'Site chat';
    panel.appendChild(head);
    panel.appendChild(frame);

    document.body.appendChild(panel);
    document.body.appendChild(btn);
    return { btn: btn, panel: panel, frame: frame, close: close };
  }

  function place(btn, panel, x, y) {
    var w = btn.offsetWidth || 56, h = btn.offsetHeight || 56;
    x = Math.max(EDGE, Math.min(x, window.innerWidth - w - EDGE));
    y = Math.max(EDGE, Math.min(y, window.innerHeight - h - EDGE));
    btn.style.left = x + 'px';
    btn.style.top = y + 'px';
    btn.style.right = 'auto';
    btn.style.bottom = 'auto';
    // Keep the panel with the bubble, and flip it above or below depending on
    // which half of the window the bubble has been dragged into, so it is
    // never half off the screen.
    var below = y < window.innerHeight / 2;
    panel.style.left = 'auto'; panel.style.right = 'auto';
    var px = Math.min(x, window.innerWidth - panel.offsetWidth - EDGE);
    panel.style.left = Math.max(EDGE, px) + 'px';
    if (below) { panel.style.top = (y + h + 10) + 'px'; panel.style.bottom = 'auto'; }
    else { panel.style.bottom = (window.innerHeight - y + 10) + 'px'; panel.style.top = 'auto'; }
    return { x: x, y: y };
  }

  function start() {
    if (document.querySelector('.cbub-btn')) return;     // never twice
    var ui = build();
    var btn = ui.btn, panel = ui.panel, frame = ui.frame;
    var pos = null;

    try {
      var saved = JSON.parse(read(POS) || 'null');
      if (saved && isFinite(saved.x) && isFinite(saved.y)) pos = place(btn, panel, saved.x, saved.y);
    } catch (e) {}

    function open(yes) {
      panel.classList.toggle('open', yes);
      btn.textContent = yes ? '✕' : '💬';
      btn.setAttribute('aria-expanded', yes ? 'true' : 'false');
      if (yes && !frame.src) frame.src = SRC;             // load on first open
      if (yes && pos) place(btn, panel, pos.x, pos.y);     // panel may have had no size before
      store(OPEN, yes ? '1' : null);
    }

    var down = null, moved = false;
    btn.addEventListener('pointerdown', function (e) {
      down = { x: e.clientX, y: e.clientY,
               ox: btn.getBoundingClientRect().left, oy: btn.getBoundingClientRect().top };
      moved = false;
      btn.classList.add('dragging');
      btn.setPointerCapture(e.pointerId);
    });
    btn.addEventListener('pointermove', function (e) {
      if (!down) return;
      var dx = e.clientX - down.x, dy = e.clientY - down.y;
      if (!moved && Math.abs(dx) + Math.abs(dy) < DRAG_SLOP) return;
      moved = true;
      pos = place(btn, panel, down.ox + dx, down.oy + dy);
    });
    function end(e) {
      if (!down) return;
      btn.classList.remove('dragging');
      try { btn.releasePointerCapture(e.pointerId); } catch (err) {}
      down = null;
      if (moved) { if (pos) store(POS, JSON.stringify(pos)); }
      else open(!panel.classList.contains('open'));
    }
    btn.addEventListener('pointerup', end);
    btn.addEventListener('pointercancel', function (e) {
      btn.classList.remove('dragging'); down = null;
    });

    ui.close.addEventListener('click', function () { open(false); });
    addEventListener('keydown', function (e) {
      if (e.key === 'Escape' && panel.classList.contains('open')) open(false);
    });
    addEventListener('resize', function () { if (pos) pos = place(btn, panel, pos.x, pos.y); });

    if (read(OPEN) === '1') open(true);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
