/* Native SVG research charts. Calculations use completed daily observations. */
const ChartKit=(()=>{
 const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 const cache=new WeakMap();
 function ema(v,n){if(!v.length)return [];const a=2/(n+1),out=[v[0]];for(let i=1;i<v.length;i++)out.push(a*v[i]+(1-a)*out[i-1]);return out;}
 function volatility(v){if(v.length<2)return null;const mean=v.reduce((a,b)=>a+b,0)/v.length;return Math.sqrt(v.reduce((s,r)=>s+(r-mean)**2,0)/(v.length-1)*252)*100;}
 function series(history){
  if(cache.has(history))return cache.get(history);
  const v=history.map(p=>p.close),ma50=[],ma200=[],upper=[],lower=[],rsi=[],drawdown=[],volatility20=[],ema20=ema(v,20),fast=ema(v,12),slow=ema(v,26),rawMacd=fast.map((x,i)=>x-slow[i]),rawSignal=ema(rawMacd,9),returns=[];
  let gain=0,loss=0,peak=v[0];
  for(let i=0;i<v.length;i++){
   ma50.push(i>=49?v.slice(i-49,i+1).reduce((a,b)=>a+b,0)/50:null);
   ma200.push(i>=199?v.slice(i-199,i+1).reduce((a,b)=>a+b,0)/200:null);
   if(i>=19){const vs=v.slice(i-19,i+1),mean=vs.reduce((a,b)=>a+b,0)/20,sd=Math.sqrt(vs.reduce((s,x)=>s+(x-mean)**2,0)/20);upper.push(mean+2*sd);lower.push(mean-2*sd);}else{upper.push(null);lower.push(null);}
   if(i>0){const d=v[i]-v[i-1];returns.push(v[i]/v[i-1]-1);if(i<=14){gain+=Math.max(d,0)/14;loss+=Math.max(-d,0)/14;}else{gain=(gain*13+Math.max(d,0))/14;loss=(loss*13+Math.max(-d,0))/14;}}
   rsi.push(i<14?null:gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss));
   peak=Math.max(peak,v[i]);drawdown.push((v[i]/peak-1)*100);
   volatility20.push(i>=20?volatility(returns.slice(-20)):null);
  }
  const result={ma50,ma200,upper,lower,rsi,ema20,drawdown,volatility20,macd:rawMacd.map((v,i)=>i>=25?v:null),signal:rawSignal.map((v,i)=>i>=33?v:null)};
  cache.set(history,result);return result;
 }
 function windowBounds(length,start,end){if(length<2)return {start:0,end:Math.max(0,length-1)};const span=Math.max(1,Math.min(length-1,Math.round(end-start))),s=Math.max(0,Math.min(length-1-span,Math.round(start)));return {start:s,end:s+span};}
 const day=p=>new Date(p.time*1000).toISOString().slice(0,10);
 function comparison(history,other){
  const lookup=new Map((other||[]).map(p=>[day(p),p.close]));
  const pairs=history.map(p=>({point:p,other:lookup.get(day(p))})).filter(p=>Number.isFinite(p.other)&&p.other>0);
  if(pairs.length<2)return {values:history.map(()=>null),pairs:[],correlation:null,beta:null,excess:null};
  const first=pairs[0],anchor=first.point.close/first.other;
  const values=history.map(p=>{const v=lookup.get(day(p));return v>0?v*anchor:null;});
  const a=[],b=[];for(let i=1;i<pairs.length;i++){a.push(pairs[i].point.close/pairs[i-1].point.close-1);b.push(pairs[i].other/pairs[i-1].other-1);}
  const mean=v=>v.reduce((a,b)=>a+b,0)/v.length,ma=mean(a),mb=mean(b),cov=a.reduce((s,v,i)=>s+(v-ma)*(b[i]-mb),0),va=a.reduce((s,v)=>s+(v-ma)**2,0),vb=b.reduce((s,v)=>s+(v-mb)**2,0),last=pairs[pairs.length-1];
  return {values,pairs,correlation:a.length>=20&&va>1e-20&&vb>1e-20?cov/Math.sqrt(va*vb):null,beta:a.length>=20&&vb>1e-20?cov/vb:null,excess:((last.point.close/first.point.close-1)-(last.other/first.other-1))*100};
 }
 function analytics(history,other){
  if(history.length<2)return null;
  const v=history.map(p=>p.close),r=v.slice(1).map((p,i)=>p/v[i]-1),sorted=r.slice().sort((a,b)=>a-b),at=(r.length-1)*.05,q=sorted[Math.floor(at)]+(sorted[Math.ceil(at)]-sorted[Math.floor(at)])*(at%1);
  let peak=v[0],dd=0;for(const price of v){peak=Math.max(peak,price);dd=Math.min(dd,(price/peak-1)*100);}
  const n=r.length,mean=r.reduce((a,b)=>a+b,0)/n,vol=volatility(r),mass=n*.05,k=Math.floor(mass),tail=(sorted.slice(0,k).reduce((a,b)=>a+b,0)+(mass-k)*sorted[k])/mass;
  return {observations:history.length,returnPct:(v[v.length-1]/v[0]-1)*100,volatility:vol,maxDrawdown:dd,var95:n>=20?Math.max(0,-q*100):null,expectedShortfall95:n>=20?Math.max(0,-tail*100):null,sharpe:n>=20&&vol>1e-10?mean*252/(vol/100):null,best:Math.max(...r)*100,worst:Math.min(...r)*100,positivePct:r.filter(v=>v>0).length/n*100,comparison:other?comparison(history,other):null};
 }
 function navigator(history,start,end){
  if(history.length<2)return '';
  const values=history.map(p=>p.close),lo=Math.min(...values),hi=Math.max(...values),x=i=>12+i/(values.length-1)*876,y=v=>45-(v-lo)/(hi-lo||1)*32;
  return `<svg viewBox="0 0 900 60" role="img" aria-label="Full available history and selected chart window"><path d="${values.map((v,i)=>(i?'L':'M')+x(i).toFixed(1)+','+y(v).toFixed(1)).join(' ')}" fill="none" stroke="#6d9781"/><rect x="${x(start)}" y="5" width="${Math.max(2,x(end)-x(start))}" height="47" fill="#28785818" stroke="#287858" rx="3"/></svg>`;
 }
 function layout(compact=false){return compact?{W:600,H:440,L:64,R:18,T:30,P:252,B:390}:{W:900,H:470,L:76,R:22,T:30,P:282,B:418};}
 function svg(history,options={}){
  if(history.length<2)return '<p>Not enough history to draw this chart.</p>';
  const {start:s,end:e}=windowBounds(history.length,options.start==null?Math.max(0,history.length-126):options.start,options.end==null?history.length-1:options.end),pts=history.slice(s,e+1),calc=series(history);
  const {W,H,L,R,T,P,B}=layout(options.compact),base=pts[0].close,percent=!!options.percent,log=!!options.log&&!percent;
  const convert=v=>percent?(v/base-1)*100:log?Math.log(v):v;
  const x=i=>L+(i-s)/(e-s)*(W-L-R),overlays=options.overlays||[],values=pts.flatMap(p=>[p.low>0?p.low:p.close,p.high>0?p.high:p.close]);
  const compared=options.compare?comparison(pts,options.compare):null,comparedValues=compared?[...Array(s).fill(null),...compared.values]:null;
  if(compared)values.push(...compared.values.filter(v=>v!==null));
  for(const key of overlays)if(calc[key])values.push(...calc[key].slice(s,e+1).filter(v=>Number.isFinite(v)&&(!log||v>0)));
  const transformed=values.filter(v=>Number.isFinite(v)&&(!log||v>0)).map(convert),lo0=Math.min(...transformed),hi0=Math.max(...transformed),pad=(hi0-lo0)*.08||(log?.01:1),lo=percent||log?lo0-pad:Math.max(0,lo0-pad),hi=hi0+pad,y=v=>T+(hi-convert(v))/(hi-lo)*(P-T);
  const path=(v,yy=y)=>{let active=false;return v.map((n,i)=>{if(i<s||i>e||n==null||!Number.isFinite(n)){active=false;return '';}const p=(active?'L':'M')+x(i).toFixed(2)+','+yy(n).toFixed(2);active=true;return p;}).join(' ');};
  let out=`<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" role="img" aria-label="Interactive ${escape(options.symbol||'stock')} price chart"><title>${escape(options.symbol||'Stock')} historical chart</title><text x="${L}" y="17">${percent?'Period change (%)':log?'Price · logarithmic scale':'Price · '+escape(options.currency||'NOK')}</text>`;
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4,yy=T+(hi-value)/(hi-lo)*(P-T),label=log?Math.exp(value):value;out+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="#e0e8dd"/><text x="${L-8}" y="${yy+4}" text-anchor="end">${label.toFixed(2)}${percent?'%':''}</text>`;}
  if(overlays.includes('upper')&&overlays.includes('lower')){const idx=Array.from({length:e-s+1},(_,i)=>s+i).filter(i=>calc.lower[i]!=null&&(!log||calc.lower[i]>0));if(idx.length>1)out+=`<path d="M${idx.map(i=>x(i)+','+y(calc.upper[i])).join(' L')} L${idx.slice().reverse().map(i=>x(i)+','+y(calc.lower[i])).join(' L')} Z" fill="#a48cae14"/>`;}
  const candles=options.type==='candles'&&pts.every(p=>p.open>0&&p.high>=Math.max(p.open,p.close)&&p.low>0&&p.low<=Math.min(p.open,p.close)),bar=Math.max(1,Math.min(12,(W-L-R)/pts.length*.6));
  if(candles){for(let i=s;i<=e;i++){const p=history[i],color=p.close>=p.open?'#16825b':'#bc4b49';out+=`<line x1="${x(i)}" x2="${x(i)}" y1="${y(p.high)}" y2="${y(p.low)}" stroke="${color}"/><rect x="${x(i)-bar/2}" y="${Math.min(y(p.open),y(p.close))}" width="${bar}" height="${Math.max(1,Math.abs(y(p.open)-y(p.close)))}" fill="${color}"/>`;}}
  else out+=`<path d="${path(history.map(p=>p.close))}" fill="none" stroke="#207653" stroke-width="2.4"/>`;
  const colors={ema20:'#138c9c',ma50:'#c08a24',ma200:'#596eae',upper:'#a48cae',lower:'#a48cae'};
  for(const key of overlays)if(calc[key])out+=`<path d="${path(calc[key].map(v=>log&&v<=0?null:v))}" fill="none" stroke="${colors[key]||'#777'}" stroke-width="1.5" ${key==='upper'||key==='lower'?'stroke-dasharray="5 4"':''}/>`;
  if(comparedValues)out+=`<path d="${path(comparedValues)}" fill="none" stroke="#bc6340" stroke-width="2" stroke-dasharray="6 3"/>`;
  const dateIndices=new Map(history.map((p,i)=>[day(p),i]));
  const eventRows=(options.events||[]).filter(event=>Number.isFinite(event.time)&&dateIndices.has(day(event))&&dateIndices.get(day(event))>=s&&dateIndices.get(day(event))<=e).slice(0,100);
  const perDay=new Map();
  for(const event of eventRows){const i=dateIndices.get(day(event)),stack=perDay.get(i)||0;perDay.set(i,stack+1);const color=event.kind==='dividend'?'#596eae':event.kind==='split'?'#b08030':'#9c5985',yy=T+14+stack*16;out+=`<g><title>${escape(day(event)+' · '+event.label+' · '+(event.source||'Source unavailable'))}</title><line x1="${x(i)}" x2="${x(i)}" y1="${T}" y2="${P}" stroke="${color}" stroke-dasharray="2 5" opacity=".35"/><circle cx="${x(i)}" cy="${yy}" r="7" fill="${color}"/><text x="${x(i)}" y="${yy+3}" text-anchor="middle" style="fill:white;font-size:9px">${event.kind==='dividend'?'D':event.kind==='split'?'S':'E'}</text></g>`;}
  const panel=options.panel||'volume',labels={rsi:'RSI (14)',macd:'MACD (12,26,9)',drawdown:'Drawdown from loaded-history peak (%)',volatility:'20-session annualised volatility (%)',relative:'Relative performance · ratio rebased to 100',volume:'Daily volume'};
  out+=`<line x1="${L}" x2="${W-R}" y1="${P+15}" y2="${P+15}" stroke="#dce5d7"/><text x="${L}" y="${P+40}">${labels[panel]||labels.volume}</text>`;
  const panelTop=P+58,panelHeight=B-panelTop;
  if(panel==='rsi'){const yy=v=>B-v/100*panelHeight;for(const level of [30,70])out+=`<line x1="${L}" x2="${W-R}" y1="${yy(level)}" y2="${yy(level)}" stroke="#a9b3a9" stroke-dasharray="4"/><text x="${L-8}" y="${yy(level)+4}" text-anchor="end">${level}</text>`;out+=`<path d="${path(calc.rsi,yy)}" fill="none" stroke="#7964a3" stroke-width="2"/>`;}
  else if(panel==='drawdown'||panel==='volatility'){
   const data=panel==='drawdown'?calc.drawdown:calc.volatility20,visible=data.slice(s,e+1).filter(Number.isFinite),min=panel==='drawdown'?Math.min(-1,...visible):0,max=panel==='drawdown'?0:Math.max(1,...visible)*1.1,yy=v=>B-(v-min)/(max-min)*panelHeight;
   for(const level of [min,(max+min)/2,max])out+=`<line x1="${L}" x2="${W-R}" y1="${yy(level)}" y2="${yy(level)}" stroke="#e0e8dd"/><text x="${L-8}" y="${yy(level)+4}" text-anchor="end">${level.toFixed(1)}%</text>`;
   out+=`<path d="${path(data,yy)}" fill="none" stroke="${panel==='drawdown'?'#bc4b49':'#596eae'}" stroke-width="2"/>`;
  }
  else if(panel==='relative'){
   if(!compared||compared.pairs.length<2)out+=`<text x="${L}" y="${B-20}">Choose a comparison with shared dates</text>`;
   else{const data=[...Array(s).fill(null),...compared.values.map((v,i)=>v==null?null:pts[i].close/v*100)],visible=data.filter(Number.isFinite),min=Math.min(...visible,100),max=Math.max(...visible,100),pad=(max-min)*.1||1,yy=v=>B-(v-min+pad)/(max-min+2*pad)*panelHeight;out+=`<line x1="${L}" x2="${W-R}" y1="${yy(100)}" y2="${yy(100)}" stroke="#a9b3a9" stroke-dasharray="4"/><text x="${L-8}" y="${yy(100)+4}" text-anchor="end">100</text><path d="${path(data,yy)}" fill="none" stroke="#138c9c" stroke-width="2"/>`;}
  }
  else if(panel==='macd'){
   const histogram=calc.macd.map((v,i)=>v==null||calc.signal[i]==null?null:v-calc.signal[i]),max=Math.max(...calc.macd.slice(s,e+1).filter(Number.isFinite).map(Math.abs),...calc.signal.slice(s,e+1).filter(Number.isFinite).map(Math.abs),...histogram.slice(s,e+1).filter(Number.isFinite).map(Math.abs),.001),yy=v=>B-panelHeight/2-v/max*panelHeight/2;
   out+=`<line x1="${L}" x2="${W-R}" y1="${yy(0)}" y2="${yy(0)}" stroke="#ddd"/>`;for(let i=s;i<=e;i++){const v=histogram[i];if(v==null)continue;out+=`<rect x="${x(i)-bar/2}" y="${Math.min(yy(v),yy(0))}" width="${bar}" height="${Math.max(1,Math.abs(yy(v)-yy(0)))}" fill="${v>=0?'#8bbca0':'#db9a96'}"/>`;}out+=`<path d="${path(calc.macd,yy)}" fill="none" stroke="#596eae"/><path d="${path(calc.signal,yy)}" fill="none" stroke="#c08a24"/>`;
  }
  else {const max=Math.max(...pts.map(p=>p.volume||0),1);for(let i=s;i<=e;i++)if(history[i].volume!=null)out+=`<rect x="${x(i)-bar/2}" y="${B-history[i].volume/max*panelHeight}" width="${bar}" height="${history[i].volume/max*panelHeight}" fill="${i>0&&history[i].close<history[i-1].close?'#d89e97':'#8bbca0'}"/>`;if(pts.every(p=>p.volume==null))out+=`<text x="${L}" y="${B-20}">Volume data unavailable</text>`;}
  for(const i of [...new Set([s,Math.round((s+e)/2),e])])out+=`<text x="${x(i)}" y="${H-18}" text-anchor="${i===s?'start':i===e?'end':'middle'}">${day(history[i])}</text>`;
  return out+`<line id="explorerCursor" x1="0" x2="0" y1="${T}" y2="${B}" stroke="#627867" stroke-dasharray="3" visibility="hidden"/></svg>`;
 }
 function csv(history,options={}){
  if(!history.length)return '';
  const bounds=windowBounds(history.length,options.start==null?0:options.start,options.end==null?history.length-1:options.end),calc=series(history),keys=['ema20','ma50','ma200','rsi','macd','signal','drawdown','volatility20'];
  const rows=[['Date UTC','Close','Open','High','Low','Volume','EMA20','MA50','MA200','RSI14','MACD','MACD signal','Loaded-history drawdown %','20-session annual volatility %']];
  for(let i=bounds.start;i<=bounds.end;i++){const p=history[i];rows.push([day(p),p.close,p.open,p.high,p.low,p.volume,...keys.map(k=>calc[k][i])]);}
  return rows.map(row=>row.map(v=>v==null?'':String(v)).join(',')).join('\r\n')+'\r\n';
 }
 return {series,svg,windowBounds,analytics,comparison,navigator,layout,csv};
})();
if(typeof module!=='undefined')module.exports=ChartKit;
