lamejs 1.2.1 — vendored, not a build step
Copied from the npm package `lamejs@1.2.1` (LGPL-3.0), file lame.min.js, unmodified.
Used by razor-cut-tool.html to encode clips as MP3 (it falls back to WAV if this is missing).
Vendored rather than loaded from jsdelivr so a CDN outage cannot break MP3 export, and so the tool keeps working offline.
