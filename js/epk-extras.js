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

    // ---- sending it here, without opening anything -------------------
    //
    // The page cannot send mail on its own, and must not be able to: a public
    // press kit that posts to any address a visitor types is a spam relay
    // wearing a band's name, and the first thing that happens is the domain
    // gets blacklisted.
    //
    // So the credentials never ship in the page. They live in localStorage on
    // the devices of the people in the band, pasted once, exactly like the
    // GitHub token on the admin page and the API key on the chat page. A
    // stranger reading this file finds nothing to abuse; a bandmate who has
    // set it up once gets type-the-address-and-send.
    //
    // The mail goes out through EmailJS, from the band's own connected
    // account, so replies land where they should rather than at a form.
    var CREDS = 'epk:send';
    var SEND_API = 'https://api.emailjs.com/api/v1.0/email/send';

    function creds() {
      try {
        var v = JSON.parse(localStorage.getItem(CREDS) || 'null');
        return (v && v.service && v.template && v.key) ? v : null;
      } catch (e) { return null; }
    }
    function saveCreds(v) {
      try { localStorage.setItem(CREDS, JSON.stringify(v)); return true; }
      catch (e) { return false; }
    }
    function forgetCreds() { try { localStorage.removeItem(CREDS); } catch (e) {} }

    function sendDirect(to, personal) {
      var c = creds();
      return fetch(SEND_API, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          service_id: c.service,
          template_id: c.template,
          user_id: c.key,
          template_params: {
            to_email: to,
            subject: subject,
            // The web composers' version: there is no URL here to overflow,
            // so the bio goes out whole.
            message: fullMessage(personal),
            band: band,
            reply_to: c.from || ''
          }
        })
      }).then(function (r) {
        if (r.ok) return true;
        return r.text().then(function (msg) {
          throw new Error(msg || ('the mail service answered ' + r.status));
        });
      });
    }

    var dlg = buildDialog();

    function buildDialog() {
      var d = document.createElement('dialog');
      d.className = 'venue-dialog';
      d.setAttribute('aria-label', 'Send the ' + band + ' press kit');
      d.innerHTML =
        '<form method="dialog" class="vd-form">' +
          '<h3>Send the press kit</h3>' +
          '<p class="vd-sub" id="vd-sub"></p>' +
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
          '<p class="vd-alt" id="vd-alt">Use <button type="button" class="vd-swap" data-k="gmail">Gmail</button>' +
            '<button type="button" class="vd-swap" data-k="outlook">Outlook</button>' +
            '<button type="button" class="vd-swap" data-k="mail">my mail app</button>' +
            '<button type="button" class="vd-swap" data-k="copy">copy it instead</button></p>' +
          '<p class="vd-setup-row"><button type="button" class="vd-setup-toggle" id="vd-setup-toggle"></button></p>' +
          '<div class="vd-setup" id="vd-setup" hidden>' +
            '<p class="vd-setup-why">Send straight from here, with no Gmail tab. Connect an ' +
              '<a href="https://www.emailjs.com/" target="_blank" rel="noopener">EmailJS</a> account ' +
              'to the band\u2019s mailbox and paste its three IDs. They are kept on this device only ' +
              'and never go into the page, so nobody reading the site can send mail as you \u2014 ' +
              'which is the whole reason it is done this way.</p>' +
            '<label for="vd-svc">Service ID</label><input id="vd-svc" autocomplete="off" placeholder="service_xxxxxxx">' +
            '<label for="vd-tpl">Template ID</label><input id="vd-tpl" autocomplete="off" placeholder="template_xxxxxxx">' +
            '<label for="vd-key">Public key</label><input id="vd-key" autocomplete="off" placeholder="xxxxxxxxxxxxxxxx">' +
            '<label for="vd-from">Reply-to address <span class="vd-opt">(optional)</span></label>' +
            '<input id="vd-from" type="email" autocomplete="off" placeholder="band@example.com">' +
            '<div class="vd-actions">' +
              '<button type="button" class="vd-cancel" id="vd-save">Save on this device</button>' +
              '<button type="button" class="vd-cancel" id="vd-forget">Forget</button>' +
            '</div>' +
            '<p class="vd-setup-why">The template needs <code>{{to_email}}</code> in its To field, and ' +
              '<code>{{subject}}</code> and <code>{{message}}</code> in the subject and body.</p>' +
          '</div>' +
        '</form>';
      document.body.appendChild(d);

      var to = d.querySelector('#vd-to');
      var personal = d.querySelector('#vd-note');
      var err = d.querySelector('#vd-err');
      var send = d.querySelector('#vd-send');
      var choice = preferred();

      var alt = d.querySelector('#vd-alt');
      var setup = d.querySelector('#vd-setup');
      var setupToggle = d.querySelector('#vd-setup-toggle');

      function paint() {
        var direct = !!creds();
        // Configured means one button that does the thing. The provider list
        // is only useful when the page still has to hand off, so it goes away
        // rather than sitting there offering a longer way round.
        send.textContent = direct ? 'Send'
                          : choice === 'copy' ? 'Copy the message'
                          : 'Open in ' + PROVIDERS[choice].label;
        alt.hidden = direct;
        // "It opens ready to send" stops being true the moment it sends from
        // here, and a dialog describing the wrong behaviour is how people
        // stop believing the rest of the words on it.
        d.querySelector('#vd-sub').textContent = direct
          ? 'The whole message is written — bio, photos, music and the kit. Put the address in and press Send.'
          : 'The whole message is written — bio, photos, music and the kit. Put the address in and it opens ready to send.';
        setupToggle.textContent = direct ? 'Sending from this device · change'
                                         : 'Send from here instead, without opening Gmail';
        Array.prototype.forEach.call(d.querySelectorAll('.vd-swap'), function (s) {
          s.setAttribute('aria-pressed', String(s.dataset.k === choice));
        });
      }

      setupToggle.addEventListener('click', function () {
        setup.hidden = !setup.hidden;
        if (!setup.hidden) {
          var c = creds() || {};
          d.querySelector('#vd-svc').value = c.service || '';
          d.querySelector('#vd-tpl').value = c.template || '';
          d.querySelector('#vd-key').value = c.key || '';
          d.querySelector('#vd-from').value = c.from || '';
          d.querySelector('#vd-svc').focus();
        }
      });
      d.querySelector('#vd-save').addEventListener('click', function () {
        var v = { service: d.querySelector('#vd-svc').value.trim(),
                  template: d.querySelector('#vd-tpl').value.trim(),
                  key: d.querySelector('#vd-key').value.trim(),
                  from: d.querySelector('#vd-from').value.trim() };
        if (!v.service || !v.template || !v.key) {
          err.textContent = 'All three IDs are needed before it can send.';
          return;
        }
        err.textContent = saveCreds(v) ? '' : 'This browser would not store it.';
        setup.hidden = true;
        paint();
      });
      d.querySelector('#vd-forget').addEventListener('click', function () {
        forgetCreds(); setup.hidden = true; paint();
      });

      d.addEventListener('click', function (e) {
        var s = e.target.closest('.vd-swap');
        if (s) { choice = s.dataset.k; remember(choice); paint(); return; }
        // Clicking the backdrop rather than the panel closes it.
        if (e.target === d) d.close();
      });
      d.querySelector('.vd-cancel').addEventListener('click', function () { d.close(); });

      send.addEventListener('click', function () {
        var address = to.value.trim();
        if (!creds() && choice === 'copy') {
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

        // Configured: no hand-off, no new tab, no Gmail.
        if (creds()) {
          var was = send.textContent;
          send.disabled = true;
          send.textContent = 'Sending…';
          sendDirect(address, personal.value.trim()).then(function () {
            if (typeof global.gtag === 'function') {
              global.gtag('event', 'share', { method: 'email_venue_direct',
                                              content_type: 'epk', item_id: band });
            }
            send.disabled = false; send.textContent = was;
            d.close();
            note('Sent to ' + address + '.');
          }).catch(function (e) {
            send.disabled = false; send.textContent = was;
            // Stay open with the address still in the box: retyping it is the
            // last thing anyone wants after a failed send.
            err.textContent = 'Did not send — ' + (e && e.message ? e.message : 'unknown error') +
                              '. Try “copy it instead”, or check the setup below.';
            alt.hidden = false;
          });
          return;
        }

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

    function copyOut(personal) {
      var text = fullMessage(personal);
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text)
          .then(function () { note('Message copied — paste it into an email to the venue.'); })
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
