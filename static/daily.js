/* Notification permission is requested only by the user's explicit button click. */
let dailyView = null,
  dailyRequest = 0,
  overviewAccountRequest = 0,
  overviewAccountLoaded = false;
async function loadOverviewAccount(refreshErrors = []) {
  const token = ++overviewAccountRequest;
  if (!overviewAccountLoaded)
    $('#overviewAccountStatus').textContent = 'Loading current valuation and ledger performance…';
  try {
    const value = await api('account-performance?allow_prior_close=0');
    if (token !== overviewAccountRequest) return;
    renderToday(value, refreshErrors);
    renderLast7Days(value.last_7_days, refreshErrors);
    renderOverviewChart(value);
    $('#overviewValue').textContent =
      value.current_value_nok == null ? 'Unavailable' : money(value.current_value_nok);
    $('#overviewValueMeta').textContent =
      (value.current_price_basis || 'Provider quote basis') +
      ' · reporting date ' +
      (value.current_date || 'unavailable') +
      (value.current_asof
        ? ' · provider prices as of ' + new Date(value.current_asof * 1000).toLocaleString()
        : '');
    $('#overviewMove').textContent =
      value.today_change_nok == null
        ? 'Unavailable'
        : money(value.today_change_nok) + ' · ' + value.today_change_pct.toFixed(2) + '%';
    $('#overviewMoveMeta').textContent =
      value.today_change_nok == null
        ? 'Today’s movement needs current same-session quotes and prior closes.'
        : 'Held-asset price change · % of prior account value · ' +
          value.today_date +
          ' · cash flows excluded';
    const verified =
      ['available', 'estimated'].includes(value.status) && value.investment_pnl_nok != null;
    $('#overviewPnl').textContent = verified ? money(value.investment_pnl_nok) : 'Unavailable';
    $('#overviewPnlMeta').textContent = verified
      ? value.from + ' to ' + value.to + ' · ledger-derived investment P&L'
      : 'Requires reconciled ledger, comparable valuations and verified opening history.';
    const notices = (value.current_coverage || []).concat(value.coverage || [], refreshErrors);
    $('#overviewAccountStatus').textContent = notices.length
      ? notices.join(' ')
      : 'Current valuation uses provider quotes and recorded holdings/cash. Historical results end at the last completed priced date.';
    overviewAccountLoaded = true;
  } catch (error) {
    if (token === overviewAccountRequest) {
      if (!overviewAccountLoaded) clearWorkspaceChart($('#overviewChart'), 'Account value history unavailable.');
      showPortfolioRefreshFailure(error, refreshErrors);
      $('#overviewValue').textContent = 'Unavailable';
      $('#overviewMove').textContent = 'Unavailable';
      $('#overviewPnl').textContent = 'Unavailable';
      $('#overviewAccountStatus').textContent = [error.message, ...refreshErrors].join(' ');
    }
  }
}
function resetTradingWorkspace() {
  dailyRequest++;
  overviewAccountRequest++;
  overviewAccountLoaded = false;
  dailyView = null;
  selectedCandidate = '';
  useRecordedCandidateCash();
  renderCandidatePlan({});
  resetWorkspaceCharts();
  $('#holdingMarket').hidden = true;
}
function safeDailyLink(url) {
  return typeof officialNoticeUrl === 'function' ? officialNoticeUrl(url) : '';
}
function reviewPresentationFor(review) {
  if (review.kind === 'data') {
    if (review.title === 'Check announcement coverage')
      return {
        category: 'ISSUER COVERAGE WARNING',
        action: 'announcements',
        label: 'Check announcement coverage',
      };
    if (review.title === 'Refresh the market report')
      return {
        category: 'SIGNAL EVIDENCE UNCERTAINTY',
        action: 'research',
        label: 'Review research status',
      };
    if (/^Refresh .* before sizing trades/.test(review.title))
      return {
        category: 'VALUATION DATA WARNING',
        action: 'freshness',
        label: 'Refresh market data',
      };
    return { category: 'DATA WARNING', action: 'freshness', label: 'Refresh market data' };
  }
  const presentation = {
    holding: {
      category: review.review_type || 'technical sell review',
      action: 'holding',
      label: 'Review holding',
    },
    company: {
      category: 'annual accounting evidence',
      action: 'stock',
      label: 'Review annual evidence',
    },
    ledger: {
      category: 'ledger / reconciliation blocker',
      action: 'ledger',
      label: 'Open reconciliation',
    },
    announcement: { category: 'issuer notice', action: 'stock', label: 'Review company' },
    calendar: { category: 'issuer date', action: 'stock', label: 'Review company' },
    purchase: { category: 'purchase plan review', action: 'stock', label: 'Review company' },
    change: { category: 'changed or withdrawn evidence', action: 'stock', label: 'Review company' },
  }[review.kind] || { category: 'review', action: 'stock', label: 'Review company' };
  return { ...presentation, category: presentation.category.toUpperCase() };
}
function renderEmailStatus(v) {
  if (!v) return;
  if (dailyView) dailyView.email = v;
  $('#emailStatus').textContent =
    (!v.configured
      ? 'Email is not configured on the server. ' +
        (v.configuration_errors || []).join(' ') +
        ' Run python3 scripts/setup-email.py on the server, then restart Northstar.'
      : v.server_enabled === false
      ? 'Email delivery is disabled in the server settings.'
      : !v.enabled
      ? 'Email alerts are paused.'
      : 'Email alerts are enabled and work with this page closed. ' +
        v.pending +
        ' update(s) waiting.') +
    (v.last_sent
      ? ' Last accepted by the mail server: ' + new Date(v.last_sent * 1000).toLocaleString() + '.'
      : '') +
    (v.error ? ' ' + v.error : '');
  $('#enableEmail').disabled = !v.configured || v.server_enabled === false || v.enabled;
  $('#pauseEmail').disabled = !v.enabled;
  $('#testEmail').disabled = !v.active;
}
function renderDaily(v) {
  dailyView = v;
  if (typeof renderHoldingAssessments === 'function')
    renderHoldingAssessments(v.holding_assessments);
  if (activeCandidateCash == null) renderCandidatePlan(v);
  else if (!$('#candidates').hidden) previewCandidateCash();
  $('#dailyStatus').textContent =
    'Updated ' +
    new Date(v.generated * 1000).toLocaleString() +
    ' · ' +
    (v.coverage.analysed || 0) +
    ' / ' +
    (v.coverage.requested || 0) +
    ' stocks analysed · Announcement feed ' +
    v.announcement_status +
    '.';
  const visibleReviews = Array.from(
    new Map(
      v.top3
        .concat(
          v.reviews.filter(
            (r) =>
              r.kind === 'ledger' ||
              /^Refresh .* before sizing trades|^Refresh the market report/.test(r.title)
          )
        )
        .map((r) => [r.id, r])
    ).values()
  );
  $('#dailyTop').innerHTML = visibleReviews.length
    ? visibleReviews
        .map((r, i) => {
          const presentation = reviewPresentationFor(r);
          return (
            '<article class="card"><p class="eyebrow">REVIEW ' +
            (i + 1) +
            ' · ' +
            esc(presentation.category) +
            '</p><h2>' +
            esc(r.title) +
            '</h2><p>' +
            esc(r.detail) +
            '</p>' +
            (safeDailyLink(r.url)
              ? '<a target="_blank" rel="noopener noreferrer" href="' +
                safeDailyLink(r.url) +
                '">Read issuer source ↗</a>'
              : '') +
            (presentation.action === 'stock'
              ? r.symbol
                ? '<button type="button" data-daily-stock="' +
                  esc(r.symbol) +
                  '">' +
                  esc(presentation.label) +
                  '</button>'
                : ''
              : '<button type="button" data-review-action="' +
                presentation.action +
                '"' +
                (presentation.action === 'holding'
                  ? ' data-review-symbol="' + esc(r.symbol) + '"'
                  : '') +
                '>' +
                esc(presentation.label) +
                '</button>') +
            '</article>'
          );
        })
        .join('')
    : '<p>No actionable review is currently generated. This is based on the successfully loaded review rules and available evidence; it is not a recommendation to buy or hold.</p>';
  const blocker =
    v.reviews.find((r) => r.kind === 'ledger') ||
    v.reviews.find(
      (r) =>
        r.kind === 'data' &&
        /^Refresh .* before sizing trades|^Refresh the market report/.test(r.title)
    );
  const blockerAction = !blocker
    ? 'portfolio'
    : blocker.kind === 'ledger'
    ? 'ledger'
    : blocker.title === 'Refresh the market report'
    ? 'research'
    : 'freshness';
  $('#portfolioReviewEntry').innerHTML =
    '<p>' +
    (blocker
      ? 'Resolve the current data or reconciliation blocker before relying on portfolio sizing or account results.'
      : v.reviews.length
      ? 'Review the prioritized items and their linked evidence. Each prompt has a specific evidence type.'
      : 'No actionable reviews are available after a successful load. Check coverage above before relying on this quiet state.') +
    '</p><button type="button" data-review-action="' +
    blockerAction +
    '">' +
    (blockerAction === 'ledger'
      ? 'Fix reconciliation'
      : blockerAction === 'research'
      ? 'Review research status'
      : blockerAction === 'freshness'
      ? 'Refresh market data'
      : 'Review portfolio') +
    '</button>';
  $('#dailyChanges').innerHTML = v.changes.length
    ? '<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Change</th><th>Direction / shares</th></tr></thead><tbody>' +
      v.changes
        .map(
          (r) =>
            '<tr><td>' +
            esc(r.symbol) +
            '</td><td>' +
            esc(r.change) +
            '</td><td>' +
            esc(r.direction) +
            ' · ' +
            esc(r.shares) +
            '</td></tr>'
        )
        .join('') +
      '</tbody></table></div>'
    : '<p>Changes will appear after the next completed scan. Polling does not count as a new signal observation.</p>';
  $('#dailyAlerts').innerHTML =
    v.alerts
      .slice(0, 30)
      .map(
        (a) =>
          '<article class="notice"><b>' +
          esc(a.title) +
          '</b><p>' +
          esc(a.detail) +
          '</p><small>' +
          new Date(a.first_seen * 1000).toLocaleString() +
          ' · ' +
          (a.read ? 'Read' : 'Unread') +
          '</small></article>'
      )
      .join('') || '<p>No retained alerts.</p>';
  $('#dailyMethod').textContent = v.method;
  renderEmailStatus(v.email);
  let enabled = false;
  try {
    enabled = sessionStorage.getItem('northstar-notifications') === 'on';
  } catch (e) {}
  $('#notificationStatus').textContent = enabled
    ? 'Desktop notifications enabled for this tab. Keep it open for updates.'
    : 'Dashboard alerts are active. Desktop notifications are optional and require this tab to stay open.';
  if (enabled && typeof Notification !== 'undefined' && Notification.permission === 'granted') {
    let seen = [];
    try {
      seen = JSON.parse(sessionStorage.getItem('northstar-notified') || '[]');
    } catch (e) {}
    const fresh = v.alerts.filter(
      (a) => !a.read && !seen.includes(a.id) && Date.now() / 1000 - a.first_seen < 86400
    );
    for (const a of fresh.slice(0, 3))
      new Notification('Northstar review', { body: a.title, tag: 'northstar-' + a.id });
    try {
      sessionStorage.setItem(
        'northstar-notified',
        JSON.stringify(Array.from(new Set(seen.concat(v.alerts.map((a) => a.id)))).slice(-300))
      );
    } catch (e) {}
  }
}
let selectedCandidate = '';
let activeCandidateCash = null;
let cashPreviewRequest = 0;

