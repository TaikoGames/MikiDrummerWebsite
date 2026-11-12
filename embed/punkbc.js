/*!
 * Punk BC show widget: upcoming punk, hardcore and metal shows in BC,
 * for any website. https://www.mikidrummer.ca/punkbc-embed.html
 *
 * Paste where the list should appear:
 *
 *   <div class="punkbc-shows" data-city="Vancouver" data-limit="5"></div>
 *   <script src="https://www.mikidrummer.ca/embed/punkbc.js" async></script>
 *
 * Options (all optional) as data- attributes on the div:
 *   data-limit   how many shows (1-50, default 5)
 *   data-city    only this city, e.g. "Vancouver" or "Victoria"
 *   data-venue   only this venue, e.g. "Rickshaw Theatre"
 *   data-band    only shows whose bill mentions this band
 *   data-genre   only shows whose genre mentions this, e.g. "metal"
 *   data-theme   "dark" (default) or "light"
 *   data-images  "true" to show each show's picture
 *   data-title   heading text; "" for no heading
 *
 * Renders inside a shadow root so the host site's CSS can't break it and
 * its CSS can't leak out. Several widgets on one page share one request.
 */
(function () {
  'use strict';
  var SITE = 'https://www.mikidrummer.ca';
  var DATA = SITE + '/punkbc-shows.json';
  var BOARD = SITE + '/punkbc.html';
  var request;

  function load() {
    if (!request) {
      request = fetch(DATA, { mode: 'cors' }).then(function (r) {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }
    return request;
  }

  function esc(v) {
    return String(v == null ? '' : v).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }
  function safeUrl(u) { return /^https?:\/\//i.test(u || '') ? u : ''; }
  function has(field, want) {
    return !want || String(field || '').toLowerCase().indexOf(want.toLowerCase()) !== -1;
  }

  // Today in Vancouver, so tonight's show stays listed until the night is over.
  function today() {
    try {
      return new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Vancouver' }).format(new Date());
    } catch (e) { return new Date().toISOString().slice(0, 10); }
  }

  function dateParts(iso) {
    var d = new Date(iso + 'T12:00:00');
    return {
      dow: d.toLocaleDateString('en-CA', { weekday: 'short' }),
      mon: d.toLocaleDateString('en-CA', { month: 'short' }),
      day: d.getDate()
    };
  }

  function time12(t) {
    var m = /^(\d{1,2}):(\d{2})/.exec(t || '');
    if (!m) return '';
    var h = +m[1], ap = h >= 12 ? 'pm' : 'am';
    h = h % 12 || 12;
    return h + (m[2] === '00' ? '' : ':' + m[2]) + ap;
  }

  var CSS = [
    ':host{display:block;--bg:#0f0d0c;--card:#181412;--edge:#2a2421;--ink:#f3eee9;--dim:#a39b95;--hot:#e8372a;--hot-ink:#fff}',
    ':host([data-theme=light]){--bg:#fff;--card:#f6f3f1;--edge:#e3ddd8;--ink:#1a1614;--dim:#6b625c;--hot:#d42c20;--hot-ink:#fff}',
    '.w{background:var(--bg);color:var(--ink);border:1px solid var(--edge);border-radius:12px;padding:14px;',
    'font:15px/1.4 system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;box-sizing:border-box}',
    'h3{margin:2px 2px 12px;font-size:17px;letter-spacing:.02em;text-transform:uppercase}',
    'ul{list-style:none;margin:0;padding:0;display:grid;gap:8px}',
    'li{display:flex;align-items:center;gap:12px;background:var(--card);border:1px solid var(--edge);border-radius:10px;padding:10px}',
    '.d{flex:0 0 52px;text-align:center;line-height:1.1}',
    '.d b{display:block;font-size:22px;color:var(--hot)}',
    '.d span{font-size:11px;text-transform:uppercase;color:var(--dim);letter-spacing:.06em}',
    '.img{flex:0 0 56px;width:56px;height:56px;border-radius:8px;object-fit:cover;background:var(--edge)}',
    '.i{flex:1 1 auto;min-width:0}',
    '.b{font-weight:700;overflow-wrap:anywhere}',
    '.m{font-size:13px;color:var(--dim)}',
    'a.t{flex:0 0 auto;display:inline-flex;align-items:center;justify-content:center;min-height:44px;min-width:44px;',
    'padding:0 14px;border-radius:8px;background:var(--hot);color:var(--hot-ink);font-weight:700;font-size:13px;text-decoration:none}',
    'a.t:focus-visible,.f a:focus-visible{outline:3px solid #facc15;outline-offset:2px}',
    '.sk{height:62px;border-radius:10px;background:linear-gradient(90deg,var(--card) 25%,var(--edge) 50%,var(--card) 75%);',
    'background-size:200% 100%;animation:s 1.2s infinite}',
    '@keyframes s{to{background-position:-200% 0}}',
    '@media (prefers-reduced-motion:reduce){.sk{animation:none}}',
    '.e{color:var(--dim);padding:8px 2px}',
    '.f{margin-top:10px;font-size:12px;color:var(--dim);text-align:right}',
    '.f a,.e a{color:var(--ink)}',
    '@media (max-width:420px){.img{display:none}li{flex-wrap:wrap}.i{flex-basis:calc(100% - 64px)}a.t{flex:1 1 100%}}'
  ].join('');

  function render(host) {
    if (host.__punkbc) return;
    host.__punkbc = true;
    var o = host.dataset;
    var limit = Math.max(1, Math.min(50, parseInt(o.limit, 10) || 5));
    var title = o.title != null ? o.title
      : 'Upcoming shows' + (o.venue ? ' at ' + o.venue : o.city ? ' in ' + o.city : ' in BC');
    if (o.theme === 'light') host.setAttribute('data-theme', 'light');

    var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;
    var foot = '<div class="f">Shows from <a href="' + BOARD + '?utm_source=embed" target="_blank" rel="noopener">Punk BC</a></div>';
    root.innerHTML = '<style>' + CSS + '</style><div class="w" role="region" aria-label="' + esc(title || 'Punk BC shows') + '">' +
      (title ? '<h3>' + esc(title) + '</h3>' : '') +
      '<ul aria-busy="true"><li class="sk"></li><li class="sk"></li><li class="sk"></li></ul>' + foot + '</div>';
    var list = root.querySelector('ul');

    load().then(function (data) {
      var t = today();
      var shows = (Array.isArray(data) ? data : data.shows || []).filter(function (s) {
        return s.date && s.date >= t &&
          (!o.city || String(s.city || '').toLowerCase() === o.city.toLowerCase()) &&
          has(s.venue, o.venue) && has(s.band, o.band) && has(s.genre, o.genre);
      }).sort(function (a, b) {
        return (a.date + (a.time || '')).localeCompare(b.date + (b.time || ''));
      }).slice(0, limit);

      if (!shows.length) {
        list.outerHTML = '<p class="e">No shows announced right now. <a href="' + BOARD + '" target="_blank" rel="noopener">See the full board</a>.</p>';
        return;
      }
      list.innerHTML = shows.map(function (s) {
        var d = dateParts(s.date), img = o.images === 'true' && safeUrl(s.image);
        var meta = [s.venue, s.city].filter(Boolean).join(', ');
        var extra = [time12(s.time), s.price].filter(Boolean).join(' \u00b7 ');
        var link = safeUrl(s.ticket) || BOARD;
        return '<li>' +
          '<div class="d"><span>' + esc(d.dow) + '</span><b>' + d.day + '</b><span>' + esc(d.mon) + '</span></div>' +
          (img ? '<img class="img" src="' + esc(img) + '" alt="" loading="lazy">' : '') +
          '<div class="i"><div class="b">' + esc(s.band) + '</div><div class="m">' + esc(meta) +
          (extra ? ' \u00b7 ' + esc(extra) : '') + '</div></div>' +
          '<a class="t" href="' + esc(link) + '" target="_blank" rel="noopener">' + (safeUrl(s.ticket) ? 'Tickets' : 'Info') + '</a>' +
          '</li>';
      }).join('');
      list.removeAttribute('aria-busy');
    }).catch(function () {
      list.outerHTML = '<p class="e">Couldn\'t load shows. <a href="' + BOARD + '" target="_blank" rel="noopener">See them on Punk BC</a>.</p>';
    });
  }

  function init() {
    var nodes = document.querySelectorAll('.punkbc-shows, [data-punkbc]');
    for (var i = 0; i < nodes.length; i++) render(nodes[i]);
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init);
  else init();
  window.PunkBC = { render: render, init: init };
})();
