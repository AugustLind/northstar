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
    '</article>';
  $('#decisionChecks').innerHTML = toolTable(
    ['Entry condition', 'Current result'],
    (v.checks || []).map((r) => [
      esc(r.label),
      r.passes == null ? 'Unavailable / stale' : r.passes ? 'Pass' : 'Does not pass',
    ])
  );
  $('#decisionMethod').textContent = v.method;
}
