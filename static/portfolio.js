/* Holdings notebook, editor and local export. Depends on app.js and ui-common.js. */
const holdingSymbol = ({ symbol, currency }) =>
  currency === 'NOK' && !symbol.includes('.') ? symbol + '.OL' : symbol;
let holdingAdviceBySymbol = new Map();

function holdingQuote(position, quotes) {
  return quotes[holdingSymbol(position)] || quotes[position.symbol];
}

function renderHoldingAdvice(symbol, currency) {
  const advice = holdingAdviceBySymbol.get(symbol);
  if (!advice) return '<b>Insufficient data</b><small>No current holding advice.</small>';
  const price =
    advice.review_price == null
      ? ''
      : '<small>Saved review price: ' + esc(money(advice.review_price, currency)) + '</small>';
  const sizing = advice.shares
    ? '<small>Review ' +
      esc(advice.shares) +
      (advice.shares === 1 ? ' share' : ' shares') +
      ' · ' +
      advice.percent.toFixed(2) +
      '% of holding</small>'
    : advice.sizing_blocker
    ? '<small>Sizing unavailable: ' + esc(advice.sizing_blocker) + '</small>'
    : '';
  return '<b>' + esc(advice.label) + '</b><small>' + esc(advice.reason) + '</small>' + price + sizing;
}

function updateHoldingAdvice(assessments) {
  holdingAdviceBySymbol = new Map(assessments.map((a) => [a.position_symbol, a.advice]));
  for (const cell of document.querySelectorAll('#holdings [data-holding-advice]')) {
    cell.innerHTML = renderHoldingAdvice(cell.dataset.holdingAdvice, cell.dataset.currency);
  }
  if ($('#salePlanner').open) renderSalePlan();
}

