/* Experiments are kept separate from the real portfolio. */
async function loadValidation(){
 try{const v=await api('validation');renderValidation(v.historical);const p=v.paper;
 $('#paperMethod').textContent=p.method;
 $('#paperResults').innerHTML=p.snapshots.length?p.snapshots.map(s=>'<article class="card"><h3>'+escapeHtml(new Date(s.captured*1000).toLocaleString())+'</h3><p>'+s.measured+' / '+s.symbols.length+' outcomes measurable · '+(s.return_pct==null?'Cohort pending':s.return_pct.toFixed(2)+'% after assumed costs')+'</p><div class="tablewrap"><table><thead><tr><th>Saved stock</th><th>Saved action</th><th>Later entry close</th><th>Return after costs</th></tr></thead><tbody>'+s.symbols.map(r=>'<tr><td>'+escapeHtml(r.symbol)+'</td><td>'+escapeHtml(r.action||'')+'</td><td>'+(r.entry==null?'Pending':r.entry.toFixed(2))+'</td><td>'+(r.return_pct==null?'Pending':r.return_pct.toFixed(2)+'%')+'</td></tr>').join('')+'</tbody></table></div></article>').join(''):'<p>The next completed market scan will save the first dated cohort. Outcomes require later market sessions.</p>';
 }catch(e){$('#validationStatus').textContent=e.message;}
}
function renderValidation(v){
 if(!v){$('#validationStatus').textContent='No historical experiment yet. Run after market histories have downloaded.';return;}
 $('#validationStatus').textContent='Saved experiment: '+new Date(v.generated*1000).toLocaleString()+' · '+v.stocks+' / '+v.requested+' stocks · '+v.sessions+' common sessions · '+v.decisions+' decisions · '+v.trades+' simulated weight changes.';
 $('#validationSummary').textContent='Strategy '+v.return_pct.toFixed(2)+'% · Same-basket buy and hold '+v.benchmark_pct.toFixed(2)+'% · Maximum drawdown '+v.max_drawdown_pct.toFixed(2)+'% · Costs '+v.cost_pct_initial.toFixed(2)+'% of initial capital.';
 $('#validationLimits').textContent=v.limits;
 $('#validationChart').innerHTML=ChartKit.svg(v.curve,{symbol:'Strategy equity (green), same-basket benchmark (orange)',start:0,end:v.curve.length-1,percent:true,compare:v.curve.map(p=>({time:p.time,close:p.benchmark})),panel:'volume'});
 $('#validationPoints').innerHTML='<summary>Daily values (start = 100)</summary><div class="tablewrap"><table><thead><tr><th>Date</th><th>Strategy</th><th>Benchmark</th></tr></thead><tbody>'+v.curve.map(p=>'<tr><td>'+new Date(p.time*1000).toISOString().slice(0,10)+'</td><td>'+(p.close*100).toFixed(2)+'</td><td>'+(p.benchmark*100).toFixed(2)+'</td></tr>').join('')+'</tbody></table></div>';
}
$('#runValidation').onclick=async()=>{const b=$('#runValidation');b.disabled=true;$('#validationStatus').textContent='Running a historical experiment on cached histories…';try{renderValidation(await api('validation',{cost_bps:Number($('#validationCost').value)}));}catch(e){$('#validationStatus').textContent=e.message;}finally{b.disabled=false;}};
for(const b of document.querySelectorAll('[data-tab="validation"]'))b.addEventListener('click',loadValidation);
function escapeHtml(v){return String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
