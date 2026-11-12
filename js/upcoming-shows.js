// "Next shows in BC" on the homepage: the next three Punk BC shows, read from
// the same punkbc-shows.json the board is built from. Loaded with `defer`, so
// the page paints first with skeleton rows of the same height, and nothing
// jumps when the real rows replace them. If the fetch fails or is slow, the
// skeletons give way to a link to the full board instead of spinning forever.
(() => {
  const ENDPOINT = '/punkbc-shows.json';
  const LIMIT = 3;
  const TIMEOUT_MS = 8000;

  const section = document.getElementById('upcoming');
  const list = document.getElementById('show-list');
  const error = document.getElementById('show-error');
  if (!section || !list) return;

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));

  const fmtDate = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-CA', {
    weekday: 'short', month: 'short', day: 'numeric'
  });

  // Today in Vancouver, not UTC: after 4pm Pacific, UTC is already tomorrow
  // and tonight's show would drop off the list while people are heading to it.
  const today = new Intl.DateTimeFormat('en-CA', { timeZone: 'America/Vancouver' }).format(new Date());

  const row = (s) => {
    const ticket = /^https?:\/\//.test(s.ticket || '')
      ? `<a class="tap-btn tap-btn--tickets" href="${esc(s.ticket)}" target="_blank" rel="noopener">Tickets</a>`
      : '';
    const map = `<a class="tap-btn tap-btn--map" target="_blank" rel="noopener"
      href="https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(`${s.venue} ${s.city} BC`)}">Venue map</a>`;
    return `<li class="up-row">
      <time class="up-date" datetime="${esc(s.date)}">${fmtDate(s.date)}</time>
      <div class="up-info">
        <strong class="up-band">${esc(s.band)}</strong>
        <span class="up-where">${esc(s.venue)}, ${esc(s.city)}</span>
      </div>
      <div class="show-actions">${ticket}${map}</div>
    </li>`;
  };

  async function loadShows() {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);
    try {
      const res = await fetch(ENDPOINT, { signal: controller.signal });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const shows = (Array.isArray(data) ? data : data.shows ?? [])
        .filter((s) => s.date && s.date >= today)
        .sort((a, b) => a.date.localeCompare(b.date))
        .slice(0, LIMIT);
      list.innerHTML = shows.length
        ? shows.map(row).join('')
        : '<li class="up-empty">No shows announced right now. Check back soon.</li>';
    } catch (err) {
      console.warn('Could not load shows:', err);
      list.innerHTML = '';
      if (error) error.hidden = false;
    } finally {
      clearTimeout(timer);
      section.setAttribute('aria-busy', 'false');
    }
  }

  loadShows();
})();