function render() {
  const { positions, quotes } = state;
  const alerts = [],
    assessments = [];
  $('#holdings').innerHTML = positions.length
    ? positions
        .map((p) => {
          const q = holdingQuote(p, quotes),
            valid = q && q.currency === p.currency;
          const gain = valid && p.cost > 0 ? (q.price / p.cost - 1) * 100 : null;
          return `<tr><td><button type="button" class="holding-market-link" data-holding-market="${esc(p.symbol)}">${esc(p.symbol)}</button><small>${
            p.shares
              ? p.long_term
                ? 'Long-term holding · keep under review'
                : 'Holding'
              : 'Watchlist'
          } · ${esc(p.currency)}</small></td><td${
            p.shares > 0
              ? ` data-holding-advice="${esc(p.symbol)}" data-currency="${esc(p.currency)}"`
              : ''
          }>${p.shares > 0 ? renderHoldingAdvice(p.symbol, p.currency) : '—'}</td><td>${p.shares}<small>${money(
            p.cost,
            p.currency
          )}</small></td><td>${valid ? money(q.price, p.currency) : 'Unavailable'}<small>${
            valid
              ? fresh(q)
                ? 'Provider quote'
                : 'Stale · excluded from total'
              : 'Refresh or check ticker/currency'
          }</small></td><td class="${signedClass(gain)}">${
            gain === null ? '—' : gain.toFixed(2) + '%'
          }</td><td>${q ? esc(new Date(q.asof * 1000).toLocaleString()) : 'Not fetched'}<small>${
            q ? esc(q.source) : 'No data'
          }</small></td><td><button data-edit="${esc(
            p.symbol
          )}">Edit</button> <button data-delete="${esc(p.symbol)}">Remove</button>${
            p.shares > 0
              ? ` <button data-plan-sale="${esc(p.symbol)}" aria-label="Plan a sale for ${esc(p.symbol)}">Plan a sale</button>`
              : ''
          }</td></tr>`;
        })
        .join('')
    : '<tr><td colspan="7">Your notebook is empty. Add your first holding or watchlist company.</td></tr>';
  for (const p of positions) {
    const q = holdingQuote(p, quotes),
      items = [];
    if (p.shares > 0 && p.long_term)
      items.push(
        'Long-term designation does not remove this holding from review; significant price, concentration and portfolio risks still matter.'
      );
    if (!fresh(q) || q.currency !== p.currency)
      items.push(
        'Current usable data unavailable. Refresh quotes and check the selected trading currency.'
      );
    else {
      if (p.below !== null && q.price <= p.below)
        items.push(
          `Price ${money(q.price, p.currency)} is at or below your review level ${money(
            p.below,
            p.currency
          )}.`
        );
      if (p.above !== null && q.price >= p.above)
        items.push(
          `Price ${money(q.price, p.currency)} is at or above your review level ${money(
            p.above,
            p.currency
          )}.`
        );
      if (q.ma200 && q.price < q.ma200)
        items.push(
          `Price is below its 200-session average (${money(
            q.ma200,
            p.currency
          )}). Review the business case before acting on this trend.`
        );
      const ctx = state.portfolio_context,
        limit = (state.portfolio_preferences || {}).max_stock_pct;
      const h = ctx?.holdings?.find((h) => h.symbol === holdingSymbol(p));
      if (h && h.weight_pct != null && h.weight_pct > limit)
        items.push(
          `Represents ${h.weight_pct.toFixed(
            1
          )}% of tracked holdings plus cash, above your ${limit}% position limit.`
        );
    }
    assessments.push(
      `<article class="card" data-assessment-symbol="${esc(p.symbol)}"><h3>${esc(p.symbol)} · ${
        p.shares > 0 ? 'Holding' : 'Watchlist'
      }</h3>${
        items.length
          ? items.map((t) => `<p>${esc(t)}</p>`).join('')
          : `<p>${
              p.shares > 0
                ? 'No current price or concentration prompts are triggered by the available local rules.'
                : 'No shares are held; this watchlist entry has no holding assessment.'
            }</p>`
      }<p><b>Your thesis:</b> ${esc(
        p.thesis || 'No thesis recorded.'
      )}</p><p><b>Reconsider when:</b> ${esc(
        p.review || 'No conditions recorded.'
      )}</p><p class="muted">Limitations: price and concentration prompts are rule based, may be unavailable when data is stale, and do not assess whether a business is suitable or tell you to trade. Fees and taxes are not included in these prompts.</p><a target="_blank" rel="noopener noreferrer" href="https://finance.yahoo.com/quote/${encodeURIComponent(
        p.symbol
      )}/news/">Research company news ↗</a><p class="muted">External research link; news is not analysed by this app.</p></article>`
    );
    if (items.length) {
      alerts.push(
        `<article class="card"><h2>${esc(p.symbol)}</h2>${items
          .map((t) => `<p>${esc(t)}</p>`)
          .join('')}<p><b>Your thesis:</b> ${esc(
          p.thesis || 'No thesis recorded.'
        )}</p><p><b>Reconsider when:</b> ${esc(
          p.review || 'No conditions recorded.'
        )}</p><a target="_blank" rel="noopener noreferrer" href="https://finance.yahoo.com/quote/${encodeURIComponent(
          p.symbol
        )}/news/">Research company news ↗</a><p class="muted">External research link; news is not analysed by this app.</p></article>`
      );
    }
  }
  $('#alerts').innerHTML =
    alerts.join('') ||
    '<article class="card">No rules triggered. This does not establish that a stock is a good investment. Review company reports and your thesis regularly.</article>';
  $('#holdingAssessments').innerHTML =
    assessments.join('') || '<p>No holdings or watchlist entries are recorded.</p>';
}
function renderHoldingAssessments(assessments) {
  if (!$('#holdingAssessments') || !Array.isArray(assessments)) return;
  updateHoldingAdvice(assessments);
  const bySymbol = new Map(assessments.map((a) => [a.symbol, a]));
  $('#holdingAssessments').innerHTML =
    state.positions
      .map((p) => {
        const symbol = holdingSymbol(p);
        const a = p.shares > 0 ? bySymbol.get(symbol) : null;
        if (!p.shares)
          return `<article class="card"><h3>${esc(
            p.symbol
          )} · Watchlist</h3><p>No shares are held, so there is no holding assessment.</p><p><b>Your thesis:</b> ${esc(
            p.thesis || 'No thesis recorded.'
          )}</p><p><b>Reconsider when:</b> ${esc(
            p.review || 'No conditions recorded.'
          )}</p></article>`;
        const category =
          a && a.sale_review
            ? a.sale_review.technical
              ? 'Technical sell review'
              : 'Portfolio-limit sale scenario'
            : a && a.action === 'Hold / monitor'
            ? 'Existing technical hold assessment'
            : a && a.action
            ? 'Existing technical assessment'
            : 'Assessment unavailable';
        const reasons =
          a && a.reasons.length
            ? '<ul>' + a.reasons.map((reason) => '<li>' + esc(reason) + '</li>').join('') + '</ul>'
            : '<p>No policy reasons are available.</p>';
        const freshness =
          !a || a.status === 'unavailable'
            ? '<p role="status">No matching current assessment was returned. Missing evidence is not a hold verdict.</p>'
            : a.status === 'stale'
            ? '<p role="status">This assessment is based on a stale report and needs fresh evidence before use.</p>'
            : '<p class="muted">Market report assessment · ' +
              esc(
                a.source_asof
                  ? new Date(a.source_asof * 1000).toLocaleString()
                  : 'source timestamp unavailable'
              ) +
              '</p>';
        const sale =
          a && a.sale_review
            ? '<p><b>Scenario:</b> Review ' +
              esc(a.sale_review.shares) +
              ' shares. ' +
              esc(a.sale_review.reasons.join(' ')) +
              '</p><p>' +
              (a.sale_review.fee_nok == null
                ? 'Sale fee unknown; gross estimate only.'
                : 'Entered sale fee: ' + esc(a.sale_review.fee_nok) + ' NOK.') +
              ' Tax is excluded. No trade is placed.</p>'
            : '';
        return `<article class="card" data-assessment-symbol="${esc(symbol)}"><h3>${esc(
          p.symbol
        )} · ${category}</h3>${
          a && a.action
            ? '<p><b>Policy result:</b> ' +
              esc(a.action) +
              (a.status === 'stale' ? ' · stale' : '') +
              '</p>'
            : ''
        }${freshness}${reasons}${sale}<p><b>Your thesis:</b> ${esc(
          p.thesis || 'No thesis recorded.'
        )}</p><p><b>Reconsider when:</b> ${esc(
          p.review || 'No conditions recorded.'
        )}</p><p class="muted">Technical evidence does not establish business value or suitability. A hold label is the existing screen result, not an investment verdict. Fees and taxes are excluded unless a fee is explicitly shown above.</p></article>`;
      })
      .join('') || '<p>No holdings or watchlist entries are recorded.</p>';
}
async function reloadHoldings() {
  updateHoldingAdvice([]);
  await load();
  await loadDaily();
}

