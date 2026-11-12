/* Stock history cache, chart windows and pointer/keyboard interaction. */
let explorerSymbol = '',
  explorerEvents = {},
  explorerCache = {},
  explorerWindow = { start: 0, end: 1 },
  explorerCompare = '',
  explorerDrag = null,
  explorerLoad = 0;
function currentHistory() {
  return (explorerCache[explorerSymbol] || {}).history || [];
}
function diagnosticTile(label, value, note = '', tone = '') {
  return (
    '<article><small>' +
    esc(label) +
    '</small><strong class="' +
    tone +
    '">' +
    esc(value) +
    '</strong>' +
    (note ? '<small>' + esc(note) + '</small>' : '') +
    '</article>'
  );
}
const metricNumber = (value, suffix = '', digits = 1) =>
  Number.isFinite(value) ? value.toFixed(digits) + suffix : 'Unavailable';
function renderDiagnostics(c) {
  const m = c.metrics || {},
    adx = m.adx14,
    trend = Number.isFinite(adx)
      ? adx >= 25
        ? 'Stronger directional trend'
        : adx < 20
        ? 'Weak directional trend'
        : 'Transitional trend'
      : 'OHLC history required';
  $('#advancedMetrics').innerHTML = [
    diagnosticTile(
      '20-session volatility',
      metricNumber(m.volatility20, '%'),
      'Annualised daily returns'
    ),
    diagnosticTile(
      '63-session volatility',
      metricNumber(m.volatility63, '%'),
      'Annualised daily returns'
    ),
    diagnosticTile(
      'ATR (14)',
      metricNumber(m.atr_pct, '% of close'),
      metricNumber(m.atr14, ' ' + (c.currency || 'NOK')) + ' · daily range'
    ),
    diagnosticTile('ADX (14)', metricNumber(adx), trend),
    diagnosticTile(
      '1-year maximum drawdown',
      metricNumber(m.max_drawdown1y, '%'),
      'Up to 253 closes; peak to trough'
    ),
    diagnosticTile(
      'Historical 95% daily VaR',
      metricNumber(m.var95_loss, '% loss'),
      'Up to 252 daily returns'
    ),
    diagnosticTile(
      'Historical tail loss (95%)',
      metricNumber(m.expected_shortfall95, '% loss'),
      'Worst 5% probability mass'
    ),
    diagnosticTile(
      'Relative volume',
      metricNumber(m.relative_volume20, '×', 2),
      'Latest / preceding 20 sessions'
    ),
    diagnosticTile(
      '63-session trend fit',
      metricNumber(m.trend_r2 == null ? null : m.trend_r2 * 100, '% R²'),
      (m.trend_direction || 'Unavailable') + ' log-price regression'
    ),
    diagnosticTile(
      '20-session efficiency',
      metricNumber(m.efficiency20, '%'),
      'Net move / total absolute moves'
    ),
    diagnosticTile(
      '252-close range position',
      metricNumber(m.range_position, '%'),
      '0% = low; 100% = high'
    ),
    diagnosticTile(
      'Sessions below 1-year peak',
      metricNumber(m.underwater_sessions, '', 0),
      'Recovery to peak: ' + metricNumber(m.recovery_pct, '%')
    ),
  ].join('');
  $('#returnHorizons').innerHTML = [
    ['1 week', 'return1w'],
    ['1 month', 'return1m'],
    ['3 months', 'return3m'],
    ['6 months', 'return6m'],
    ['1 year', 'return1y'],
  ]
    .map(([label, key]) =>
      diagnosticTile(
        label,
        metricNumber(m[key], '%'),
        '',
        m[key] == null ? '' : m[key] >= 0 ? 'positive' : 'negative'
      )
    )
    .join('');
  $('#diagnosticNote').textContent = m.risk_sessions
    ? 'Diagnostics as of ' +
      timeLabel(m.history_end) +
      ' · ' +
      m.risk_sessions +
      ' daily returns in the risk window. Descriptive measurements; they do not change entry scores. ATR/ADX require complete high/low data. Missing values stay unavailable.'
    : 'Run a new analysis to populate the expanded diagnostics. Existing research and charts remain available.';
}
function renderStockDetail(c) {
  renderDiagnostics(c);
  if (typeof loadStockDecision === 'function') loadStockDecision(c.symbol);
  $('#explorer').hidden = false;
  $('#explorerTitle').textContent = (c.name || c.symbol) + ' · ' + c.symbol;
  $('#explorerAction').textContent = c.action;
  $('#componentScores').innerHTML = (c.analyses || [])
    .map(
      (p) =>
        `<article><small>${esc(p.name)} · ${p.weight}% weight</small><strong>${p.score.toFixed(
          0
        )}<small>/100</small></strong><div class="scoretrack"><span style="width:${Math.max(
          0,
          Math.min(100, p.score)
        )}%"></span></div><p>${esc(p.explanation)}</p></article>`
    )
    .join('');
  const fee = c.portfolio_fit;
  $('#stockFeeImpact').textContent =
    fee && fee.fee_model === 'fixed-buy-79-v1' && fee.shares
      ? 'Purchase fee: 79 kr once for ' +
        fee.shares +
        ' shares · ' +
        fee.fee_pct.toFixed(2) +
        '% of stock value. Price needed to recover this purchase fee: ' +
        money(fee.break_even_price, c.currency) +
        ' (+' +
        fee.break_even_gain_pct.toFixed(2) +
        '%). Selling fees are not included.'
      : 'Your purchase fee is 79 kr per order. Open Portfolio fit to calculate its impact for your budget.';
  $('#stockObservations').innerHTML =
    '<ul>' +
    [...c.reasons, ...(c.observations || [])].map((t) => '<li>' + esc(t) + '</li>').join('') +
    '</ul>';
}
async function selectStock(symbol, scroll) {
  explorerSymbol = symbol;
  const token = ++explorerLoad;
  const card =
    researchView &&
    researchView.report &&
    researchView.report.cards.find((c) => c.symbol === symbol);
  if (card) renderStockDetail(card);
  $('#chartPlot').innerHTML = '<p>Loading daily price and volume history…</p>';
  $('#chartTooltip').textContent = '';
  if (typeof loadStockDecision === 'function') loadStockDecision(symbol);
  loadFinancials(symbol);
  if (typeof loadStockAnnouncements === 'function') loadStockAnnouncements(symbol);
  try {
    const quote = await api('history?symbol=' + encodeURIComponent(symbol));
    if (token !== explorerLoad) return;
    explorerCache[symbol] = quote;
    const h = quote.history || [],
      n = h.length,
      days = typeof chartPreferenceDays === 'function' ? chartPreferenceDays() : 370,
      limit = n ? h[n - 1].time - days * 86400 : 0;
    explorerWindow = {
      start: Math.max(
        0,
        h.findIndex((p) => p.time >= limit)
      ),
      end: Math.max(0, n - 1),
    };
    explorerCompare = '';
    $('#compareStock').value = '';
    drawExplorer();
    if (typeof restoreBenchmark === 'function') restoreBenchmark();
    if (scroll && $('#explorer').scrollIntoView)
      $('#explorer').scrollIntoView({ behavior: 'smooth', block: 'start' });
  } catch (e) {
    if (token === explorerLoad) $('#chartPlot').textContent = e.message;
  }
}
function drawExplorer() {
  const quote = explorerCache[explorerSymbol];
  if (!quote) return;
  const history = quote.history || [];
  if (history.length < 2) {
    $('#chartPlot').textContent = 'History unavailable. Refresh the scan and try again.';
    return;
  }
  explorerWindow = ChartKit.windowBounds(history.length, explorerWindow.start, explorerWindow.end);
  const overlays = [];
  if ($('#show20').checked) overlays.push('ema20');
  if ($('#show50').checked) overlays.push('ma50');
  if ($('#show200').checked) overlays.push('ma200');
  if ($('#showBands').checked) overlays.push('upper', 'lower');
  const compare = explorerCompare ? (explorerCache[explorerCompare] || {}).history : null;
  $('#chartPlot').innerHTML = ChartKit.svg(history, {
    ...explorerWindow,
    symbol: explorerSymbol,
    compact: window.innerWidth <= 600,
    type: $('#chartType').value,
    panel: $('#chartPanel').value,
    percent: $('#showPercent').checked,
    log: $('#showLog').checked,
    currency: quote.currency,
    overlays,
    compare,
    events: typeof currentStockEvents === 'function' ? currentStockEvents() : [],
  });
  $('#chartFrom').value = new Date(history[explorerWindow.start].time * 1000)
    .toISOString()
    .slice(0, 10);
  $('#chartTo').value = new Date(history[explorerWindow.end].time * 1000)
    .toISOString()
    .slice(0, 10);
  const visible = history.slice(explorerWindow.start, explorerWindow.end + 1);
  renderWindowStats(visible, compare);
  if (typeof renderEventSources === 'function') renderEventSources();
  $('#chartNavigator').innerHTML = ChartKit.navigator(
    history,
    explorerWindow.start,
    explorerWindow.end
  );
  const position = $('#chartPosition');
  position.max = history.length - visible.length;
  position.value = explorerWindow.start;
  position.disabled = visible.length === history.length;
  const candlesMissing =
    $('#chartType').value === 'candles' &&
    !visible.every(
      (p) =>
        p.open > 0 &&
        p.high >= Math.max(p.open, p.close) &&
        p.low > 0 &&
        p.low <= Math.min(p.open, p.close)
    );
  $('#chartNote').textContent =
    `${quote.history_basis || 'Provider daily close'} · ${quote.currency || 'NOK'} · ${
      visible.length
    } daily observations · quote ${timeLabel(quote.asof)}. ` +
    (candlesMissing ? 'OHLC data incomplete; displaying a price line. ' : '') +
    (explorerCompare
      ? 'Comparison: ' + explorerCompare + '; aligned at the first shared UTC date. '
      : '') +
    'Charts show historical observations, not forecasts.';
}
function renderWindowStats(visible, compare) {
  const v = ChartKit.analytics(visible, compare);
  if (!v) return;
  $('#windowStats').innerHTML = [
    diagnosticTile(
      'Period return',
      metricNumber(v.returnPct, '%'),
      v.observations + ' closes',
      v.returnPct >= 0 ? 'positive' : 'negative'
    ),
    diagnosticTile(
      'Annualised volatility',
      metricNumber(v.volatility, '%'),
      'Daily simple returns'
    ),
    diagnosticTile('Maximum drawdown', metricNumber(v.maxDrawdown, '%'), 'Within selected period'),
    diagnosticTile('95% daily VaR', metricNumber(v.var95, '% loss'), 'Empirical daily percentile'),
    diagnosticTile(
      'Tail loss (95%)',
      metricNumber(v.expectedShortfall95, '% loss'),
      'Mean worst 5% probability mass'
    ),
    diagnosticTile('Sharpe · zero rate', metricNumber(v.sharpe, '', 2), 'Annualised; no costs'),
    diagnosticTile(
      'Best / worst session',
      metricNumber(v.best, '%') + ' / ' + metricNumber(v.worst, '%'),
      'Close-to-close changes'
    ),
    diagnosticTile(
      'Positive sessions',
      metricNumber(v.positivePct, '%'),
      'Flat sessions excluded from positives'
    ),
  ].join('');
  const c = v.comparison;
  $('#comparisonStats').textContent = !compare
    ? 'Choose another company to compare returns, correlation and beta.'
    : !c || c.pairs.length < 2
    ? 'No usable shared dates for this comparison.'
    : explorerCompare +
      ' · ' +
      c.pairs.length +
      ' shared dates · Return difference ' +
      metricNumber(c.excess, ' percentage points') +
      ' · Correlation ' +
      metricNumber(c.correlation, '', 2) +
      ' · Beta ' +
      metricNumber(c.beta, '×', 2) +
      '. Correlation and beta use shared-date intervals, which may span gaps; 20 return intervals required. These describe past co-movement.';
}
function zoomExplorer(factor, anchor = 0.5) {
  const h = currentHistory();
  if (h.length < 2) return;
  const span = explorerWindow.end - explorerWindow.start,
    next = Math.max(5, Math.min(h.length - 1, span * factor)),
    at = explorerWindow.start + span * anchor;
  explorerWindow = ChartKit.windowBounds(h.length, at - next * anchor, at + next * (1 - anchor));
  drawExplorer();
}
function initExplorer() {
  if (window.addEventListener)
    window.addEventListener('resize', () => {
      if (explorerSymbol) drawExplorer();
    });
  $('#showLog').onchange = () => {
    if ($('#showLog').checked) $('#showPercent').checked = false;
    drawExplorer();
  };
  $('#showPercent').onchange = () => {
    if ($('#showPercent').checked) $('#showLog').checked = false;
    drawExplorer();
  };
  $('#chartPosition').oninput = () => {
    const span = explorerWindow.end - explorerWindow.start,
      start = Number($('#chartPosition').value);
    explorerWindow = { start, end: start + span };
    drawExplorer();
  };
  for (const id of ['chartType', 'chartPanel', 'show20', 'show50', 'show200', 'showBands'])
    $('#' + id).onchange = drawExplorer;
  $('#explorerRanges').onclick = (e) => {
    if (!e.target.dataset.days) return;
    const h = currentHistory();
    if (!h.length) return;
    const limit = h[h.length - 1].time - Number(e.target.dataset.days) * 86400;
    let start = h.findIndex((p) => p.time >= limit);
    explorerWindow = { start: Math.max(0, start), end: h.length - 1 };
    drawExplorer();
  };
  $('#zoomIn').onclick = () => zoomExplorer(0.7);
  $('#zoomOut').onclick = () => zoomExplorer(1.4);
  $('#resetChart').onclick = () => {
    const n = currentHistory().length;
    explorerWindow = { start: Math.max(0, n - 252), end: n - 1 };
    drawExplorer();
  };
  const dates = () => {
    const h = currentHistory(),
      a = Date.parse($('#chartFrom').value + 'T00:00:00Z') / 1000,
      b = Date.parse($('#chartTo').value + 'T23:59:59Z') / 1000;
    if (!h.length || !Number.isFinite(a) || !Number.isFinite(b)) return;
    const start = h.findIndex((p) => p.time >= a);
    let end = -1;
    h.forEach((p, i) => {
      if (p.time <= b) end = i;
    });
    if (start < 0 || end <= start) {
      $('#chartTooltip').textContent =
        'Select at least two trading observations, with From before To.';
      return;
    }
    explorerWindow = { start, end };
    drawExplorer();
  };
  $('#chartFrom').onchange = dates;
  $('#chartTo').onchange = dates;
  $('#compareStock').onchange = async () => {
    const symbol = $('#compareStock').value;
    explorerCompare = symbol;
    if (!symbol) {
      drawExplorer();
      return;
    }
    try {
      if (!explorerCache[symbol])
        explorerCache[symbol] = await api('history?symbol=' + encodeURIComponent(symbol));
      drawExplorer();
    } catch (e) {
      $('#chartTooltip').textContent = e.message;
    }
  };
  const plot = $('#chartPlot');
  const anchor = (e) => {
    const r = (plot.querySelector('svg') || plot).getBoundingClientRect(),
      g = ChartKit.layout(window.innerWidth <= 600);
    return Math.max(
      0,
      Math.min(1, (((e.clientX - r.left) / r.width) * g.W - g.L) / (g.W - g.L - g.R))
    );
  };
  plot.addEventListener(
    'wheel',
    (e) => {
      if (!currentHistory().length) return;
      e.preventDefault();
      zoomExplorer(e.deltaY > 0 ? 1.15 : 0.85, anchor(e));
    },
    { passive: false }
  );
  plot.addEventListener('pointerdown', (e) => {
    if (!currentHistory().length) return;
    explorerDrag = { x: e.clientX, start: explorerWindow.start, end: explorerWindow.end };
    plot.setPointerCapture(e.pointerId);
  });
  plot.addEventListener('pointermove', (e) => {
    const h = currentHistory();
    if (!h.length) return;
    if (explorerDrag) {
      const shift = Math.round(
        ((explorerDrag.x - e.clientX) /
          (plot.querySelector('svg') || plot).getBoundingClientRect().width) *
          (explorerDrag.end - explorerDrag.start)
      );
      explorerWindow = ChartKit.windowBounds(
        h.length,
        explorerDrag.start + shift,
        explorerDrag.end + shift
      );
      drawExplorer();
    }
    const ratio = anchor(e),
      index = Math.round(
        explorerWindow.start + ratio * (explorerWindow.end - explorerWindow.start)
      ),
      p = h[index];
    if (!p) return;
    $('#chartTooltip').textContent =
      new Date(p.time * 1000).toLocaleDateString() +
      ' · Close ' +
      money(p.close, (explorerCache[explorerSymbol] || {}).currency || 'NOK') +
      (p.open
        ? ' · Open ' +
          p.open.toFixed(2) +
          ' · High ' +
          p.high.toFixed(2) +
          ' · Low ' +
          p.low.toFixed(2)
        : '') +
      (p.volume != null ? ' · Volume ' + new Intl.NumberFormat('nb-NO').format(p.volume) : '');
    const measured = ChartKit.series(h);
    $('#chartTooltip').textContent +=
      ' · RSI ' +
      metricNumber(measured.rsi[index]) +
      ' · MACD ' +
      metricNumber(measured.macd[index], '', 2) +
      ' · Drawdown ' +
      metricNumber(measured.drawdown[index], '%');
    const cursor = $('#explorerCursor');
    if (cursor) {
      const g = ChartKit.layout(window.innerWidth <= 600),
        x = g.L + ratio * (g.W - g.L - g.R);
      cursor.setAttribute('x1', x);
      cursor.setAttribute('x2', x);
      cursor.setAttribute('visibility', 'visible');
    }
  });
  plot.addEventListener('pointerleave', () => {
    if (!explorerDrag) {
      const cursor = $('#explorerCursor');
      if (cursor) cursor.setAttribute('visibility', 'hidden');
    }
  });
  const finish = () => {
    explorerDrag = null;
  };
  plot.addEventListener('pointerup', finish);
  plot.addEventListener('pointercancel', finish);
  plot.addEventListener('keydown', (e) => {
    if (e.key === '+' || e.key === '=') {
      e.preventDefault();
      zoomExplorer(0.7);
    } else if (e.key === '-') {
      e.preventDefault();
      zoomExplorer(1.4);
    } else if (e.key === 'ArrowLeft' || e.key === 'ArrowRight') {
      e.preventDefault();
      const shift =
        (e.key === 'ArrowLeft' ? -1 : 1) *
        Math.max(1, Math.round((explorerWindow.end - explorerWindow.start) / 10));
      explorerWindow = ChartKit.windowBounds(
        currentHistory().length,
        explorerWindow.start + shift,
        explorerWindow.end + shift
      );
      drawExplorer();
    }
  });
  $('#resetUniverse').onclick = async () => {
    try {
      const settings = {
        ...researchView.settings,
        universe: researchView.default_universe || researchView.settings.universe,
      };
      await api('settings', settings);
      researchSettingsLoaded = false;
      await loadResearch();
      $('#settingsMessage').textContent = 'Broad universe restored. Scan queued.';
    } catch (e) {
      $('#message').textContent = e.message;
    }
  };
}
