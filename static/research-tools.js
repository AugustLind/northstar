/* Research tools stay within the four workspaces. All calculations are descriptive. */
let portfolioRiskRequest=0,systemStatusRequest=0,decisionRequest=0,stockDecisionSymbol='',stockDecisionLoaded=0;
const toolNumber=(v,suffix='',digits=1)=>Number.isFinite(v)?v.toFixed(digits)+suffix:'Unavailable';
const toolTile=(label,value,note='')=>'<article><small>'+esc(label)+'</small><strong>'+esc(value)+'</strong>'+(note?'<small>'+esc(note)+'</small>':'')+'</article>';
const toolTable=(headers,rows)=>'<table><thead><tr>'+headers.map(h=>'<th>'+esc(h)+'</th>').join('')+'</tr></thead><tbody>'+rows.map(row=>'<tr>'+row.map(v=>'<td>'+v+'</td>').join('')+'</tr>').join('')+'</tbody></table>';
const sourceLink=url=>/^https:\/\/newsweb\.oslobors\.no\/message\/\d+$/.test(url||'')||/^https:\/\/finance\.yahoo\.com\/quote\/[A-Za-z0-9.%^_-]+\/history\/$/.test(url||'')?url:'';

async function loadPortfolioRisk(){
 const token=++portfolioRiskRequest;
 const stock=Number($('#stockShock').value||-20),fx=Number($('#fxShock').value||-10);
 try{const v=await api('portfolio-risk?stock_shock='+encodeURIComponent(stock)+'&fx_shock='+encodeURIComponent(fx));if(token!==portfolioRiskRequest)return;renderPortfolioRisk(v);}
 catch(e){if(token===portfolioRiskRequest)$('#portfolioRiskStatus').textContent=e.message;}
}
function renderPortfolioRisk(v){
 $('#portfolioRiskStatus').textContent='Risk model: '+v.status+' · '+v.observations+' shared return intervals'+(v.from?' · '+new Date(v.from*1000).toISOString().slice(0,10)+' to '+new Date(v.to*1000).toISOString().slice(0,10):'')+'. '+(v.missing||[]).join(' ');
 const c=v.concentration||{},b=v.benchmark||{};
 $('#portfolioRiskMetrics').innerHTML=[
  toolTile('Portfolio volatility',toolNumber(v.volatility_pct,'%'),'Annualised, current NOK weights'),
  toolTile('Historical 95% daily VaR',toolNumber(v.var95_pct,'% loss'),'Sample loss percentile'),
  toolTile('Historical tail loss',toolNumber(v.tail95_pct,'% loss'),'Worst 5% probability mass'),
  toolTile('Proxy maximum drawdown',toolNumber(v.proxy_drawdown_pct,'%'),'Current weights; not account history'),
  toolTile('Largest company',toolNumber(c.largest_company_pct,'%'),'Known share classes combined'),
  toolTile('Effective equity companies',toolNumber(c.effective_equity_companies,'',2),'Inverse concentration; excludes cash'),
  toolTile('USD asset exposure',toolNumber(c.usd_asset_pct,'%'),'Current tracked NOK value'),
  toolTile('Beta to Oslo benchmark',toolNumber(b.beta,'×',2),(b.observations||0)+' matching intervals')
 ].join('');
 $('#riskContributions').innerHTML=(v.risk_contributions||[]).length?toolTable(['Holding','Weight incl. cash','Standalone volatility','Share of portfolio variance','Contribution to annual volatility'],v.risk_contributions.slice().sort((a,b)=>(b.risk_share_pct||0)-(a.risk_share_pct||0)).map(r=>[esc(r.symbol),esc(toolNumber(r.weight_pct,'%')),esc(toolNumber(r.annual_volatility_pct,'%')),esc(toolNumber(r.risk_share_pct,'%')),esc(toolNumber(r.volatility_contribution_pct,' percentage points'))])):'<p>Risk contributions require complete, aligned historical coverage.</p>';
 const matrix=v.correlations||[];
 $('#correlationNote').textContent=(v.matrix_note||'')+' Negative contributions can indicate hedging. Flat series have no defined correlation.';
 $('#correlationMatrix').innerHTML=matrix.length?toolTable(['Holding',...matrix.map(r=>r.symbol)],matrix.map(r=>[esc(r.symbol),...r.values.map(value=>'<span class="correlationcell" style="background:'+(value==null?'#f1f1ed':value>=0?'rgba(40,120,88,'+(Math.abs(value)*.35)+')':'rgba(188,75,73,'+(Math.abs(value)*.25)+')')+'">'+esc(toolNumber(value,'',2))+'</span>')])):'<p>No comparable full-portfolio sample.</p>';
 $('#portfolioRiskChart').innerHTML=(v.curve||[]).length>1?ChartKit.svg(v.curve,{symbol:'Current-weight historical proxy',percent:true,start:0,end:v.curve.length-1,panel:'drawdown',compact:window.innerWidth<=600}):'<p>No proxy curve available.</p>';
 $('#riskScenarios').innerHTML=(v.scenarios||[]).length?toolTable(['Hypothetical assumption','NOK change','Portfolio change','Value after shock'],v.scenarios.map(s=>[esc(s.label),esc(money(s.change_nok)),esc(toolNumber(s.change_pct,'%')),esc(money(s.after_nok))])):'<p>Complete current valuation is required to calculate shocks.</p>';
 $('#riskMethod').textContent=v.method;
}
$('#refreshPortfolioRisk').onclick=loadPortfolioRisk;
$('#riskScenarioForm').onsubmit=e=>{e.preventDefault();loadPortfolioRisk();};