function renderCandidatePlan(value) {
  renderBuyCandidates(value);
  renderFundedSwitch(value.funded_switch);
  $('#switchComparison').hidden = false;
  $('#buyCandidates').removeAttribute('aria-busy');
}

async function previewCandidateCash() {
  const token = ++cashPreviewRequest;
  $('#switchComparison').hidden = true;
  $('#switchStatus').textContent = 'Calculating comparison…';
  $('#buyCandidates').setAttribute('aria-busy', 'true');
  $('#buyCandidatesStatus').textContent = 'Updating ranked quantities…';
  $('#candidateCashBasis').textContent = 'Calculating with ' + money(activeCandidateCash) + ' of available cash…';
  try {
    const plan = await api('candidate-plan', {cash_nok:activeCandidateCash});
    if (token !== cashPreviewRequest) return;
    renderCandidatePlan(plan);
    $('#candidateCashBasis').textContent = 'Using ' + money(activeCandidateCash) + ' of available cash for this preview.';
  } catch (error) {
    if (token !== cashPreviewRequest) return;
    renderCandidatePlan({});
    $('#candidateCashBasis').textContent = 'Cash preview unavailable. ' + error.message;
  }
}

function useRecordedCandidateCash() {
  cashPreviewRequest++;
  activeCandidateCash = null;
  $('#candidateCashForm').reset();
  $('#candidateCashReset').hidden = true;
  $('#candidateCashBasis').textContent = 'Using recorded cash. Enter an amount to preview with different cash.';
}
$('#candidateCashReset').onclick = () => {
  useRecordedCandidateCash();
  if (dailyView) renderCandidatePlan(dailyView);
  else loadDaily();
};

