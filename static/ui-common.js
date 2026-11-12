/* Shared formatting and safe DOM helpers. No network or portfolio mutations. */
const $ = (s) => document.querySelector(s),
  money = (v, c = 'NOK') =>
    new Intl.NumberFormat('nb-NO', {
      style: 'currency',
      currency: c,
      maximumFractionDigits: 2,
    }).format(v);
const esc = (v) =>
  String(v == null ? '' : v).replace(
    /[&<>"']/g,
    (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c])
  );
const fresh = (q) =>
  q &&
  Number.isFinite(q.price) &&
  q.price > 0 &&
  Date.now() / 1000 - q.asof < 4 * 86400 &&
  q.asof <= Date.now() / 1000 + 300;

const toolNumber = (v, suffix = '', digits = 1) =>
  Number.isFinite(v) ? v.toFixed(digits) + suffix : 'Unavailable';
const toolTile = (label, value, note = '') =>
  '<article><small>' +
  esc(label) +
  '</small><strong>' +
  esc(value) +
  '</strong>' +
  (note ? '<small>' + esc(note) + '</small>' : '') +
  '</article>';
const toolTable = (headers, rows) =>
  '<table><thead><tr>' +
  headers.map((h) => '<th>' + esc(h) + '</th>').join('') +
  '</tr></thead><tbody>' +
  rows.map((row) => '<tr>' + row.map((v) => '<td>' + v + '</td>').join('') + '</tr>').join('') +
  '</tbody></table>';
const sourceLink = (url) =>
  /^https:\/\/newsweb\.oslobors\.no\/message\/\d+$/.test(url || '') ||
  /^https:\/\/finance\.yahoo\.com\/quote\/[A-Za-z0-9.%^_-]+\/history\/$/.test(url || '')
    ? url
    : '';
