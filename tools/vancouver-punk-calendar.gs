/**
 * Pull the Vancouver Punk Calendar into the Punk BC shows sheet.
 *
 * Paste this into the sheet: Extensions → Apps Script, replace everything,
 * Save, then reload the sheet. A "Punk BC" menu appears next to Help.
 *
 * It only ever appends. Nothing already in the sheet is edited or removed, so
 * anything hand-corrected stays corrected, and a second run adds nothing.
 *
 * It reads the calendar's public .ics feed rather than going through
 * CalendarApp, which needs the calendar subscribed to the account first. No
 * subscription, no advanced services, no API key.
 */

var CAL_ID = 'vancouverpunkcalendar@gmail.com';
var DEFAULT_CITY = 'Vancouver';
var MONTHS_AHEAD = 12;

/* The same room is written several ways across sources. Left alone that puts
 * the same gig in twice and splits the venue pages on the site. Keys lowercase. */
var VENUE_ALIAS = {
  'astoria': 'The Astoria',
  'astoria pub': 'The Astoria',
  'the astoria pub': 'The Astoria',
  'cobalt': 'The Cobalt',
  'cobalt cabaret': 'The Cobalt',
  'the cobalt cabaret': 'The Cobalt',
  'wise hall': 'The WISE Hall',
  'the wise': 'The WISE Hall',
  'the wise hall': 'The WISE Hall',
  'wise hall & lounge': 'The WISE Hall',
  'lanalous': "LanaLou's",
  "lanalou's": "LanaLou's",
  "lanalou's restaurant": "LanaLou's",
  'red gate': 'Red Gate Arts Society',
  'green auto body': 'Green Auto',
  'rickshaw': 'Rickshaw Theatre',
  'the rickshaw': 'Rickshaw Theatre',
  'the rickshaw theatre': 'Rickshaw Theatre',
  'biltmore': 'Biltmore Cabaret',
  'the biltmore': 'Biltmore Cabaret',
  'commodore': 'Commodore Ballroom',
  'the commodore': 'Commodore Ballroom',
  'pearl': 'The Pearl',
  'the pearl vancouver': 'The Pearl',
  'luckybar': 'Lucky Bar',
  'lucky bar': 'Lucky Bar'
};

function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('Punk BC')
    .addItem('Import from Vancouver Punk Calendar', 'importPunkCalendar')
    .addItem('Preview — what would be added', 'previewPunkCalendar')
    .addToUi();
}

function importPunkCalendar() { runImport(false); }
function previewPunkCalendar() { runImport(true); }

function runImport(previewOnly) {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  var ui = SpreadsheetApp.getUi();

  var events;
  try {
    events = fetchCalendar();
  } catch (err) {
    ui.alert('Could not read the calendar', String(err), ui.ButtonSet.OK);
    return;
  }

  var header = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var col = {};
  for (var i = 0; i < header.length; i++) {
    col[String(header[i]).trim().toLowerCase()] = i;
  }
  var iBand = pick(col, ['band / artist', 'band', 'artist']);
  var iDate = pick(col, ['date']);
  if (iBand < 0 || iDate < 0) {
    ui.alert('Could not find the columns',
             'This needs a "Band / Artist" column and a "Date" column on row 1.',
             ui.ButtonSet.OK);
    return;
  }
  var iTime   = pick(col, ['time']);
  var iVenue  = pick(col, ['venue']);
  var iCity   = pick(col, ['city']);
  var iTicket = pick(col, ['ticket link', 'ticket', 'tickets']);
  var iNotes  = pick(col, ['notes']);

  // What is already here, keyed the way the site keys it: band + date + venue,
  // with the venue folded onto its canonical spelling first.
  var last = sheet.getLastRow();
  var seen = {};
  if (last > 1) {
    var rows = sheet.getRange(2, 1, last - 1, sheet.getLastColumn()).getValues();
    for (var r = 0; r < rows.length; r++) {
      var band = String(rows[r][iBand] || '').trim();
      var date = asIsoDate(rows[r][iDate]);
      if (!band || !date) continue;
      var venue = iVenue >= 0 ? canonicalVenue(rows[r][iVenue]) : '';
      seen[key(band, date, venue)] = true;
    }
  }

  var width = Math.max(sheet.getLastColumn(), header.length);
  var adding = [], names = [];
  for (var e = 0; e < events.length; e++) {
    var ev = events[e];
    var venueC = canonicalVenue(ev.location);
    var k = key(ev.band, ev.date, venueC);
    if (seen[k]) continue;
    seen[k] = true;                       // the calendar can repeat within itself

    var row = new Array(width).fill('');
    row[iBand] = ev.band;
    row[iDate] = ev.date;
    if (iTime   >= 0) row[iTime]   = ev.time;
    if (iVenue  >= 0) row[iVenue]  = venueC;
    if (iCity   >= 0) row[iCity]   = DEFAULT_CITY;
    if (iTicket >= 0) row[iTicket] = ev.ticket;
    if (iNotes  >= 0) row[iNotes]  = ev.notes;
    adding.push(row);
    names.push(ev.date + '  ' + ev.band + (venueC ? '  @ ' + venueC : ''));
  }

  if (!adding.length) {
    ui.alert('Nothing missing',
             'All ' + events.length + ' shows on their calendar are already in this sheet.',
             ui.ButtonSet.OK);
    return;
  }

  if (previewOnly) {
    ui.alert(adding.length + ' would be added',
             names.slice(0, 40).join('\n') +
             (names.length > 40 ? '\n… and ' + (names.length - 40) + ' more' : ''),
             ui.ButtonSet.OK);
    return;
  }

  var start = sheet.getLastRow() + 1;
  sheet.getRange(start, 1, adding.length, width).setValues(adding);
  // Keep the dates exporting as YYYY-MM-DD whatever the sheet's locale does.
  sheet.getRange(start, iDate + 1, adding.length, 1).setNumberFormat('yyyy-mm-dd');

  ui.alert('Added ' + adding.length,
           names.slice(0, 40).join('\n') +
           (names.length > 40 ? '\n… and ' + (names.length - 40) + ' more' : ''),
           ui.ButtonSet.OK);
}

