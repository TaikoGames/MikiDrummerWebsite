/* What people actually do on the site.
 *
 * The Google tag was on nine pages out of forty. The ninety-four band pages
 * and eight venue pages — most of the site, and the half that search traffic
 * lands on — had none at all, so the answer to "is the Punk BC board working"
 * was unknowable rather than bad.
 *
 * This is the tag plus one helper, in one file, so a new page gets measured by
 * including a script rather than by remembering to paste eleven lines into the
 * head. The generators include it too, which is what makes the generated pages
 * count.
 *
 *   Track.ev('tool_used', { tool: 'poster', action: 'save_png' })
 *
 * There is no personal data here and none should be added. It records which
 * page and which action, never who. An analytics call that carries a name or
 * an email is a liability that outlives whatever question it was meant to
 * answer.
 */
(function (global, doc) {
  'use strict';

  var ID = 'G-C75363M813';

  // The standard bootstrap. Guarded, because several pages already have their
  // own copy inline and loading gtag twice sends every pageview twice —
  // which does not look like a bug, it looks like traffic.
  if (!global.dataLayer) {
    global.dataLayer = global.dataLayer || [];
    if (typeof global.gtag !== 'function') {
      global.gtag = function () { global.dataLayer.push(arguments); };
    }
    var s = doc.createElement('script');
    s.async = true;
    s.src = 'https://www.googletagmanager.com/gtag/js?id=' + ID;
    doc.head.appendChild(s);
    global.gtag('js', new Date());
    global.gtag('config', ID);
  }

  function ev(name, params) {
    try {
      if (typeof global.gtag === 'function') global.gtag('event', name, params || {});
    } catch (e) {
      // Analytics failing must never take a page down with it. A blocked
      // tag is the normal case, not the exception.
    }
  }

  /* Outbound clicks and file downloads are deliberately NOT handled here.
   * GA4's enhanced measurement already fires `click` and `file_download` for
   * those, with the same link_domain, link_url and link_text. A second event
   * for the same action does not give a fuller picture, it gives two numbers
   * that disagree and a fortnight lost to working out which is real.
   *
   * What follows is only the things GA4 cannot infer: whether a tool was
   * actually used, and whether the music got played.
   */

  // A tool's whole purpose is the thing it produces. Page views say people
  // arrived; this says the poster got made. Delegated and pattern-matched, so
  // the ninth tool is measured without anybody remembering to add a line.
  var ACTION = /^(save|download|export|share|dl|sheet|copy|print|render|generate)/i;

  function toolName() {
    var f = (location.pathname.split('/').pop() || 'index').replace(/\.html?$/, '');
    return f || 'index';
  }

  function watchActions() {
    doc.addEventListener('click', function (e) {
      var el = e.target && e.target.closest ? e.target.closest('button[id], a[id]') : null;
      if (!el) return;
      var id = el.id || '';
      if (!ACTION.test(id)) return;
      // Something that already reports itself under a clearer name opts out
      // here, rather than being counted twice under two. The press kit button
      // is the case: "dlAllBtn" matches the pattern, and press_kit_download
      // is what the number is actually called when somebody reads it.
      if (el.hasAttribute('data-no-track')) return;
      ev('tool_used', {
        tool: toolName(),
        action: id,
        label: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 60)
      });
    }, true);

    // HTML5 audio is outside enhanced measurement entirely -- it covers
    // embedded YouTube and nothing else -- so a promoter playing the master
    // on the press kit currently leaves no trace at all. Once per element:
    // a play/pause/play while someone listens is one person listening.
    Array.prototype.forEach.call(doc.querySelectorAll('audio'), function (a) {
      var counted = false;
      a.addEventListener('play', function () {
        if (counted) return;
        counted = true;
        ev('audio_play', { file: (a.currentSrc || a.src || '').split('/').pop().slice(0, 60),
                           page: toolName() });
      });
    });
  }

  if (doc.readyState === 'loading') {
    doc.addEventListener('DOMContentLoaded', watchActions);
  } else {
    watchActions();
  }

  global.Track = { ev: ev, id: ID };
})(window, document);
