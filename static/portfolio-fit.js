/* Portfolio constraints are calculated by Oracle; this page never places trades. */
let fitView=null,fitDirty=false,fitLoading=0;
const fitPercent=v=>v==null?'Unavailable':v.toFixed(1)+'%';
const fitMoney=v=>v==null?'Unavailable':money(v);
async function loadPortfolioFit(){
 const token=++fitLoading;
 try{const v=await api('portfolio-fit');if(token!==fitLoading)return;fitView=v;renderPortfolioFit(v);}
 catch(e){$('#fitStatus').textContent=e.message;}
}
function renderPortfolioFit(v){
 const p=v.portfolio;if(typeof renderQuantityPlan==='function'&&v.trade_plan)renderQuantityPlan(v.trade_plan);
 $('#fitStatus').textContent='Current portfolio check: '+new Date(v.generated*1000).toLocaleString()+'. Ranking: '+(v.report_generated?new Date(v.report_generated*1000).toLocaleString():'not available')+(v.report_stale?' · stale; no candidate cleared.':'');
 $('#fitTotal').textContent=fitMoney(p.total_nok);$('#fitCash').textContent=fitMoney(p.cash_nok);$('#fitCashShare').textContent=fitPercent(p.cash_pct)+' of tracked total';
 $('#fitCandidateCount').textContent=v.candidates.filter(c=>c.buy_candidate).length;
 $('#fitWarnings').innerHTML=p.warnings.map(w=>'<p class="fitwarning">'+esc(w)+'</p>').join('');
 $('#fitScope').textContent=p.scope;
 $('#fitExposure').innerHTML=p.holdings.length?'<div class="tablewrap"><table><thead><tr><th>Holding</th><th>Sector / company</th><th>Value · NOK</th><th>Weight incl. cash</th></tr></thead><tbody>'+p.holdings.map(h=>'<tr><td>'+esc(h.symbol)+'</td><td>'+esc(h.sector||'Unclassified')+'<small>Company: '+esc(h.issuer||h.symbol)+'</small></td><td>'+fitMoney(h.value_nok)+'</td><td>'+fitPercent(h.weight_pct)+'</td></tr>').join('')+'</tbody></table></div>':'<p>Add holdings in Portfolio &amp; watchlist. You can also model a cash-only starting portfolio.</p>';
 $('#fitSectors').innerHTML=p.sectors.map(s=>'<div class="fitsector"><div>'+esc(s.sector)+' · '+fitMoney(s.value_nok)+' · '+fitPercent(s.weight_pct)+'</div>'+(s.weight_pct==null?'':'<div class="scoretrack"><span style="width:'+Math.min(100,Math.max(0,s.weight_pct))+'%;background:'+(s.sector==='Unclassified'||s.weight_pct>v.profile.max_sector_pct?'#b08030':'#287858')+'"></span></div>')+'</div>').join('')||'<p>No held-stock sector exposure yet.</p>';
 if(!fitDirty){
  const f=$('#fitPreferences');for(const k of ['cash_nok','purchase_nok','max_stock_pct','max_sector_pct','reserve_pct','max_buy_fee_pct','review_sell_pct','confirm_sessions','signal_wait_hours','trade_cooldown_days','min_change_pct'])f.elements[k].value=v.profile[k];
  const symbols=Array.from(new Set(p.holdings.map(h=>h.symbol).concat(v.candidates.map(c=>c.symbol),Object.keys(v.profile.sectors)))).sort();
  $('#fitClassifications').innerHTML=symbols.map(s=>'<label>'+esc(s)+'<small>'+esc((v.sector_sources||{})[s]||'No classification source')+'</small><select data-sector="'+esc(s)+'"><option value="">Unclassified</option>'+v.sector_choices.map(choice=>'<option value="'+esc(choice)+'"'+(v.profile.sectors[s]===choice?' selected':'')+'>'+esc(choice)+'</option>').join('')+'</select></label>').join('')||'<p>Holdings and top-20 stocks appear here after a scan.</p>';
  $('#fitExtraSector').innerHTML='<option value="">Choose a sector</option>'+v.sector_choices.map(s=>'<option>'+esc(s)+'</option>').join('');
 }
 $('#fitCandidates').innerHTML=v.candidates.length?'<div class="tablewrap"><table><thead><tr><th>Market rank / stock</th><th>Technical action</th><th>Portfolio check</th><th>Purchase fee drag</th><th>Maximum purchase value*</th><th>Strongest measured correlation</th><th></th></tr></thead><tbody>'+v.candidates.map(c=>{const co=c.highest_correlation;return '<tr><td>'+esc(c.rank||'—')+' · '+esc(c.symbol)+(c.held?' · Owned':'')+'<small>'+esc(c.name)+'</small></td><td>'+esc(c.technical_action)+'</td><td><b>'+esc(c.status)+'</b><small>'+esc(c.warnings.join(' '))+'</small></td><td>'+fitPercent(c.fee_pct)+'<small>79 kr per purchase</small></td><td>'+fitMoney(c.max_purchase_nok)+'</td><td>'+(co?esc(co.symbol)+' · '+co.value.toFixed(2)+'<small>'+co.observations+' matching daily returns</small>':'Unavailable')+'</td><td><button type="button" data-fit-preview="'+esc(c.symbol)+'">Preview purchase</button></td></tr>';}).join('')+'</tbody></table></div>':'<p>A completed market scan is needed to show the current top 20 here.</p>';
 $('#fitMethod').textContent=v.method;
}
$('#fitPreferences').oninput=()=>{fitDirty=true;$('#fitSaveStatus').textContent='Unsaved changes.';};
$('#fitPreferences').onchange=()=>{fitDirty=true;$('#fitSaveStatus').textContent='Unsaved changes.';};
$('#fitPreferences').onsubmit=async e=>{
 e.preventDefault();if(!fitView)return;const f=e.target,data={sectors:Object.assign({},fitView.manual_sectors||fitView.profile.sectors)};
 for(const k of ['cash_nok','purchase_nok','max_stock_pct','max_sector_pct','reserve_pct','max_buy_fee_pct','review_sell_pct','confirm_sessions','signal_wait_hours','trade_cooldown_days','min_change_pct'])data[k]=Number(f.elements[k].value);
 for(const select of document.querySelectorAll('#fitClassifications select[data-sector]')){if(select.value!==(fitView.profile.sectors[select.dataset.sector]||'')){if(select.value)data.sectors[select.dataset.sector]=select.value;else delete data.sectors[select.dataset.sector];}}
 const extra=$('#fitExtraSymbol').value.trim().toUpperCase();if(extra){if(!$('#fitExtraSector').value){$('#fitSaveStatus').textContent='Choose a sector for the additional ticker.';return;}data.sectors[extra.includes('.')?extra:extra+'.OL']=$('#fitExtraSector').value;}
 const b=$('#saveFit');b.disabled=true;try{await api('portfolio-fit',data);fitDirty=false;$('#fitExtraSymbol').value='';$('#fitSaveStatus').textContent='Saved on Oracle. Purchase previews do not update cash or holdings.';$('#fitPreviewResult').innerHTML='';await loadPortfolioFit();await load();if(typeof loadResearch==='function')await loadResearch();}catch(error){$('#fitSaveStatus').textContent=error.message;}finally{b.disabled=false;}
};
async function previewFitPurchase(){
 const b=$('#fitPreviewButton');b.disabled=true;
 try{const r=await api('portfolio-fit/preview',{symbol:$('#fitPreviewSymbol').value,amount:Number($('#fitPreviewAmount').value)});
 $('#fitPreviewResult').innerHTML='<h3>'+esc(r.symbol)+' · '+(r.ready?'Within chosen allocation limits':'Review needed')+'</h3><p>'+r.warnings.map(esc).join(' ')+'</p><div class="tablewrap"><table><tbody>'+[
 ['Whole shares',r.shares==null?'Unavailable':r.shares],['Quote timestamp',r.quote_asof?new Date(r.quote_asof*1000).toLocaleString():'Unavailable'],['Stock purchase value',fitMoney(r.purchase_nok)],['Purchase fee · once per order',fitMoney(r.fees_nok)],['Purchase fee / stock value',fitPercent(r.fee_pct)],['Price to recover purchase fee',fitMoney(r.break_even_price)+' · +'+fitPercent(r.break_even_gain_pct)],['Company weight incl. known share classes',fitPercent(r.current_stock_pct)+' → '+fitPercent(r.after_stock_pct)],['Sector weight',fitPercent(r.current_sector_pct)+' → '+fitPercent(r.after_sector_pct)],['Cash after purchase',fitMoney(r.after_cash_nok)+' · '+fitPercent(r.after_cash_pct)]
 ].map(row=>'<tr><th>'+esc(row[0])+'</th><td>'+esc(row[1])+'</td></tr>').join('')+'</tbody></table></div><p>Hypothetical allocation check using saved settings. Technical signal, valuation and suitability require separate review. No trade has been placed and your records have not changed.</p>';
 }catch(e){$('#fitPreviewResult').textContent=e.message;}finally{b.disabled=false;}
}
$('#fitPreviewForm').onsubmit=e=>{e.preventDefault();previewFitPurchase();};
$('#fitCandidates').onclick=e=>{if(!e.target.dataset.fitPreview)return;$('#fitPreviewSymbol').value=e.target.dataset.fitPreview;$('#fitPreviewAmount').value=fitView.profile.purchase_nok;previewFitPurchase();if($('#fitPreviewForm').scrollIntoView)$('#fitPreviewForm').scrollIntoView({behavior:'smooth',block:'start'});};
$('#refreshFit').onclick=loadPortfolioFit;
for(const b of document.querySelectorAll('[data-tab="fit"]'))b.addEventListener('click',loadPortfolioFit);
