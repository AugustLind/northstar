/* Ledger-derived performance. Never substitutes the current-weight proxy for account history. */
let accountPerformanceRequest = 0;
async function loadAccountPerformance() {
  const token = ++accountPerformanceRequest;
  try {
    const value = await api(
      'account-performance?allow_prior_close=' + ($('#allowPriorClose').checked ? '1' : '0')
    );
    if (token === accountPerformanceRequest) renderAccountPerformance(value);
  } catch (error) {
    if (token === accountPerformanceRequest)
      $('#accountPerformanceStatus').textContent = error.message;
  }
}
function renderAccountPerformance(value) {
  $('#accountPerformanceStatus').textContent =
    'Ledger performance: ' +
    value.status +
    (value.from ? ' · ' + value.from + ' to ' + value.to : '') +
    '. ' +
    (value.coverage || []).join(' ');
  $('#accountOpeningBasis').textContent =
    value.opening_basis || 'A reconciled, verified opening snapshot is required.';
  $('#accountPerformanceMetrics').innerHTML = [
    toolTile(
      'Account investment P&L',
      value.investment_pnl_nok == null ? 'Unavailable' : money(value.investment_pnl_nok),
      'Ending value − opening value − net contributions'
    ),
    toolTile(
      'Ending account value',
      value.ending_value_nok == null ? 'Unavailable' : money(value.ending_value_nok),
      'Historical holdings plus recorded cash'
    ),
    toolTile(
      'Net external contributions',
      value.net_contributions_nok == null ? 'Unavailable' : money(value.net_contributions_nok),
      'Deposits less withdrawals'
    ),
    toolTile(
      'Daily-linked return',
      toolNumber(value.daily_linked_return_pct, '%'),
      'End-of-day cash-flow timing assumption'
    ),
    toolTile(
      'Modified Dietz return',
      toolNumber(value.modified_dietz_pct, '%'),
      'Date-weighted approximation'
    ),
    toolTile(
      'Realised trade P&L',
      value.realized_trade_pnl_nok == null ? 'Unavailable' : money(value.realized_trade_pnl_nok),
      'NOK GAV/book basis; gains may predate this period. Not a tax calculation.'
    ),
    toolTile(
      'Recorded income',
      value.income_nok == null ? 'Unavailable' : money(value.income_nok),
      'Net dividends and interest within the measured period'
    ),
    toolTile(
      'Separately reported fees',
      value.reported_fees_nok == null ? 'Unavailable' : money(value.reported_fees_nok),
      'Informational: already included in net broker cash'
    ),
  ].join('');
  const curve = value.curve || [];
  $('#accountPerformanceChart').innerHTML =
    curve.length > 1 && curve.every((p) => Number.isFinite(p.close) && p.close > 0)
      ? ChartKit.svg(curve, {
          symbol: 'Ledger-derived account return',
          percent: true,
          start: 0,
          end: curve.length - 1,
          panel: 'drawdown',
          compact: window.innerWidth <= 600,
        })
      : '<p>No complete daily-linked return curve. Review coverage and reconciliation above.</p>';
  $('#accountPerformanceValues').innerHTML = curve.length
    ? toolTable(
        ['Date', 'Account value', 'Cash', 'External flow', 'Price basis'],
        curve.map((p) => [
          esc(p.date),
          esc(money(p.value_nok)),
          esc(money(p.cash_nok)),
          esc(money(p.external_cash_nok)),
          p.prior_close_used ? 'Flagged prior close' : 'Exact-date closes',
        ])
      )
    : '<p>Incomplete price or ledger records prevent a complete return calculation.</p>';
  $('#accountPerformanceMethod').textContent = value.method || '';
  $('#accountLaterEvents').textContent = value.excluded_later_events
    ? value.excluded_later_events +
      ' later event(s) excluded because the measurement ends at the last completed, priced day.'
    : '';
}
$('#refreshAccountPerformance').onclick = loadAccountPerformance;
$('#allowPriorClose').onchange = loadAccountPerformance;

