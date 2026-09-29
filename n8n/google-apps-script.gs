// Google Apps Script for the ExtractAI n8n workflow: appends the rows it receives to the first tab.
// Setup: in your sheet, Extensions -> Apps Script, paste this, set TOKEN to a long random string,
// Deploy -> New deployment -> Web app (Execute as: Me, Who has access: Anyone) and copy the /exec URL.
// In n8n: put the URL in the "Google Sheet: append rows" node, and create a Custom Auth credential
// "Google Sheet token" with {"body": {"token": "<the same TOKEN>"}}.
const TOKEN = 'REPLACE_WITH_A_LONG_RANDOM_TOKEN';
const HEADERS = ['Processed at', 'File', 'Owner', 'Type', 'Document name', 'ID number', 'Date of birth', 'Details', 'Error'];

function doPost(e) {
  const body = JSON.parse(e.postData.contents);
  if (body.token !== TOKEN) return reply({ ok: false, error: 'unauthorized' });
  const sheet = SpreadsheetApp.getActiveSpreadsheet().getSheets()[0];
  if (sheet.getLastRow() === 0) sheet.appendRow(HEADERS);
  // Text from documents must never become a formula: prefix =, +, - and @ with an apostrophe.
  const safe = (v) => { const s = String(v ?? ''); return /^[=+\-@]/.test(s) ? "'" + s : s; };
  const rows = (body.rows || []).map((r) => HEADERS.map((h) => safe(r[h])));
  if (rows.length) sheet.getRange(sheet.getLastRow() + 1, 1, rows.length, HEADERS.length).setValues(rows);
  return reply({ ok: true, added: rows.length });
}

function reply(obj) {
  return ContentService.createTextOutput(JSON.stringify(obj)).setMimeType(ContentService.MimeType.JSON);
}
