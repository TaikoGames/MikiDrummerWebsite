/* Applies the band's edits to the Lift the Anchor press kit.
 *
 * Shared by the kit itself and by the editor's preview, so what the band sees
 * before sending is produced by the same code that renders the real page —
 * a preview drawn a second way is a preview that can lie.
 *
 * The rule throughout: the markup in the HTML is the truth. This hides,
 * reorders, renames and fills in text. The only things it may create are a
 * YouTube iframe from a validated video id and an <img> from a link the band
 * pasted — both go through the same guards as everything else. A missing or
 * broken file leaves the page exactly as it was baked, so nobody can take the
 * press kit down with a bad edit.
 */
(function (global) {
  'use strict';

  function txt(el, value) {
    if (el && typeof value === 'string' && value.trim()) el.textContent = value;
  }

  // Only ever an 11-character YouTube id, never whatever arrived in the file.
  function embedFor(url) {
    var m = String(url || '').match(/([A-Za-z0-9_-]{11})(?:[?&].*)?$/);
    return m ? 'https://www.youtube.com/embed/' + m[1] : null;
  }

  // What may become an <img src>. Four shapes, and nothing else:
  //   http(s)://…            a hosted file
  //   /path or path/file.jpg one of ours, absolute or relative — the baked
  //                          gallery uses relative paths, and an earlier
  //                          version of this rejected them, which silently
  //                          dropped every photo already on the page
  //   data:image/…;base64,   a photo the band added off a phone
  // Anything carrying a scheme we did not name — javascript:, vbscript: — is
  // refused, which is the whole point of doing this by allowlist.
  function safeImage(src) {
    var s = String(src || '').trim();
    if (!s) return null;
    if (/^data:image\/(png|jpe?g|webp|gif);base64,[A-Za-z0-9+/=\s]+$/i.test(s)) return s;
    if (/^https?:\/\//i.test(s)) return s;
    if (/^[a-z][a-z0-9+.-]*:/i.test(s)) return null;   // some other scheme
    if (/^\/\//.test(s)) return null;                  // protocol-relative
    return s;                                          // ours, absolute or relative
  }

  // Put nodes back in the order the band chose, without rebuilding them —
  // rebuilding would drop the audio element's state mid-song.
  function reorder(parent, nodes) {
    nodes.forEach(function (n) { if (n && n.parentNode === parent) parent.appendChild(n); });
  }

  function applyLive(cfg, doc) {
    var section = doc.getElementById('live');
    if (!section) return;
    if (!cfg.live) return;
    if (cfg.live.show === false) { section.hidden = true; return; }
    section.hidden = false;

    var head = section.querySelector('.sec-head h2');
    txt(head, cfg.live.headline);

    var meta = section.querySelector('.live-meta');
    var rows = [].slice.call(section.querySelectorAll('.live-row'));
    var byFile = {};
    (cfg.live.tracks || []).forEach(function (t) { if (t && t.file) byFile[t.file] = t; });

    var order = [], shown = 0;
    (cfg.live.tracks || []).forEach(function (t) {
      var row = rows.filter(function (r) {
        return (r.dataset.src || '').split('/').pop() === t.file;
      })[0];
      if (row) order.push(row);
    });
    reorder(section.querySelector('.live-set'), order);

    rows.forEach(function (row) {
      var want = byFile[(row.dataset.src || '').split('/').pop()];
      if (!want) { row.hidden = false; shown++; return; }
      if (want.show === false) { row.hidden = true; return; }
      row.hidden = false; shown++;
      if (want.title) {
        var name = row.querySelector('.live-name');
        if (name) name.textContent = want.title;
        row.dataset.title = want.title;
      }
    });

    if (meta && (cfg.live.venue || cfg.live.date)) {
      var when = cfg.live.date ? new Date(cfg.live.date + 'T12:00:00') : null;
      var pretty = when && !isNaN(when) ? when.toLocaleDateString('en-CA',
        { day: 'numeric', month: 'long', year: 'numeric' }) : cfg.live.date;
      var bits = [];
      if (cfg.live.venue) bits.push('<b>' + esc(cfg.live.venue) + '</b>');
      if (cfg.live.city) bits.push(esc(cfg.live.city));
      if (pretty) bits.push(esc(pretty));
      var line = bits.join(' &middot; ');
      if (shown) line += ' &mdash; ' + shown + (shown === 1 ? ' song' : ' songs');
      if (cfg.live.blurb) line += ', ' + esc(cfg.live.blurb);
      meta.innerHTML = line;
    }

    // A heading over an empty box reads as a broken page.
    if (!shown) section.hidden = true;
  }

  function esc(s) {
    return String(s).replace(/[&<>"]/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c];
    });
  }

  function applyPhotos(cfg, doc) {
    if (!Array.isArray(cfg.photos)) return;
    var gallery = doc.querySelector('#media .gallery');
    if (!gallery) return;
    var shots = [].slice.call(gallery.querySelectorAll('.shot'));
    var bySrc = {};
    shots.forEach(function (s) {
      var img = s.querySelector('img');
      if (img) bySrc[img.getAttribute('src')] = s;
    });

    var order = [];
    cfg.photos.forEach(function (p) {
      var src = safeImage(p && p.src);
      if (!src) return;
      var shot = bySrc[src];
      if (!shot) {
        // Something the band added. Built here rather than baked, so it can
        // only ever be an image from a link they pasted.
        shot = doc.createElement('div');
        // Plain .shot, not .feature. A photo off a phone is nearly always
        // portrait, and .feature crops to 2:1 — which takes the top off
        // whoever is in it.
        shot.className = 'shot';
        var img = doc.createElement('img');
        img.src = src;
        img.alt = p.alt || 'Lift the Anchor';
        img.loading = 'lazy';
        shot.appendChild(img);
        gallery.appendChild(shot);
        bySrc[src] = shot;
      }
      shot.hidden = p.show === false;
      if (p.show !== false) order.push(shot);
    });
    reorder(gallery, order);
  }

  function applyVideos(cfg, doc) {
    if (!Array.isArray(cfg.videos)) return;
    var box = doc.querySelector('#media .videos');
    if (!box) return;
    var vids = [].slice.call(box.querySelectorAll('.vid'));
    var byId = {};
    vids.forEach(function (v) {
      var f = v.querySelector('iframe');
      var e = f && embedFor(f.getAttribute('src'));
      if (e) byId[e] = v;
    });

    var order = [];
    cfg.videos.forEach(function (item) {
      var embed = embedFor(item && item.embed);
      if (!embed) return;
      var vid = byId[embed];
      if (!vid) {
        var model = vids[0];
        vid = doc.createElement('div');
        vid.className = 'vid';
        var frame = doc.createElement('iframe');
        frame.src = embed;
        frame.loading = 'lazy';
        frame.allowFullscreen = true;
        frame.setAttribute('title', item.title || 'Lift the Anchor');
        frame.style.cssText = 'width:100%;aspect-ratio:16/9;border:0;display:block';
        vid.appendChild(frame);
        if (item.title) {
          var cap = doc.createElement('div');
          cap.className = 'cap';
          cap.textContent = item.title;
          vid.appendChild(cap);
        }
        box.appendChild(vid);
        byId[embed] = vid;
      } else if (item.title) {
        var existing = vid.querySelector('.cap');
        if (existing) existing.textContent = item.title;
      }
      vid.hidden = item.show === false;
      if (item.show !== false) order.push(vid);
    });
    reorder(box, order);
  }

  function applyBio(cfg, doc) {
    if (Array.isArray(cfg.bio) && cfg.bio.length) {
      var body = doc.querySelector('.bio-body');
      if (body) {
        var keep = cfg.bio.filter(function (p) { return String(p || '').trim(); });
        if (keep.length) {
          body.innerHTML = '';
          keep.forEach(function (p) {
            var el = doc.createElement('p');
            el.textContent = p;
            body.appendChild(el);
          });
        }
      }
    }
    if (Array.isArray(cfg.facts) && cfg.facts.length) {
      var facts = doc.querySelector('.facts');
      if (facts) {
        var rows = cfg.facts.filter(function (f) { return f && String(f.k || '').trim(); });
        if (rows.length) {
          facts.innerHTML = '';
          rows.forEach(function (f) {
            var row = doc.createElement('div');
            row.className = 'row';
            var k = doc.createElement('span'); k.className = 'k'; k.textContent = f.k;
            var v = doc.createElement('span'); v.className = 'v'; v.textContent = f.v || '';
            row.appendChild(k); row.appendChild(v);
            facts.appendChild(row);
          });
        }
      }
    }
  }

  function apply(cfg, doc) {
    doc = doc || document;
    if (!cfg || typeof cfg !== 'object') return;
    try { applyLive(cfg, doc); }   catch (e) {}
    try { applyPhotos(cfg, doc); } catch (e) {}
    try { applyVideos(cfg, doc); } catch (e) {}
    try { applyBio(cfg, doc); }    catch (e) {}
  }

  global.LTAEpk = { apply: apply, embedFor: embedFor, safeImage: safeImage };
})(window);
