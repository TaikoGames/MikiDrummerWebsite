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

const CACHE = 'miki-tools-v3';

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

  '/js/install.js',
];
const OWNED = new Set(SHELL);

// Files we write ourselves and will change again: never trust the cached copy
// while there is a network to ask.
const FRESH_FIRST = [
  '/razor-cut-tool.html',
  '/click-track.html',
  '/js/install.js',
  '/razor.webmanifest',
  '/click-track.webmanifest',
];

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

  // Our own code — pages, the install script, the manifests — is served
  // newest-first, falling back to cache when there is no network.
  //
  // Learned the hard way: the install script used to be cache-first like the
  // libraries, so when its contents changed every browser that had already
  // been here kept running the old copy, with no way to notice. Only genuinely
  // immutable things (a pinned library version, an icon) get to be cache-first.
  if (FRESH_FIRST.some((path) => url.pathname === path)) {
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

  // Pinned library versions and icons: cache first, these really do not change.
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