async function loadStockDecision(symbol){
 if(stockDecisionSymbol===symbol&&Date.now()-stockDecisionLoaded<15000)return;
 if(stockDecisionSymbol!==symbol){$('#decisionStatus').textContent='Checking current signal and portfolio gates…';$('#decisionSummary').innerHTML='';}
 stockDecisionSymbol=symbol;stockDecisionLoaded=Date.now();const token=++decisionRequest;
 try{const v=await api('stock-summary?symbol='+encodeURIComponent(symbol));if(token!==decisionRequest||symbol!==explorerSymbol)return;renderStockDecision(v);}
 catch(e){if(token===decisionRequest){stockDecisionLoaded=0;$('#decisionStatus').textContent=e.message;}}
}
function renderStockDecision(v){
 const list=rows=>'<ul>'+(rows||[]).map(text=>'<li>'+esc(text)+'</li>').join('')+'</ul>';
 $('#decisionStatus').textContent=v.action+' · '+(v.current?(v.qualifies?'Qualifies for the technical entry screen.':'Does not currently qualify for the technical entry screen.'):'Current research required.')+' · Portfolio quantities checked '+new Date(v.generated*1000).toLocaleString()+'.';
 const p=v.portfolio||{};
 $('#decisionSummary').innerHTML='<article><h4>Why this signal?</h4>'+list(v.why)+'</article><article><h4>What could invalidate it?</h4>'+list(v.invalidation)+'</article><article><h4>Main measured risks</h4>'+list(v.risks)+'</article><article><h4>What fits my portfolio?</h4>'+list(['Confirmed buy quantity: '+(p.buy_shares||0)+' shares.',p.sell_shares==null?'Sale quantity unavailable / no held position.':'Sale-review quantity: '+p.sell_shares+' shares.',p.reason||'No current plan.',...(p.sale_reasons||[])])+'</article>';
 $('#decisionChecks').innerHTML=toolTable(['Entry condition','Current result'],(v.checks||[]).map(r=>[esc(r.label),r.passes==null?'Unavailable / stale':r.passes?'Pass':'Does not pass']));
 $('#decisionMethod').textContent=v.method;
}

