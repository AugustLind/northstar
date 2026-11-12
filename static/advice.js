let researchView=null, researchSettingsLoaded=false, chartRanges={}, askingModel=false;
const timeLabel=t=>t?new Date(t*1000).toLocaleString():'not yet';
function chart(card,range='1Y'){
 const days={'1M':31,'3M':93,'1Y':370}[range];
 const points=(card.history||[]).filter(p=>p.time>=Date.now()/1000-days*86400);
 if(points.length<2)return '<p class="muted">Chart unavailable — run analysis to download daily history.</p>';
 const W=500,H=190,left=54,right=15,top=16,bottom=30;
 const values=points.map(p=>p.close),min=Math.min(...values),max=Math.max(...values),pad=(max-min)*.08||1,lo=min-pad,hi=max+pad;
 const x=i=>left+i/(points.length-1)*(W-left-right),y=v=>top+(hi-v)/(hi-lo)*(H-top-bottom);
 const d=points.map((p,i)=>(i?'L':'M')+x(i).toFixed(2)+','+y(p.close).toFixed(2)).join(' ');
 let grid='';for(let i=0;i<3;i++){const v=lo+(hi-lo)*i/2;grid+=`<line x1="${left}" y1="${y(v)}" x2="${W-right}" y2="${y(v)}" stroke="#e0e8dd"/><text x="${left-5}" y="${y(v)+4}" text-anchor="end">${v.toFixed(1)}</text>`;}
 return `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc(card.symbol)} daily historical prices over ${range}"><title>${esc(card.symbol)} ${range} historical prices in ${esc(card.currency)}</title>${grid}<path d="${d}" fill="none" stroke="#287858" stroke-width="2.5"/>${points.map((p,i)=>`<circle cx="${x(i)}" cy="${y(p.close)}" r="3" fill="transparent"><title>${new Date(p.time*1000).toLocaleDateString()}: ${money(p.close,card.currency)}</title></circle>`).join('')}<text x="${left}" y="${H-5}">${new Date(points[0].time*1000).toLocaleDateString()}</text><text x="${W-right}" y="${H-5}" text-anchor="end">${new Date(points[points.length-1].time*1000).toLocaleDateString()}</text></svg><p class="muted">${esc(card.history_basis||'Provider daily close')} · ${esc(card.currency)} · hover points for values</p>`;
}
function renderAdvice(){
 if(!researchView)return;const r=researchView.report,w=researchView.worker||{},s=researchView.settings,p=researchView.progress;
 const financialProgress=researchView.fundamentals_progress;
 $('#researchStatus').textContent=(w.running?'Analysis running. ':'')+(w.running&&p&&p.started>=w.last_started-5?`Downloaded ${p.done}/${p.total}; ${p.failed} failures. `:'')+`Last report: ${r?timeLabel(r.generated):'not yet'}. Next scheduled: ${timeLabel(w.next_run)}.`+(w.error?' '+w.error:'')+(financialProgress&&financialProgress.running?` Financial scan: ${financialProgress.done}/${financialProgress.total}.`:'');
 if(!researchSettingsLoaded){const f=$('#researchSettings');f.elements.universe.value=s.universe.join(', ');f.elements.interval_minutes.value=s.interval_minutes;f.elements.model.value=s.model;f.elements.min_turnover_nok.value=s.min_turnover_nok;f.elements.llm_enabled.checked=s.llm_enabled;researchSettingsLoaded=true;}
 if(!r){$('#adviceCards').innerHTML='<div class="card">Preparing a broad market scan. Progress updates every 15 seconds; larger scans may take several minutes.</div>';return;}
 const reportOld=Date.now()/1000-r.generated>86400;const cards=r.cards.map(c=>(reportOld||!c.asof||Date.now()/1000-c.asof>4*86400)?Object.assign({},c,{action:'Insufficient data',score:null,composite:null,rank:null,analyses:[],rank_eligible:false,reasons:['Report or quote is stale. Run analysis before using a recommendation.'].concat(c.reasons)}):c),buy=cards.filter(c=>c.rank_eligible),sell=cards.filter(c=>c.held&&/selling|sell threshold|taking profits/.test(c.action));
 $('#adviceSummary').textContent=`${buy.length} buy candidate${buy.length===1?'':'s'} · ${sell.length} holding${sell.length===1?'':'s'} to review for selling · ${cards.filter(c=>c.score!==null).length}/${cards.length} stocks analysed`;
 $('#llmStatus').textContent=`${r.model?r.model+' · ':''}${r.llm_status}. AI explains selected stocks; the same measured analysis runs on every stock.`;
 const busy=!!researchView.model_busy;$('#askButton').disabled=askingModel||busy;$('#askButton').textContent=busy&&!askingModel?'Local AI busy…':'Ask local AI';
 $('#commentary').textContent=r.commentary||(r.llm_status==='generating local briefing'?'Ollama is writing your briefing. The stock rankings and explorer are ready while you wait.':r.llm_status==='disabled'?'Enable local AI in Research settings for a written briefing.':'No AI briefing generated. See its status above.');
 $('#providerErrors').textContent=(r.errors||[]).length?`${r.errors.length} refresh error(s). Affected stocks may be excluded.\n`+r.errors.slice(0,8).join('\n')+(r.errors.length>8?'\nAdditional failures are included in scan coverage.':''):'';
 const filter=$('#adviceFilter').value,search=$('#stockSearch').value.trim().toLowerCase(),by=$('#rankBy').value||'composite';
 const eligible=cards.filter(c=>c.rank_eligible),metric=c=>by==='composite'?(c.composite==null?c.score:c.composite):['return1m','volatility63','max_drawdown1y'].includes(by)?((c.metrics||{})[by]==null?null:(by==='volatility63'?-1:1)*c.metrics[by]):((c.analyses||[]).find(a=>a.name===by)||{}).score;
 const measured=cards.filter(c=>c.score!==null),above=measured.filter(c=>c.metrics.close>c.metrics.ma200).length,rising=measured.filter(c=>c.metrics.momentum3m>0).length;
 $('#marketBreadth').innerHTML=[['Analysed',measured.length,cards.length],['Above MA200',above,measured.length],['Positive 3-month return',rising,measured.length],['Pass entry policy',eligible.length,measured.length]].map(([label,n,total])=>'<article><small>'+label+'</small><strong>'+n+' <span>/ '+total+'</span></strong><div class="scoretrack"><span style="width:'+(total?n/total*100:0)+'%"></span></div></article>').join('');
 let filtered=cards.filter(c=>filter==='held'?c.held:filter==='buy'?c.rank_eligible:filter==='sell'?(c.held&&/selling|sell threshold|taking profits/.test(c.action)):filter==='top20'?(c.rank_eligible&&c.rank>=1&&c.rank<=20):true);
 filtered.sort((a,b)=>(metric(b)==null?-Infinity:metric(b))-(metric(a)==null?-Infinity:metric(a))||a.symbol.localeCompare(b.symbol));
 filtered=filtered.filter(c=>(c.symbol+' '+(c.name||'')).toLowerCase().includes(search));
 $('#rankingCoverage').textContent=`${filtered.length} shown · ${eligible.length} pass the entry policy · ${cards.filter(c=>c.score===null).length} without sufficient data. Top-20 uses the complete buy screen; owned candidates may qualify for additions. Portfolio limits and signal confirmation still apply.`;
 $('#adviceCards').innerHTML=filtered.length?'<div class="tablewrap"><table class="ranktable"><thead><tr><th>Entry rank</th><th>Stock</th><th>Overall</th><th>Trend</th><th>Momentum</th><th>Risk</th><th>Timing</th><th>Liquidity</th><th>Annual quality</th><th>Purchase fee drag*</th><th>Action</th><th></th></tr></thead><tbody>'+filtered.map(c=>`<tr><td>${c.rank||'—'}</td><td><b>${esc(c.symbol)}</b><small>${esc(c.name||'')} ${c.held?'· Owned':''}</small></td><td><b>${c.composite==null?'—':c.composite.toFixed(1)}</b></td>${['Trend','Momentum','Risk','Timing','Liquidity'].map(name=>{const part=(c.analyses||[]).find(p=>p.name===name);return `<td>${part?part.score.toFixed(0):'—'}</td>`;}).join('')}<td>${esc(c.quality?c.quality.label:'Awaiting financial data')}</td><td>${c.portfolio_fit&&c.portfolio_fit.fee_model==='fixed-buy-79-v1'&&c.portfolio_fit.fee_pct!=null?c.portfolio_fit.fee_pct.toFixed(2)+'%':'—'}<small>79 kr / purchase</small></td><td><span class="signal ${c.action==='Consider buying'?'buy':''}">${esc(c.action)}</span></td><td><button data-inspect="${esc(c.symbol)}">Explore</button></td></tr>`).join('')+'</tbody></table></div>':'<div class="card">No stocks match this view. Try All analysed stocks, a different search, or wait for scan completion.</div>';
 // Keep detailed charts stable across background polling and tab changes.
 if(explorerSymbol){const selected=cards.find(c=>c.symbol===explorerSymbol);if(selected){renderStockDetail(selected);const cached=explorerCache[explorerSymbol];if(cached&&cached.asof!==selected.asof&&!explorerDrag)selectStock(explorerSymbol,false);else {loadFinancials(explorerSymbol);if(typeof loadStockAnnouncements==='function')loadStockAnnouncements(explorerSymbol);}}}
 else if(filtered.length&&filtered[0].score!==null){selectStock(filtered[0].symbol,false);}
 const compare=$('#compareStock'),previous=compare.value;compare.innerHTML='<option value="">No comparison</option>'+cards.filter(c=>c.score!==null&&c.symbol!==explorerSymbol).map(c=>`<option value="${esc(c.symbol)}">${esc(c.symbol)}</option>`).join('');compare.value=previous;
}
async function loadResearch(){try{researchView=await api('research');renderAdvice();if(typeof loadQuantityPlan==='function')loadQuantityPlan();}catch(e){$('#researchStatus').textContent=e.message;}}
$('#adviceFilter').onchange=renderAdvice;
$('#adviceCards').onclick=e=>{if(e.target.dataset.inspect)selectStock(e.target.dataset.inspect,true);};
$('#stockSearch').oninput=renderAdvice;$('#rankBy').onchange=renderAdvice;
$('#analyze').onclick=async()=>{try{await api('analyze',{});$('#researchStatus').textContent='Analysis queued; results will appear automatically.';setTimeout(loadResearch,1000);}catch(e){$('#researchStatus').textContent=e.message;}};
$('#researchSettings').onsubmit=async e=>{e.preventDefault();const f=e.target;try{await api('settings',{universe:f.elements.universe.value.split(',').map(s=>s.trim()).filter(Boolean),interval_minutes:Number(f.elements.interval_minutes.value),model:f.elements.model.value,min_turnover_nok:Number(f.elements.min_turnover_nok.value),llm_enabled:f.elements.llm_enabled.checked});$('#settingsMessage').textContent='Saved. New analysis queued.';await loadResearch();}catch(e){$('#settingsMessage').textContent=e.message;}};
$('#askForm').onsubmit=async e=>{e.preventDefault();askingModel=true;$('#askButton').disabled=true;$('#answer').textContent='Asking your local model…';try{const r=await api('ask',{question:$('#question').value});$('#answer').textContent=r.answer+'\n\n'+r.model+' · '+timeLabel(r.generated);}catch(e){$('#answer').textContent=e.message;}finally{askingModel=false;loadResearch();}};
let explorerSymbol='',explorerCache={},explorerWindow={start:0,end:1},explorerCompare='',explorerDrag=null,explorerLoad=0;
function currentHistory(){return (explorerCache[explorerSymbol]||{}).history||[];}
function diagnosticTile(label,value,note='',tone=''){
 return '<article><small>'+esc(label)+'</small><strong class="'+tone+'">'+esc(value)+'</strong>'+(note?'<small>'+esc(note)+'</small>':'')+'</article>';
}
const metricNumber=(value,suffix='',digits=1)=>Number.isFinite(value)?value.toFixed(digits)+suffix:'Unavailable';
function renderDiagnostics(c){
 const m=c.metrics||{},adx=m.adx14,trend=Number.isFinite(adx)?(adx>=25?'Stronger directional trend':adx<20?'Weak directional trend':'Transitional trend'):'OHLC history required';
 $('#advancedMetrics').innerHTML=[
  diagnosticTile('20-session volatility',metricNumber(m.volatility20,'%'),'Annualised daily returns'),
  diagnosticTile('63-session volatility',metricNumber(m.volatility63,'%'),'Annualised daily returns'),
  diagnosticTile('ATR (14)',metricNumber(m.atr_pct,'% of close'),metricNumber(m.atr14,' '+(c.currency||'NOK'))+' · daily range'),
  diagnosticTile('ADX (14)',metricNumber(adx),trend),
  diagnosticTile('1-year maximum drawdown',metricNumber(m.max_drawdown1y,'%'),'Up to 253 closes; peak to trough'),
  diagnosticTile('Historical 95% daily VaR',metricNumber(m.var95_loss,'% loss'),'Up to 252 daily returns'),
  diagnosticTile('Historical tail loss (95%)',metricNumber(m.expected_shortfall95,'% loss'),'Worst 5% probability mass'),
  diagnosticTile('Relative volume',metricNumber(m.relative_volume20,'×',2),'Latest / preceding 20 sessions'),
  diagnosticTile('63-session trend fit',metricNumber(m.trend_r2==null?null:m.trend_r2*100,'% R²'),(m.trend_direction||'Unavailable')+' log-price regression'),
  diagnosticTile('20-session efficiency',metricNumber(m.efficiency20,'%'),'Net move / total absolute moves'),
  diagnosticTile('252-close range position',metricNumber(m.range_position,'%'),'0% = low; 100% = high'),
  diagnosticTile('Sessions below 1-year peak',metricNumber(m.underwater_sessions,'',0),'Recovery to peak: '+metricNumber(m.recovery_pct,'%'))
 ].join('');
 $('#returnHorizons').innerHTML=[['1 week','return1w'],['1 month','return1m'],['3 months','return3m'],['6 months','return6m'],['1 year','return1y']].map(([label,key])=>diagnosticTile(label,metricNumber(m[key],'%'),'',m[key]==null?'':m[key]>=0?'positive':'negative')).join('');
 $('#diagnosticNote').textContent=m.risk_sessions?'Diagnostics as of '+timeLabel(m.history_end)+' · '+m.risk_sessions+' daily returns in the risk window. Descriptive measurements; they do not change entry scores. ATR/ADX require complete high/low data. Missing values stay unavailable.':'Run a new analysis to populate the expanded diagnostics. Existing research and charts remain available.';
}
function renderStockDetail(c){
 renderDiagnostics(c);
 $('#explorer').hidden=false;$('#explorerTitle').textContent=(c.name||c.symbol)+' · '+c.symbol;$('#explorerAction').textContent=c.action;
 $('#componentScores').innerHTML=(c.analyses||[]).map(p=>`<article><small>${esc(p.name)} · ${p.weight}% weight</small><strong>${p.score.toFixed(0)}<small>/100</small></strong><div class="scoretrack"><span style="width:${Math.max(0,Math.min(100,p.score))}%"></span></div><p>${esc(p.explanation)}</p></article>`).join('');
 const fee=c.portfolio_fit;$('#stockFeeImpact').textContent=fee&&fee.fee_model==='fixed-buy-79-v1'&&fee.shares?'Purchase fee: 79 kr once for '+fee.shares+' shares · '+fee.fee_pct.toFixed(2)+'% of stock value. Price needed to recover this purchase fee: '+money(fee.break_even_price,c.currency)+' (+'+fee.break_even_gain_pct.toFixed(2)+'%). Selling fees are not included.':'Your purchase fee is 79 kr per order. Open Portfolio fit to calculate its impact for your budget.';
 $('#stockObservations').innerHTML='<ul>'+[...c.reasons,...(c.observations||[])].map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>';
}
async function selectStock(symbol,scroll){
 explorerSymbol=symbol;const token=++explorerLoad;const card=researchView&&researchView.report&&researchView.report.cards.find(c=>c.symbol===symbol);if(card)renderStockDetail(card);
 $('#chartPlot').innerHTML='<p>Loading daily price and volume history…</p>';$('#chartTooltip').textContent='';
 loadFinancials(symbol);if(typeof loadStockAnnouncements==='function')loadStockAnnouncements(symbol);
 try{const quote=await api('history?symbol='+encodeURIComponent(symbol));if(token!==explorerLoad)return;explorerCache[symbol]=quote;const n=(quote.history||[]).length;explorerWindow={start:Math.max(0,n-252),end:Math.max(0,n-1)};explorerCompare='';$('#compareStock').value='';drawExplorer();if(scroll&&$('#explorer').scrollIntoView)$('#explorer').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){if(token===explorerLoad)$('#chartPlot').textContent=e.message;}
}
function drawExplorer(){
 const quote=explorerCache[explorerSymbol];if(!quote)return;const history=quote.history||[];
 if(history.length<2){$('#chartPlot').textContent='History unavailable. Refresh the scan and try again.';return;}
 explorerWindow=ChartKit.windowBounds(history.length,explorerWindow.start,explorerWindow.end);
 const overlays=[];if($('#show20').checked)overlays.push('ema20');if($('#show50').checked)overlays.push('ma50');if($('#show200').checked)overlays.push('ma200');if($('#showBands').checked)overlays.push('upper','lower');
 const compare=explorerCompare?(explorerCache[explorerCompare]||{}).history:null;
 $('#chartPlot').innerHTML=ChartKit.svg(history,{...explorerWindow,symbol:explorerSymbol,compact:window.innerWidth<=600,type:$('#chartType').value,panel:$('#chartPanel').value,percent:$('#showPercent').checked,log:$('#showLog').checked,currency:quote.currency,overlays,compare});
 $('#chartFrom').value=new Date(history[explorerWindow.start].time*1000).toISOString().slice(0,10);$('#chartTo').value=new Date(history[explorerWindow.end].time*1000).toISOString().slice(0,10);
 const visible=history.slice(explorerWindow.start,explorerWindow.end+1);
 renderWindowStats(visible,compare);
 $('#chartNavigator').innerHTML=ChartKit.navigator(history,explorerWindow.start,explorerWindow.end);
 const position=$('#chartPosition');position.max=history.length-visible.length;position.value=explorerWindow.start;position.disabled=visible.length===history.length;
 const candlesMissing=$('#chartType').value==='candles'&&!visible.every(p=>p.open>0&&p.high>=Math.max(p.open,p.close)&&p.low>0&&p.low<=Math.min(p.open,p.close));
 $('#chartNote').textContent=`${quote.history_basis||'Provider daily close'} · ${quote.currency||'NOK'} · ${visible.length} daily observations · quote ${timeLabel(quote.asof)}. `+(candlesMissing?'OHLC data incomplete; displaying a price line. ':'')+(explorerCompare?'Comparison: '+explorerCompare+'; aligned at the first shared UTC date. ':'')+'Charts show historical observations, not forecasts.';
}
function renderWindowStats(visible,compare){
 const v=ChartKit.analytics(visible,compare);if(!v)return;
 $('#windowStats').innerHTML=[
  diagnosticTile('Period return',metricNumber(v.returnPct,'%'),v.observations+' closes',v.returnPct>=0?'positive':'negative'),
  diagnosticTile('Annualised volatility',metricNumber(v.volatility,'%'),'Daily simple returns'),
  diagnosticTile('Maximum drawdown',metricNumber(v.maxDrawdown,'%'),'Within selected period'),
  diagnosticTile('95% daily VaR',metricNumber(v.var95,'% loss'),'Empirical daily percentile'),
  diagnosticTile('Tail loss (95%)',metricNumber(v.expectedShortfall95,'% loss'),'Mean worst 5% probability mass'),
  diagnosticTile('Sharpe · zero rate',metricNumber(v.sharpe,'',2),'Annualised; no costs'),
  diagnosticTile('Best / worst session',metricNumber(v.best,'%')+' / '+metricNumber(v.worst,'%'),'Close-to-close changes'),
  diagnosticTile('Positive sessions',metricNumber(v.positivePct,'%'),'Flat sessions excluded from positives')
 ].join('');
 const c=v.comparison;
 $('#comparisonStats').textContent=!compare?'Choose another company to compare returns, correlation and beta.':!c||c.pairs.length<2?'No usable shared dates for this comparison.':explorerCompare+' · '+c.pairs.length+' shared dates · Return difference '+metricNumber(c.excess,' percentage points')+' · Correlation '+metricNumber(c.correlation,'',2)+' · Beta '+metricNumber(c.beta,'×',2)+'. Correlation and beta use shared-date intervals, which may span gaps; 20 return intervals required. These describe past co-movement.';
}
function zoomExplorer(factor,anchor=.5){const h=currentHistory();if(h.length<2)return;const span=explorerWindow.end-explorerWindow.start,next=Math.max(5,Math.min(h.length-1,span*factor)),at=explorerWindow.start+span*anchor;explorerWindow=ChartKit.windowBounds(h.length,at-next*anchor,at+next*(1-anchor));drawExplorer();}
function initExplorer(){
 if(window.addEventListener)window.addEventListener('resize',()=>{if(explorerSymbol)drawExplorer();});
 $('#showLog').onchange=()=>{if($('#showLog').checked)$('#showPercent').checked=false;drawExplorer();};
 $('#showPercent').onchange=()=>{if($('#showPercent').checked)$('#showLog').checked=false;drawExplorer();};
 $('#chartPosition').oninput=()=>{const span=explorerWindow.end-explorerWindow.start,start=Number($('#chartPosition').value);explorerWindow={start,end:start+span};drawExplorer();};
 for(const id of ['chartType','chartPanel','show20','show50','show200','showBands'])$('#'+id).onchange=drawExplorer;
 $('#explorerRanges').onclick=e=>{if(!e.target.dataset.days)return;const h=currentHistory();if(!h.length)return;const limit=h[h.length-1].time-Number(e.target.dataset.days)*86400;let start=h.findIndex(p=>p.time>=limit);explorerWindow={start:Math.max(0,start),end:h.length-1};drawExplorer();};
 $('#zoomIn').onclick=()=>zoomExplorer(.7);$('#zoomOut').onclick=()=>zoomExplorer(1.4);$('#resetChart').onclick=()=>{const n=currentHistory().length;explorerWindow={start:Math.max(0,n-252),end:n-1};drawExplorer();};
 const dates=()=>{const h=currentHistory(),a=Date.parse($('#chartFrom').value+'T00:00:00Z')/1000,b=Date.parse($('#chartTo').value+'T23:59:59Z')/1000;if(!h.length||!Number.isFinite(a)||!Number.isFinite(b))return;const start=h.findIndex(p=>p.time>=a);let end=-1;h.forEach((p,i)=>{if(p.time<=b)end=i;});if(start<0||end<=start){$('#chartTooltip').textContent='Select at least two trading observations, with From before To.';return;}explorerWindow={start,end};drawExplorer();};
 $('#chartFrom').onchange=dates;$('#chartTo').onchange=dates;
 $('#compareStock').onchange=async()=>{const symbol=$('#compareStock').value;explorerCompare=symbol;if(!symbol){drawExplorer();return;}try{if(!explorerCache[symbol])explorerCache[symbol]=await api('history?symbol='+encodeURIComponent(symbol));drawExplorer();}catch(e){$('#chartTooltip').textContent=e.message;}};
 const plot=$('#chartPlot');const anchor=e=>{const r=(plot.querySelector('svg')||plot).getBoundingClientRect(),g=ChartKit.layout(window.innerWidth<=600);return Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*g.W-g.L)/(g.W-g.L-g.R)));};
 plot.addEventListener('wheel',e=>{if(!currentHistory().length)return;e.preventDefault();zoomExplorer(e.deltaY>0?1.15:.85,anchor(e));},{passive:false});
 plot.addEventListener('pointerdown',e=>{if(!currentHistory().length)return;explorerDrag={x:e.clientX,start:explorerWindow.start,end:explorerWindow.end};plot.setPointerCapture(e.pointerId);});
 plot.addEventListener('pointermove',e=>{const h=currentHistory();if(!h.length)return;if(explorerDrag){const shift=Math.round((explorerDrag.x-e.clientX)/(plot.querySelector('svg')||plot).getBoundingClientRect().width*(explorerDrag.end-explorerDrag.start));explorerWindow=ChartKit.windowBounds(h.length,explorerDrag.start+shift,explorerDrag.end+shift);drawExplorer();}
 const ratio=anchor(e),index=Math.round(explorerWindow.start+ratio*(explorerWindow.end-explorerWindow.start)),p=h[index];if(!p)return;$('#chartTooltip').textContent=new Date(p.time*1000).toLocaleDateString()+' · Close '+money(p.close,(explorerCache[explorerSymbol]||{}).currency||'NOK')+(p.open?' · Open '+p.open.toFixed(2)+' · High '+p.high.toFixed(2)+' · Low '+p.low.toFixed(2):'')+(p.volume!=null?' · Volume '+new Intl.NumberFormat('nb-NO').format(p.volume):'');const measured=ChartKit.series(h);$('#chartTooltip').textContent+=' · RSI '+metricNumber(measured.rsi[index])+' · MACD '+metricNumber(measured.macd[index],'',2)+' · Drawdown '+metricNumber(measured.drawdown[index],'%');const cursor=$('#explorerCursor');if(cursor){const g=ChartKit.layout(window.innerWidth<=600),x=g.L+ratio*(g.W-g.L-g.R);cursor.setAttribute('x1',x);cursor.setAttribute('x2',x);cursor.setAttribute('visibility','visible');}});
 plot.addEventListener('pointerleave',()=>{if(!explorerDrag){const cursor=$('#explorerCursor');if(cursor)cursor.setAttribute('visibility','hidden');}});
 const finish=()=>{explorerDrag=null;};plot.addEventListener('pointerup',finish);plot.addEventListener('pointercancel',finish);
 plot.addEventListener('keydown',e=>{if(e.key==='+'||e.key==='='){e.preventDefault();zoomExplorer(.7);}else if(e.key==='-'){e.preventDefault();zoomExplorer(1.4);}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const shift=(e.key==='ArrowLeft'?-1:1)*Math.max(1,Math.round((explorerWindow.end-explorerWindow.start)/10));explorerWindow=ChartKit.windowBounds(currentHistory().length,explorerWindow.start+shift,explorerWindow.end+shift);drawExplorer();}});
 $('#resetUniverse').onclick=async()=>{try{const settings={...researchView.settings,universe:researchView.default_universe||researchView.settings.universe};await api('settings',settings);researchSettingsLoaded=false;await loadResearch();$('#settingsMessage').textContent='Broad universe restored. Scan queued.';}catch(e){$('#message').textContent=e.message;}};
}

