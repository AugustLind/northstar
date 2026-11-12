let state={positions:[],quotes:{}};
const $=s=>document.querySelector(s), money=(v,c='NOK')=>new Intl.NumberFormat('nb-NO',{style:'currency',currency:c,maximumFractionDigits:2}).format(v);
const esc=v=>String(v == null ? '' : v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fresh=q=>q&&Number.isFinite(q.price)&&q.price>0&&Date.now()/1000-q.asof<4*86400&&q.asof<=Date.now()/1000+300;
let apiBase=window.NORTHSTAR_CONFIG&&window.NORTHSTAR_CONFIG.apiBase||'', accessKey='';
try{apiBase=sessionStorage.getItem('northstar-api')||apiBase;accessKey=sessionStorage.getItem('northstar-key')||'';}catch(e){}
function showConnection(message=''){ $('#connectionPanel').hidden=false;$('#backendAddress').value=apiBase;$('#connectionMessage').textContent=message; }
async function api(path,data){
 if(location.hostname.endsWith('.github.io')&&!apiBase){showConnection('Set your Oracle HTTPS server address to connect.');throw Error('Connect to your Oracle server first.');}
 const headers={};if(accessKey)headers.Authorization='Bearer '+accessKey;
 const options={headers,credentials:'omit'};if(data!==undefined){options.method='POST';headers['Content-Type']='application/json';options.body=JSON.stringify(data);}
 let r;try{r=await fetch(apiBase+'/api/'+path,options);}catch(e){throw Error('Cannot reach Oracle. Check its HTTPS address, server status and allowed Pages origin.');}
 const body=await r.json();if(r.status===401)showConnection(body.error);if(!r.ok)throw Error(body.error||'Request failed');return body;
}
$('#connectionButton').onclick=()=>showConnection();
$('#disconnect').onclick=()=>{accessKey='';try{sessionStorage.removeItem('northstar-key');}catch(e){}$('#accessKey').value='';state={positions:[],quotes:{}};render();$('#adviceCards').innerHTML='';$('#commentary').textContent='';$('#answer').textContent='';showConnection('Signed out.');location.reload();};
$('#connectionForm').onsubmit=async e=>{e.preventDefault();const address=$('#backendAddress').value.trim().replace(/\/$/,'');try{if(address){const u=new URL(address);if(u.protocol!=='https:'||u.pathname!=='/'||u.username||u.password||u.search||u.hash)throw Error('Use an HTTPS server origin, such as https://northstar.example.com.');}else if(location.hostname.endsWith('.github.io'))throw Error('An HTTPS Oracle address is required.');apiBase=address;accessKey=$('#accessKey').value.trim();await api('state');try{sessionStorage.setItem('northstar-api',apiBase);sessionStorage.setItem('northstar-key',accessKey);}catch(e){}$('#accessKey').value='';$('#connectionPanel').hidden=true;$('#message').textContent='Connected to Oracle.';await load();if(typeof loadResearch==='function')await loadResearch();}catch(e){$('#connectionMessage').textContent=e.message;}};
function render(){
 const {positions,quotes}=state,fx=quotes['NOK=X'];let total=0,priced=0;const values={},alerts=[];
 const held=positions.filter(p=>p.shares>0);
 for(const p of positions){const q=quotes[p.symbol];if(p.shares>0&&fresh(q)&&q.currency===p.currency&&(p.currency==='NOK'||(fresh(fx)&&fx.currency==='NOK'))){values[p.symbol]=q.price*p.shares*(p.currency==='USD'?fx.price:1);total+=values[p.symbol];priced++;}}
 $('#value').textContent=priced?money(total):'—';$('#count').textContent=held.length;
 $('#coverage').textContent=`${priced} / ${held.length} holdings priced. ${priced<held.length?'Incomplete total.':''}${fresh(fx)?' USD/NOK: '+fx.price.toFixed(4)+' · '+new Date(fx.asof*1000).toLocaleDateString():''}`;
 $('#holdings').innerHTML=positions.length?positions.map(p=>{const q=quotes[p.symbol],valid=q&&q.currency===p.currency;const gain=valid&&p.cost>0?(q.price/p.cost-1)*100:null;return `<tr><td><b>${esc(p.symbol)}</b><small>${p.shares?'Holding':'Watchlist'} · ${esc(p.currency)}</small></td><td>${p.shares}<small>${money(p.cost,p.currency)}</small></td><td>${valid?money(q.price,p.currency):'Unavailable'}<small>${valid?(fresh(q)?'Provider quote':'Stale · excluded from total'):'Refresh or check ticker/currency'}</small></td><td class="${gain>=0?'positive':'negative'}">${gain===null?'—':gain.toFixed(2)+'%'}</td><td>${q?esc(new Date(q.asof*1000).toLocaleString()):'Not fetched'}<small>${q?esc(q.source):'No data'}</small></td><td><button data-edit="${esc(p.symbol)}">Edit</button> <button data-delete="${esc(p.symbol)}">Remove</button></td></tr>`;}).join(''):'<tr><td colspan="6">Your notebook is empty. Add your first holding or watchlist company.</td></tr>';
 for(const p of positions){const q=quotes[p.symbol],items=[];if(!fresh(q)||q.currency!==p.currency)items.push('Current usable data unavailable. Refresh quotes and check the selected trading currency.');else{if(p.below!==null&&q.price<=p.below)items.push(`Price ${money(q.price,p.currency)} is at or below your review level ${money(p.below,p.currency)}.`);if(p.above!==null&&q.price>=p.above)items.push(`Price ${money(q.price,p.currency)} is at or above your review level ${money(p.above,p.currency)}.`);if(q.ma200&&q.price<q.ma200)items.push(`Price is below its 200-session average (${money(q.ma200,p.currency)}). Review the business case before acting on this trend.`);const ctx=state.portfolio_context,limit=(state.portfolio_preferences||{}).max_stock_pct;const h=ctx&&(ctx.holdings||[]).find(h=>h.symbol===(p.currency==='NOK'&&!p.symbol.includes('.')?p.symbol+'.OL':p.symbol));if(h&&h.weight_pct!=null&&h.weight_pct>limit)items.push(`Represents ${h.weight_pct.toFixed(1)}% of tracked holdings plus cash, above your ${limit}% position limit.`);}if(items.length){alerts.push(`<article class="card"><h2>${esc(p.symbol)}</h2>${items.map(t=>`<p>${esc(t)}</p>`).join('')}<p><b>Your thesis:</b> ${esc(p.thesis||'No thesis recorded.')}</p><p><b>Reconsider when:</b> ${esc(p.review||'No conditions recorded.')}</p><a target="_blank" rel="noopener noreferrer" href="https://finance.yahoo.com/quote/${encodeURIComponent(p.symbol)}/news/">Research company news ↗</a><p class="muted">External research link; news is not analysed by this app.</p></article>`);}}
 $('#alertsCount').textContent=alerts.length;$('#alerts').innerHTML=alerts.join('')||'<article class="card">No rules triggered. This does not establish that a stock is a good investment. Review company reports and your thesis regularly.</article>';
}
async function load(){state=await api('state');render();}
function edit(p={symbol:'',currency:'NOK',shares:0,cost:0,below:'',above:'',thesis:'',review:''}){const f=$('#positionForm');f.reset();for(const [k,v] of Object.entries(p))if(f.elements.namedItem(k))f.elements.namedItem(k).value=v == null ? '' : v;f.elements.symbol.readOnly=!!p.symbol;$('#formError').textContent='';$('#editor').showModal();}
$('#add').onclick=()=>edit();$('#close').onclick=()=>$('#editor').close();
$('#positionForm').onsubmit=async e=>{e.preventDefault();try{await api('position',Object.fromEntries(new FormData(e.target)));$('#editor').close();await load();}catch(e){$('#formError').textContent=e.message;}};
$('#holdings').onclick=async e=>{const editSymbol=e.target.dataset.edit,del=e.target.dataset.delete;if(editSymbol)edit(state.positions.find(p=>p.symbol===editSymbol));if(del&&confirm(`Remove ${del} and its notes?`)){try{await api('delete',{symbol:del});await load();}catch(e){$('#message').textContent=e.message;}}};
$('#refresh').onclick=async()=>{const b=$('#refresh');b.disabled=true;b.textContent='Refreshing…';$('#message').textContent='Fetching quotes. This may take a moment.';try{const r=await api('refresh',{});await load();$('#message').textContent=r.errors.length?r.errors.join('\n'):'Refresh complete. Check provider timestamps before making a decision.';}catch(e){$('#message').textContent=e.message;}finally{b.disabled=false;b.textContent='Refresh market data';}};
const workspaceRoutes={daily:'daily',announcements:'daily',briefing:'daily',method:'daily',recommendations:'recommendations',portfolio:'portfolio',fit:'portfolio',activity:'portfolio',validation:'validation'};
function openWorkspace(target,updateHash=true){
 if(!Object.prototype.hasOwnProperty.call(workspaceRoutes,target))target='daily';
 const page=workspaceRoutes[target]||'daily';
 for(const section of document.querySelectorAll('.tab'))section.hidden=section.id!==page;
 for(const button of document.querySelectorAll('[data-tab]')){const active=button.dataset.tab===page;button.classList.toggle('active',active);if(active)button.setAttribute('aria-current','page');else button.removeAttribute('aria-current');}
 if(target!==page){const group=$('#'+target+'Group');if(group)group.open=true;const section=$('#'+target);if(section&&section.scrollIntoView)section.scrollIntoView({behavior:'smooth',block:'start'});}
 if(updateHash&&typeof history!=='undefined'&&history.replaceState)history.replaceState({},'','#'+target);
 if(page==='daily'){if(typeof loadDaily==='function')loadDaily();if(typeof loadSystemStatus==='function')loadSystemStatus();}
 if(page==='portfolio'){if(typeof loadPortfolioRisk==='function')loadPortfolioRisk();if(typeof loadPortfolioFit==='function')loadPortfolioFit();if(typeof loadLedger==='function')loadLedger();if(typeof loadQuantityPlan==='function')loadQuantityPlan();}
 if(page==='validation'&&typeof loadValidation==='function')loadValidation();
}
for(const button of document.querySelectorAll('[data-tab]'))button.onclick=()=>openWorkspace(button.dataset.tab);
if(window.addEventListener)window.addEventListener('hashchange',()=>openWorkspace(location.hash.slice(1),false));

$('#export').onclick=()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(state,null,2)],{type:'application/json'}));const a=document.createElement('a');a.href=url;a.download='northstar-notebook.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
load().catch(e=>$('#message').textContent=e.message);
