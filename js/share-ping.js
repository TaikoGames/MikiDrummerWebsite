/* An email when someone shares something, on its own Formspree form.
 *
 * Eight pages post to form xpqgrqvb, and two of them matter: /play-with-us.html
 * takes band bookings and /ask-a-band.html sends invites. Formspree's free tier
 * allows fifty submissions a month across the whole form, so every share
 * notification was quietly spending the same allowance a booking needs. A
 * booking bouncing because the quota went on "someone shared your page" is a
 * bad trade, and an invisible one -- nobody finds out a submission was refused.
 *
 * So share pings get their own form and their own ceiling. Set FORM below to
 * the new form's id and it starts working; leave it empty and every call here
 * is a no-op, which is the state this ships in, since creating the form needs
 * a Formspree login.
 *
 *   SharePing.send({ what: 'poster tool', how: 'share sheet', link: '...' })
 *
 * Throttled to one per browser per day per thing. A page someone taps five
 * times is one share, and the interesting signal is that it happened at all.
 */
(function (global) {
  'use strict';

  // ---------------------------------------------------------------------
  // Paste the new form's id here (the bit after /f/ in the Formspree URL).
  // Create it at formspree.io -> New Form, name it something like
  // "mikidrummer share pings", and point it at the same inbox.
  var FORM = '';
  // ---------------------------------------------------------------------

  var ENDPOINT = 'https://formspree.io/f/';

  // ?sharetest=1 sends every time and reports what came back on the page, so
  // a mail that never arrived can be told apart from one that was refused
  // without opening a console.
  function testing() {
    return /[?&]sharetest=1/.test(global.location.search);
  }

  function key(what) {
    return 'mdSharePing:' + String(what || 'page');
  }

  function stamp() {
    return new Date().toISOString().slice(0, 10);
  }

  function sentToday(what) {
    try {
      return localStorage.getItem(key(what)) === stamp();
    } catch (e) {
      // Private browsing throws on access. Send it -- better twice than never.
      return false;
    }
  }

  function remember(what) {
    try { localStorage.setItem(key(what), stamp()); } catch (e) {}
  }

  function send(detail, done) {
    detail = detail || {};
    var report = typeof done === 'function' ? done : function () {};

    if (!FORM) {
      report(false, 'no form configured');
      return;
    }
    if (!testing() && sentToday(detail.what)) {
      report(false, 'already counted today');
      return;
    }

    fetch(ENDPOINT + FORM, {
      method: 'POST',
      // keepalive, or the request dies when the share sheet takes the page
      // away mid-flight -- which is exactly when it is sent.
      keepalive: true,
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({
        _subject: 'Someone shared ' + (detail.what || 'your page'),
        shared: detail.what || '',
        how: detail.how || '',
        link: detail.link || global.location.href,
        page: global.location.pathname,
        when: new Date().toLocaleString('en-CA', { timeZone: 'America/Vancouver' })
      })
    }).then(function (r) {
      // Only remember it once it actually went. Stamping first meant a single
      // rejected send silenced the whole day.
      if (r.ok) remember(detail.what);
      report(r.ok, r.ok ? 'sent' : 'refused: HTTP ' + r.status);
    }).catch(function (e) {
      report(false, 'never left the browser: ' + e);
    });
  }

  global.SharePing = {
    send: send,
    configured: function () { return !!FORM; },
    // services.html has its own working ping and only needs the id, so it
    // reads it from here rather than carrying a second copy to fall out of
    // step with this one.
    formId: function () { return FORM; }
  };
})(window);
