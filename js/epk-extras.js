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

    function compose(bioParas, trimmed, note) {
      var out = ['Hi,', ''];
      if (note) { out.push(note); out.push(''); }
      out.push("I'm with " + band + ', ' + (opts.blurb || 'a band') +
               '. We would like to play at your venue.');
      out.push('');

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
    function fullMessage(note) {
      return compose(bioParagraphs(), false, note);
    }

    // The most of it that will survive being a URL. Drops whole paragraphs
    // from the end rather than cutting mid-sentence, because half a sentence
    // about your own band reads worse than a shorter bio.
    function mailtoMessage(note) {
      var all = bioParagraphs(), paras = all;
      while (true) {
        var body = compose(paras, paras.length < all.length, note);
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

    var subject = band + ' — press kit and booking enquiry';

    // Where the message is handed over to actually be sent.
    //
    // This site cannot send the mail itself, and should not: a page that
    // posts to any address somebody types is an open relay, and it would be
    // found and used for spam long before it was useful. What it can do is
    // compose the whole thing -- recipient, subject, body -- and hand it to
    // the mail the sender already has, one press from Send.
    //
    // Gmail and Outlook on the web are the point of this. mailto only works
    // if a desktop mail client is set up, which on a borrowed laptop or a
    // phone with only the Gmail app often it is not, and then the button
    // appears to do nothing at all.
    var PROVIDERS = {
      gmail: {
        label: 'Gmail',
        make: function (to, body) {
          return 'https://mail.google.com/mail/?view=cm&fs=1' +
                 '&to=' + encodeURIComponent(to) +
                 '&su=' + encodeURIComponent(subject) +
                 '&body=' + encodeURIComponent(body);
        }
      },
      outlook: {
        label: 'Outlook',
        make: function (to, body) {
          return 'https://outlook.live.com/mail/0/deeplink/compose?to=' + encodeURIComponent(to) +
                 '&subject=' + encodeURIComponent(subject) +
                 '&body=' + encodeURIComponent(body);
        }
      },
      mail: {
        label: 'My mail app',
        // The only one with a length ceiling worth worrying about, so it is
        // the only one that gets the trimmed bio. The web composers take the
        // whole thing.
        trims: true,
        make: function (to, body) {
          return 'mailto:' + encodeURIComponent(to) +
                 '?subject=' + encodeURIComponent(subject) +
                 '&body=' + encodeURIComponent(body);
        }
      }
    };

    var REMEMBER = 'epk:mailProvider';
    function preferred() {
      try { return localStorage.getItem(REMEMBER) || 'gmail'; } catch (e) { return 'gmail'; }
    }
    function remember(k) { try { localStorage.setItem(REMEMBER, k); } catch (e) {} }

    // Deliberately loose. This is a hint that a typo has happened, not an
    // authority on what a valid address is -- rejecting a real venue address
    // because it has an unusual domain would be worse than sending nothing.
    function looksLikeEmail(v) {
      return /^[^\s@]+@[^\s@.]+\.[^\s@]+$/.test(String(v || '').trim());
    }

    function bodyFor(key, personal) {
      return PROVIDERS[key].trims ? mailtoMessage(personal) : fullMessage(personal);
    }

    var dlg = buildDialog();

    function buildDialog() {
      var d = document.createElement('dialog');
      d.className = 'venue-dialog';
      d.setAttribute('aria-label', 'Send the ' + band + ' press kit');
      d.innerHTML =
        '<form method="dialog" class="vd-form">' +
          '<h3>Send the press kit</h3>' +
          '<p class="vd-sub">The whole message is written — bio, links, music and the kit. ' +
             'Put the address in and it opens ready to send. For the photos <em>inside</em> the ' +
             'email, use \u201ccopy it with the photos\u201d and paste into a new message.</p>' +
          '<label for="vd-to">Venue or promoter\u2019s email</label>' +
          '<input id="vd-to" type="email" inputmode="email" autocomplete="off" ' +
                 'placeholder="bookings@venue.com" required>' +
          '<label for="vd-note">Add a line first <span class="vd-opt">(optional)</span></label>' +
          '<input id="vd-note" type="text" autocomplete="off" ' +
                 'placeholder="We played with Baron at the Cobalt in June.">' +
          '<p class="vd-err" id="vd-err" role="alert"></p>' +
          '<div class="vd-actions">' +
            '<button type="button" class="vd-send" id="vd-send">Open in Gmail</button>' +
            '<button type="button" class="vd-cancel" value="cancel">Cancel</button>' +
          '</div>' +
          '<p class="vd-alt">Use <button type="button" class="vd-swap" data-k="gmail">Gmail</button>' +
            '<button type="button" class="vd-swap" data-k="outlook">Outlook</button>' +
            '<button type="button" class="vd-swap" data-k="mail">my mail app</button>' +
            '<button type="button" class="vd-swap" data-k="copy">copy it with the photos</button></p>' +
        '</form>';
      document.body.appendChild(d);

      var to = d.querySelector('#vd-to');
      var personal = d.querySelector('#vd-note');
      var err = d.querySelector('#vd-err');
      var send = d.querySelector('#vd-send');
      var choice = preferred();

      function paint() {
        send.textContent = choice === 'copy' ? 'Copy it with the photos'
                                             : 'Open in ' + PROVIDERS[choice].label;
        Array.prototype.forEach.call(d.querySelectorAll('.vd-swap'), function (s) {
          s.setAttribute('aria-pressed', String(s.dataset.k === choice));
        });
      }

      d.addEventListener('click', function (e) {
        var s = e.target.closest('.vd-swap');
        if (s) { choice = s.dataset.k; remember(choice); paint(); return; }
        // Clicking the backdrop rather than the panel closes it.
        if (e.target === d) d.close();
      });
      d.querySelector('.vd-cancel').addEventListener('click', function () { d.close(); });

      send.addEventListener('click', function () {
        var address = to.value.trim();
        if (choice === 'copy') {
          copyOut(personal.value.trim());
          d.close();
          return;
        }
        if (!looksLikeEmail(address)) {
          err.textContent = 'That does not look like an email address — check it and try again.';
          to.focus();
          return;
        }
        err.textContent = '';
        var href = PROVIDERS[choice].make(address, bodyFor(choice, personal.value.trim()));
        if (typeof global.gtag === 'function') {
          global.gtag('event', 'share', { method: 'email_venue_' + choice,
                                          content_type: 'epk', item_id: band });
        }
        // A new tab for the web composers so the press kit stays open behind
        // it; mailto hands off to the OS and never navigates this page.
        // location.assign rather than setting location.href: same effect, and
        // it is a method, so a test can watch what gets handed to it without
        // launching a mail client.
        if (choice === 'mail') global.location.assign(href);
        else global.open(href, '_blank', 'noopener');
        d.close();
        note('Opened ' + PROVIDERS[choice].label + ' with the message ready. ' +
             'Nothing there? Reopen this and choose “copy it instead”.');
      });

      paint();
      return d;
    }

    // ---- the same message, as rich mail ------------------------------
    //
    // mailto and the webmail compose URLs are plain text and nothing else:
    // RFC 6068 has no HTML, no attachments, no images, and Gmail's and
    // Outlook's compose parameters follow it. So a prefilled link can never
    // show a photo, however it is written.
    //
    // The clipboard can. Written as text/html it pastes into Gmail as
    // formatted mail with the pictures in place, and text/plain rides along
    // in the same write so pasting anywhere else still gives the plain
    // version. No account, nothing to set up.
    function esc(s) {
      return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;')
                      .replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }

    function isImage(u) { return /\.(jpe?g|png|gif|webp)(\?|$)/i.test(u); }

    function htmlMessage(personal) {
      var media = opts.media || [];
      var pics = media.filter(function (m) { return isImage(m.url); });
      var rest = media.filter(function (m) { return !isImage(m.url); });

      // 600px is the width every email client has agreed on for twenty years,
      // and max-width:100% is what keeps it from overflowing a phone.
      function img(m) {
        return '<img src="' + esc(m.url) + '" alt="' + esc(m.label) + '" width="600" ' +
               'style="display:block;width:100%;max-width:600px;height:auto;' +
               'border-radius:6px;margin:0 0 14px">';
      }

      var h = ['<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;' +
               'line-height:1.6;color:#141414;max-width:600px">'];
      h.push('<p>Hi,</p>');
      if (personal) h.push('<p>' + esc(personal) + '</p>');
      h.push('<p>I\u2019m with <strong>' + esc(band) + '</strong>, ' + esc(opts.blurb || 'a band') +
             '. We would like to play at your venue.</p>');

      if (pics.length) h.push(img(pics[0]));

      var paras = bioParagraphs();
      if (paras.length) {
        h.push('<p style="margin:18px 0 6px"><strong>ABOUT</strong></p>');
        paras.forEach(function (x) { h.push('<p>' + esc(x) + '</p>'); });
      }

      if (rest.length) {
        h.push('<p style="margin:18px 0 6px"><strong>MUSIC AND VIDEO</strong></p><ul style="margin:0 0 14px;padding-left:20px">');
        rest.forEach(function (m) {
          h.push('<li><a href="' + esc(m.url) + '">' + esc(m.label) + '</a></li>');
        });
        h.push('</ul>');
      }

      // Everything after the first picture, so the mail leads with the band
      // rather than with a wall of logos.
      pics.slice(1).forEach(function (m) { h.push(img(m)); });

      h.push('<p style="margin:18px 0 6px"><strong>FULL PRESS KIT</strong></p>');
      h.push('<p><a href="' + esc(link) + '">Bio, all photos, live video and booking</a><br>' +
             '<a href="' + esc(link) + '#kit">Download everything as a zip</a></p>');
      h.push('<p>Happy to send anything else you need, and we can work around whatever ' +
             'dates you have open.</p><p>Thanks,</p></div>');
      return h.join('');
    }

    function copyOut(personal) {
      var text = fullMessage(personal);
      var html = htmlMessage(personal);

      // Both flavours in one write. Gmail takes the HTML; a plain-text box
      // takes the text; neither needs the person to have chosen correctly.
      if (global.ClipboardItem && navigator.clipboard && navigator.clipboard.write) {
        navigator.clipboard.write([new global.ClipboardItem({
          'text/html': new Blob([html], { type: 'text/html' }),
          'text/plain': new Blob([text], { type: 'text/plain' })
        })]).then(function () {
          note('Copied with the photos in it. Open a new email to the venue and paste — ' +
               'the pictures come with it.');
        }).catch(function () { plainCopy(text); });
        return;
      }
      plainCopy(text);
    }

    function plainCopy(text) {
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
          .then(function () { note('Message copied as plain text — this browser will not carry images on the clipboard.'); })
          .catch(function () { note('Could not copy. The press kit link is ' + url); });
      } else {
        note('This browser will not copy for me. The press kit link is ' + url);
      }
    }

    // The anchor keeps a working mailto href, so a right-click, a long-press
    // and a page whose script never ran all still do something sensible. The
    // dialog is the enhancement on top, not the only way through.
    btn.setAttribute('href', 'mailto:?subject=' + encodeURIComponent(subject) +
                             '&body=' + encodeURIComponent(mailtoMessage('')));

    btn.addEventListener('click', function (e) {
      if (typeof dlg.showModal !== 'function') return;   // let the mailto happen
      e.preventDefault();
      dlg.showModal();
      var to = dlg.querySelector('#vd-to');
      if (to) { to.value = ''; to.focus(); }
      var err = dlg.querySelector('#vd-err');
      if (err) err.textContent = '';
    });

    if (opts.copyBtn) {
      var cb = typeof opts.copyBtn === 'string' ? document.getElementById(opts.copyBtn) : opts.copyBtn;
      if (cb) cb.addEventListener('click', function () { copyOut(''); });
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