async function load(connectedState) {
  state = connectedState ?? await api('state');
  $('#accountStatus').textContent = 'Connected';
  render();
  if ($('#salePlanner').open) renderSalePlan();
}
function edit(
  p = {
    symbol: '',
    currency: 'NOK',
    shares: 0,
    cost: 0,
    below: '',
    above: '',
    thesis: '',
    review: '',
  }
) {
  const f = $('#positionForm');
  f.reset();
  for (const [k, v] of Object.entries(p))
    if (f.elements.namedItem(k)) {
      const input = f.elements.namedItem(k);
      if (input.type === 'checkbox') input.checked = Boolean(v);
      else input.value = v == null ? '' : v;
    }
  f.elements.symbol.readOnly = !!p.symbol;
  $('#formError').textContent = '';
  $('#editor').showModal();
}
$('#add').onclick = () => edit();
$('#close').onclick = () => {
  if (typeof clearWorkspaceUiFormState === 'function') clearWorkspaceUiFormState('positionForm');
  $('#editor').close();
};
$('#editor').addEventListener('close', () => {
  if (typeof clearWorkspaceUiFormState === 'function') clearWorkspaceUiFormState('positionForm');
});
$('#positionForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(e.target));
    data.long_term = e.target.elements.long_term.checked;
    await api('position', data);
    if (typeof clearWorkspaceUiFormState === 'function') clearWorkspaceUiFormState('positionForm');
    $('#editor').close();
    await reloadHoldings();
  } catch (e) {
    $('#formError').textContent = e.message;
  }
};
$('#holdings').onclick = async (e) => {
  const symbol = e.target.dataset.holdingMarket;
  if (symbol) {
    const panel = $('#holdingMarket');
    panel.hidden = false;
    await showWorkspaceStock(panel, symbol);
    if ($('#portfolio').hidden) return;
    panel.scrollIntoView({block:'start'});
    panel.querySelector('.trading-plot')?.focus({preventScroll:true});
    return;
  }
  const editSymbol = e.target.dataset.edit,
    del = e.target.dataset.delete,
    saleSymbol = e.target.dataset.planSale;
  if (saleSymbol) openSalePlanner(saleSymbol);
  if (editSymbol) edit(state.positions.find((p) => p.symbol === editSymbol));
  if (del && confirm(`Remove ${del} and its notes?`)) {
    try {
      await api('delete', { symbol: del });
      await reloadHoldings();
    } catch (e) {
      $('#message').textContent = e.message;
    }
  }
};
let salePlannerSymbol;
const salePlannerForm = $('#salePlannerForm');
const positiveSaleNumber = (value) => Number.isFinite(value) && value > 0;

