/* Turn on whatever the site setting asks for.
 *
 * The setting lives in config.json, which the admin page writes, so one switch
 * there reaches every page. It is fetched rather than baked in so changing it
 * does not mean rebuilding the site.
 */
(function () {
  'use strict';
  if (!window.Seasonal) return;
  // A visitor should not wait on this: it is decoration, and it starts when it
  // arrives or not at all.
  fetch('/config.json?_=' + Math.floor(Date.now() / 60000), { cache: 'no-store' })
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (c) { window.Seasonal.apply((c && c.season) || 'auto'); })
    .catch(function () { window.Seasonal.apply('auto'); });
})();
