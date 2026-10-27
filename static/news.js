let newsView=null,newsRequest=0,stockNewsRequest=0;
const newsDate=t=>t?new Intl.DateTimeFormat('en-GB',{dateStyle:'medium',timeStyle:'short',timeZone:'Europe/Oslo'}).format(new Date(t*1000))+' Oslo time':'Unknown publication time';
const officialNoticeUrl=url=>/^https:\/\/newsweb\.oslobors\.no\/message\/\d+$/.test(url||'')?url:'';
function noticeCard(item,reviewed=0){
 const link=officialNoticeUrl(item.url),tag=item.classification||{},superseded=!!item.corrected_by;
 return `<article class="notice ${superseded?'superseded':''}"><div class="noticehead"><b>${esc(item.symbol)}</b><span class="officialbadge">NewsWeb issuer notice</span>${item.first_seen>reviewed?'<span class="newbadge">New since reviewed</span>':''}<span>${newsDate(item.published)}</span></div><h3>${link?'<a href="'+link+'" target="_blank" rel="noopener noreferrer">'+esc(item.title)+' ↗</a>':esc(item.title)}</h3><p><span class="signal">${esc(tag.label||'Issuer notice')}</span> ${tag.priority>=3?'<strong class="reviewflag">Review flagged</strong>':''}</p>${superseded?'<p class="correction">Superseded by <a href="https://newsweb.oslobors.no/message/'+Number(item.corrected_by)+'" target="_blank" rel="noopener noreferrer">correction '+Number(item.corrected_by)+'</a>. Read the replacement.</p>':''}${item.correction_for?'<p class="correction">Correction to notice '+Number(item.correction_for)+'.</p>':''}<p><b>Why review:</b> ${esc(tag.why||'Read the linked source for context.')}</p>${(item.categories||[]).length?'<small>Source categories: '+esc(item.categories.join(' · '))+'</small>':''}</article>`;
}
function calendarRows(events){return events.length?'<div class="tablewrap"><table><thead><tr><th>Stated event date</th><th>Stock</th><th>Event</th><th>Source</th></tr></thead><tbody>'+events.map(e=>`<tr><td>${esc(e.date)}</td><td>${esc(e.symbol)}</td><td>${esc(e.label)}</td><td>${officialNoticeUrl(e.source_url)?'<a href="'+officialNoticeUrl(e.source_url)+'" target="_blank" rel="noopener noreferrer">Issuer notice ↗</a>':'Unavailable'}</td></tr>`).join('')+'</tbody></table></div>':'<p>No confirmed upcoming reporting dates were extracted from the covered notices. This does not establish that no event is scheduled.</p>';}
function renderAnnouncements(){
 if(!newsView)return;const n=newsView,c=n.counts||{},available=n.status!=='unavailable';
 $('#newsStatus').textContent=`Feed: ${n.status||'unavailable'} · Last successful check: ${n.fetched?newsDate(n.fetched):'not yet'} · Window: ${n.from||'unknown'} to ${n.to||'unknown'}. `+(n.partial?'Coverage is partial. ':'')+(n.error?'Latest refresh: '+n.error+' ':'')+(n.progress&&n.progress.running?'Refresh in progress. ':'')+`${(n.focus_symbols||[]).length} companies in this view.`+(n.calendar_pending?` ${n.calendar_pending} calendar notice(s) have no completed date extraction yet.`:'');
 $('#newsSummary').textContent=n.summary||'Announcement feed is not ready yet.';
 $('#newsCount').textContent=available?(c.last24h||0):'—';$('#newsPriority').textContent=available?(c.priority_review||0):'—';$('#newsEarnings').textContent=available?(c.earnings||0):'—';
 $('#newsDigest').innerHTML=(n.last24h||[]).slice(0,8).map(item=>noticeCard(item,n.reviewed_at||0)).join('')||'<p>No matching notices in the last 24 hours of available data. Check source status before interpreting an empty feed.</p>';
 $('#newsCalendar').innerHTML=calendarRows(n.events||[]);
 const category=$('#newsCategory').value||'all',days=Number($('#newsPeriod').value)||7,limit=Date.now()/1000-days*86400;
 const items=(n.items||[]).filter(i=>i.published>=limit&&(category==='all'||(i.classification||{}).kind===category));
 $('#newsItems').innerHTML=items.slice(0,50).map(i=>noticeCard(i,n.reviewed_at||0)).join('')||'<p>No matching retained notices in this filter.</p>';
 $('#newsCoverage').textContent=`${Math.min(items.length,50)} shown from ${items.length} matching returned notices. ${n.total||0} retained notices match these companies; the API returns the newest 100. Source coverage is bounded, not a complete archive. Headlines are topic-tagged by rules; no full report or attachment interpretation is performed.`;
}
async function loadAnnouncements(){
 const token=++newsRequest;
 try{const n=await api('announcements?scope='+encodeURIComponent($('#newsScope').value||'focus'));if(token!==newsRequest)return;newsView=n;renderAnnouncements();}catch(e){if(token===newsRequest)$('#newsStatus').textContent=e.message;}
}
async function loadStockAnnouncements(symbol){
 const token=++stockNewsRequest;
 try{const n=await api('announcements?symbol='+encodeURIComponent(symbol));if(token!==stockNewsRequest||symbol!==explorerSymbol)return;
 const aliases=Object.entries(n.issuer_aliases||{}).map(([s,issuer])=>s+' uses company issuer '+issuer).join('; ');
 $('#stockNewsStatus').textContent=`NewsWeb coverage: ${n.status}. Last successful check: ${n.fetched?newsDate(n.fetched):'not yet'}. `+(n.error||'')+(aliases?' '+aliases+'.':'');
 $('#stockNewsItems').innerHTML=(n.items||[]).slice(0,5).map(i=>noticeCard(i,n.reviewed_at||0)).join('')||'<p>No matching company notices were found in the covered data. This does not mean the company has issued no announcements.</p>';
 $('#stockNewsCalendar').innerHTML=calendarRows(n.events||[]);
 }catch(e){if(token===stockNewsRequest)$('#stockNewsStatus').textContent=e.message;}
}
$('#newsScope').onchange=loadAnnouncements;$('#newsCategory').onchange=renderAnnouncements;$('#newsPeriod').onchange=renderAnnouncements;
$('#refreshNews').onclick=async()=>{try{const r=await api('announcements/refresh',{});$('#newsStatus').textContent=r.queued?'Announcement refresh queued. Results update automatically.':r.message;}catch(e){$('#newsStatus').textContent=e.message;}};
$('#reviewedNews').onclick=async()=>{try{await api('announcements/reviewed',{});await loadAnnouncements();}catch(e){$('#newsStatus').textContent=e.message;}};
loadAnnouncements();setInterval(loadAnnouncements,60000);
