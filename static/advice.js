/* Research ranking and screen controls. Explorer and financial views are separate. */
let researchView = null,
  researchSettingsLoaded = false,
  chartRanges = {},
  askingModel = false;
const timeLabel = (t) => (t ? new Date(t * 1000).toLocaleString() : 'not yet');
function chart(card, range = '1Y') {
  const days = { '1M': 31, '3M': 93, '1Y': 370 }[range];
  const points = (card.history || []).filter((p) => p.time >= Date.now() / 1000 - days * 86400);
  if (points.length < 2)
    return '<p class="muted">Chart unavailable — run analysis to download daily history.</p>';
  const W = 500,
    H = 190,
    left = 54,
    right = 15,
    top = 16,
    bottom = 30;
  const values = points.map((p) => p.close),
    min = Math.min(...values),
    max = Math.max(...values),
    pad = (max - min) * 0.08 || 1,
    lo = min - pad,
    hi = max + pad;
  const x = (i) => left + (i / (points.length - 1)) * (W - left - right),
    y = (v) => top + ((hi - v) / (hi - lo)) * (H - top - bottom);
  const d = points
    .map((p, i) => (i ? 'L' : 'M') + x(i).toFixed(2) + ',' + y(p.close).toFixed(2))
    .join(' ');
  let grid = '';
  for (let i = 0; i < 3; i++) {
    const v = lo + ((hi - lo) * i) / 2;
    grid += `<line x1="${left}" y1="${y(v)}" x2="${W - right}" y2="${y(
      v
    )}" stroke="#e0e8dd"/><text x="${left - 5}" y="${y(v) + 4}" text-anchor="end">${v.toFixed(
      1
    )}</text>`;
  }
  return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(
    card.symbol
  )} daily historical prices over ${range}"><title>${esc(
    card.symbol
  )} ${range} historical prices in ${esc(
    card.currency
  )}</title>${grid}<path d="${d}" fill="none" stroke="#287858" stroke-width="2.5"/>${points
    .map(
      (p, i) =>
        `<circle cx="${x(i)}" cy="${y(p.close)}" r="3" fill="transparent"><title>${new Date(
          p.time * 1000
        ).toLocaleDateString()}: ${money(p.close, card.currency)}</title></circle>`
    )
    .join('')}<text x="${left}" y="${H - 5}">${new Date(
    points[0].time * 1000
  ).toLocaleDateString()}</text><text x="${W - right}" y="${H - 5}" text-anchor="end">${new Date(
    points[points.length - 1].time * 1000
  ).toLocaleDateString()}</text></svg><p class="muted">${esc(
    card.history_basis || 'Provider daily close'
  )} · ${esc(card.currency)} · hover points for values</p>`;
}
function renderAdvice() {
  if (!researchView) return;
  const r = researchView.report,
    w = researchView.worker || {},
    s = researchView.settings,
    p = researchView.progress;
  const financialProgress = researchView.fundamentals_progress;
  $('#researchStatus').textContent =
    (w.running ? 'Analysis running. ' : '') +
    (w.running && p && p.started >= w.last_started - 5
      ? `Downloaded ${p.done}/${p.total}; ${p.failed} failures. `
      : '') +
    `Last report: ${r ? timeLabel(r.generated) : 'not yet'}. Next scheduled: ${timeLabel(
      w.next_run
    )}.` +
    (w.error ? ' ' + w.error : '') +
    (financialProgress && financialProgress.running
      ? ` Financial scan: ${financialProgress.done}/${financialProgress.total}.`
      : '');
  if (!researchSettingsLoaded) {
    const f = $('#researchSettings');
    f.elements.universe.value = s.universe.join(', ');
    f.elements.interval_minutes.value = s.interval_minutes;
    f.elements.model.value = s.model;
    f.elements.min_turnover_nok.value = s.min_turnover_nok;
    f.elements.llm_enabled.checked = s.llm_enabled;
    researchSettingsLoaded = true;
  }
  if (!r) {
    $('#adviceCards').innerHTML =
      '<div class="card">Preparing a broad market scan. Progress updates every 15 seconds; larger scans may take several minutes.</div>';
    return;
  }
  const reportOld = Date.now() / 1000 - r.generated > 86400;
  const cards = r.cards.map((c) =>
      reportOld || !c.asof || Date.now() / 1000 - c.asof > 4 * 86400
        ? Object.assign({}, c, {
            action: 'Insufficient data',
            score: null,
            composite: null,
            rank: null,
            analyses: [],
            rank_eligible: false,
            reasons: [
              'Report or quote is stale. Run analysis before using a recommendation.',
            ].concat(c.reasons),
          })
        : c
    ),
    buy = cards.filter((c) => c.rank_eligible),
    sell = cards.filter((c) => c.held && /selling|sell threshold|taking profits/.test(c.action));
  $('#adviceSummary').textContent = `${buy.length} buy candidate${buy.length === 1 ? '' : 's'} · ${
    sell.length
  } holding${sell.length === 1 ? '' : 's'} to review for selling · ${
    cards.filter((c) => c.score !== null).length
  }/${cards.length} stocks analysed`;
  $('#llmStatus').textContent = `${r.model ? r.model + ' · ' : ''}${
    r.llm_status
  }. AI explains selected stocks; the same measured analysis runs on every stock.`;
  const busy = !!researchView.model_busy;
  $('#askButton').disabled = askingModel || busy;
  $('#askButton').textContent = busy && !askingModel ? 'Local AI busy…' : 'Ask local AI';
  $('#commentary').textContent =
    r.commentary ||
    (r.llm_status === 'generating local briefing'
      ? 'Ollama is writing your briefing. The stock rankings and explorer are ready while you wait.'
      : r.llm_status === 'disabled'
      ? 'Enable local AI in Research settings for a written briefing.'
      : 'No AI briefing generated. See its status above.');
  $('#providerErrors').textContent = (r.errors || []).length
    ? `${r.errors.length} refresh error(s). Affected stocks may be excluded.\n` +
      r.errors.slice(0, 8).join('\n') +
      (r.errors.length > 8 ? '\nAdditional failures are included in scan coverage.' : '')
    : '';
  const filter = $('#adviceFilter').value,
    search = $('#stockSearch').value.trim().toLowerCase(),
    by = $('#rankBy').value || 'composite';
  const eligible = cards.filter((c) => c.rank_eligible),
    metric = (c) =>
      by === 'composite'
        ? c.composite == null
          ? c.score
          : c.composite
        : ['return1m', 'volatility63', 'max_drawdown1y'].includes(by)
        ? (c.metrics || {})[by] == null
          ? null
          : (by === 'volatility63' ? -1 : 1) * c.metrics[by]
        : ((c.analyses || []).find((a) => a.name === by) || {}).score;
  const measured = cards.filter((c) => c.score !== null),
    above = measured.filter((c) => c.metrics.close > c.metrics.ma200).length,
    rising = measured.filter((c) => c.metrics.momentum3m > 0).length;
  $('#marketBreadth').innerHTML = [
    ['Analysed', measured.length, cards.length],
    ['Above MA200', above, measured.length],
    ['Positive 3-month return', rising, measured.length],
    ['Pass entry policy', eligible.length, measured.length],
  ]
    .map(
      ([label, n, total]) =>
        '<article><small>' +
        label +
        '</small><strong>' +
        n +
        ' <span>/ ' +
        total +
        '</span></strong><div class="scoretrack"><span style="width:' +
        (total ? (n / total) * 100 : 0) +
        '%"></span></div></article>'
    )
    .join('');
  let filtered = cards.filter((c) =>
    filter === 'held'
      ? c.held
      : filter === 'buy'
      ? c.rank_eligible
      : filter === 'sell'
      ? c.held && /selling|sell threshold|taking profits/.test(c.action)
      : filter === 'top20'
      ? c.rank_eligible && c.rank >= 1 && c.rank <= 20
      : true
  );
  filtered.sort(
    (a, b) =>
      (metric(b) == null ? -Infinity : metric(b)) - (metric(a) == null ? -Infinity : metric(a)) ||
      a.symbol.localeCompare(b.symbol)
  );
  filtered = filtered.filter((c) =>
    (c.symbol + ' ' + (c.name || '')).toLowerCase().includes(search)
  );
  $('#rankingCoverage').textContent = `${filtered.length} shown · ${
    eligible.length
  } pass the entry policy · ${
    cards.filter((c) => c.score === null).length
  } without sufficient data. Top-20 uses the complete buy screen; owned candidates may qualify for additions. Portfolio limits and signal confirmation still apply.`;
  $('#adviceCards').innerHTML = filtered.length
    ? '<div class="tablewrap"><table class="ranktable"><thead><tr><th>Entry rank</th><th>Stock</th><th>Overall</th><th>Trend</th><th>Momentum</th><th>Risk</th><th>Timing</th><th>Liquidity</th><th>Annual quality</th><th>Purchase fee drag*</th><th>Action</th><th></th></tr></thead><tbody>' +
      filtered
        .map(
          (c) =>
            `<tr><td>${c.rank || '—'}</td><td><b>${esc(c.symbol)}</b><small>${esc(c.name || '')} ${
              c.held ? '· Owned' : ''
            }</small></td><td><b>${c.composite == null ? '—' : c.composite.toFixed(1)}</b></td>${[
              'Trend',
              'Momentum',
              'Risk',
              'Timing',
              'Liquidity',
            ]
              .map((name) => {
                const part = (c.analyses || []).find((p) => p.name === name);
                return `<td>${part ? part.score.toFixed(0) : '—'}</td>`;
              })
              .join('')}<td>${esc(
              c.quality ? c.quality.label : 'Awaiting financial data'
            )}</td><td>${
              c.portfolio_fit &&
              c.portfolio_fit.fee_model === 'fixed-buy-79-v1' &&
              c.portfolio_fit.fee_pct != null
                ? c.portfolio_fit.fee_pct.toFixed(2) + '%'
                : '—'
            }<small>79 kr / purchase</small></td><td><span class="signal ${
              c.action === 'Consider buying' ? 'buy' : ''
            }">${esc(c.action)}</span></td><td><button data-inspect="${esc(
              c.symbol
            )}">Explore</button></td></tr>`
        )
        .join('') +
      '</tbody></table></div>'
    : '<div class="card">No stocks match this view. Try All analysed stocks, a different search, or wait for scan completion.</div>';
  // Keep detailed charts stable across background polling and tab changes.
  if (explorerSymbol) {
    const selected = cards.find((c) => c.symbol === explorerSymbol);
    if (selected) {
      renderStockDetail(selected);
      const cached = explorerCache[explorerSymbol];
      if (cached && cached.asof !== selected.asof && !explorerDrag)
        selectStock(explorerSymbol, false);
      else {
        loadFinancials(explorerSymbol);
        if (typeof loadStockAnnouncements === 'function') loadStockAnnouncements(explorerSymbol);
      }
    }
  } else if (filtered.length && filtered[0].score !== null) {
    selectStock(filtered[0].symbol, false);
  }
  const compare = $('#compareStock'),
    previous = compare.value;
  compare.innerHTML =
    '<option value="">No comparison</option><option value="OSEBX.OL">Oslo benchmark · OSEBX GR</option>' +
    cards
      .filter((c) => c.score !== null && c.symbol !== explorerSymbol)
      .map((c) => `<option value="${esc(c.symbol)}">${esc(c.symbol)}</option>`)
      .join('');
  compare.value = previous;
}
async function loadResearch() {
  try {
    researchView = await api('research');
    renderAdvice();
    if (typeof loadQuantityPlan === 'function') loadQuantityPlan();
  } catch (e) {
    $('#researchStatus').textContent = e.message;
  }
}
$('#adviceFilter').onchange = renderAdvice;
$('#adviceCards').onclick = (e) => {
  if (e.target.dataset.inspect) selectStock(e.target.dataset.inspect, true);
};
$('#stockSearch').oninput = renderAdvice;
$('#rankBy').onchange = renderAdvice;
$('#analyze').onclick = async () => {
  try {
    await api('analyze', {});
    $('#researchStatus').textContent = 'Analysis queued; results will appear automatically.';
    setTimeout(loadResearch, 1000);
  } catch (e) {
    $('#researchStatus').textContent = e.message;
  }
};
$('#researchSettings').onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  try {
    await api('settings', {
      universe: f.elements.universe.value
        .split(',')
        .map((s) => s.trim())
        .filter(Boolean),
      interval_minutes: Number(f.elements.interval_minutes.value),
      model: f.elements.model.value,
      min_turnover_nok: Number(f.elements.min_turnover_nok.value),
      llm_enabled: f.elements.llm_enabled.checked,
    });
    $('#settingsMessage').textContent = 'Saved. New analysis queued.';
    await loadResearch();
  } catch (e) {
    $('#settingsMessage').textContent = e.message;
  }
};
$('#askForm').onsubmit = async (e) => {
  e.preventDefault();
  askingModel = true;
  $('#askButton').disabled = true;
  $('#answer').textContent = 'Asking your local model…';
  try {
    const r = await api('ask', { question: $('#question').value });
    $('#answer').textContent = r.answer + '\n\n' + r.model + ' · ' + timeLabel(r.generated);
  } catch (e) {
    $('#answer').textContent = e.message;
  } finally {
    askingModel = false;
    loadResearch();
  }
};
