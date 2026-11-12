/* Company statement loading, dated annual charts and peer presentation. */
let financialRequest = 0;
const financialLabels = {
  revenue: 'Revenue',
  revenue_growth: 'Revenue growth',
  operating_income: 'Operating profit',
  operating_margin: 'Operating margin',
  net_income: 'Net income',
  net_margin: 'Net margin',
  operating_cash_flow: 'Operating cash flow',
  capital_expenditure: 'Capital expenditure',
  free_cash_flow: 'Free cash flow',
  debt: 'Total debt',
  cash: 'Cash & short-term investments',
  equity: 'Equity',
  net_cash: 'Cash minus debt',
  debt_to_equity: 'Debt / equity',
  diluted_eps: 'Annual diluted EPS',
  annual_pe_proxy: 'Annual P/E proxy',
  ordinary_shares: 'Year-end ordinary shares',
  diluted_shares: 'Annual diluted average shares',
  share_count_change: 'Share-count change',
};
function financialValue(metric) {
  if (!metric || !Number.isFinite(metric.value)) return 'Unavailable';
  if (metric.unit === 'percent') return metric.value.toFixed(1) + '%';
  if (metric.unit === 'ratio') return metric.value.toFixed(2) + '×';
  if (metric.unit === 'shares')
    return (
      new Intl.NumberFormat('nb-NO', { maximumFractionDigits: 0 }).format(metric.value) + ' shares'
    );
  if (metric.currency) return money(metric.value, metric.currency);
  return (
    new Intl.NumberFormat('nb-NO', { maximumFractionDigits: 2 }).format(metric.value) +
    ' (currency unspecified)'
  );
}
async function loadFinancials(symbol) {
  const token = ++financialRequest;
  try {
    const f = await api('fundamentals?symbol=' + encodeURIComponent(symbol));
    if (token !== financialRequest || symbol !== explorerSymbol) return;
    $('#financialStatus').textContent =
      `Coverage: ${f.status}. Fiscal period end: ${
        f.period || 'unavailable'
      }. Retrieved: ${timeLabel(f.fetched)}.` +
      (f.error ? ' Latest refresh: ' + f.error : '') +
      (f.scan && f.scan.running ? ` Background scan: ${f.scan.done}/${f.scan.total}.` : '');
    if (typeof renderFinancialTrends === 'function') renderFinancialTrends(f);
    const quality = f.assessment || {};
    $('#qualitySummary').textContent =
      (quality.label || 'Assessment unavailable') +
      ' · ' +
      (quality.passed || 0) +
      ' / ' +
      (quality.covered || 0) +
      ' covered accounting checks positive · Fiscal year ' +
      (quality.period || 'unknown') +
      '.';
    $('#qualityChecks').innerHTML = (quality.checks || [])
      .map(
        (c) =>
          '<p>' + esc(c.passes ? '✓ ' : 'Review: ') + esc(c.label) + ' · ' + esc(c.period) + '</p>'
      )
      .join('');
    $('#qualityMethod').textContent = quality.method || 'Financial coverage is not ready.';
    const valuation = f.valuation || {};
    $('#valuationSummary').textContent =
      valuation.median_annual_pe_proxy != null
        ? 'Annual P/E proxy ' +
          valuation.subject_annual_pe_proxy.toFixed(2) +
          '× versus sector median ' +
          valuation.median_annual_pe_proxy.toFixed(2) +
          '× (' +
          valuation.peer_count +
          ' other companies with matching fiscal periods). ' +
          valuation.method
        : 'Peer valuation unavailable: at least three comparable fresh same-sector annual observations are required. Annual P/E is not TTM and does not establish cheapness.';
    $('#financialSignals').innerHTML = (f.signals || []).length
      ? '<ul>' + f.signals.map((s) => '<li>' + esc(s) + '</li>').join('') + '</ul>'
      : '<p>Financial statements have not been retrieved for this company yet, or the provider has no coverage. Missing figures are not treated as zero.</p>';
    const keys = [
      'revenue',
      'revenue_growth',
      'operating_margin',
      'net_income',
      'operating_cash_flow',
      'free_cash_flow',
      'debt',
      'cash',
      'net_cash',
      'debt_to_equity',
      'annual_pe_proxy',
      'share_count_change',
    ];
    $('#financialMetrics').innerHTML = keys
      .map((k) => {
        const m = (f.metrics || {})[k];
        return `<article><small>${financialLabels[k]}</small><strong>${financialValue(
          m
        )}</strong><small>${m ? esc(m.period) : 'No matching annual observation'}</small>${
          m && m.note ? '<p>' + esc(m.note) + '</p>' : ''
        }</article>`;
      })
      .join('');
    const rows = [];
    for (const [key, values] of Object.entries(f.history || {}))
      for (const v of values)
        rows.push(
          `<tr><td>${esc(financialLabels[key] || key)}</td><td>${esc(
            v.period
          )}</td><td>${financialValue({
            ...v,
            unit: key === 'ordinary_shares' || key === 'diluted_shares' ? 'shares' : 'amount',
          })}</td></tr>`
        );
    $('#financialHistory').innerHTML = rows.length
      ? '<table><thead><tr><th>Annual field</th><th>Fiscal period end</th><th>Reported value</th></tr></thead><tbody>' +
        rows.join('') +
        '</tbody></table>'
      : '<p>No annual history available.</p>';
    $('#financialSource').innerHTML =
      (f.source ? esc(f.source) + '. ' : '') +
      'Fiscal period end is not the filing publication date. These snapshots are not point-in-time historical data.' +
      (f.source_url && f.source_url.startsWith('https://finance.yahoo.com/quote/')
        ? ' <a href="' +
          esc(f.source_url) +
          '" target="_blank" rel="noopener noreferrer">View provider financial statements ↗</a>'
        : '');
  } catch (e) {
    if (token === financialRequest) $('#financialStatus').textContent = e.message;
  }
}
$('#refreshFinancials').onclick = async () => {
  if (!explorerSymbol) return;
  const button = $('#refreshFinancials');
  button.disabled = true;
  try {
    const r = await api('fundamentals', { symbol: explorerSymbol });
    $('#financialStatus').textContent = r.queued
      ? 'Financial refresh queued. Results appear automatically.'
      : r.message;
  } catch (e) {
    $('#financialStatus').textContent = e.message;
  } finally {
    button.disabled = false;
  }
};

