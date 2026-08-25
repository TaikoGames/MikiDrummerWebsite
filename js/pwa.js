/* Install / offline plumbing, shared by the tools that want it.
 *
 * Both Razor Cut and the click track are self-contained once loaded — the only
 * thing between them and a rehearsal room with no signal is the download of
 * the page itself. The service worker handles that; this handles the button.
 *
 * Usage: <script src="/js/pwa.js" defer></script> plus, somewhere in the page,
 *   <div id="installRow" hidden><button id="installBtn">Install</button></div>
 *   <div id="iosHint" hidden>Share → Add to Home Screen</div>
 * Both are optional; nothing here throws if they are missing.
 */
(function () {
  if ('serviceWorker' in navigator) {
    window.addEventListener('load', function () {
      navigator.serviceWorker.register('/sw.js').catch(function () {
        /* private windows and file:// have no service workers — the tool still works */
      });
    });
  }

  var row = document.getElementById('installRow');
  var btn = document.getElementById('installBtn');
  var hint = document.getElementById('iosHint');
  var show = function (el) { if (el) { el.hidden = false; el.style.display = ''; } };
  var hide = function (el) { if (el) { el.hidden = true; el.style.display = 'none'; } };
  var prompt = null;

  window.addEventListener('beforeinstallprompt', function (e) {
    e.preventDefault();
    prompt = e;
    show(row);
  });

  if (btn) {
    btn.addEventListener('click', async function () {
      if (!prompt) return;
      btn.disabled = true;
      prompt.prompt();
      await prompt.userChoice;
      prompt = null;
      hide(row);
    });
  }

  window.addEventListener('appinstalled', function () { hide(row); });

  // iOS never fires beforeinstallprompt — it wants Share → Add to Home Screen,
  // so say so rather than showing a button that cannot work.
  var iOS = /iPad|iPhone|iPod/.test(navigator.userAgent)
    || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
  var installed = window.matchMedia('(display-mode: standalone)').matches || navigator.standalone;
  if (iOS && !installed) show(hint);
})();