const annualLabels={revenue:'Revenue',operating_margin:'Operating margin',net_margin:'Net margin',free_cash_flow:'Free cash flow',operating_cash_flow:'Operating cash flow',debt:'Debt',cash:'Cash',net_cash:'Cash minus debt',ordinary_shares:'Year-end shares',diluted_shares:'Diluted average shares',revenue_growth:'Revenue growth',fcf_margin:'Free cash flow margin',debt_to_equity:'Debt / equity',annual_pe_proxy:'Annual P/E proxy'};
function annualChart(rows,label){
 if(!rows||rows.length<2)return '<p>At least two comparable annual observations required.</p>';
 const amount=rows[0].unit==='amount';
 if(amount&&(!rows[0].currency||rows.some(r=>r.currency!==rows[0].currency)))return '<p>Currency changes or unknown currency prevent a comparable amount chart. See reported annual values.</p>';
 const W=480,H=185,L=65,R=15,T=20,B=145,values=rows.map(r=>r.value),lo=Math.min(0,...values),hi=Math.max(0,...values),span=hi-lo||1,times=rows.map(r=>Date.parse(r.period+'T00:00:00Z')),x=i=>L+(times[i]-times[0])/(times[times.length-1]-times[0]||1)*(W-L-R),y=v=>T+(hi-v)/span*(B-T),scale=Math.max(...values.map(Math.abs)),format=v=>Math.abs(scale)>=1e9?(v/1e9).toFixed(1)+'B':Math.abs(scale)>=1e6?(v/1e6).toFixed(1)+'M':Math.abs(scale)>=1e3?(v/1e3).toFixed(1)+'k':v.toFixed(1);
 let path='';for(let i=0;i<rows.length;i++){const gap=i>0&&(times[i]-times[i-1])/86400000>430;path+=(i&&!gap?' L':' M')+x(i).toFixed(2)+','+y(rows[i].value).toFixed(2);}
 return '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 '+W+' '+H+'" role="img" aria-label="'+esc(label)+' annual history"><title>'+esc(label)+' · '+esc(rows[0].currency||rows[0].unit)+'</title>'+[lo,(lo+hi)/2,hi].map(v=>'<line x1="'+L+'" x2="'+(W-R)+'" y1="'+y(v)+'" y2="'+y(v)+'" stroke="#dce4d7"/><text x="'+(L-8)+'" y="'+(y(v)+4)+'" text-anchor="end">'+format(v)+(rows[0].unit==='percent'?'%':'')+'</text>').join('')+'<path d="'+path+'" fill="none" stroke="#287858" stroke-width="2.5"/>'+rows.map((r,i)=>'<circle cx="'+x(i)+'" cy="'+y(r.value)+'" r="4" fill="#287858"><title>'+esc(r.period+': '+r.value+' '+(r.currency||r.unit)+(r.derived?' (derived)':''))+'</title></circle><text x="'+x(i)+'" y="172" text-anchor="'+(i===0?'start':i===rows.length-1?'end':'middle')+'">'+esc(r.period.slice(0,4))+'</text>').join('')+'</svg>';
}
function renderFinancialTrends(v){
 const annual=v.annual_series||{},keys=['revenue','operating_margin','free_cash_flow','operating_cash_flow','debt','cash',annual.ordinary_shares?'ordinary_shares':'diluted_shares'];
 $('#financialTrendStatus').textContent=(v.trends||[]).filter(t=>t.cagr_pct!=null).map(t=>t.label+' CAGR '+toolNumber(t.cagr_pct,'%')+' ('+t.from+' to '+t.to+').').join(' ')+' Annual figures are not point-in-time filing records; gaps and currency changes remain visible.';
 $('#financialTrendCharts').innerHTML=keys.map(key=>{const rows=annual[key]||[];return '<article><h4>'+esc(annualLabels[key]||key)+'</h4><small>'+esc(rows.length?(rows[0].currency||rows[0].unit)+' · fiscal periods':'No annual coverage')+'</small>'+annualChart(rows,annualLabels[key]||key)+'<details><summary>Annual values &amp; basis</summary>'+toolTable(['Fiscal period','Value','Basis'],rows.map(r=>[esc(r.period),esc(toolNumber(r.value,' '+(r.currency||r.unit),2)),r.derived?'Derived from same-period fields':'Provider annual observation']))+'</details></article>';}).join('');
 const peers=v.peer_comparison||{};
 $('#financialPeers').innerHTML=(peers.metrics||[]).length?toolTable(['Metric','Fiscal period','Company','Sector median','Other issuers','Magnitude percentile'],peers.metrics.map(r=>[esc(annualLabels[r.metric]||r.metric),esc(r.period),esc(toolNumber(r.subject,r.unit==='percent'?'%':'×',2)),esc(toolNumber(r.median,r.unit==='percent'?'%':'×',2)),String(r.peer_count),esc(toolNumber(r.percentile,'%',0))])):'<p>No comparable same-sector, same-period annual peer sample.</p>';
 $('#financialPeerMethod').textContent=(peers.sector?'Sector: '+peers.sector+'. ':'')+(peers.method||'Refresh company financials to load annual trend and peer comparisons.');
}

