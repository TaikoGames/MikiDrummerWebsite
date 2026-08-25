/* Install / offline plumbing, shared by the tools that want it.
 *
 * Both Razor Cut and the click track are self-contained once loaded — the only
 * thing between them and a rehearsal room with no signal is the download of
 * the page itself. The service worker handles that; this handles the button.
 *
 * The button is always on screen (until the app is actually installed), and
 * that is deliberate. Browsers only fire beforeinstallprompt when they feel
 * like it — never on iOS, not at all in Firefox on desktop, and in Chrome only
 * after its own engagement heuristics are satisfied. A button that appears
 * only when the event arrives is a button nobody can find, so this one is
 * always there: it installs directly when the browser offers a prompt, and
 * otherwise says where the option lives in that particular browser's menus.
 *
 * Usage: <script src="/js/install.js" defer></script> plus, somewhere near the top
 * of the page:
 *   <button id="installBtn" hidden>Install</button>
 *   <p id="installHow" hidden></p>
 */
(function () {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {
        /* private windows and file:// have no service workers — the tool still works */
      });
    });

    // Deliberately no reload when a new worker takes over. It looked like a
    // tidy way to pick up fresh code, and it is — right up until it fires
    // while someone has an hour of audio loaded and clips on screen, and
    // throws the lot away. Our own files are served network-first now, so a
    // new version is picked up on the next visit anyway; that is soon enough.
  }

  var btn = document.getElementById('installBtn');
  var how = document.getElementById('installHow');
  if (!btn) return;

  var ua = navigator.userAgent;
  var iOS = /iPad|iPhone|iPod/.test(ua)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var safariMac = /Safari/.test(ua) && /Macintosh/.test(ua) && !/Chrome|Chromium|Edg/.test(ua);
  var android = /Android/.test(ua);
  var firefox = /Firefox/.test(ua);

  function installed() {
    return window.matchMedia('(display-mode: standalone)').matches
      || window.matchMedia('(display-mode: minimal-ui)').matches
      || navigator.standalone === true;
  }

  var show = function (el) { if (el) { el.hidden = false; el.style.removeProperty('display'); } };
  var hide = function (el) { if (el) { el.hidden = true; el.style.display = 'none'; } };

  if (installed()) return;          // already on the home screen, nothing to offer
  show(btn);

  var prompt = null;
  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    prompt = e;                     // now the button can do it in one tap
    hide(how);
  });

  function manualSteps() {
    if (iOS) return 'Tap the Share button, then “Add to Home Screen”.';
    if (safariMac) return 'In Safari: File → Add to Dock.';
    if (firefox) return android
      ? 'Tap ⋮ (top right), then “Install”.'
      : 'Firefox on a computer cannot install web apps — open this page in Chrome or Edge, or just bookmark it.';
    if (android) return 'Tap ⋮ (top right), then “Install app” or “Add to Home screen”.';
    return 'Look for the install icon at the right-hand end of the address bar, or ⋮ menu → “Cast, save and share” → “Install page as app”.';
  }

  function tell(text) {
    if (!how) { alert(text); return; }   // no slot in the page: still say something
    how.textContent = text;
    show(how);
  }

  btn.addEventListener('click', async function () {
    // A stored prompt goes stale — the browser can refuse it if the page has
    // been open a while, or if it decided to show its own bar in the meantime.
    // Whatever happens, the tap has to visibly do something.
    if (prompt) {
      try {
        btn.disabled = true;
        var p = prompt;
        prompt = null;
        p.prompt();
        // userChoice does not always come back. If the browser thinks this app
        // is already installed it quietly does nothing at all, and awaiting it
        // forever leaves a dead button and no explanation — which is exactly
        // how this was failing on Android.
        var choice = await Promise.race([
          p.userChoice,
          new Promise(function (r) { setTimeout(function () { r({ outcome: 'no-answer' }); }, 2500); })
        ]);
        btn.disabled = false;
        if (choice && choice.outcome === 'accepted') { hide(btn); hide(how); }
        else if (choice && choice.outcome === 'dismissed') {
          tell('Not installed. You can also do it from the browser menu — ' + manualSteps());
        } else {
          tell('Your browser did not open the install dialog — it may think this is already installed. '
             + 'Check your home screen first, otherwise: ' + manualSteps());
        }
        return;
      } catch (e) {
        btn.disabled = false;
        tell(manualSteps());
        return;
      }
    }
    if (how && !how.hidden) { hide(how); return; }   // second tap closes it
    tell(manualSteps());
  });

  window.addEventListener('appinstalled', function () { hide(btn); hide(how); });
})();
