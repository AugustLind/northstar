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
 $('#researchStatus').textContent=(w.running?'Analysis running. ':'')+(w.running&&p&&p.started>=w.last_started-5?`Downloaded ${p.done}/${p.total}; ${p.failed} failures. `:'')+`Last report: ${r?timeLabel(r.generated):'not yet'}. Next scheduled: ${timeLabel(w.next_run)}.`+(w.error?' '+w.error:'');
 if(!researchSettingsLoaded){const f=$('#researchSettings');f.elements.universe.value=s.universe.join(', ');f.elements.interval_minutes.value=s.interval_minutes;f.elements.model.value=s.model;f.elements.min_turnover_nok.value=s.min_turnover_nok;f.elements.llm_enabled.checked=s.llm_enabled;researchSettingsLoaded=true;}
 if(!r){$('#adviceCards').innerHTML='<div class="card">Preparing a broad market scan. Progress updates every 15 seconds; larger scans may take several minutes.</div>';return;}
 const reportOld=Date.now()/1000-r.generated>86400;const cards=r.cards.map(c=>(reportOld||!c.asof||Date.now()/1000-c.asof>4*86400)?Object.assign({},c,{action:'Insufficient data',score:null,composite:null,rank:null,analyses:[],rank_eligible:false,reasons:['Report or quote is stale. Run analysis before using a recommendation.'].concat(c.reasons)}):c),buy=cards.filter(c=>!c.held&&c.action==='Consider buying'),sell=cards.filter(c=>c.held&&/selling|sell threshold|taking profits/.test(c.action));
 $('#adviceSummary').textContent=`${buy.length} buy candidate${buy.length===1?'':'s'} · ${sell.length} holding${sell.length===1?'':'s'} to review for selling · ${cards.filter(c=>c.score!==null).length}/${cards.length} stocks analysed`;
 $('#llmStatus').textContent=`${r.model?r.model+' · ':''}${r.llm_status}. AI explains selected stocks; the same measured analysis runs on every stock.`;
 const busy=!!researchView.model_busy;$('#askButton').disabled=askingModel||busy;$('#askButton').textContent=busy&&!askingModel?'Local AI busy…':'Ask local AI';
 $('#commentary').textContent=r.commentary||(r.llm_status==='generating local briefing'?'Ollama is writing your briefing. The stock rankings and explorer are ready while you wait.':r.llm_status==='disabled'?'Enable local AI in Research settings for a written briefing.':'No AI briefing generated. See its status above.');
 $('#providerErrors').textContent=(r.errors||[]).length?`${r.errors.length} refresh error(s). Affected stocks may be excluded.\n`+r.errors.slice(0,8).join('\n')+(r.errors.length>8?'\nAdditional failures are included in scan coverage.':''):'';
 const filter=$('#adviceFilter').value,search=$('#stockSearch').value.trim().toLowerCase(),by=$('#rankBy').value||'composite';
 const eligible=cards.filter(c=>c.rank_eligible),metric=c=>by==='composite'?(c.composite==null?c.score:c.composite):((c.analyses||[]).find(a=>a.name===by)||{}).score;
 let filtered=cards.filter(c=>filter==='held'?c.held:filter==='buy'?(!c.held&&c.action==='Consider buying'):filter==='sell'?(c.held&&/selling|sell threshold|taking profits/.test(c.action)):filter==='top20'?c.rank_eligible:true);
 filtered.sort((a,b)=>(metric(b)==null?-1:metric(b))-(metric(a)==null?-1:metric(a))||a.symbol.localeCompare(b.symbol));
 if(filter==='top20')filtered=filtered.slice(0,20);
 filtered=filtered.filter(c=>(c.symbol+' '+(c.name||'')).toLowerCase().includes(search));
 $('#rankingCoverage').textContent=`${filtered.length} shown · ${eligible.length} eligible for ranking · ${cards.filter(c=>c.score===null).length} without sufficient data. Top-20 requires liquidity and volatility checks; a ranked stock is not necessarily a buy.`;
 $('#adviceCards').innerHTML=filtered.length?'<div class="tablewrap"><table class="ranktable"><thead><tr><th>Overall rank</th><th>Stock</th><th>Overall</th><th>Trend</th><th>Momentum</th><th>Risk</th><th>Timing</th><th>Liquidity</th><th>Action</th><th></th></tr></thead><tbody>'+filtered.map(c=>`<tr><td>${c.rank||'—'}</td><td><b>${esc(c.symbol)}</b><small>${esc(c.name||'')} ${c.held?'· Owned':''}</small></td><td><b>${c.composite==null?'—':c.composite.toFixed(1)}</b></td>${['Trend','Momentum','Risk','Timing','Liquidity'].map(name=>{const part=(c.analyses||[]).find(p=>p.name===name);return `<td>${part?part.score.toFixed(0):'—'}</td>`;}).join('')}<td><span class="signal ${c.action==='Consider buying'?'buy':''}">${esc(c.action)}</span></td><td><button data-inspect="${esc(c.symbol)}">Explore</button></td></tr>`).join('')+'</tbody></table></div>':'<div class="card">No stocks match this view. Try All analysed stocks, a different search, or wait for scan completion.</div>';
 // Keep detailed charts stable across background polling and tab changes.
 if(explorerSymbol){const selected=cards.find(c=>c.symbol===explorerSymbol);if(selected){renderStockDetail(selected);const cached=explorerCache[explorerSymbol];if(cached&&cached.asof!==selected.asof&&!explorerDrag)selectStock(explorerSymbol,false);}}
 else if(filtered.length&&filtered[0].score!==null){selectStock(filtered[0].symbol,false);}
 const compare=$('#compareStock'),previous=compare.value;compare.innerHTML='<option value="">No comparison</option>'+cards.filter(c=>c.score!==null&&c.symbol!==explorerSymbol).map(c=>`<option value="${esc(c.symbol)}">${esc(c.symbol)}</option>`).join('');compare.value=previous;
}
async function loadResearch(){try{researchView=await api('research');renderAdvice();}catch(e){$('#researchStatus').textContent=e.message;}}
$('#adviceFilter').onchange=renderAdvice;
$('#adviceCards').onclick=e=>{if(e.target.dataset.inspect)selectStock(e.target.dataset.inspect,true);};
$('#stockSearch').oninput=renderAdvice;$('#rankBy').onchange=renderAdvice;
$('#analyze').onclick=async()=>{try{await api('analyze',{});$('#researchStatus').textContent='Analysis queued; results will appear automatically.';setTimeout(loadResearch,1000);}catch(e){$('#researchStatus').textContent=e.message;}};
$('#researchSettings').onsubmit=async e=>{e.preventDefault();const f=e.target;try{await api('settings',{universe:f.elements.universe.value.split(',').map(s=>s.trim()).filter(Boolean),interval_minutes:Number(f.elements.interval_minutes.value),model:f.elements.model.value,min_turnover_nok:Number(f.elements.min_turnover_nok.value),llm_enabled:f.elements.llm_enabled.checked});$('#settingsMessage').textContent='Saved. New analysis queued.';await loadResearch();}catch(e){$('#settingsMessage').textContent=e.message;}};
$('#askForm').onsubmit=async e=>{e.preventDefault();askingModel=true;$('#askButton').disabled=true;$('#answer').textContent='Asking your local model…';try{const r=await api('ask',{question:$('#question').value});$('#answer').textContent=r.answer+'\n\n'+r.model+' · '+timeLabel(r.generated);}catch(e){$('#answer').textContent=e.message;}finally{askingModel=false;loadResearch();}};
for(const b of document.querySelectorAll('[data-tab]'))b.addEventListener('click',()=>{history.replaceState({},'','#'+b.dataset.tab);});
if(location.pathname==='/recommendations'||location.hash==='#recommendations'||location.hostname.endsWith('.github.io'))document.querySelector('[data-tab="recommendations"]').click();
let explorerSymbol='',explorerCache={},explorerWindow={start:0,end:1},explorerCompare='',explorerDrag=null,explorerLoad=0;
function currentHistory(){return (explorerCache[explorerSymbol]||{}).history||[];}
function renderStockDetail(c){
 $('#explorer').hidden=false;$('#explorerTitle').textContent=(c.name||c.symbol)+' · '+c.symbol;$('#explorerAction').textContent=c.action;
 $('#componentScores').innerHTML=(c.analyses||[]).map(p=>`<article><small>${esc(p.name)} · ${p.weight}% weight</small><strong>${p.score.toFixed(0)}<small>/100</small></strong><div class="scoretrack"><span style="width:${Math.max(0,Math.min(100,p.score))}%"></span></div><p>${esc(p.explanation)}</p></article>`).join('');
 $('#stockObservations').innerHTML='<ul>'+[...c.reasons,...(c.observations||[])].map(t=>'<li>'+esc(t)+'</li>').join('')+'</ul>';
}
async function selectStock(symbol,scroll){
 explorerSymbol=symbol;const token=++explorerLoad;const card=researchView&&researchView.report&&researchView.report.cards.find(c=>c.symbol===symbol);if(card)renderStockDetail(card);
 $('#chartPlot').innerHTML='<p>Loading daily price and volume history…</p>';$('#chartTooltip').textContent='';
 try{const quote=await api('history?symbol='+encodeURIComponent(symbol));if(token!==explorerLoad)return;explorerCache[symbol]=quote;const n=(quote.history||[]).length;explorerWindow={start:Math.max(0,n-252),end:Math.max(0,n-1)};explorerCompare='';$('#compareStock').value='';drawExplorer();if(scroll&&$('#explorer').scrollIntoView)$('#explorer').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){if(token===explorerLoad)$('#chartPlot').textContent=e.message;}
}
function drawExplorer(){
 const quote=explorerCache[explorerSymbol];if(!quote)return;const history=quote.history||[];
 if(history.length<2){$('#chartPlot').textContent='History unavailable. Refresh the scan and try again.';return;}
 explorerWindow=ChartKit.windowBounds(history.length,explorerWindow.start,explorerWindow.end);
 const overlays=[];if($('#show50').checked)overlays.push('ma50');if($('#show200').checked)overlays.push('ma200');if($('#showBands').checked)overlays.push('upper','lower');
 const compare=explorerCompare?(explorerCache[explorerCompare]||{}).history:null;
 $('#chartPlot').innerHTML=ChartKit.svg(history,{...explorerWindow,symbol:explorerSymbol,type:$('#chartType').value,panel:$('#chartPanel').value,percent:$('#showPercent').checked,overlays,compare});
 $('#chartFrom').value=new Date(history[explorerWindow.start].time*1000).toISOString().slice(0,10);$('#chartTo').value=new Date(history[explorerWindow.end].time*1000).toISOString().slice(0,10);
 const visible=history.slice(explorerWindow.start,explorerWindow.end+1),candlesMissing=$('#chartType').value==='candles'&&!visible.every(p=>p.open>0&&p.high>0&&p.low>0);
 $('#chartNote').textContent=`${quote.history_basis||'Provider daily close'} · ${quote.currency||'NOK'} · ${visible.length} daily observations · quote ${timeLabel(quote.asof)}. `+(candlesMissing?'OHLC data incomplete; displaying a price line. ':'')+(explorerCompare?'Comparison: '+explorerCompare+'; normalised to the displayed period. ':'')+'Charts show historical observations, not forecasts.';
}
function zoomExplorer(factor,anchor=.5){const h=currentHistory();if(h.length<2)return;const span=explorerWindow.end-explorerWindow.start,next=Math.max(5,Math.min(h.length-1,span*factor)),at=explorerWindow.start+span*anchor;explorerWindow=ChartKit.windowBounds(h.length,at-next*anchor,at+next*(1-anchor));drawExplorer();}
function initExplorer(){
 for(const id of ['chartType','chartPanel','show50','show200','showBands','showPercent'])$('#'+id).onchange=drawExplorer;
 $('#explorerRanges').onclick=e=>{if(!e.target.dataset.days)return;const h=currentHistory();if(!h.length)return;const limit=h[h.length-1].time-Number(e.target.dataset.days)*86400;let start=h.findIndex(p=>p.time>=limit);explorerWindow={start:Math.max(0,start),end:h.length-1};drawExplorer();};
 $('#zoomIn').onclick=()=>zoomExplorer(.7);$('#zoomOut').onclick=()=>zoomExplorer(1.4);$('#resetChart').onclick=()=>{const n=currentHistory().length;explorerWindow={start:Math.max(0,n-252),end:n-1};drawExplorer();};
 const dates=()=>{const h=currentHistory(),a=Date.parse($('#chartFrom').value+'T00:00:00Z')/1000,b=Date.parse($('#chartTo').value+'T23:59:59Z')/1000;if(!h.length||!Number.isFinite(a)||!Number.isFinite(b))return;const start=h.findIndex(p=>p.time>=a);let end=-1;h.forEach((p,i)=>{if(p.time<=b)end=i;});if(start<0||end<=start){$('#chartTooltip').textContent='Select at least two trading observations, with From before To.';return;}explorerWindow={start,end};drawExplorer();};
 $('#chartFrom').onchange=dates;$('#chartTo').onchange=dates;
 $('#compareStock').onchange=async()=>{const symbol=$('#compareStock').value;explorerCompare=symbol;if(!symbol){drawExplorer();return;}try{if(!explorerCache[symbol])explorerCache[symbol]=await api('history?symbol='+encodeURIComponent(symbol));drawExplorer();}catch(e){$('#chartTooltip').textContent=e.message;}};
 const plot=$('#chartPlot');const anchor=e=>{const r=plot.getBoundingClientRect();return Math.max(0,Math.min(1,((e.clientX-r.left)/r.width*900-76)/802));};
 plot.addEventListener('wheel',e=>{if(!currentHistory().length)return;e.preventDefault();zoomExplorer(e.deltaY>0?1.15:.85,anchor(e));},{passive:false});
 plot.addEventListener('pointerdown',e=>{if(!currentHistory().length)return;explorerDrag={x:e.clientX,start:explorerWindow.start,end:explorerWindow.end};plot.setPointerCapture(e.pointerId);});
 plot.addEventListener('pointermove',e=>{const h=currentHistory();if(!h.length)return;if(explorerDrag){const shift=Math.round((explorerDrag.x-e.clientX)/plot.getBoundingClientRect().width*(explorerDrag.end-explorerDrag.start));explorerWindow=ChartKit.windowBounds(h.length,explorerDrag.start+shift,explorerDrag.end+shift);drawExplorer();}
 const ratio=anchor(e),index=Math.round(explorerWindow.start+ratio*(explorerWindow.end-explorerWindow.start)),p=h[index];if(!p)return;$('#chartTooltip').textContent=new Date(p.time*1000).toLocaleDateString()+' · Close '+money(p.close,(explorerCache[explorerSymbol]||{}).currency||'NOK')+(p.open?' · Open '+p.open.toFixed(2)+' · High '+p.high.toFixed(2)+' · Low '+p.low.toFixed(2):'')+(p.volume!=null?' · Volume '+new Intl.NumberFormat('nb-NO').format(p.volume):'');const cursor=$('#explorerCursor');if(cursor){cursor.setAttribute('x1',76+ratio*802);cursor.setAttribute('x2',76+ratio*802);cursor.setAttribute('visibility','visible');}});
 const finish=()=>{explorerDrag=null;};plot.addEventListener('pointerup',finish);plot.addEventListener('pointercancel',finish);
 plot.addEventListener('keydown',e=>{if(e.key==='+'||e.key==='='){e.preventDefault();zoomExplorer(.7);}else if(e.key==='-'){e.preventDefault();zoomExplorer(1.4);}else if(e.key==='ArrowLeft'||e.key==='ArrowRight'){e.preventDefault();const shift=(e.key==='ArrowLeft'?-1:1)*Math.max(1,Math.round((explorerWindow.end-explorerWindow.start)/10));explorerWindow=ChartKit.windowBounds(currentHistory().length,explorerWindow.start+shift,explorerWindow.end+shift);drawExplorer();}});
 $('#resetUniverse').onclick=async()=>{try{const settings={...researchView.settings,universe:researchView.default_universe||researchView.settings.universe};await api('settings',settings);researchSettingsLoaded=false;await loadResearch();$('#settingsMessage').textContent='Broad universe restored. Scan queued.';}catch(e){$('#message').textContent=e.message;}};
}

initExplorer();
loadResearch();setInterval(()=>{loadResearch();load().catch(()=>{});},15000);