const annualLabels = {
  revenue: 'Revenue',
  operating_margin: 'Operating margin',
  net_margin: 'Net margin',
  free_cash_flow: 'Free cash flow',
  operating_cash_flow: 'Operating cash flow',
  debt: 'Debt',
  cash: 'Cash',
  net_cash: 'Cash minus debt',
  ordinary_shares: 'Year-end shares',
  diluted_shares: 'Diluted average shares',
  revenue_growth: 'Revenue growth',
  fcf_margin: 'Free cash flow margin',
  debt_to_equity: 'Debt / equity',
  annual_pe_proxy: 'Annual P/E proxy',
};
function annualChart(rows, label) {
  if (!rows || rows.length < 2)
    return '<p>At least two comparable annual observations required.</p>';
  const amount = rows[0].unit === 'amount';
  if (amount && (!rows[0].currency || rows.some((r) => r.currency !== rows[0].currency)))
    return '<p>Currency changes or unknown currency prevent a comparable amount chart. See reported annual values.</p>';
  const W = 480,
    H = 185,
    L = 65,
    R = 15,
    T = 20,
    B = 145,
    values = rows.map((r) => r.value),
    lo = Math.min(0, ...values),
    hi = Math.max(0, ...values),
    span = hi - lo || 1,
    times = rows.map((r) => Date.parse(r.period + 'T00:00:00Z')),
    x = (i) =>
      L + ((times[i] - times[0]) / (times[times.length - 1] - times[0] || 1)) * (W - L - R),
    y = (v) => T + ((hi - v) / span) * (B - T),
    scale = Math.max(...values.map(Math.abs)),
    format = (v) =>
      Math.abs(scale) >= 1e9
        ? (v / 1e9).toFixed(1) + 'B'
        : Math.abs(scale) >= 1e6
        ? (v / 1e6).toFixed(1) + 'M'
        : Math.abs(scale) >= 1e3
        ? (v / 1e3).toFixed(1) + 'k'
        : v.toFixed(1);
  let path = '';
  for (let i = 0; i < rows.length; i++) {
    const gap = i > 0 && (times[i] - times[i - 1]) / 86400000 > 430;
    path += (i && !gap ? ' L' : ' M') + x(i).toFixed(2) + ',' + y(rows[i].value).toFixed(2);
  }
  return (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ' +
    W +
    ' ' +
    H +
    '" role="img" aria-label="' +
    esc(label) +
    ' annual history"><title>' +
    esc(label) +
    ' · ' +
    esc(rows[0].currency || rows[0].unit) +
    '</title>' +
    [lo, (lo + hi) / 2, hi]
      .map(
        (v) =>
          '<line x1="' +
          L +
          '" x2="' +
          (W - R) +
          '" y1="' +
          y(v) +
          '" y2="' +
          y(v) +
          '" stroke="#dce4d7"/><text x="' +
          (L - 8) +
          '" y="' +
          (y(v) + 4) +
          '" text-anchor="end">' +
          format(v) +
          (rows[0].unit === 'percent' ? '%' : '') +
          '</text>'
      )
      .join('') +
    '<path d="' +
    path +
    '" fill="none" stroke="#287858" stroke-width="2.5"/>' +
    rows
      .map(
        (r, i) =>
          '<circle cx="' +
          x(i) +
          '" cy="' +
          y(r.value) +
          '" r="4" fill="#287858"><title>' +
          esc(
            r.period +
              ': ' +
              r.value +
              ' ' +
              (r.currency || r.unit) +
              (r.derived ? ' (derived)' : '')
          ) +
          '</title></circle><text x="' +
          x(i) +
          '" y="172" text-anchor="' +
          (i === 0 ? 'start' : i === rows.length - 1 ? 'end' : 'middle') +
          '">' +
          esc(r.period.slice(0, 4)) +
          '</text>'
      )
      .join('') +
    '</svg>'
  );
}
function renderFinancialTrends(v) {
  const annual = v.annual_series || {},
    keys = [
      'revenue',
      'operating_margin',
      'free_cash_flow',
      'operating_cash_flow',
      'debt',
      'cash',
      annual.ordinary_shares ? 'ordinary_shares' : 'diluted_shares',
    ];
  $('#financialTrendStatus').textContent =
    (v.trends || [])
      .filter((t) => t.cagr_pct != null)
      .map(
        (t) =>
          t.label + ' CAGR ' + toolNumber(t.cagr_pct, '%') + ' (' + t.from + ' to ' + t.to + ').'
      )
      .join(' ') +
    ' Annual figures are not point-in-time filing records; gaps and currency changes remain visible.';
  $('#financialTrendCharts').innerHTML = keys
    .map((key) => {
      const rows = annual[key] || [];
      return (
        '<article><h4>' +
        esc(annualLabels[key] || key) +
        '</h4><small>' +
        esc(
          rows.length
            ? (rows[0].currency || rows[0].unit) + ' · fiscal periods'
            : 'No annual coverage'
        ) +
        '</small>' +
        annualChart(rows, annualLabels[key] || key) +
        '<details><summary>Annual values &amp; basis</summary>' +
        toolTable(
          ['Fiscal period', 'Value', 'Basis'],
          rows.map((r) => [
            esc(r.period),
            esc(toolNumber(r.value, ' ' + (r.currency || r.unit), 2)),
            r.derived ? 'Derived from same-period fields' : 'Provider annual observation',
          ])
        ) +
        '</details></article>'
      );
    })
    .join('');
  const peers = v.peer_comparison || {};
  $('#financialPeers').innerHTML = (peers.metrics || []).length
    ? toolTable(
        [
          'Metric',
          'Fiscal period',
          'Company',
          'Sector median',
          'Other issuers',
          'Magnitude percentile',
        ],
        peers.metrics.map((r) => [
          esc(annualLabels[r.metric] || r.metric),
          esc(r.period),
          esc(toolNumber(r.subject, r.unit === 'percent' ? '%' : '×', 2)),
          esc(toolNumber(r.median, r.unit === 'percent' ? '%' : '×', 2)),
          String(r.peer_count),
          esc(toolNumber(r.percentile, '%', 0)),
        ])
      )
    : '<p>No comparable same-sector, same-period annual peer sample.</p>';
  $('#financialPeerMethod').textContent =
    (peers.sector ? 'Sector: ' + peers.sector + '. ' : '') +
    (peers.method || 'Refresh company financials to load annual trend and peer comparisons.');
}