function salePlannerInputs(position) {
  const { symbol, currency } = position;
  const canonical = holdingSymbol(position);
  const quote = holdingQuote(position, state.quotes);
  const usableQuote = quote?.currency === currency && positiveSaleNumber(quote.price) ? quote : null;
  const fx = state.quotes['NOK=X'];
  const rate = currency === 'NOK' ? 1 : fx?.currency === 'NOK' && fresh(fx) ? fx.price : null;
  const profile = state.portfolio_preferences;
  const portfolio = state.portfolio_context;
  const fee = profile?.sell_fee_nok;
  const weightPerShare =
    portfolio?.complete && positiveSaleNumber(portfolio.total_nok) && fresh(usableQuote) && rate
      ? (usableQuote.price * rate * 100) / portfolio.total_nok
      : null;
  const holding = portfolio?.holdings?.find((item) => item.symbol === canonical);
  return {
    quote: usableQuote,
    weightPerShare,
    weight: weightPerShare === null ? null : holding?.weight_pct ?? null,
    assessment: holdingAdviceBySymbol.get(symbol),
    fee: fee === 0 ? 0 : fee == null || !rate ? null : fee / rate,
  };
}

function openSalePlanner(symbol) {
  const position = state.positions.find((item) => item.symbol === symbol && item.shares > 0);
  if (!position) return;
  salePlannerSymbol = symbol;
  salePlannerForm.reset();
  const { weight, quote, assessment } = salePlannerInputs(position);
  const limit = state.portfolio_preferences?.max_stock_pct;
  if (weight > limit) salePlannerForm.elements.target.value = limit;
  if (quote && position.above > quote.price) salePlannerForm.elements.limit.value = position.above;
  renderSalePlan();
  $('#salePlanner').showModal();
  if (!assessment && typeof loadDaily === 'function') loadDaily();
}

