/* What the site assistant actually answers, checked against what it should.
 *
 *     python3 -m http.server 8781 &
 *     npm i playwright                     (not a dependency of the site)
 *     PORT=8781 node tools/chat_probe.mjs
 *
 * Drives the real page in a real browser rather than testing the matcher in
 * isolation, because the interesting failures are in the routing between the
 * shows board and the knowledge base, and that only exists on the page.
 *
 * Every case asserts WHICH answer came back, not merely that one did. That
 * distinction is the entire reason this file exists. The first run of this
 * probe reported 25 of 30 answered and looked healthy; three of those 25 were
 * confidently wrong, and they were the expensive ones:
 *
 *   "drum lesons vancouver"        -> 56 gig listings
 *   "i need a drummer for one show"-> 58 gig listings
 *   "how do i bok the band"        -> the list of bands
 *
 * A question answered with the wrong thing is worse than one answered with
 * "I don't know", because the visitor believes it and leaves. Counting
 * responses hides that; matching them does not.
 */
import { chromium } from 'playwright';

const PORT = process.env.PORT || 8781;
const BASE = `http://127.0.0.1:${PORT}`;

// [question, a fragment the right answer contains]
// Fragments are deliberately short and stable -- enough to identify the topic,
// not so much that rewording an answer breaks the test.
const CASES = [
  // plain topic questions
  ['who is miki',                   'Ibiza'],
  ['does he teach drums',           'lessons'],
  ['what bands does he play in',    'Lift the Anchor'],
  ['who are lift the anchor',       'melodic'],
  ['tell me about granite',         'grunge'],
  ['how do i book the band',        'Book the band form'],
  ['what is punk bc',               'board of upcoming'],
  ['what kit does he play',         'drum map'],
  ['is there a metronome',          'click track'],
  ['where can i watch videos',      'Drum covers'],

  // the shows board
  ['what shows are coming up',      'shows coming up'],
  ['anything in victoria',          'Victoria'],
  ['whats on tonight',              'tonight'],
  ['how many shows are there',      'upcoming shows on the board'],

  // typos. one wrong letter used to lose the whole question
  ['does he teech drums',           'lessons'],
  ['who are lift the anchr',        'melodic'],
  ['tell me about granit',          'grunge'],
  ['wat is punk bc',                'board of upcoming'],

  // A place name must not hijack a question that is not about listings.
  ['drum lesons vancouver',         'lessons'],

  // Hiring language outranks the board, whatever words it contains. These are
  // the questions the site exists to receive.
  ['can i hire you for a session',  'Remote drum recording'],
  ['do you record drums remotely',  'Remote drum recording'],
  ['i need a drummer for one show', 'Book the band form'],

  // The newer tools, which the knowledge base did not know about.
  ['whats the cymbal thing',        'cymbal'],
  ['do you have a poster maker',    'poster'],
  ['can i mock up merch',           'shirt'],
  ['is there a qr code maker',      'QR'],
  ['what tools are on the site',    'Eight free'],
];

// Follow-ups, run in order against a fresh page: each pair is a question that
// sets the subject, then one that relies on it.
const THREADS = [
  [['who are lift the anchor', 'melodic'],
   ['how do i book them',      'Book the band form']],
  [['tell me about granite',   'grunge'],
   ['when do they play next',  'shows board']],
];

const UNKNOWN = /do not know that one/i;

async function answer(page, q) {
  await page.fill('#q', q);
  await page.click('#send');
  await page.waitForTimeout(160);
  return (await page.$eval('#log .msg.bot:last-child', e => e.textContent.trim()));
}

async function fresh(browser) {
  const page = await browser.newPage();
  page.on('pageerror', e => { throw e; });
  await page.goto(`${BASE}/chat.html`, { waitUntil: 'networkidle' });
  await page.waitForFunction(() => document.querySelectorAll('#log .msg').length > 0);
  return page;
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM || '/opt/pw-browsers/chromium'
});

let wrong = 0, unknown = 0;
const page = await fresh(browser);

for (const [q, want] of CASES) {
  const got = await answer(page, q);
  const ok = got.toLowerCase().includes(want.toLowerCase());
  if (!ok) { (UNKNOWN.test(got) ? unknown++ : wrong++); }
  console.log(`${ok ? 'ok  ' : UNKNOWN.test(got) ? 'MISS' : 'WRONG'}  ${q.padEnd(32)} want ${JSON.stringify(want).padEnd(24)} ${ok ? '' : 'got: ' + got.slice(0, 60).replace(/\n/g, ' ')}`);
}
await page.close();

for (const thread of THREADS) {
  const p = await fresh(browser);
  for (const [q, want] of thread) {
    const got = await answer(p, q);
    const ok = got.toLowerCase().includes(want.toLowerCase());
    if (!ok) { (UNKNOWN.test(got) ? unknown++ : wrong++); }
    console.log(`${ok ? 'ok  ' : UNKNOWN.test(got) ? 'MISS' : 'WRONG'}  ${('↳ ' + q).padEnd(32)} want ${JSON.stringify(want).padEnd(24)} ${ok ? '' : 'got: ' + got.slice(0, 60).replace(/\n/g, ' ')}`);
  }
  await p.close();
}

const total = CASES.length + THREADS.reduce((n, t) => n + t.length, 0);
console.log(`\n${total - wrong - unknown}/${total} right · ${wrong} answered with the wrong thing · ${unknown} not answered`);
await browser.close();
process.exit(wrong + unknown ? 1 : 0);
