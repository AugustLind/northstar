/* Quantities come from Oracle's shared-budget calculation, never from the LLM. */
let quantityPlanRequest=0,quantityPlanGenerated=0;
function renderQuantityPlan(plan){
 if(plan.generated<quantityPlanGenerated)return;quantityPlanGenerated=plan.generated;
 const buys=plan.buys||[],holdings=plan.holdings||[],blocked=plan.blocked_buys||[];
 let html='<p class="muted">Calculated '+new Date(plan.generated*1000).toLocaleString()+' · Market report '+(plan.report_generated?new Date(plan.report_generated*1000).toLocaleString():'unavailable')+'</p>';
 html+=(plan.warnings||[]).map(w=>'<p class="fitwarning">'+esc(w)+'</p>').join('');
 html+='<h3>Buy plan · one shared budget</h3><p>Budget '+money(plan.buy_budget_nok)+' · Planned spend '+money(plan.spent_nok)+' · Purchase fees '+money(plan.buy_fees_nok)+' · Unallocated '+money(plan.unallocated_budget_nok)+'.</p>';
 html+=buys.length?'<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Quantity to consider</th><th>Quote</th><th>Order total incl. fee</th><th>Why this quantity?</th></tr></thead><tbody>'+buys.map(r=>'<tr><td><b>'+esc(r.symbol)+'</b><small>'+esc(r.name)+'</small></td><td><strong class="positive">Buy '+r.buy_shares+' shares</strong></td><td>'+money(r.price)+'<small>'+new Date(r.quote_asof*1000).toLocaleString()+'</small></td><td>'+money(r.total_nok)+'<small>'+money(r.fee_nok)+' fee · '+r.fee_pct.toFixed(2)+'% of stock value</small></td><td>'+esc(r.reason)+'</td></tr>').join('')+'</tbody></table></div>':'<p>No purchase currently fits the shared budget and active rules. See the reasons below or change your saved budget and sizing limits.</p>';
 if((plan.post_buy_warnings||[]).length)html+='<p class="fitwarning">After the buy plan: '+plan.post_buy_warnings.map(esc).join(' ')+'</p>';
 html+='<h3>Your holdings · sale-review scenario</h3>';
 html+=holdings.length?'<div class="tablewrap"><table><thead><tr><th>Stock / held shares</th><th>Quantity to consider</th><th>Shares remaining</th><th>Gross sale value</th><th>Why this quantity?</th></tr></thead><tbody>'+holdings.map(r=>'<tr><td><b>'+esc(r.symbol)+'</b><small>Owned: '+esc(r.owned)+' shares</small>'+(r.price?'<small>Reference '+money(r.price)+' · '+new Date(r.quote_asof*1000).toLocaleString()+'</small>':'')+'</td><td><strong class="'+(r.sell_shares?'negative':'')+'">'+(r.sell_shares==null?'Quantity unavailable':r.sell_shares?'Sell '+r.sell_shares+' shares':'Hold · sell 0 shares')+'</strong></td><td>'+esc(r.sell_shares==null?'Unavailable':r.remaining_shares)+'</td><td>'+(r.gross_proceeds_nok==null?'Unavailable':money(r.gross_proceeds_nok))+'<small>Before selling fees and tax</small></td><td>'+r.reasons.map(esc).join(' ')+'</td></tr>').join('')+'</tbody></table></div>':'<p>No holdings saved. Import your current Nordnet CSV under Portfolio &amp; watchlist.</p>';
 if(blocked.length)html+='<details><summary>Stocks with no planned purchase ('+blocked.length+')</summary>'+blocked.map(r=>'<p><b>'+esc(r.symbol)+': buy 0 shares.</b> '+esc(r.reason)+'</p>').join('')+'</details>';
 html+='<p class="muted">'+esc(plan.method)+'</p>';
 for(const id of ['quantityPlanMain','quantityPlanFit']){const node=$('#'+id);if(node)node.innerHTML=html;}
}
async function loadQuantityPlan(){
 const token=++quantityPlanRequest;
 try{const plan=await api('trade-plan');if(token===quantityPlanRequest)renderQuantityPlan(plan);}
 catch(e){if(token!==quantityPlanRequest)return;for(const id of ['quantityPlanMain','quantityPlanFit']){const node=$('#'+id);if(node)node.textContent='Share-count plan unavailable: '+e.message;}}
}
for(const b of document.querySelectorAll('[data-plan-settings]'))b.onclick=()=>{document.querySelector('[data-tab="fit"]').click();if($('#fitPreferences').scrollIntoView)$('#fitPreferences').scrollIntoView({behavior:'smooth',block:'start'});};

for(const b of document.querySelectorAll('[data-view-plan]'))b.onclick=()=>{document.querySelector('[data-tab="recommendations"]').click();loadQuantityPlan();if($('#quantityPlanMain').scrollIntoView)$('#quantityPlanMain').scrollIntoView({behavior:'smooth',block:'start'});};
