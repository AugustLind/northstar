/* Notification permission is requested only by the user's explicit button click. */
let dailyView=null,dailyRequest=0;
function safeDailyLink(url){return typeof officialNoticeUrl==='function'?officialNoticeUrl(url):'';}
function renderEmailStatus(v){
 if(!v)return;
 if(dailyView)dailyView.email=v;
 $('#emailStatus').textContent=(!v.configured?'Email is not configured on the server. '+(v.configuration_errors||[]).join(' ')+' Run python3 scripts/setup-email.py on the server, then restart Northstar.':v.server_enabled===false?'Email delivery is disabled in the server settings.':!v.enabled?'Email alerts are paused.':'Email alerts are enabled and work with this page closed. '+v.pending+' update(s) waiting.')+(v.last_sent?' Last accepted by the mail server: '+new Date(v.last_sent*1000).toLocaleString()+'.':'')+(v.error?' '+v.error:'');
 $('#enableEmail').disabled=!v.configured||v.server_enabled===false||v.enabled;$('#pauseEmail').disabled=!v.enabled;$('#testEmail').disabled=!v.active;
}
function renderDaily(v){
 dailyView=v;$('#dailyStatus').textContent='Updated '+new Date(v.generated*1000).toLocaleString()+' · '+(v.coverage.analysed||0)+' / '+(v.coverage.requested||0)+' stocks analysed · Announcement feed '+v.announcement_status+'.';
 $('#dailyTop').innerHTML=v.top3.length?v.top3.map((r,i)=>'<article class="card"><p class="eyebrow">REVIEW '+(i+1)+' · '+esc(r.kind)+'</p><h2>'+esc(r.title)+'</h2><p>'+esc(r.detail)+'</p>'+(safeDailyLink(r.url)?'<a target="_blank" rel="noopener noreferrer" href="'+safeDailyLink(r.url)+'">Read issuer source ↗</a>':'')+(r.symbol?'<button type="button" data-daily-stock="'+esc(r.symbol)+'">Explore company</button>':'')+'</article>').join(''):'<p>No priority review was generated. Check coverage before treating an empty list as reassurance.</p>';
 $('#dailyChanges').innerHTML=v.changes.length?'<div class="tablewrap"><table><thead><tr><th>Stock</th><th>Change</th><th>Direction / shares</th></tr></thead><tbody>'+v.changes.map(r=>'<tr><td>'+esc(r.symbol)+'</td><td>'+esc(r.change)+'</td><td>'+esc(r.direction)+' · '+esc(r.shares)+'</td></tr>').join('')+'</tbody></table></div>':'<p>Changes will appear after the next completed scan. Polling does not count as a new signal observation.</p>';
 $('#dailyAlerts').innerHTML=v.alerts.slice(0,30).map(a=>'<article class="notice"><b>'+esc(a.title)+'</b><p>'+esc(a.detail)+'</p><small>'+new Date(a.first_seen*1000).toLocaleString()+' · '+(a.read?'Read':'Unread')+'</small></article>').join('')||'<p>No retained alerts.</p>';
 $('#dailyMethod').textContent=v.method;
 renderEmailStatus(v.email);
 let enabled=false;try{enabled=sessionStorage.getItem('northstar-notifications')==='on';}catch(e){}
 $('#notificationStatus').textContent=enabled?'Desktop notifications enabled for this tab. Keep it open for updates.':'Dashboard alerts are active. Desktop notifications are optional and require this tab to stay open.';
 if(enabled&&typeof Notification!=='undefined'&&Notification.permission==='granted'){
  let seen=[];try{seen=JSON.parse(sessionStorage.getItem('northstar-notified')||'[]');}catch(e){}
  const fresh=v.alerts.filter(a=>!a.read&&!seen.includes(a.id)&&Date.now()/1000-a.first_seen<86400);
  for(const a of fresh.slice(0,3))new Notification('Northstar review',{body:a.title,tag:'northstar-'+a.id});
  try{sessionStorage.setItem('northstar-notified',JSON.stringify(Array.from(new Set(seen.concat(v.alerts.map(a=>a.id)))).slice(-300)));}catch(e){}
 }
}
async function loadDaily(){const token=++dailyRequest;try{const v=await api('daily');if(token===dailyRequest)renderDaily(v);}catch(e){if(token===dailyRequest)$('#dailyStatus').textContent=e.message;}}
$('#refreshDaily').onclick=loadDaily;
$('#markAlertsRead').onclick=async()=>{if(!dailyView)return;try{await api('alerts/read',{ids:dailyView.alerts.map(a=>a.id)});await loadDaily();}catch(e){$('#dailyStatus').textContent=e.message;}};
$('#enableNotifications').onclick=async()=>{if(typeof Notification==='undefined'){$('#notificationStatus').textContent='This browser does not support desktop notifications.';return;}try{const permission=await Notification.requestPermission();if(permission==='granted'){sessionStorage.setItem('northstar-notifications','on');await loadDaily();}else $('#notificationStatus').textContent='Permission was not granted; dashboard alerts remain available.';}catch(e){$('#notificationStatus').textContent=e.message;}};
$('#disableNotifications').onclick=()=>{try{sessionStorage.removeItem('northstar-notifications');}catch(e){}$('#notificationStatus').textContent='Desktop notifications disabled. Dashboard alerts remain active.';};
async function emailSetting(enabled){try{const v=await api('email/settings',{enabled});renderEmailStatus(v);$('#emailActionMessage').textContent=enabled?'Email alerts enabled.':'Email alerts paused. A message already being sent may still arrive.';}catch(e){$('#emailActionMessage').textContent=e.message;}}
$('#enableEmail').onclick=()=>emailSetting(true);
$('#pauseEmail').onclick=()=>emailSetting(false);
$('#testEmail').onclick=async()=>{const b=$('#testEmail');b.disabled=true;try{const r=await api('email/test',{});$('#emailActionMessage').textContent=r.message;}catch(e){$('#emailActionMessage').textContent=e.message;}finally{if(dailyView&&dailyView.email)renderEmailStatus(dailyView.email);}};
$('#dailyTop').onclick=e=>{const symbol=e.target.dataset.dailyStock;if(!symbol)return;document.querySelector('[data-tab="recommendations"]').click();if(typeof selectStock==='function')selectStock(symbol,true);};
setInterval(()=>{if(apiBase&&accessKey)loadDaily();},60000);
