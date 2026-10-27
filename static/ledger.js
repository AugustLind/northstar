/* Actual transaction cash is imported, never inferred from the estimated purchase fee. */
let ledgerTable=null,ledgerPreview=null;
async function loadLedger(){
 try{const v=await api('ledger');$('#ledgerStatus').textContent=(v.initialized?(v.reconciled?'Ledger matches tracked holdings and cash.':'Reconciliation required: tracked holdings or cash changed.'):'Initialize a verified opening snapshot first.')+(v.baseline?' Opening cutoff: '+v.baseline.cutoff_date+'.':'')+' '+v.count+' imported events · Tracked cash '+money(v.cash_nok)+'.';$('#ledgerMethod').textContent=v.method;
 $('#ledgerEvents').innerHTML=v.events.length?'<div class="tablewrap"><table><thead><tr><th>Date</th><th>Type / stock</th><th>Shares</th><th>Net cash</th><th>Reported fee</th></tr></thead><tbody>'+v.events.map(e=>'<tr><td>'+esc(e.date)+'</td><td>'+esc(e.type)+' · '+esc(e.symbol||e.name||'Cash')+'</td><td>'+esc(e.quantity)+'</td><td>'+money(e.net_cash)+'</td><td>'+(e.fee==null?'Not separately reported':money(e.fee))+'</td></tr>').join('')+'</tbody></table></div>':'<p>No transaction history imported yet.</p>';
 if(!$('#ledgerDate').value)$('#ledgerDate').value=v.baseline?v.baseline.cutoff_date:new Date().toISOString().slice(0,10);
 }catch(e){$('#ledgerStatus').textContent=e.message;}
}
$('#ledgerInitialize').onclick=async()=>{try{await api('ledger/initialize',{date:$('#ledgerDate').value});ledgerPreview=null;$('#ledgerApply').disabled=true;$('#ledgerMessage').textContent='Opening snapshot saved. Earlier/same-day transactions are history only; only later transactions change cash and holdings.';await loadLedger();}catch(e){$('#ledgerMessage').textContent=e.message;}};
$('#ledgerInspect').onclick=async()=>{
 const f=$('#ledgerFile').files&&$('#ledgerFile').files[0];if(!f||!f.size||f.size>262144){$('#ledgerMessage').textContent='Choose a transaction export up to 256 KiB.';return;}
 $('#ledgerInspect').disabled=true;ledgerPreview=null;$('#ledgerApply').disabled=true;
 try{const bytes=new Uint8Array(await f.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));ledgerTable=await api('ledger/inspect',{file_b64:btoa(binary)});
 $('#ledgerColumns').innerHTML=ledgerTable.fields.map(k=>'<label>'+esc(k)+( ['date','type','net_cash','currency'].includes(k)?' (required)':'')+'<select data-ledger-column="'+esc(k)+'"><option value="">Not in file</option>'+ledgerTable.columns.map(c=>'<option value="'+esc(c)+'"'+(ledgerTable.mapping[k]===c?' selected':'')+'>'+esc(c)+'</option>').join('')+'</select></label>').join('');$('#ledgerMessage').textContent=ledgerTable.rows+' rows read. Map signed NET cash (including actual fees), then preview.';
 }catch(e){$('#ledgerMessage').textContent=e.message;}finally{$('#ledgerInspect').disabled=false;}
};
$('#ledgerPreview').onclick=async()=>{
 if(!ledgerTable){$('#ledgerMessage').textContent='Read the transaction export first.';return;}
 const mapping={};for(const s of document.querySelectorAll('[data-ledger-column]'))mapping[s.dataset.ledgerColumn]=s.value;
 try{ledgerPreview=await api('ledger/preview',{token:ledgerTable.token,mapping,scope:$('#ledgerScope').value.trim()||'default'});
 $('#ledgerRows').innerHTML='<div class="tablewrap"><table><thead><tr><th>Import</th><th>Date / event</th><th>Oslo ticker for trades</th><th>Shares</th><th>Net cash</th><th>Status</th></tr></thead><tbody>'+ledgerPreview.rows.map(r=>'<tr><td><input type="checkbox" data-ledger-select="'+r.id+'"'+(!r.error&&!r.duplicate?' checked':'')+(r.error||r.duplicate?' disabled':'')+' aria-label="Select transaction '+r.id+'"></td><td>'+esc(r.date||'')+' · '+esc(r.type||'')+'<small>'+esc(r.name)+'</small></td><td><input data-ledger-symbol="'+r.id+'" value="'+esc(r.symbol)+'" placeholder="BOUV.OL"'+(r.type!=='buy'&&r.type!=='sell'?' disabled':'')+'></td><td>'+esc(r.quantity)+'</td><td>'+(r.net_cash==null?'Unavailable':money(r.net_cash))+'</td><td>'+esc(r.error||(r.duplicate?'Already imported':ledgerPreview.baseline&&r.date<=ledgerPreview.baseline.cutoff_date?'History only: included in opening snapshot':'Changes holdings / cash'))+'</td></tr>').join('')+'</tbody></table></div>';
 $('#ledgerMessage').textContent=ledgerPreview.method;$('#ledgerConfirm').checked=false;$('#ledgerApply').disabled=true;
 }catch(e){$('#ledgerMessage').textContent=e.message;}
};
$('#ledgerConfirm').onchange=()=>{$('#ledgerApply').disabled=!ledgerPreview||!$('#ledgerConfirm').checked;};
$('#ledgerRows').oninput=()=>{$('#ledgerConfirm').checked=false;$('#ledgerApply').disabled=true;};
$('#ledgerRows').onchange=()=>{$('#ledgerConfirm').checked=false;$('#ledgerApply').disabled=true;};
$('#ledgerApply').onclick=async()=>{
 if(!ledgerPreview||!$('#ledgerConfirm').checked)return;
 const selections=[];for(const s of document.querySelectorAll('[data-ledger-select]'))if(s.checked){const field=document.querySelector('[data-ledger-symbol="'+s.dataset.ledgerSelect+'"]');selections.push({id:Number(s.dataset.ledgerSelect),symbol:field?field.value:''});}
 if(!selections.length){$('#ledgerMessage').textContent='Select new valid transaction rows.';return;}
 $('#ledgerApply').disabled=true;
 try{const r=await api('ledger/apply',{token:ledgerPreview.token,selections});ledgerPreview=null;$('#ledgerRows').innerHTML='';$('#ledgerFile').value='';$('#ledgerMessage').textContent=r.imported+' new events imported; '+r.duplicates+' duplicates skipped. Verify the result against Nordnet.';await loadLedger();await load();if(typeof loadResearch==='function')await loadResearch();}
 catch(e){$('#ledgerMessage').textContent=e.message;$('#ledgerApply').disabled=false;}
};
$('#ledgerFile').onchange=()=>{ledgerPreview=null;ledgerTable=null;$('#ledgerApply').disabled=true;$('#ledgerRows').innerHTML='';};
for(const b of document.querySelectorAll('[data-tab="activity"]'))b.addEventListener('click',loadLedger);

$('#checkBrokerCash').onclick=async()=>{try{if(!$('#brokerCash').value)throw Error('Enter Nordnet’s available cash balance.');const r=await api('ledger/reconcile',{cash_nok:Number($('#brokerCash').value)});$('#brokerCashStatus').textContent=(r.mismatch_active?'Mismatch: ':'Matched: ')+'Nordnet '+money(r.reported_cash)+' · Tracked '+money(r.tracked_cash)+' · Difference '+money(r.difference)+'.';await loadLedger();if(typeof loadQuantityPlan==='function')loadQuantityPlan();}catch(e){$('#brokerCashStatus').textContent=e.message;}};

function invalidateLedgerPreview(){ledgerPreview=null;$('#ledgerConfirm').checked=false;$('#ledgerApply').disabled=true;$('#ledgerMessage').textContent='Mapping or account label changed. Preview again before applying.';}
$('#ledgerColumns').onchange=invalidateLedgerPreview;$('#ledgerScope').oninput=invalidateLedgerPreview;
