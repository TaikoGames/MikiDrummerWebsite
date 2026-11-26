/**
 * GRANITE pitch sender — a Google Apps Script web app that sends from the
 * Gmail of whoever deploys it. granite-pitch.html posts to it.
 *
 * Deploy once: Deploy → New deployment → Web app, "Execute as: Me",
 * "Who has access: Anyone". Allow the Gmail and fetch permissions it asks for.
 *
 * Safety: it only ever sends the fixed GRANITE pitch below (the page supplies
 * the address, the writer's name, the venue name and one optional line), only
 * with the band password, at most DAILY_LIMIT a day, and not to the same
 * address twice inside REPEAT_DAYS unless asked.
 */
// Filled in by granite-sender-setup.html when the script is copied; never
// committed, because this file is public.
const BAND_PASSWORD = '__SET_BY_SETUP_PAGE__';
const DAILY_LIMIT = 25;
const REPEAT_DAYS = 60;
const KIT_PDF = 'https://www.mikidrummer.ca/files/granite-press-kit.pdf';
const EPK = 'https://www.mikidrummer.ca/granite-epk.html';
const VIDEO = 'https://www.youtube.com/watch?v=Qovij1CQUV4';
const IG = 'https://www.instagram.com/granitevancouver/';
const EMAIL = /^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$/;

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}

function clean(s, max) {
  return String(s || '').replace(/[\u0000-\u001f\u007f]/g, ' ').trim().slice(0, max);
}

function history() {
  const raw = PropertiesService.getScriptProperties().getProperty('sent');
  return raw ? JSON.parse(raw) : [];
}

function saveHistory(list) {
  PropertiesService.getScriptProperties().setProperty('sent', JSON.stringify(list.slice(-300)));
}

function letter(venue, writer, note) {
  const first = writer.split(/\s+/)[0] || 'GRANITE';
  const subject = 'GRANITE (Vancouver metal/grunge): booking enquiry' + (venue ? ' for ' + venue : '');
  const body = (venue ? 'Hi ' + venue + ' team,' : 'Hi there,') + '\n\n' +
    "I'm " + first + " from GRANITE, a metal and grunge band from Vancouver. Downtuned riffs, raw vocals, and a loud, sweaty live show. We'd love to play " + (venue || 'your room') + '.\n' +
    (note ? '\n' + note + '\n' : '') +
    '\nOur press kit is attached (PDF): a one-sheet with our bio, plus press photos and artwork. You can also download it here:\n' + KIT_PDF + '\n\n' +
    'Music, photos and everything else are on our press page:\n' + EPK + '\n\n' +
    'Live video: ' + VIDEO + '\nInstagram: ' + IG + '\n\n' +
    "If there's a night that could fit us, just reply to this email. Happy to share draw numbers, a stage plot, or anything else you need.\n\n" +
    'Thanks,\n' + writer + '\nGRANITE\n';
  return { subject: subject, body: body, first: first };
}

function locked() { return BAND_PASSWORD.indexOf('__SET') === 0; }

function doGet(e) {
  if (locked() || (e.parameter.pw || '') !== BAND_PASSWORD) return reply({ ok: false, error: 'Wrong band password.' });
  return reply({ ok: true, sent: history().slice(-40).reverse() });
}

function doPost(e) {
  const lock = LockService.getScriptLock();
  lock.waitLock(20000);
  try {
    let d = {};
    try { d = JSON.parse(e.postData.contents); } catch (err) { return reply({ ok: false, error: 'Bad request.' }); }
    if (locked() || d.pw !== BAND_PASSWORD) return reply({ ok: false, error: 'Wrong band password.' });
    const to = clean(d.to, 120).toLowerCase();
    const writer = clean(d.writer, 60);
    const venue = clean(d.venue, 80);
    const note = String(d.note || '').replace(/\r/g, '').trim().slice(0, 500);
    if (!EMAIL.test(to)) return reply({ ok: false, error: "That doesn't look like an email address." });
    if (!writer) return reply({ ok: false, error: "Say who's writing." });

    const list = history();
    const now = Date.now();
    const today = list.filter(function (h) { return now - h.at < 864e5; }).length;
    if (today >= DAILY_LIMIT) return reply({ ok: false, error: 'Daily limit reached (' + DAILY_LIMIT + '). Try tomorrow.' });
    const prev = list.filter(function (h) { return h.to === to && now - h.at < REPEAT_DAYS * 864e5; }).pop();
    if (prev && !d.again) {
      return reply({ ok: false, repeat: true,
        error: to + ' was already pitched on ' + new Date(prev.at).toDateString() + ' by ' + prev.writer + '.' });
    }

    const l = letter(venue, writer, note);
    const kit = UrlFetchApp.fetch(KIT_PDF).getBlob().setName('GRANITE-press-kit.pdf');
    MailApp.sendEmail({ to: to, subject: l.subject, body: l.body, attachments: [kit], name: l.first + ' from GRANITE' });

    list.push({ at: now, to: to, venue: venue, writer: writer });
    saveHistory(list);
    return reply({ ok: true, message: 'Sent to ' + to + ' with the press kit attached.' });
  } catch (err) {
    return reply({ ok: false, error: 'Gmail said: ' + err.message });
  } finally {
    lock.releaseLock();
  }
}