let financialRequest=0;
const financialLabels={revenue:'Revenue',revenue_growth:'Revenue growth',operating_income:'Operating profit',operating_margin:'Operating margin',net_income:'Net income',net_margin:'Net margin',operating_cash_flow:'Operating cash flow',capital_expenditure:'Capital expenditure',free_cash_flow:'Free cash flow',debt:'Total debt',cash:'Cash & short-term investments',equity:'Equity',net_cash:'Cash minus debt',debt_to_equity:'Debt / equity',diluted_eps:'Annual diluted EPS',annual_pe_proxy:'Annual P/E proxy',ordinary_shares:'Year-end ordinary shares',diluted_shares:'Annual diluted average shares',share_count_change:'Share-count change'};
function financialValue(metric){if(!metric||!Number.isFinite(metric.value))return 'Unavailable';if(metric.unit==='percent')return metric.value.toFixed(1)+'%';if(metric.unit==='ratio')return metric.value.toFixed(2)+'×';if(metric.unit==='shares')return new Intl.NumberFormat('nb-NO',{maximumFractionDigits:0}).format(metric.value)+' shares';if(metric.currency)return money(metric.value,metric.currency);return new Intl.NumberFormat('nb-NO',{maximumFractionDigits:2}).format(metric.value)+' (currency unspecified)';}
async function loadFinancials(symbol){
 const token=++financialRequest;
 try{const f=await api('fundamentals?symbol='+encodeURIComponent(symbol));if(token!==financialRequest||symbol!==explorerSymbol)return;
 $('#financialStatus').textContent=`Coverage: ${f.status}. Fiscal period end: ${f.period||'unavailable'}. Retrieved: ${timeLabel(f.fetched)}.`+(f.error?' Latest refresh: '+f.error:'')+(f.scan&&f.scan.running?` Background scan: ${f.scan.done}/${f.scan.total}.`:'');
 const quality=f.assessment||{};$('#qualitySummary').textContent=(quality.label||'Assessment unavailable')+' · '+(quality.passed||0)+' / '+(quality.covered||0)+' covered accounting checks positive · Fiscal year '+(quality.period||'unknown')+'.';$('#qualityChecks').innerHTML=(quality.checks||[]).map(c=>'<p>'+esc(c.passes?'✓ ':'Review: ')+esc(c.label)+' · '+esc(c.period)+'</p>').join('');$('#qualityMethod').textContent=quality.method||'Financial coverage is not ready.';const valuation=f.valuation||{};$('#valuationSummary').textContent=valuation.median_annual_pe_proxy!=null?'Annual P/E proxy '+valuation.subject_annual_pe_proxy.toFixed(2)+'× versus sector median '+valuation.median_annual_pe_proxy.toFixed(2)+'× ('+valuation.peer_count+' other companies with matching fiscal periods). '+valuation.method:'Peer valuation unavailable: at least three comparable fresh same-sector annual observations are required. Annual P/E is not TTM and does not establish cheapness.';
 $('#financialSignals').innerHTML=(f.signals||[]).length?'<ul>'+f.signals.map(s=>'<li>'+esc(s)+'</li>').join('')+'</ul>':'<p>Financial statements have not been retrieved for this company yet, or the provider has no coverage. Missing figures are not treated as zero.</p>';
 const keys=['revenue','revenue_growth','operating_margin','net_income','operating_cash_flow','free_cash_flow','debt','cash','net_cash','debt_to_equity','annual_pe_proxy','share_count_change'];
 $('#financialMetrics').innerHTML=keys.map(k=>{const m=(f.metrics||{})[k];return `<article><small>${financialLabels[k]}</small><strong>${financialValue(m)}</strong><small>${m?esc(m.period):'No matching annual observation'}</small>${m&&m.note?'<p>'+esc(m.note)+'</p>':''}</article>`;}).join('');
 const rows=[];for(const [key,values]of Object.entries(f.history||{}))for(const v of values)rows.push(`<tr><td>${esc(financialLabels[key]||key)}</td><td>${esc(v.period)}</td><td>${financialValue({...v,unit:key==='ordinary_shares'||key==='diluted_shares'?'shares':'amount'})}</td></tr>`);
 $('#financialHistory').innerHTML=rows.length?'<table><thead><tr><th>Annual field</th><th>Fiscal period end</th><th>Reported value</th></tr></thead><tbody>'+rows.join('')+'</tbody></table>':'<p>No annual history available.</p>';
 $('#financialSource').innerHTML=(f.source?esc(f.source)+'. ':'')+'Fiscal period end is not the filing publication date. These snapshots are not point-in-time historical data.'+(f.source_url&&f.source_url.startsWith('https://finance.yahoo.com/quote/')?' <a href="'+esc(f.source_url)+'" target="_blank" rel="noopener noreferrer">View provider financial statements ↗</a>':'');
 }catch(e){if(token===financialRequest)$('#financialStatus').textContent=e.message;}
}
$('#refreshFinancials').onclick=async()=>{if(!explorerSymbol)return;const button=$('#refreshFinancials');button.disabled=true;try{const r=await api('fundamentals',{symbol:explorerSymbol});$('#financialStatus').textContent=r.queued?'Financial refresh queued. Results appear automatically.':r.message;}catch(e){$('#financialStatus').textContent=e.message;}finally{button.disabled=false;}};

initExplorer();
openWorkspace(location.hash?location.hash.slice(1):location.pathname==='/recommendations'?'recommendations':'daily',false);
loadResearch();setInterval(()=>{loadResearch();load().catch(()=>{});},15000);

$('#checkStockFit').onclick=()=>{if(!explorerSymbol)return;openWorkspace('fit');$('#fitPreviewSymbol').value=explorerSymbol;$('#fitPreviewAmount').value=(researchView.report.portfolio_limits||{}).purchase_nok||0;previewFitPurchase();};
