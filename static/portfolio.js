/* Holdings notebook, editor and local export. Depends on app.js and ui-common.js. */
function render() {
  const { positions, quotes } = state;
  const alerts = [],
    assessments = [];
  $('#holdings').innerHTML = positions.length
    ? positions
        .map((p) => {
          const q = quotes[p.symbol],
            valid = q && q.currency === p.currency;
          const gain = valid && p.cost > 0 ? (q.price / p.cost - 1) * 100 : null;
          return `<tr><td><b>${esc(p.symbol)}</b><small>${
            p.shares
              ? p.long_term
                ? 'Long-term holding · keep under review'
                : 'Holding'
              : 'Watchlist'
          } · ${esc(p.currency)}</small></td><td>${p.shares}<small>${money(
            p.cost,
            p.currency
          )}</small></td><td>${valid ? money(q.price, p.currency) : 'Unavailable'}<small>${
            valid
              ? fresh(q)
                ? 'Provider quote'
                : 'Stale · excluded from total'
              : 'Refresh or check ticker/currency'
          }</small></td><td class="${gain >= 0 ? 'positive' : 'negative'}">${
            gain === null ? '—' : gain.toFixed(2) + '%'
          }</td><td>${q ? esc(new Date(q.asof * 1000).toLocaleString()) : 'Not fetched'}<small>${
            q ? esc(q.source) : 'No data'
          }</small></td><td><button data-edit="${esc(
            p.symbol
          )}">Edit</button> <button data-delete="${esc(p.symbol)}">Remove</button></td></tr>`;
        })
        .join('')
    : '<tr><td colspan="6">Your notebook is empty. Add your first holding or watchlist company.</td></tr>';
  for (const p of positions) {
    const q = quotes[p.symbol],
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
      const h =
        ctx &&
        (ctx.holdings || []).find(
          (h) =>
            h.symbol ===
            (p.currency === 'NOK' && !p.symbol.includes('.') ? p.symbol + '.OL' : p.symbol)
        );
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
  const bySymbol = new Map(assessments.map((a) => [a.symbol, a]));
  $('#holdingAssessments').innerHTML =
    state.positions
      .map((p) => {
        const symbol =
          p.currency === 'NOK' && !p.symbol.includes('.') ? p.symbol + '.OL' : p.symbol;
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
async function load() {
  state = await api('state');
  $('#accountStatus').textContent = 'Connected';
  render();
  renderGettingStarted();
}
function renderGettingStarted() {
  if (!$('#gettingStarted')) return;
  const held = state.positions.some((p) => p.shares > 0);
  const tracked = state.positions.length > 0;
  const priced =
    tracked &&
    state.positions.every(
      (p) => fresh(state.quotes[p.symbol]) && state.quotes[p.symbol].currency === p.currency
    );
  const reconciled = state.ledger_reconciled === true;
  const steps = [
    [
      tracked,
      'Add a holding or watchlist company in Portfolio, or import your Nordnet holdings CSV.',
    ],
    [priced, 'Refresh market data and check the quote dates and currencies.'],
    [
      reconciled,
      'For account returns, verify cash and an opening snapshot in Activity & cash. Import later transactions and reconcile with your broker.',
    ],
  ];
  $('#gettingStarted').hidden = false;
  $('#setupProgress').textContent =
    reconciled && priced
      ? 'Your records are ready for review. Check account-performance coverage in Portfolio.'
      : held
      ? 'Continue setting up your portfolio. Research is available while you do this.'
      : 'Start with research or add your portfolio. You can use either independently.';
  $('#setupChecklist').innerHTML = steps
    .map(([done, text]) => '<li>' + (done ? '✓ Completed: ' : 'Next: ') + esc(text) + '</li>')
    .join('');
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
$('#close').onclick = () => $('#editor').close();
$('#positionForm').onsubmit = async (e) => {
  e.preventDefault();
  try {
    const data = Object.fromEntries(new FormData(e.target));
    data.long_term = e.target.elements.long_term.checked;
    await api('position', data);
    $('#editor').close();
    await load();
  } catch (e) {
    $('#formError').textContent = e.message;
  }
};
$('#holdings').onclick = async (e) => {
  const editSymbol = e.target.dataset.edit,
    del = e.target.dataset.delete;
  if (editSymbol) edit(state.positions.find((p) => p.symbol === editSymbol));
  if (del && confirm(`Remove ${del} and its notes?`)) {
    try {
      await api('delete', { symbol: del });
      await load();
    } catch (e) {
      $('#message').textContent = e.message;
    }
  }
};
$('#refresh').onclick = async () => {
  const b = $('#refresh');
  b.disabled = true;
  b.textContent = 'Refreshing…';
  $('#message').textContent = 'Fetching quotes. This may take a moment.';
  try {
    const r = await api('refresh', {});
    await load();
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
