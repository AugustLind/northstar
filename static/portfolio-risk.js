/* Read-only covariance/scenario presentation. Calculations run on the server. */
let portfolioRiskRequest = 0;
async function loadPortfolioRisk() {
  const token = ++portfolioRiskRequest;
  const stock = Number($('#stockShock').value || -20),
    fx = Number($('#fxShock').value || -10);
  try {
    const v = await api(
      'portfolio-risk?stock_shock=' +
        encodeURIComponent(stock) +
        '&fx_shock=' +
        encodeURIComponent(fx)
    );
    if (token !== portfolioRiskRequest) return;
    renderPortfolioRisk(v);
  } catch (e) {
    if (token === portfolioRiskRequest) $('#portfolioRiskStatus').textContent = e.message;
  }
}
function renderPortfolioRisk(v) {
  $('#portfolioRiskStatus').textContent =
    'Risk model: ' +
    v.status +
    ' · ' +
    v.observations +
    ' shared return intervals' +
    (v.from
      ? ' · ' +
        new Date(v.from * 1000).toISOString().slice(0, 10) +
        ' to ' +
        new Date(v.to * 1000).toISOString().slice(0, 10)
      : '') +
    '. ' +
    (v.missing || []).join(' ');
  const c = v.concentration || {},
    b = v.benchmark || {};
  $('#portfolioRiskMetrics').innerHTML = [
    toolTile(
      'Portfolio volatility',
      toolNumber(v.volatility_pct, '%'),
      'Annualised, current NOK weights'
    ),
    toolTile(
      'Historical 95% daily VaR',
      toolNumber(v.var95_pct, '% loss'),
      'Sample loss percentile'
    ),
    toolTile(
      'Historical tail loss',
      toolNumber(v.tail95_pct, '% loss'),
      'Worst 5% probability mass'
    ),
    toolTile(
      'Proxy maximum drawdown',
      toolNumber(v.proxy_drawdown_pct, '%'),
      'Current weights; not account history'
    ),
    toolTile(
      'Largest company',
      toolNumber(c.largest_company_pct, '%'),
      'Known share classes combined'
    ),
    toolTile(
      'Effective equity companies',
      toolNumber(c.effective_equity_companies, '', 2),
      'Inverse concentration; excludes cash'
    ),
    toolTile('USD asset exposure', toolNumber(c.usd_asset_pct, '%'), 'Current tracked NOK value'),
    toolTile(
      'Beta to Oslo benchmark',
      toolNumber(b.beta, '×', 2),
      (b.observations || 0) + ' matching intervals'
    ),
  ].join('');
  $('#riskContributions').innerHTML = (v.risk_contributions || []).length
    ? toolTable(
        [
          'Holding',
          'Weight incl. cash',
          'Standalone volatility',
          'Share of portfolio variance',
          'Contribution to annual volatility',
        ],
        v.risk_contributions
          .slice()
          .sort((a, b) => (b.risk_share_pct || 0) - (a.risk_share_pct || 0))
          .map((r) => [
            esc(r.symbol),
            esc(toolNumber(r.weight_pct, '%')),
            esc(toolNumber(r.annual_volatility_pct, '%')),
            esc(toolNumber(r.risk_share_pct, '%')),
            esc(toolNumber(r.volatility_contribution_pct, ' percentage points')),
          ])
      )
    : '<p>Risk contributions require complete, aligned historical coverage.</p>';
  const matrix = v.correlations || [];
  $('#correlationNote').textContent =
    (v.matrix_note || '') +
    ' Negative contributions can indicate hedging. Flat series have no defined correlation.';
  $('#correlationMatrix').innerHTML = matrix.length
    ? toolTable(
        ['Holding', ...matrix.map((r) => r.symbol)],
        matrix.map((r) => [
          esc(r.symbol),
          ...r.values.map(
            (value) =>
              '<span class="correlationcell" style="background:' +
              (value == null
                ? '#f1f1ed'
                : value >= 0
                ? 'rgba(40,120,88,' + Math.abs(value) * 0.35 + ')'
                : 'rgba(188,75,73,' + Math.abs(value) * 0.25 + ')') +
              '">' +
              esc(toolNumber(value, '', 2)) +
              '</span>'
          ),
        ])
      )
    : '<p>No comparable full-portfolio sample.</p>';
  $('#portfolioRiskChart').innerHTML =
    (v.curve || []).length > 1
      ? ChartKit.svg(v.curve, {
          symbol: 'Current-weight historical proxy',
          percent: true,
          start: 0,
          end: v.curve.length - 1,
          panel: 'drawdown',
          compact: window.innerWidth <= 600,
        })
      : '<p>No proxy curve available.</p>';
  $('#riskScenarios').innerHTML = (v.scenarios || []).length
    ? toolTable(
        ['Hypothetical assumption', 'NOK change', 'Portfolio change', 'Value after shock'],
        v.scenarios.map((s) => [
          esc(s.label),
          esc(money(s.change_nok)),
          esc(toolNumber(s.change_pct, '%')),
          esc(money(s.after_nok)),
        ])
      )
    : '<p>Complete current valuation is required to calculate shocks.</p>';
  $('#riskMethod').textContent = v.method;
}
$('#refreshPortfolioRisk').onclick = loadPortfolioRisk;
$('#riskScenarioForm').onsubmit = (e) => {
  e.preventDefault();
  loadPortfolioRisk();
};