function performanceTiles(v){return [toolTile('Period return',toolNumber(v.return_pct,'%')),toolTile('Annual return (CAGR)',toolNumber(v.cagr_pct,'%'),'At least one calendar year required'),toolTile('Annual volatility',toolNumber(v.annual_volatility_pct,'%')),toolTile('Sharpe · zero rate',toolNumber(v.sharpe_zero_rate,'',2)),toolTile('Sortino · zero rate',toolNumber(v.sortino_zero_rate,'',2)),toolTile('Maximum drawdown',toolNumber(v.max_drawdown_pct,'%')),toolTile('Longest underwater spell',toolNumber(v.longest_underwater_sessions,' sessions',0)),toolTile('Average invested',toolNumber(v.average_invested_pct,'%'))].join('');}
function renderValidationDiagnostics(v){
 $('#validationMetrics').innerHTML=performanceTiles(v.performance||{})+toolTile('One-way turnover',toolNumber(v.one_way_turnover_pct,'%'),'Cumulative half gross traded weight');
 const r=v.robustness;$('#robustnessPanel').hidden=!r;
 if(!r)return;
 $('#robustnessStatus').textContent='Selected using training data: '+r.selected+'. Holdout starts '+new Date(r.split_date*1000).toISOString().slice(0,10)+'. Training '+toolNumber(r.training.return_pct,'%')+'; later holdout '+toolNumber(r.holdout.return_pct,'%')+'.';
 $('#holdoutMetrics').innerHTML=performanceTiles(r.holdout);
 $('#holdoutChart').innerHTML=ChartKit.svg(r.holdout_curve,{symbol:'Chronological holdout wealth',start:0,end:r.holdout_curve.length-1,percent:true,panel:'drawdown',compact:window.innerWidth<=600});
 $('#parameterSensitivity').innerHTML=toolTable(['Fixed variant','Training return','Training Sharpe','Holdout return','Holdout drawdown'],r.variants.map(x=>[esc(x.label),esc(toolNumber(x.training.return_pct,'%')),esc(toolNumber(x.training.sharpe_zero_rate,'',2)),esc(toolNumber(x.holdout.return_pct,'%')),esc(toolNumber(x.holdout.max_drawdown_pct,'%'))]));
 $('#costSensitivity').innerHTML='<h4>Selected variant with extra slippage</h4>'+toolTable(['Slippage each direction','Holdout return','Holdout drawdown','Whole-run costs'],r.cost_sensitivity.map(x=>[esc(x.cost_bps+' bps'),esc(toolNumber(x.holdout.return_pct,'%')),esc(toolNumber(x.holdout.max_drawdown_pct,'%')),esc(money(x.total_costs_nok))]));
 $('#robustnessMethod').textContent=r.method;
}

async function loadSystemStatus(){
 const token=++systemStatusRequest;
 try{const v=await api('system-status');if(token!==systemStatusRequest)return;renderSystemStatus(v);}
 catch(e){if(token===systemStatusRequest)$('#systemStatus').textContent=e.message;}
}
function renderSystemStatus(v){
 $('#systemStatus').textContent=(v.state==='ready'?'Services and data checks ready.':'Some services or data need attention.')+' Updated '+new Date(v.generated*1000).toLocaleString()+' · Process uptime '+Math.floor(v.uptime_seconds/60)+' minutes.';
 $('#systemComponents').innerHTML=(v.components||[]).map(c=>'<article><div><strong>'+esc(c.label)+'</strong><span class="healthbadge '+(c.state==='ready'?'healthy':c.state==='running'?'working':'attention')+'">'+esc(c.state)+'</span></div><p>'+esc(c.detail)+'</p><small>'+(c.last_success?'Last success: '+esc(new Date(c.last_success*1000).toLocaleString())+'. ':'')+esc(c.action)+'</small></article>').join('');
 $('#workerStatus').innerHTML=toolTable(['Worker','Process state'],(v.workers||[]).map(w=>[esc(w.name),esc(w.state)]));
 $('#emailHistory').innerHTML=(v.email_history||[]).length?toolTable(['Created','Kind / stock','State','Attempts','Next retry / accepted','Result'],v.email_history.map(e=>[esc(new Date(e.created*1000).toLocaleString()),esc(e.kind+(e.symbol?' · '+e.symbol:'')),esc(e.status==='sent'?'Accepted by SMTP':e.status),String(e.attempts),esc(e.sent?new Date(e.sent*1000).toLocaleString():e.status==='pending'&&e.next_attempt?new Date(e.next_attempt*1000).toLocaleString():'—'),esc(e.last_error||'')])):'<p>No email events for the current configured destination. Configure email and send a test from Overview to verify SMTP acceptance.</p>';
}
$('#refreshSystemStatus').onclick=loadSystemStatus;