function signedMoney(amount) {
  return amount == null ? 'Unavailable' : (amount > 0 ? '+' : '') + money(amount);
}
function signedPercent(amount) {
  return amount == null ? 'Unavailable' : (amount > 0 ? '+' : '') + amount.toFixed(1) + '%';
}
function portfolioPeriodTiles(period, returnBasis) {
  return [
    toolTile(
      'Investment performance',
      signedMoney(period.change_nok) + ' · ' + signedPercent(period.change_pct),
      returnBasis
    ),
    toolTile(
      'Net external cash flow',
      signedMoney(period.net_external_nok),
      'Deposits less withdrawals'
    ),
  ].join('');
}
function holdingMovements(holdings) {
  return holdings?.length
    ? toolTable(
        ['Holding', 'Price change per share in NOK', 'Price change %'],
        holdings.map((row) => [
          esc(row.symbol),
          esc(signedMoney(row.change_nok)),
          signedPercent(row.change_pct),
        ])
      )
    : '';
}

const portfolioPeriodStatus = { today: '', week: '' };
function showPortfolioRefreshFailure(error, refreshErrors = []) {
  const failure = 'Refresh failed. ' + [error.message, ...refreshErrors].join(' ');
  for (const [period, status] of Object.entries(portfolioPeriodStatus)) {
    $('#' + period + 'Status').textContent = status
      ? status + ' Showing last loaded figures. ' + failure
      : failure;
  }
}

function renderToday(value, refreshErrors = []) {
  const today = value.today || {};
  const dateLabel = today.date
    ? (today.live ? 'Session ' : 'Last completed session ') + today.date + ' (Europe/Oslo)'
    : '';
  portfolioPeriodStatus.today = [dateLabel, ...(today.coverage || []), ...refreshErrors]
    .filter(Boolean)
    .join(' · ');
  $('#todayStatus').textContent = portfolioPeriodStatus.today;
  $('#todayMetrics').innerHTML =
    toolTile(
      'Current account value',
      value.current_value_nok == null ? 'Unavailable' : money(value.current_value_nok),
      'Recorded cash and holdings at provider quotes'
    ) + portfolioPeriodTiles(today, 'Return assumes external cash flows occur at day end');
  renderPerformanceChart('today', today);
  $('#todayHoldings').innerHTML = holdingMovements(today.holdings);
}

function renderLast7Days(week = {}, refreshErrors = []) {
  const windowLabel = week.window_start
    ? week.window_start + ' to ' + week.window_end + ' (Europe/Oslo)'
    : '';
  const latest =
    week.date && week.date !== week.window_end ? 'Latest valuation date ' + week.date : '';
  const closures =
    week.curve?.length && week.closed_dates.length
      ? 'Prior closes carried on ' + week.closed_dates.join(', ')
      : '';
  portfolioPeriodStatus.week = [
    windowLabel,
    latest,
    closures,
    ...(week.coverage || []),
    ...refreshErrors,
  ]
    .filter(Boolean)
    .join(' · ');
  $('#weekStatus').textContent = portfolioPeriodStatus.week;
  $('#weekMetrics').innerHTML = portfolioPeriodTiles(
    week,
    'Daily-linked return assumes external cash flows occur at day end'
  );
  renderPerformanceChart('week', week);
  $('#weekHoldings').innerHTML = holdingMovements(week.holdings);
}

function renderPerformanceChart(prefix, period) {
  const chart = $('#' + prefix + 'Chart');
  const curve = period.curve || [];
  chart.hidden = curve.length < 2;
  if (chart.hidden) {
    clearWorkspaceChart(chart, '');
    return;
  }
  plotWorkspaceChart(chart, {
    title:'Investment value',
    detail:'NOK · Excludes net external flows',
    currency:'NOK',
    points:curve.map(point=>({time:chartTime(point.date),value:point.adjusted_value_nok})),
    days:prefix === 'today' ? 2 : 8,
  });
}
