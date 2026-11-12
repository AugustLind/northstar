/* Supplementary holdout and execution-cost presentation. */
function performanceTiles(v) {
  return [
    toolTile('Period return', toolNumber(v.return_pct, '%')),
    toolTile(
      'Annual return (CAGR)',
      toolNumber(v.cagr_pct, '%'),
      'At least one calendar year required'
    ),
    toolTile('Annual volatility', toolNumber(v.annual_volatility_pct, '%')),
    toolTile('Sharpe · zero rate', toolNumber(v.sharpe_zero_rate, '', 2)),
    toolTile('Sortino · zero rate', toolNumber(v.sortino_zero_rate, '', 2)),
    toolTile('Maximum drawdown', toolNumber(v.max_drawdown_pct, '%')),
    toolTile('Longest underwater spell', toolNumber(v.longest_underwater_sessions, ' sessions', 0)),
    toolTile('Average invested', toolNumber(v.average_invested_pct, '%')),
  ].join('');
}
function renderValidationDiagnostics(v) {
  $('#validationMetrics').innerHTML =
    performanceTiles(v.performance || {}) +
    toolTile(
      'One-way turnover',
      toolNumber(v.one_way_turnover_pct, '%'),
      'Cumulative half gross traded weight'
    );
  const r = v.robustness;
  $('#robustnessPanel').hidden = !r;
  if (!r) return;
  $('#robustnessStatus').textContent =
    'Selected using training data: ' +
    r.selected +
    '. Holdout starts ' +
    new Date(r.split_date * 1000).toISOString().slice(0, 10) +
    '. Training ' +
    toolNumber(r.training.return_pct, '%') +
    '; later holdout ' +
    toolNumber(r.holdout.return_pct, '%') +
    '.';
  $('#holdoutMetrics').innerHTML = performanceTiles(r.holdout);
  $('#holdoutChart').innerHTML = ChartKit.svg(r.holdout_curve, {
    symbol: 'Chronological holdout wealth',
    start: 0,
    end: r.holdout_curve.length - 1,
    percent: true,
    panel: 'drawdown',
    compact: window.innerWidth <= 600,
  });
  $('#parameterSensitivity').innerHTML = toolTable(
    ['Fixed variant', 'Training return', 'Training Sharpe', 'Holdout return', 'Holdout drawdown'],
    r.variants.map((x) => [
      esc(x.label),
      esc(toolNumber(x.training.return_pct, '%')),
      esc(toolNumber(x.training.sharpe_zero_rate, '', 2)),
      esc(toolNumber(x.holdout.return_pct, '%')),
      esc(toolNumber(x.holdout.max_drawdown_pct, '%')),
    ])
  );
  $('#costSensitivity').innerHTML =
    '<h4>Selected variant with extra slippage</h4>' +
    toolTable(
      ['Slippage each direction', 'Holdout return', 'Holdout drawdown', 'Whole-run costs'],
      r.cost_sensitivity.map((x) => [
        esc(x.cost_bps + ' bps'),
        esc(toolNumber(x.holdout.return_pct, '%')),
        esc(toolNumber(x.holdout.max_drawdown_pct, '%')),
        esc(money(x.total_costs_nok)),
      ])
    );
  $('#robustnessMethod').textContent = r.method;
}