// Persist chart appearance only; credentials and portfolio records are never stored here.
const chartPreferenceKey='northstar-chart-preferences-v1';
let savedChartPreferences={};
function chartPreferenceDays(){return [31,93,186,370,740,100000].includes(savedChartPreferences.days)?savedChartPreferences.days:370;}
function restoreChartPreferences(){
 try{savedChartPreferences=JSON.parse(window.localStorage.getItem(chartPreferenceKey)||'{}')||{};}catch(e){savedChartPreferences={};}
 if(['line','candles'].includes(savedChartPreferences.type))$('#chartType').value=savedChartPreferences.type;
 if(['volume','rsi','macd','drawdown','volatility','relative'].includes(savedChartPreferences.panel))$('#chartPanel').value=savedChartPreferences.panel;
 for(const id of ['show20','show50','show200','showBands','showPercent','showLog','showEvents'])if(typeof savedChartPreferences[id]==='boolean')$('#'+id).checked=savedChartPreferences[id];
 if($('#showPercent').checked)$('#showLog').checked=false;
}
function saveChartPreferences(){
 const values={type:$('#chartType').value,panel:$('#chartPanel').value,days:chartPreferenceDays(),benchmark:$('#compareStock').value==='OSEBX.OL'};
 for(const id of ['show20','show50','show200','showBands','showPercent','showLog','showEvents'])values[id]=!!$('#'+id).checked;
 savedChartPreferences=values;try{window.localStorage.setItem(chartPreferenceKey,JSON.stringify(values));}catch(e){}
}
async function restoreBenchmark(){
 if(!savedChartPreferences.benchmark||!explorerSymbol)return;
 $('#compareStock').value='OSEBX.OL';explorerCompare='OSEBX.OL';
 try{if(!explorerCache['OSEBX.OL'])explorerCache['OSEBX.OL']=await api('history?symbol=OSEBX.OL');drawExplorer();}catch(e){$('#comparisonStats').textContent='Oslo benchmark unavailable: '+e.message;}
}
function currentStockEvents(){
 if(!$('#showEvents').checked)return [];
 return [...((explorerCache[explorerSymbol]||{}).events||[]),...(explorerEvents[explorerSymbol]||[])].filter(e=>Number.isFinite(e.time)&&sourceLink(e.source_url));
}
function renderEventSources(){
 const events=currentStockEvents().slice().sort((a,b)=>a.time-b.time),h=currentHistory(),windowStart=h[explorerWindow.start],windowEnd=h[explorerWindow.end];
 const visible=events.filter(e=>(windowStart&&windowEnd&&e.time>=windowStart.time-86400&&e.time<=windowEnd.time+86400)||e.time>Date.now()/1000).slice(-30);
 $('#chartEventSources').innerHTML=visible.length?'<p>D = provider dividend/ex-date · S = provider split · E = issuer-stated earnings/reporting event. Only events on observed chart dates receive markers.</p>'+toolTable(['Source date','Event','Source'],visible.map(e=>[esc(new Date(e.time*1000).toISOString().slice(0,10)),esc(e.label),'<a href="'+esc(sourceLink(e.source_url))+'" target="_blank" rel="noopener noreferrer">'+esc(e.source||'View source')+' ↗</a>'])):'<p>No sourced events in this period or upcoming covered notices. Refresh market data and issuer notices for updated coverage.</p>';
}
function downloadResearch(name,text,type){
 const url=URL.createObjectURL(new Blob([text],{type})),link=document.createElement('a');link.href=url;link.download=name;document.body.appendChild(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
}
$('#exportChartCSV').onclick=()=>{const h=currentHistory();if(h.length)downloadResearch(explorerSymbol+'-daily-analysis.csv',ChartKit.csv(h,explorerWindow),'text/csv;charset=utf-8');};
$('#exportChartSVG').onclick=()=>{const svg=$('#chartPlot').querySelector('svg');if(svg){const copy=svg.cloneNode(true),style=document.createElementNS('http://www.w3.org/2000/svg','style');style.textContent='text{font-family:system-ui,sans-serif;font-size:'+(window.innerWidth<=600?16:11)+'px;fill:#5c6f63}';copy.insertBefore(style,copy.firstChild);downloadResearch(explorerSymbol+'-chart.svg',copy.outerHTML,'image/svg+xml');}};
restoreChartPreferences();
for(const id of ['chartType','chartPanel','show20','show50','show200','showBands','showPercent','showLog','showEvents','compareStock'])$('#'+id).addEventListener('change',()=>{saveChartPreferences();if(id==='showEvents')drawExplorer();});
$('#explorerRanges').addEventListener('click',e=>{if(e.target.dataset.days){savedChartPreferences.days=Number(e.target.dataset.days);saveChartPreferences();}});
$('#resetChart').addEventListener('click',()=>{savedChartPreferences.days=370;saveChartPreferences();});
loadSystemStatus();
if(!$('#portfolio').hidden)loadPortfolioRisk();
setInterval(()=>{if(!$('#daily').hidden)loadSystemStatus();},60000);
