// Persist chart appearance only; credentials and portfolio records are never stored here.
const chartPreferenceKey = 'northstar-chart-preferences-v1';
let savedChartPreferences = {};
function chartPreferenceDays() {
  return [31, 93, 186, 370, 740, 100000].includes(savedChartPreferences.days)
    ? savedChartPreferences.days
    : 370;
}
function restoreChartPreferences() {
  try {
    savedChartPreferences =
      JSON.parse(window.localStorage.getItem(chartPreferenceKey) || '{}') || {};
  } catch (e) {
    savedChartPreferences = {};
  }
  if (['line', 'candles'].includes(savedChartPreferences.type))
    $('#chartType').value = savedChartPreferences.type;
  if (
    ['volume', 'rsi', 'macd', 'drawdown', 'volatility', 'relative'].includes(
      savedChartPreferences.panel
    )
  )
    $('#chartPanel').value = savedChartPreferences.panel;
  for (const id of [
    'show20',
    'show50',
    'show200',
    'showBands',
    'showPercent',
    'showLog',
    'showEvents',
  ])
    if (typeof savedChartPreferences[id] === 'boolean')
      $('#' + id).checked = savedChartPreferences[id];
  if ($('#showPercent').checked) $('#showLog').checked = false;
}
function saveChartPreferences() {
  const values = {
    type: $('#chartType').value,
    panel: $('#chartPanel').value,
    days: chartPreferenceDays(),
    benchmark: $('#compareStock').value === 'OSEBX.OL',
  };
  for (const id of [
    'show20',
    'show50',
    'show200',
    'showBands',
    'showPercent',
    'showLog',
    'showEvents',
  ])
    values[id] = !!$('#' + id).checked;
  savedChartPreferences = values;
  try {
    window.localStorage.setItem(chartPreferenceKey, JSON.stringify(values));
  } catch (e) {}
}
async function restoreBenchmark() {
  if (!savedChartPreferences.benchmark || !explorerSymbol) return;
  $('#compareStock').value = 'OSEBX.OL';
  explorerCompare = 'OSEBX.OL';
  try {
    if (!explorerCache['OSEBX.OL'])
      explorerCache['OSEBX.OL'] = await api('history?symbol=OSEBX.OL');
    drawExplorer();
  } catch (e) {
    $('#comparisonStats').textContent = 'Oslo benchmark unavailable: ' + e.message;
  }
}
function currentStockEvents() {
  if (!$('#showEvents').checked) return [];
  return [
    ...((explorerCache[explorerSymbol] || {}).events || []),
    ...(explorerEvents[explorerSymbol] || []),
  ].filter((e) => Number.isFinite(e.time) && sourceLink(e.source_url));
}
function renderEventSources() {
  const events = currentStockEvents()
      .slice()
      .sort((a, b) => a.time - b.time),
    h = currentHistory(),
    windowStart = h[explorerWindow.start],
    windowEnd = h[explorerWindow.end];
  const visible = events
    .filter(
      (e) =>
        (windowStart &&
          windowEnd &&
          e.time >= windowStart.time - 86400 &&
          e.time <= windowEnd.time + 86400) ||
        e.time > Date.now() / 1000
    )
    .slice(-30);
  $('#chartEventSources').innerHTML = visible.length
    ? '<p>D = provider dividend/ex-date · S = provider split · E = issuer-stated earnings/reporting event. Only events on observed chart dates receive markers.</p>' +
      toolTable(
        ['Source date', 'Event', 'Source'],
        visible.map((e) => [
          esc(new Date(e.time * 1000).toISOString().slice(0, 10)),
          esc(e.label),
          '<a href="' +
            esc(sourceLink(e.source_url)) +
            '" target="_blank" rel="noopener noreferrer">' +
            esc(e.source || 'View source') +
            ' ↗</a>',
        ])
      )
    : '<p>No sourced events in this period or upcoming covered notices. Refresh market data and issuer notices for updated coverage.</p>';
}
function downloadResearch(name, text, type) {
  const url = URL.createObjectURL(new Blob([text], { type })),
    link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
$('#exportChartCSV').onclick = () => {
  const h = currentHistory();
  if (h.length)
    downloadResearch(
      explorerSymbol + '-daily-analysis.csv',
      ChartKit.csv(h, explorerWindow),
      'text/csv;charset=utf-8'
    );
};
$('#exportChartSVG').onclick = () => {
  const svg = $('#chartPlot').querySelector('svg');
  if (svg) {
    const copy = svg.cloneNode(true),
      style = document.createElementNS('http://www.w3.org/2000/svg', 'style');
    style.textContent =
      'text{font-family:system-ui,sans-serif;font-size:' +
      (window.innerWidth <= 600 ? 16 : 11) +
      'px;fill:#5c6f63}';
    copy.insertBefore(style, copy.firstChild);
    downloadResearch(explorerSymbol + '-chart.svg', copy.outerHTML, 'image/svg+xml');
  }
};
function initChartTools() {
  restoreChartPreferences();
  for (const id of [
    'chartType',
    'chartPanel',
    'show20',
    'show50',
    'show200',
    'showBands',
    'showPercent',
    'showLog',
    'showEvents',
    'compareStock',
  ])
    $('#' + id).addEventListener('change', () => {
      saveChartPreferences();
      if (id === 'showEvents') drawExplorer();
    });
  $('#explorerRanges').addEventListener('click', (e) => {
    if (e.target.dataset.days) {
      savedChartPreferences.days = Number(e.target.dataset.days);
      saveChartPreferences();
    }
  });
  $('#resetChart').addEventListener('click', () => {
    savedChartPreferences.days = 370;
    saveChartPreferences();
  });
}
