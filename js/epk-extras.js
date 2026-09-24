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

  // The bio prose, read off the page. One reader for both the zip's text file
  // and the venue email, so the two can never say different things about the
  // same band -- which is the failure nobody notices until a listing quotes
  // the wrong one.
  function bioParagraphs() {
    var paras = document.querySelectorAll('#bio .bio-body p');
    if (!paras.length) paras = document.querySelectorAll('#bio p');
    return Array.prototype.map.call(paras, function (p) {
      return (p.textContent || '').replace(/\s+/g, ' ').trim();
    }).filter(Boolean);
  }

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

    bioParagraphs().forEach(function (t) { out.push(t); out.push(''); });

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

  // ---- email the kit to a venue ------------------------------------------
  // The download button hands you a zip, which assumes you already know what
  // to do with it. Bandmates were not sending the kit anywhere, because
  // "download" is a step in a job nobody explained. This is the job: a
  // finished email to a booker, already written, with the link in it.
  //
  // No recipient is filled in -- that is the one thing the sender knows and
  // this does not. Nothing is sent from here either; it opens whatever mail
  // app they already use, so the reply goes to them and not to a form.
  function wireVenueEmail(opts) {
    var btn = typeof opts.btn === 'string' ? document.getElementById(opts.btn) : opts.btn;
    if (!btn) return;
    var said = typeof opts.said === 'string' ? document.getElementById(opts.said) : opts.said;
    var band = opts.band || document.title;
    var url = opts.url || (location.origin + location.pathname);
    var link = url + '?utm_source=email&utm_medium=venue&utm_campaign=epk';

    // Outlook has historically truncated a mailto URL somewhere around 2000
    // characters, silently, mid-word. Percent-encoding roughly doubles what a
    // newline or a space costs, so a body that looks fine as text can blow the
    // budget once it is a URL. Everything below is measured encoded, and the
    // bio is what gets shortened, because a booker who wants the whole thing
    // has the press kit link two lines further down.
    var MAILTO_BUDGET = 1750;

    function compose(bioParas, trimmed) {
      var out = [
        'Hi,',
        '',
        "I'm with " + band + ', ' + (opts.blurb || 'a band') + '. We would like to play at your venue.',
        ''
      ];

      if (bioParas.length) {
        out.push('ABOUT');
        out.push('');
        bioParas.forEach(function (t) { out.push(t); out.push(''); });
        // Say so rather than just stopping. A bio that ends early with no
        // explanation reads as a band that could not be bothered finishing
        // the sentence.
        if (trimmed) { out.push('(Full bio in the press kit, linked below.)'); out.push(''); }
      }

      var media = opts.media || [];
      if (media.length) {
        out.push('MUSIC AND PHOTOS');
        out.push('');
        media.forEach(function (m) { out.push(m.label + ': ' + m.url); });
        out.push('');
      }

      out.push('FULL PRESS KIT');
      out.push('');
      out.push('Bio, all photos, live video and booking: ' + link);
      // #kit rather than the bare page: the download button is most of the way
      // down a long press kit, and "it is on there somewhere" is how a booker
      // decides not to bother.
      out.push('Download everything as a zip (photos, logo, bio): ' + link + '#kit');
      out.push('');
      out.push('Happy to send anything else you need, and we can work around whatever');
      out.push('dates you have open.');
      out.push('');
      out.push('Thanks,');
      return out.join('\r\n');
    }

    // The whole thing, for the clipboard and for any client that can take it.
    function fullMessage() {
      return compose(bioParagraphs(), false);
    }

    // The most of it that will survive being a URL. Drops whole paragraphs
    // from the end rather than cutting mid-sentence, because half a sentence
    // about your own band reads worse than a shorter bio.
    function mailtoMessage() {
      var all = bioParagraphs(), paras = all;
      while (true) {
        var body = compose(paras, paras.length < all.length);
        if (encodeURIComponent(body).length <= MAILTO_BUDGET || !paras.length) return body;
        paras = paras.slice(0, -1);
      }
    }

    function note(msg) {
      if (!said) return;
      said.textContent = msg;
      clearTimeout(note.t);
      note.t = setTimeout(function () { said.textContent = ''; }, 9000);
    }

    // The mailto lives on the anchor's href rather than being assigned to
    // location on click. It opens even if the rest of this script has fallen
    // over, it can be long-pressed or right-clicked like any other link, and
    // it is inspectable -- a button that navigates from a handler can only be
    // tested by launching a mail client.
    var subject = band + ' — press kit and booking enquiry';
    // encodeURIComponent, not escape: an em dash in a band name or an
    // ampersand in the blurb otherwise truncates the body at that character
    // and the booker gets half a sentence.
    btn.setAttribute('href', 'mailto:?subject=' + encodeURIComponent(subject) +
                             '&body=' + encodeURIComponent(mailtoMessage()));

    btn.addEventListener('click', function () {
      if (typeof global.gtag === 'function') {
        global.gtag('event', 'share', { method: 'email_venue', content_type: 'epk', item_id: band });
      }
      // A machine with no mail app configured does nothing visible at all,
      // which reads as a broken button. Say what should have happened and
      // offer the other way out.
      note('Opening your email app. Nothing happened? Tap “Copy the message” and paste it into your mail.');
    });

    if (opts.copyBtn) {
      var cb = typeof opts.copyBtn === 'string' ? document.getElementById(opts.copyBtn) : opts.copyBtn;
      if (cb) {
        cb.addEventListener('click', function () {
          var text = fullMessage();
          if (navigator.clipboard && navigator.clipboard.writeText) {
            navigator.clipboard.writeText(text)
              .then(function () { note('Message copied — paste it into an email to the venue.'); })
              .catch(function () { note('Could not copy. Select the link above and send it by hand.'); });
          } else {
            note('This browser will not copy for me. The link is ' + url);
          }
        });
      }
    }
  }

  // Arriving from the email's zip link. The download button lives most of the
  // way down a long page, so landing on the page is not the same as finding
  // it; this scrolls to it and makes it obvious which thing to press.
  function wireKitAnchor(btnId) {
    if (location.hash !== '#kit') return;
    var btn = document.getElementById(btnId);
    if (!btn) return;
    // A frame late, so it runs after the browser has done its own hash jump.
    setTimeout(function () {
      btn.scrollIntoView({ behavior: 'smooth', block: 'center' });
      btn.classList.add('kit-called');
      // Not auto-clicked: a download that starts on its own is how a page
      // gets treated as hostile, and some browsers refuse it anyway without
      // a gesture.
      if (typeof btn.focus === 'function') btn.focus({ preventScroll: true });
    }, 60);
  }

  global.EpkExtras = {
    bioText: bioText,
    bioParagraphs: bioParagraphs,
    wireShare: wireShare,
    wireVenueEmail: wireVenueEmail,
    wireKitAnchor: wireKitAnchor
  };
})(window);