$('#candidateCashForm').onsubmit = event => {
  event.preventDefault();
  const cash = $('#candidateCash').valueAsNumber;
  if (!Number.isFinite(cash) || cash < 0 || cash > 1e9) return;
  activeCandidateCash = cash;
  $('#candidateCashReset').hidden = false;
  previewCandidateCash();
};

function renderBuyCandidates(v) {
  const status = $('#buyCandidatesStatus'),
    list = $('#buyCandidates'),
    recovery = $('#buyCandidatesRecovery');
  const candidates = Array.isArray(v.buy_candidates) ? v.buy_candidates.slice(0, 5) : [];
  const market = $('#candidateMarket');
  const previousFocus = document.activeElement?.dataset?.candidateStock;
  list.innerHTML = '';
  recovery.hidden = true;
  if (v.buy_candidates_stale) {
    status.textContent =
      'Research is stale or unavailable. Current signals are required before showing buying candidates.';
    recovery.textContent = 'Refresh research';
    recovery.dataset.action = 'refresh';
    recovery.hidden = false;
  } else if (candidates.length) {
    status.textContent =
      candidates.length +
      ' eligible candidate' +
      (candidates.length === 1 ? '' : 's') +
      ' from your current portfolio and trade plan.';
    if (!candidates.some(c => c.symbol === selectedCandidate)) selectedCandidate = candidates[0].symbol;
    list.innerHTML = candidates
      .map(
        (c) =>

          '<article><button type="button" data-candidate-stock="' + esc(c.symbol) +
          '" aria-pressed="' + (c.symbol === selectedCandidate) + '"><span class="candidate-rank" aria-label="Rank ' +
          esc(c.rank) + '">' + esc(c.rank) + '</span><strong>' + esc(c.name) +
          '</strong><small>' + esc(c.symbol) + '</small></button><p>' + esc(c.portfolio_reason) +
          '</p><small>' + esc(c.buy_shares) + ' shares · ' + money(c.total_nok) + ' including estimated fee</small></article>'
      )
      .join('');
  } else if (v.buy_candidate_research_incomplete) {
    status.textContent = 'Buying candidates unavailable. Some companies lack usable research evidence.';
    recovery.textContent = 'Refresh research';
    recovery.dataset.action = 'refresh';
    recovery.hidden = false;
  } else {
    const warnings = Array.isArray(v.buy_candidate_warnings) ? v.buy_candidate_warnings : [];
    status.textContent = warnings.length
      ? 'Buying candidates unavailable with the current portfolio inputs. ' + warnings[0]
      : 'No eligible buying candidates under the current portfolio settings.';
    recovery.textContent = warnings.length ? 'Review portfolio inputs' : 'Explore Research';
    recovery.dataset.action = warnings.length ? 'portfolio' : 'research';
    recovery.hidden = false;
  }
  if (v.buy_candidates_stale || !candidates.length) selectedCandidate = '';
  if (previousFocus) {
    [...list.querySelectorAll('button')].find(button => button.dataset.candidateStock === previousFocus)?.focus();
  }
  if (!$('#candidates').hidden) showWorkspaceStock(market, selectedCandidate);
}
function renderFundedSwitch(comparison) {
  const status = $('#switchStatus'),
    container = $('#switchComparison');
  container.innerHTML = '';
  if (!comparison || comparison.status === 'unavailable') {
    status.textContent =
      'Comparison unavailable.' + (comparison?.reason ? ' ' + comparison.reason : '');
    return;
  }
  if (comparison.status === 'none') {
    status.textContent = 'No switch qualifies.';
    return;
  }
  status.textContent =
    'This ranked purchase uses proceeds from an existing sell review. Amounts are estimates before tax.';
  const pct = (value) => value.toFixed(1) + '%';
  const weightRows = (rows, label) =>
    rows.map((r) => [r.name + ' ' + label, pct(r.keep_pct), pct(r.switch_pct)]);
  const rows = [
    [comparison.sell_symbol + ' shares sold', 0, comparison.sell_shares],
    [comparison.buy_symbol + ' shares bought', 0, comparison.buy_shares],
    ['Sale fee', money(0), money(comparison.sell_fee_nok)],
    ['Purchase fee', money(0), money(comparison.buy_fee_nok)],
    ['Cash after trades', money(comparison.keep_cash_nok), money(comparison.switch_cash_nok)],
    ...weightRows(comparison.companies, 'company weight'),
    ...weightRows(comparison.sectors, 'sector weight'),
  ];
  container.innerHTML =
    '<table aria-labelledby="switchTitle"><thead><tr><th scope="col">Measure</th><th scope="col">Keep</th><th scope="col">Switch</th></tr></thead><tbody>' +
    rows
      .map(([label, keep, change]) =>
        `<tr><th scope="row">${esc(label)}</th><td>${esc(keep)}</td><td>${esc(change)}</td></tr>`
      )
      .join('') +
    '</tbody></table>';
}
async function loadDaily() {
  const token = ++dailyRequest;
  if (!$('#daily').hidden || !$('#portfolio').hidden) loadOverviewAccount();
  try {
    const v = await api('daily');
    if (token === dailyRequest) renderDaily(v);
  } catch (e) {
    if (token === dailyRequest) {
      if (typeof updateHoldingAdvice === 'function') updateHoldingAdvice([]);
      $('#dailyStatus').textContent = 'Reviews unavailable: ' + e.message;
      $('#dailyTop').textContent =
        'Review data is unavailable. Check the connection and try again.';
      $('#portfolioReviewEntry').textContent =
        'Needs attention is unavailable until the review request succeeds.';
      renderFundedSwitch();
      $('#buyCandidates').innerHTML = '';
      showWorkspaceStock($('#candidateMarket'), '');
      $('#buyCandidatesStatus').textContent = 'Buying candidates could not be loaded. ' + e.message;
      $('#buyCandidatesRecovery').textContent = 'Retry';
      $('#buyCandidatesRecovery').dataset.action = 'retry';
      $('#buyCandidatesRecovery').hidden = false;
    }
  }
}
$('#refreshDaily').onclick = loadDaily;
async function refreshAccountMarketData(button, status, showFailure) {
  const label = button.textContent;
  button.disabled = true;
  button.textContent = 'Refreshing market data…';
  try {
    const result = await api('refresh', {});
    await Promise.all([loadOverviewAccount(result.errors || []), refreshWorkspaceStockCharts()]);
  } catch (error) {
    if (showFailure) showFailure(error);
    else status.textContent = error.message;
  } finally {
    button.disabled = false;
    button.textContent = label;
  }
}
$('#refreshOverviewAccount').onclick = (event) =>
  refreshAccountMarketData(event.currentTarget, $('#overviewAccountStatus'));
