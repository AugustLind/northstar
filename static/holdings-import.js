/* The file stays out of GitHub; only authenticated Oracle APIs receive its contents. */
let holdingsImportPreview=null,holdingsImportRevision=0;
function updateImportExisting(id,ticker){
 if(!holdingsImportPreview)return;const symbol=ticker.trim().toUpperCase(),canonical=symbol.includes('.')?symbol:symbol+'.OL';
 const matches=(holdingsImportPreview.existing_holdings||[]).filter(p=>p.currency==='NOK'&&(p.symbol.includes('.')?p.symbol:p.symbol+'.OL')===canonical);
 const cell=document.querySelector('[data-import-existing="'+id+'"]');if(cell)cell.textContent=matches.length>1?'Duplicate holdings: resolve before importing':matches.length?matches[0].shares+' shares · '+money(matches[0].cost,'NOK'):'No matched holding';
}
function resetHoldingsImport(){holdingsImportPreview=null;holdingsImportRevision++;$('#nordnetImportRows').innerHTML='';$('#nordnetImportApply').disabled=true;$('#nordnetImportConfirmed').checked=false;}
function renderHoldingsImport(preview){
 holdingsImportPreview=preview;
 $('#nordnetImportStatus').textContent=preview.rows.length+' export rows · '+preview.valid+' supported rows. Review the selected tickers, quantities and GAV. Preview expires in 15 minutes.';
 $('#nordnetImportMethod').textContent=preview.method;
 $('#nordnetTickerOptions').innerHTML=preview.companies.map(c=>'<option value="'+esc(c.symbol)+'">'+esc(c.name)+'</option>').join('');
 $('#nordnetImportRows').innerHTML='<div class="tablewrap"><table><thead><tr><th>Import</th><th>Company in export</th><th>Oslo ticker</th><th>Shares</th><th>Average cost · GAV</th><th>Existing holding</th><th>Match / issue</th></tr></thead><tbody>'+preview.rows.map(r=>'<tr><td><input type="checkbox" data-import-select="'+r.id+'" aria-label="Import row '+r.id+'"'+(r.selected?' checked':'')+(r.error?' disabled':'')+'></td><td>'+esc(r.name)+'<small>'+esc(r.currency)+'</small></td><td><input data-import-symbol="'+r.id+'" aria-label="Oslo ticker for row '+r.id+'" list="nordnetTickerOptions" value="'+esc(r.symbol)+'" placeholder="Choose / enter ticker" maxlength="20"'+(r.error?' disabled':'')+'></td><td>'+esc(r.shares==null?'Unavailable':r.shares)+'</td><td>'+(r.cost==null?'Unavailable':money(r.cost,r.currency))+'</td><td data-import-existing="'+r.id+'">'+(r.existing?esc(r.existing.shares)+' shares · '+money(r.existing.cost,r.currency):'No matched holding')+'</td><td>'+esc(r.error||r.match)+'</td></tr>').join('')+'</tbody></table></div>';
 $('#nordnetImportConfirmed').checked=false;$('#nordnetImportApply').disabled=true;
}
$('#importNordnet').onclick=()=>{$('#nordnetImportPanel').hidden=false;if($('#nordnetImportPanel').scrollIntoView)$('#nordnetImportPanel').scrollIntoView({behavior:'smooth',block:'start'});};
$('#closeNordnetImport').onclick=()=>{$('#nordnetImportPanel').hidden=true;resetHoldingsImport();$('#nordnetFile').value='';$('#nordnetImportStatus').textContent='';};
$('#nordnetFile').onchange=()=>{resetHoldingsImport();$('#nordnetImportStatus').textContent='File selected. Preview it before applying changes.';};
$('#nordnetImportConfirmed').onchange=()=>{$('#nordnetImportApply').disabled=!holdingsImportPreview||!$('#nordnetImportConfirmed').checked;};
$('#nordnetImportRows').oninput=e=>{if(!e.target.dataset.importSymbol)return;const select=document.querySelector('[data-import-select="'+e.target.dataset.importSymbol+'"]');if(select)select.checked=!!e.target.value.trim();updateImportExisting(e.target.dataset.importSymbol,e.target.value);$('#nordnetImportConfirmed').checked=false;$('#nordnetImportApply').disabled=true;};
$('#nordnetImportRows').onchange=()=>{$('#nordnetImportConfirmed').checked=false;$('#nordnetImportApply').disabled=true;};
$('#nordnetPreview').onclick=async()=>{
 const file=$('#nordnetFile').files&&$('#nordnetFile').files[0];if(!file){$('#nordnetImportStatus').textContent='Choose your Nordnet holdings CSV first.';return;}
 if(!file.size||file.size>262144){$('#nordnetImportStatus').textContent='Choose a nonempty CSV up to 256 KiB.';return;}
 resetHoldingsImport();const revision=holdingsImportRevision,b=$('#nordnetPreview');b.disabled=true;$('#nordnetImportStatus').textContent='Reading holdings and preparing a preview…';
 try{const bytes=new Uint8Array(await file.arrayBuffer());let binary='';for(let i=0;i<bytes.length;i+=8192)binary+=String.fromCharCode.apply(null,bytes.subarray(i,i+8192));
 const preview=await api('import/preview',{file_b64:btoa(binary)});if(revision!==holdingsImportRevision)return;renderHoldingsImport(preview);
 }catch(e){if(revision===holdingsImportRevision)$('#nordnetImportStatus').textContent=e.message;}finally{b.disabled=false;}
};
$('#nordnetImportApply').onclick=async()=>{
 if(!holdingsImportPreview||!$('#nordnetImportConfirmed').checked)return;
 const selections=[];for(const input of document.querySelectorAll('[data-import-select]'))if(input.checked){const field=document.querySelector('[data-import-symbol="'+input.dataset.importSelect+'"]');const symbol=field.value.trim();if(!symbol){$('#nordnetImportStatus').textContent='Choose a ticker for every selected row.';return;}selections.push({id:Number(input.dataset.importSelect),symbol});}
 if(!selections.length){$('#nordnetImportStatus').textContent='Select at least one supported holding.';return;}
 const b=$('#nordnetImportApply');b.disabled=true;
 try{const result=await api('import/apply',{token:holdingsImportPreview.token,selections});resetHoldingsImport();$('#nordnetFile').value='';$('#nordnetImportStatus').textContent='Imported '+result.updated+' holdings. Notes preserved. The market scan has been queued.';await load();if(typeof loadResearch==='function')await loadResearch();if(typeof loadPortfolioFit==='function')await loadPortfolioFit();}
 catch(e){$('#nordnetImportStatus').textContent=e.message;b.disabled=false;}
};
