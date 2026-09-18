/* Shared bits for the press kits: a share button, and the bio as a text file.
 *
 * Both EPKs are the same page with different words in it, so this lives once
 * rather than twice. Two copies of anything drift, and the one that drifts
 * quietly here is the bio -- the thing a promoter actually pastes into a
 * listing.
 *
 *   EpkExtras.wireShare({ btn, label, band, url })
 *   EpkExtras.bioText({ band, url })
 */
(function (global) {
  'use strict';

  // ---- the bio, read off the page ---------------------------------------
  // Read from the DOM rather than kept as a string in here. A press kit whose
  // zip carries a bio the page no longer says is worse than one with no bio
  // at all: nobody checks, and the wrong version is the one that gets pasted
  // into a listing. Edit the page, the download follows.
  function bioText(opts) {
    opts = opts || {};
    var out = [];
    var band = opts.band || document.title;
    var url = opts.url || location.href;

    out.push(band.toUpperCase());
    out.push(new Array(band.length + 1).join('='));
    out.push('');

    var paras = document.querySelectorAll('#bio .bio-body p');
    if (!paras.length) paras = document.querySelectorAll('#bio p');
    Array.prototype.forEach.call(paras, function (p) {
      var t = (p.textContent || '').replace(/\s+/g, ' ').trim();
      if (t) { out.push(t); out.push(''); }
    });

    var facts = document.querySelectorAll('#bio .facts .row');
    if (facts.length) {
      out.push('---');
      out.push('');
      Array.prototype.forEach.call(facts, function (row) {
        var k = row.querySelector('.k'), v = row.querySelector('.v');
        if (k && v) {
          out.push((k.textContent || '').trim() + ': ' + (v.textContent || '').trim());
        }
      });
      out.push('');
    }

    out.push('---');
    out.push('');
    out.push('Full press kit: ' + url);
    out.push('Photos and logo are in this download.');
    out.push('');
    out.push('Pulled from the press kit on ' +
             new Date().toLocaleDateString('en-CA', {
               year: 'numeric', month: 'long', day: 'numeric'
             }) + '.');

    // \r\n, because a promoter on Windows opening this in Notepad should not
    // get one run-on line.
    return out.join('\r\n');
  }

  // ---- share this page ---------------------------------------------------
  function wireShare(opts) {
    var btn = typeof opts.btn === 'string' ? document.getElementById(opts.btn) : opts.btn;
    if (!btn) return;
    var label = btn.querySelector('.lbl') || btn;
    var original = label.textContent, timer = 0;
    var band = opts.band || document.title;
    var base = opts.url || (location.origin + location.pathname);

    function link(medium) {
      return base + '?utm_source=share&utm_medium=' + medium + '&utm_campaign=epk';
    }

    function say(msg) {
      label.textContent = msg;
      clearTimeout(timer);
      timer = setTimeout(function () { label.textContent = original; }, 3500);
    }

    function track(method) {
      if (typeof global.gtag === 'function') {
        global.gtag('event', 'share', {
          method: method, content_type: 'epk', item_id: band
        });
      }
      if (global.SharePing && global.SharePing.send) {
        global.SharePing.send({
          what: band + ' press kit',
          how: method === 'web_share' ? 'share sheet (phone)' : 'copied the link',
          link: link(method)
        });
      }
    }

    btn.addEventListener('click', function () {
      var data = {
        title: band + ' — press kit',
        text: opts.blurb || ('Press kit for ' + band + ': bio, photos, music and contact.'),
        url: link('web_share')
      };
      if (navigator.share) {
        navigator.share(data).then(function () {
          track('web_share'); say('Shared');
        }).catch(function (e) {
          // Dismissing the sheet is a decision, not a failure.
          if (e && e.name === 'AbortError') { label.textContent = original; return; }
          copy();
        });
        return;
      }
      copy();
    });

    function copy() {
      var l = link('copy');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(l).then(function () {
          track('copy'); say('Link copied');
        }).catch(function () { say('Copy failed'); });
      } else {
        say('Copy failed');
      }
    }
  }

  global.EpkExtras = { bioText: bioText, wireShare: wireShare };
})(window);