/* ---- reading the calendar ------------------------------------------------ */

function fetchCalendar() {
  var url = 'https://calendar.google.com/calendar/ical/' +
            encodeURIComponent(CAL_ID) + '/public/basic.ics';
  var res = UrlFetchApp.fetch(url, { muteHttpExceptions: true });
  if (res.getResponseCode() !== 200) {
    throw new Error('The calendar feed answered ' + res.getResponseCode() +
                    '. It may have stopped being public.');
  }

  // Unfold first: .ics wraps long lines, and a continuation starts with a
  // space or tab. Parsing without this cuts long band lists in half.
  var text = res.getContentText().replace(/\r\n[ \t]/g, '').replace(/\r\n/g, '\n');
  var blocks = text.split('BEGIN:VEVENT').slice(1);

  var today = new Date(); today.setHours(0, 0, 0, 0);
  var horizon = new Date(today.getTime());
  horizon.setMonth(horizon.getMonth() + MONTHS_AHEAD);

  var out = [];
  for (var i = 0; i < blocks.length; i++) {
    var b = blocks[i].split('END:VEVENT')[0];
    if (/^STATUS:CANCELLED$/m.test(b)) continue;

    var start = field(b, 'DTSTART');
    if (!start) continue;
    var m = start.match(/(\d{4})(\d{2})(\d{2})(?:T(\d{2})(\d{2}))?/);
    if (!m) continue;
    var date = m[1] + '-' + m[2] + '-' + m[3];
    var when = new Date(+m[1], +m[2] - 1, +m[3]);
    if (when < today || when > horizon) continue;

    // An all-day entry states no time; inventing one would be a lie on a
    // listing people turn up to.
    var time = m[4] ? m[4] + ':' + m[5] : '';

    var summary = unescapeIcs(field(b, 'SUMMARY'));
    if (!summary) continue;
    var location = unescapeIcs(field(b, 'LOCATION')).split('\n')[0].trim();
    var desc = unescapeIcs(field(b, 'DESCRIPTION'));

    out.push({
      band: cleanBill(summary, location),
      date: date,
      time: time || timeFromText(desc),
      location: location,
      ticket: firstUrl(desc),
      notes: ''
    });
  }
  return out;
}

function field(block, name) {
  var re = new RegExp('^' + name + '(?:;[^:\\n]*)?:(.*)$', 'm');
  var m = block.match(re);
  return m ? m[1].trim() : '';
}

function unescapeIcs(s) {
  return String(s || '')
    .replace(/\\n/gi, '\n').replace(/\\,/g, ',')
    .replace(/\\;/g, ';').replace(/\\\\/g, '\\');
}

/* "Dead Pioneers @ Wise Hall" is a band and a room, and the room is already in
 * its own column. Pipes become slashes, which is how bills are written on the
 * board. */
function cleanBill(summary, location) {
  var s = summary.replace(/\s*[|]\s*/g, ' / ').trim();
  var venueWords = String(location || '').replace(/[^A-Za-z0-9 ]/g, ' ').trim();
  if (venueWords) {
    var esc = venueWords.replace(/[.*+?^${}()|[\]\\]/g, '\\$&').replace(/\s+/g, '\\s+');
    s = s.replace(new RegExp('\\s*(?:@|\\bat\\b)\\s*(?:the\\s+)?' + esc + '\\s*$', 'i'), '');
  }
  return s.replace(/\s*(?:@|\bat\b)\s+[A-Z][\w'’& ]{2,30}$/, '').trim() || summary;
}

function timeFromText(desc) {
  var m = String(desc || '').match(/\b(\d{1,2}):(\d{2})\b/);
  return m ? ('0' + m[1]).slice(-2) + ':' + m[2] : '';
}

/* Tracking parameters are noise and they follow people around. */
function firstUrl(desc) {
  var m = String(desc || '').match(/https?:\/\/[^\s<>"']+/);
  if (!m) return '';
  return m[0].split('?')[0].replace(/[.,;]+$/, '');
}

/* ---- small helpers ------------------------------------------------------- */

function pick(col, names) {
  for (var i = 0; i < names.length; i++) {
    if (col[names[i]] !== undefined) return col[names[i]];
  }
  return -1;
}

function canonicalVenue(name) {
  var s = String(name || '').split('\n')[0].trim();
  if (!s) return '';
  return VENUE_ALIAS[s.toLowerCase()] || s;
}

function key(band, date, venue) {
  return String(band).trim().toLowerCase() + '|' + date + '|' +
         String(venue).trim().toLowerCase();
}

/* The Date column may hold a real date or a string, depending on how the row
 * got there. Both have to key the same way or every row looks new. */
function asIsoDate(v) {
  if (v instanceof Date && !isNaN(v)) {
    return Utilities.formatDate(v, Session.getScriptTimeZone(), 'yyyy-MM-dd');
  }
  var s = String(v || '').trim();
  var m = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
  if (m) return m[1] + '-' + ('0' + m[2]).slice(-2) + '-' + ('0' + m[3]).slice(-2);
  var d = new Date(s);
  return isNaN(d) ? '' : Utilities.formatDate(d, Session.getScriptTimeZone(), 'yyyy-MM-dd');
}