function renderSalePlan() {
  const position = state.positions.find((item) => item.symbol === salePlannerSymbol && item.shares > 0);
  if (!position) {
    $('#salePlanner').close();
    return;
  }
  const { symbol, currency, shares } = position;
  const { quote, weight, weightPerShare, assessment, fee } = salePlannerInputs(position);
  const { goal, timing, target, cash, limit } = salePlannerForm.elements;
  const waiting = timing.value === 'limit';
  $('#saleTrimFields').hidden = goal.value !== 'trim';
  $('#saleCashFields').hidden = goal.value !== 'cash';
  $('#saleLimitFields').hidden = !waiting;
  $('#saleCashCurrency').textContent = currency;
  $('#saleLimitCurrency').textContent = currency;
  $('#salePlannerTitle').textContent = 'Plan a sale for ' + symbol;
  $('#salePlannerPolicy').textContent = assessment?.label
    ? 'Current Northstar recommendation: ' + assessment.label + ' · ' + assessment.reason
    : 'Current Northstar recommendation unavailable.';
  $('#salePlannerQuote').textContent = quote
    ? 'Latest quote: ' + money(quote.price, currency) +
      (Number.isFinite(quote.asof)
        ? ' · ' + new Date(quote.asof * 1000).toLocaleString()
        : ' · timestamp unavailable') +
      (fresh(quote) ? '' : ' · stale')
    : 'Latest quote unavailable.';

  const price = waiting ? limit.valueAsNumber : quote?.price;
  const hasPrice = positiveSaleNumber(price);
  const notes = [];
  if (state.ledger_reconciled === false)
    notes.push('These estimates use recorded holdings and cash. Check them against your broker.');
  if (!hasPrice) notes.push(waiting ? 'Enter a positive limit price.' : 'A market quote is needed for Sell soon.');
  else if (waiting) {
    if (quote && price <= quote.price) notes.push('Enter a limit price above the latest quote.');
    else {
      if (quote && price === position.above) notes.push('Limit uses your saved upper review price.');
      notes.push('A limit order may go unfilled.');
    }
  }
  const usablePrice = hasPrice && (!waiting || !quote || price > quote.price);
  let quantity = null;
  let shortfall = null;
  if (goal.value === 'exit') {
    quantity = shares;
  } else if (goal.value === 'trim') {
    const desired = target.valueAsNumber;
    if (weight !== null) notes.push(`Current weight ${weight.toFixed(2)}%.`);
    if (weight === null) notes.push('Trim sizing needs a complete, current portfolio valuation.');
    else if (!Number.isFinite(desired) || desired < 0 || desired > 100)
      notes.push('Enter a target weight from 0% to 100%.');
    else {
      quantity = Math.min(shares, Math.max(0, Math.ceil((weight - desired) / weightPerShare - 1e-10)));
      const remaining = Math.max(0, weight - quantity * weightPerShare);
      notes.push(`Estimated remaining weight ${remaining.toFixed(2)}% at current valuation before selling costs.`);
      if (!quantity) notes.push('This holding is already at or below your target weight.');
      else if (remaining - desired > 1e-8)
        notes.push('Selling this entire entry would still leave the stock above your target.');
    }
  } else if (goal.value === 'cash') {
    const desired = cash.valueAsNumber;
    if (!positiveSaleNumber(desired)) notes.push('Enter a positive cash goal.');
    else if (usablePrice) {
      const needed = Math.ceil((desired + (fee ?? 0)) / price - 1e-10);
      quantity = Math.min(shares, Math.max(1, needed));
      const gap = desired - (quantity * price - (fee ?? 0));
      if (gap > 1e-8) {
        notes.push('The estimate shows the maximum proceeds. Selling the full holding would fall short of the cash goal.');
        if (fee !== null) shortfall = gap;
      }
    }
  }

  const output = [];
  if (usablePrice) {
    const formatPrice = new Intl.NumberFormat('nb-NO', {
      style: 'currency',
      currency,
      maximumFractionDigits: 12,
    });
    output.push(`${waiting ? 'Limit' : 'Estimated sale'} price: ${formatPrice.format(price)} per share.`);
  }
  if (quantity !== null) output.push(`Shares to sell: ${quantity}.`);
  if (quantity !== null && usablePrice) {
    const gross = quantity * price;
    output.push('Estimated gross proceeds: ' + money(gross, currency) + '.');
    if (quantity && fee === null) {
      output.push('Selling fee unavailable. Net proceeds are unconfirmed.');
      output.push('Gain/loss after selling fee unavailable until a sell fee is entered in Portfolio fit.');
      if (goal.value === 'cash') output.push('Shares are sized against gross proceeds.');
    }
    else {
      const saleFee = quantity ? fee : 0;
      output.push(`Estimated net proceeds: ${money(gross - saleFee, currency)} (${money(saleFee, currency)} selling fee).`);
      if (quantity && Number.isFinite(position.cost) && position.cost > 0)
        output.push(`Estimated gain/loss after selling fee: ${money(gross - saleFee - quantity * position.cost, currency)} versus saved average cost, before tax.`);
      else if (quantity)
        output.push('Gain/loss unavailable until a positive average cost is saved.');
    }
    if (shortfall !== null) output.push('Estimated cash shortfall: ' + money(shortfall, currency) + '.');
  }
  $('#salePlannerResult').textContent = [...output, ...notes].join(' ');
}
salePlannerForm.addEventListener('input', renderSalePlan);
salePlannerForm.addEventListener('submit', (event) => event.preventDefault());
$('#closeSalePlanner').onclick = () => $('#salePlanner').close();
$('#refresh').onclick = async () => {
  const b = $('#refresh');
  b.disabled = true;
  b.textContent = 'Refreshing…';
  $('#message').textContent = 'Fetching quotes. This may take a moment.';
  try {
    const r = await api('refresh', {});
    await reloadHoldings();
    await refreshWorkspaceStockCharts();
    $('#message').textContent = r.errors.length
      ? r.errors.join('\n')
      : 'Refresh complete. Check provider timestamps before making a decision.';
  } catch (e) {
    $('#message').textContent = e.message;
  } finally {
    b.disabled = false;
    b.textContent = 'Refresh market data';
  }
};
$('#export').onclick = () => {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(state, null, 2)], { type: 'application/json' })
  );
  const a = document.createElement('a');
  a.href = url;
  a.download = 'northstar-notebook.json';
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
};
