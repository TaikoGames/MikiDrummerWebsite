/* Service worker for the practice tools — Razor Cut and the click track.
 *
 * A service worker registered from the site root controls every page on the
 * domain, which is not what we want here: the homepage reads config.json to
 * decide whether the live overlay is on, the shows board wants the newest
 * bake, and admin must never be served from a stale cache. So this one keeps
 * to a strict allowlist — anything not on it is left completely alone, with no
 * respondWith call, so the browser fetches it exactly as it always would.
 *
 * The point of it is those two working in a rehearsal room with no signal.
 */

const CACHE = 'miki-tools-v2';

// Everything the tools need to run with the network switched off.
const SHELL = [
  '/razor-cut-tool.html',
  '/vendor/jszip/jszip.min.js',
  '/vendor/lamejs/lame.min.js',
  '/razor.webmanifest',
  '/images/razor-icon-192.png',
  '/images/razor-icon-512.png',
  '/images/razor-icon-maskable.png',
  '/images/razor-icon-180.png',

  '/click-track.html',
  '/click-track.webmanifest',
  '/images/click-icon-192.png',
  '/images/click-icon-512.png',
  '/images/click-icon-maskable.png',
  '/images/click-icon-180.png',

  '/js/pwa.js',
];
const OWNED = new Set(SHELL);

self.addEventListener('install', (event) => {
  event.waitUntil(
    caches.open(CACHE)
      // one missing file must not fail the whole install
      .then((cache) => Promise.allSettled(SHELL.map((url) => cache.add(url))))
      .then(() => self.skipWaiting())
  );
});

self.addEventListener('activate', (event) => {
  event.waitUntil(
    caches.keys()
      .then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
      .then(() => self.clients.claim())
  );
});

self.addEventListener('fetch', (event) => {
  const req = event.request;
  if (req.method !== 'GET') return;

  let url;
  try { url = new URL(req.url); } catch (e) { return; }
  if (url.origin !== self.location.origin) return;      // never touch other hosts
  if (!OWNED.has(url.pathname)) return;                 // not ours: hands off

  // The page itself: newest wins when there is a network, cache when there is not.
  if (url.pathname.endsWith('.html')) {
    event.respondWith(
      fetch(req)
        .then((res) => {
          if (res && res.ok) {
            const copy = res.clone();
            caches.open(CACHE).then((c) => c.put(req, copy));
          }
          return res;
        })
        .catch(() => caches.match(req))
    );
    return;
  }

  // Pinned library versions and icons: cache first, they do not change under us.
  event.respondWith(
    caches.match(req).then((hit) => hit || fetch(req).then((res) => {
      if (res && res.ok) {
        const copy = res.clone();
        caches.open(CACHE).then((c) => c.put(req, copy));
      }
      return res;
    }))
  );
});