$('#refreshToday').onclick = (event) =>
  refreshAccountMarketData(event.currentTarget, $('#todayStatus'), showPortfolioRefreshFailure);
$('#openAccountPerformance').onclick = () => {
  openWorkspace('accountPerformance');
};
$('#openAccountSetup').onclick = () => openWorkspace('activity');
$('#markAlertsRead').onclick = async () => {
  if (!dailyView) return;
  try {
    await api('alerts/read', { ids: dailyView.alerts.map((a) => a.id) });
    await loadDaily();
  } catch (e) {
    $('#dailyStatus').textContent = e.message;
  }
};
$('#enableNotifications').onclick = async () => {
  if (typeof Notification === 'undefined') {
    $('#notificationStatus').textContent = 'This browser does not support desktop notifications.';
    return;
  }
  try {
    const permission = await Notification.requestPermission();
    if (permission === 'granted') {
      sessionStorage.setItem('northstar-notifications', 'on');
      await loadDaily();
    } else
      $('#notificationStatus').textContent =
        'Permission was not granted; dashboard alerts remain available.';
  } catch (e) {
    $('#notificationStatus').textContent = e.message;
  }
};
$('#disableNotifications').onclick = () => {
  try {
    sessionStorage.removeItem('northstar-notifications');
  } catch (e) {}
  $('#notificationStatus').textContent =
    'Desktop notifications disabled. Dashboard alerts remain active.';
};
async function emailSetting(enabled) {
  try {
    const v = await api('email/settings', { enabled });
    renderEmailStatus(v);
    $('#emailActionMessage').textContent = enabled
      ? 'Email alerts enabled.'
      : 'Email alerts paused. A message already being sent may still arrive.';
  } catch (e) {
    $('#emailActionMessage').textContent = e.message;
  }
}
$('#enableEmail').onclick = () => emailSetting(true);
$('#pauseEmail').onclick = () => emailSetting(false);
$('#testEmail').onclick = async () => {
  const b = $('#testEmail');
  b.disabled = true;
  try {
    const r = await api('email/test', {});
    $('#emailActionMessage').textContent = r.message;
  } catch (e) {
    $('#emailActionMessage').textContent = e.message;
  } finally {
    if (dailyView && dailyView.email) renderEmailStatus(dailyView.email);
  }
};
function openReviewAction(action, symbol) {
  if (action === 'ledger') openWorkspace('activity');
  else if (action === 'announcements') openWorkspace('announcements');
  else if (action === 'freshness') {
    openWorkspace('portfolio');
    $('#refresh').click();
  } else if (action === 'holding') {
    openWorkspace('portfolio');
    const target = Array.from(document.querySelectorAll('[data-assessment-symbol]')).find(
      (node) => node.dataset.assessmentSymbol === symbol
    );
    if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
  } else if (action === 'research') openWorkspace('recommendations');
  else openWorkspace('portfolio');
}
$('#dailyTop').onclick = (e) => {
  const action = e.target.dataset.reviewAction;
  if (action) {
    openReviewAction(action, e.target.dataset.reviewSymbol || '');
    return;
  }
  const symbol = e.target.dataset.dailyStock;
  if (!symbol) return;
  openWorkspace('recommendations');
  if (typeof selectStock === 'function') selectStock(symbol, true);
};
$('#portfolioReviewEntry').onclick = (e) => {
  const action = e.target.dataset.reviewAction;
  if (action) openReviewAction(action, e.target.dataset.reviewSymbol || '');
};
$('#buyCandidates').onclick = event => {
  const button = event.target.closest('[data-candidate-stock]');
  if (!button) return;
  selectedCandidate = button.dataset.candidateStock;
  for (const other of $('#buyCandidates').querySelectorAll('button')) {
    other.setAttribute('aria-pressed', other === button);
  }
  showWorkspaceStock($('#candidateMarket'), selectedCandidate);
};
$('#candidateResearch').onclick = () => {
  openWorkspace('recommendations');
  if (selectedCandidate) selectStock(selectedCandidate, true);
};
$('#buyCandidatesRecovery').onclick = async (e) => {
  const button = e.currentTarget,
    action = button.dataset.action;
  if (action === 'retry') {
    await loadDaily();
    return;
  }
  if (action === 'portfolio') {
    openWorkspace('fit');
    return;
  }
  if (action === 'research') {
    openWorkspace('recommendations');
    return;
  }
  button.disabled = true;
  try {
    await api('analyze', {});
    $('#buyCandidatesStatus').textContent =
      'Research refresh queued. Candidates will update when the scan completes.';
  } catch (error) {
    $('#buyCandidatesStatus').textContent = error.message;
  } finally {
    button.disabled = false;
  }
};
setInterval(() => {
  if (apiBase && accessKey) loadDaily();
}, 60000);
