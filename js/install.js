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
 * Usage: <script src="/js/pwa.js" defer></script> plus, somewhere near the top
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

  btn.addEventListener('click', async function () {
    if (prompt) {
      btn.disabled = true;
      prompt.prompt();
      var choice = await prompt.userChoice;
      prompt = null;
      btn.disabled = false;
      if (choice && choice.outcome === 'accepted') hide(btn);
      return;
    }
    if (how) {
      how.textContent = manualSteps();
      how.hidden ? show(how) : hide(how);
    }
  });

  window.addEventListener('appinstalled', function () { hide(btn); hide(how); });
})();
