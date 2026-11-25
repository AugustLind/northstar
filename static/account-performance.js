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


let portfolioAccountRequest = 0;
let portfolioAccountLoaded = false;
let todayHoldingMoves = new Map();

function signedMove(nok, percent) {
  if (nok == null) return 'Unavailable';
  const amount = (nok > 0 ? '+' : '') + money(nok);
  return percent == null
    ? amount
    : amount + ' (' + (percent > 0 ? '+' : '') + percent.toFixed(1) + '%)';
}

function renderTodayHoldingMoves() {
  for (const cell of document.querySelectorAll('[data-today-holding]')) {
    const move = todayHoldingMoves.get(cell.dataset.todayHolding);
    cell.firstElementChild.textContent = move
      ? signedMove(move.change_nok, move.change_pct)
      : 'Unavailable';
    cell.lastElementChild.textContent = move ? move.date : '';
  }
}

function renderTodayPerformance(value) {
  const date = value.today_date;
  const label = date === value.current_date ? 'Today’s performance' : 'Last completed session';
  $('#todayChartTitle').textContent = date ? label + ' · ' + date : 'Today’s performance';
  $('#portfolioMove').textContent = signedMove(value.today_change_nok, value.today_change_pct);
  $('#portfolioMoveMeta').textContent = date
    ? label + ' · ' + date + ' (Europe/Oslo)' +
      (value.today_change_pct != null && value.today_has_external_cash
        ? ' · Percentage assumes end-of-day external cash flows'
        : '')
    : 'Session performance unavailable';
  $('#todayExternalCash').textContent =
    value.today_external_cash_nok == null ? 'Unavailable' : signedMove(value.today_external_cash_nok);
  todayHoldingMoves = new Map((value.today_holdings || []).map((move) => [move.symbol, move]));
  renderTodayHoldingMoves();
  const chart = $('#todayChart');
  if (value.today_change_nok == null) {
    chart.textContent = 'Session chart unavailable. See coverage above.';
    return;
  }
  const opening = value.today_opening_value_nok;
  const adjusted = value.today_ending_value_nok - value.today_external_cash_nok;
  const scale = Math.max(Math.abs(opening), Math.abs(adjusted), 1);
  // A shared zero supports negative account values as well as ordinary positive balances.
  chart.innerHTML = [
    ['Previous close', opening],
    ['Session value less net external cash flow', adjusted],
  ].map(([label, amount]) => {
    const left = amount < 0 ? 50 - Math.abs(amount) / scale * 50 : 50;
    return `<div class="today-chart-row"><span>${label}</span><strong>${esc(money(amount))}</strong>
      <div class="today-chart-track" aria-hidden="true"><span style="left:${left}%;width:${Math.abs(amount) / scale * 50}%"></span></div></div>`;
  }).join('');
}

async function loadPortfolioAccount() {
  const token = ++portfolioAccountRequest;
  if (!portfolioAccountLoaded)
    $('#portfolioAccountStatus').textContent = 'Loading current valuation and ledger performance…';
  try {
    const value = await api('account-performance?allow_prior_close=0');
    if (token !== portfolioAccountRequest) return;
    $('#portfolioValue').textContent =
      value.current_value_nok == null ? 'Unavailable' : money(value.current_value_nok);
    $('#portfolioValueMeta').textContent =
      (value.current_price_basis || 'Provider quote basis') +
      ' · reporting date ' +
      (value.current_date || 'unavailable') +
      (value.current_asof
        ? ' · provider prices as of ' + new Date(value.current_asof * 1000).toLocaleString(undefined, { timeZone: 'Europe/Oslo' }) + ' (Europe/Oslo)'
        : '');
    renderTodayPerformance(value);
    const verified =
      ['available', 'estimated'].includes(value.status) && value.investment_pnl_nok != null;
    $('#portfolioPnl').textContent = verified ? money(value.investment_pnl_nok) : 'Unavailable';
    $('#portfolioPnlMeta').textContent = verified
      ? value.from + ' to ' + value.to + ' · ledger-derived investment P&L'
      : 'Requires reconciled ledger, comparable valuations and verified opening history.';
    const notices = (value.current_coverage || []).concat(value.coverage || []);
    $('#portfolioAccountStatus').textContent = notices.length
      ? notices.join(' ')
      : 'Current valuation uses provider quotes and recorded holdings/cash. Historical results end at the last completed priced date.';
    portfolioAccountLoaded = true;
  } catch (error) {
    if (token === portfolioAccountRequest) {
      $('#portfolioValue').textContent = 'Unavailable';
      renderTodayPerformance({});
      $('#portfolioPnl').textContent = 'Unavailable';
      $('#portfolioAccountStatus').textContent = error.message;
    }
  }
}
$('#refreshPortfolioAccount').onclick = async () => {
  const button = $('#refreshPortfolioAccount');
  button.disabled = true;
  button.textContent = 'Refreshing market data…';
  try {
    const result = await api('refresh', {});
    await loadPortfolioAccount();
    if (result.errors && result.errors.length)
      $('#portfolioAccountStatus').textContent = result.errors.join(' ');
  } catch (error) {
    $('#portfolioAccountStatus').textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = 'Refresh account value';
  }
};
$('#openAccountPerformance').onclick = () => {
  openWorkspace('accountPerformance');
};
$('#openAccountSetup').onclick = () => openWorkspace('activity');
