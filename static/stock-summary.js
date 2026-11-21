/* Current policy explanation and shared-budget gates. */
let decisionRequest = 0,
  stockDecisionSymbol = '',
  stockDecisionLoaded = 0;
async function loadStockDecision(symbol) {
  if (stockDecisionSymbol === symbol && Date.now() - stockDecisionLoaded < 15000) return;
  if (stockDecisionSymbol !== symbol) {
    $('#decisionStatus').textContent = 'Checking current signal and portfolio gates…';
    $('#decisionSummary').innerHTML = '';
  }
  stockDecisionSymbol = symbol;
  stockDecisionLoaded = Date.now();
  const token = ++decisionRequest;
  try {
    const v = await api('stock-summary?symbol=' + encodeURIComponent(symbol));
    if (token !== decisionRequest || symbol !== explorerSymbol) return;
    renderStockDecision(v);
  } catch (e) {
    if (token === decisionRequest) {
      stockDecisionLoaded = 0;
      $('#decisionStatus').textContent = e.message;
    }
  }
}
function renderStockDecision(v) {
  const list = (rows) =>
    '<ul>' + (rows || []).map((text) => '<li>' + esc(text) + '</li>').join('') + '</ul>';
  const estimate = v.return_estimate;
  const percent = (value) =>
    Number.isFinite(value) ? `${value > 0 ? '+' : ''}${value.toFixed(1)}%` : '—';
  const estimateTitle = estimate && estimate.validation && estimate.validation.status === 'initial_support'
    ? '3-month return range · initial evidence supports calibration'
    : 'Experimental 3-month return range';
  let estimateCard = `<article><h4>${estimateTitle}</h4><p>No current estimate.</p></article>`;
  if (estimate && estimate.status === 'experimental') {
    estimateCard = `<article><h4>${estimateTitle}</h4><p><strong>${percent(estimate.median_pct)}</strong> median · ${percent(estimate.p10_pct)} to ${percent(estimate.p90_pct)} historical range</p><p>${estimate.sample_count} completed signal outcomes; 63 Oslo sessions.</p></article>`;
  } else if (estimate && estimate.status === 'insufficient_history') {
    estimateCard = `<article><h4>${estimateTitle}</h4><p>Insufficient history: ${estimate.sample_count}/${estimate.minimum_samples} completed signal outcomes.</p></article>`;
  } else if (estimate && estimate.status === 'not_applicable') {
    estimateCard = `<article><h4>${estimateTitle}</h4><p>Not applicable: ${esc(estimate.reason || 'Current entry screen not passed.')}</p></article>`;
  } else if (estimate && estimate.status === 'unavailable') {
    estimateCard = `<article><h4>${estimateTitle}</h4><p>${esc(estimate.reason || 'Adjusted price history unavailable.')}</p></article>`;
  }
  $('#decisionStatus').textContent =
    v.action +
    ' · ' +
    (v.current
      ? v.qualifies
        ? 'Qualifies for the technical entry screen.'
        : 'Does not currently qualify for the technical entry screen.'
      : 'Current research required.') +
    ' · Portfolio quantities checked ' +
    new Date(v.generated * 1000).toLocaleString() +
    '.';
  const p = v.portfolio || {};
  $('#decisionSummary').innerHTML =
    '<article><h4>Why this signal?</h4>' +
    list(v.why) +
    '</article><article><h4>What could invalidate it?</h4>' +
    list(v.invalidation) +
    '</article><article><h4>Main measured risks</h4>' +
    list(v.risks) +
    '</article><article><h4>What fits my portfolio?</h4>' +
    list([
      'Confirmed buy quantity: ' + (p.buy_shares || 0) + ' shares.',
      p.sell_shares == null
        ? 'Sale quantity unavailable / no held position.'
        : 'Sale-review quantity: ' + p.sell_shares + ' shares.',
      p.reason || 'No current plan.',
      ...(p.sale_reasons || []),
    ]) +
    '</article>' + estimateCard;
  const validation = estimate && estimate.validation;
  const samples = (estimate && estimate.samples) || [];
  const sampleRows = samples
    .slice()
    .reverse()
    .map((row) => `<tr><td>${new Date(row.from_day * 86400000).toLocaleDateString()}</td><td>${new Date(row.to_day * 86400000).toLocaleDateString()}</td><td>${percent(row.return_pct)}</td><td>${Number.isFinite(row.score) ? row.score.toFixed(1) : '—'}</td></tr>`)
    .join('');
  const validationText = validation
    ? validation.forecasts
      ? `${validation.forecasts} walk-forward forecasts · ${validation.coverage_pct}% interval coverage (target about 80%) · median forecast MAE ${Number.isFinite(validation.median_forecast_mae_pct) ? validation.median_forecast_mae_pct.toFixed(2) : '—'}% vs ${Number.isFinite(validation.baseline_median_forecast_mae_pct) ? validation.baseline_median_forecast_mae_pct.toFixed(2) : '—'}% baseline. ${validation.status === 'initial_support' ? 'Initial evidence meets both checks; the estimate remains experimental.' : validation.forecasts < 20 ? 'Too few forecasts to support a calibration claim.' : 'The calibration checks are not both met.'}`
      : 'Not enough completed walk-forward forecasts to assess calibration.'
    : 'Walk-forward assessment unavailable.';
  const sourceLink = estimate && estimate.source_url
    ? `<a href="${esc(estimate.source_url)}" target="_blank" rel="noopener noreferrer">Yahoo Finance historical prices</a>`
    : 'Historical price source unavailable.';
  $('#returnEstimateEvidence').innerHTML = estimate
    ? `<p>${esc(estimate.method || '')}</p><p>${esc(validationText)}</p><p>${sourceLink} · ${esc(estimate.history_basis || 'Price history')} · personal fees and tax excluded.</p>${sampleRows ? `<div class="tablewrap"><table><thead><tr><th>Signal month</th><th>Outcome end</th><th>63-session return</th><th>Historical score</th></tr></thead><tbody>${sampleRows}</tbody></table></div>` : '<p>No completed historical outcomes are available.</p>'}`
    : '<p>No historical return estimate is available for this stock.</p>';
  $('#decisionChecks').innerHTML = toolTable(
    ['Entry condition', 'Current result'],
    (v.checks || []).map((r) => [
      esc(r.label),
      r.passes == null ? 'Unavailable / stale' : r.passes ? 'Pass' : 'Does not pass',
    ])
  );
  $('#decisionMethod').textContent = v.method;
}
