/* Native SVG chart explorer: no CDN, remote scripts, or paid chart API. */
const ChartKit=(()=>{
 const escape=v=>String(v).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
 function ema(v,n){if(!v.length)return [];const a=2/(n+1),out=[v[0]];for(let i=1;i<v.length;i++)out.push(a*v[i]+(1-a)*out[i-1]);return out;}
 function series(history){
  const v=history.map(p=>p.close),ma50=[],ma200=[],upper=[],lower=[],rsi=[],fast=ema(v,12),slow=ema(v,26),macd=fast.map((x,i)=>x-slow[i]),signal=ema(macd,9);let gain=0,loss=0;
  for(let i=0;i<v.length;i++){
   ma50.push(i>=49?v.slice(i-49,i+1).reduce((a,b)=>a+b,0)/50:null);ma200.push(i>=199?v.slice(i-199,i+1).reduce((a,b)=>a+b,0)/200:null);
   if(i>=19){const vs=v.slice(i-19,i+1),mean=vs.reduce((a,b)=>a+b,0)/20,sd=Math.sqrt(vs.reduce((s,x)=>s+(x-mean)**2,0)/20);upper.push(mean+2*sd);lower.push(mean-2*sd);}else{upper.push(null);lower.push(null);}
   if(i>0){const d=v[i]-v[i-1];if(i<=14){gain+=Math.max(d,0)/14;loss+=Math.max(-d,0)/14;}else{gain=(gain*13+Math.max(d,0))/14;loss=(loss*13+Math.max(-d,0))/14;}}
   rsi.push(i<14?null:gain===0&&loss===0?50:loss===0?100:100-100/(1+gain/loss));
  }
  return {ma50,ma200,upper,lower,rsi,macd,signal};
 }
 function windowBounds(length,start,end){if(length<2)return {start:0,end:Math.max(0,length-1)};const span=Math.max(1,Math.min(length-1,end-start)),s=Math.max(0,Math.min(length-1-span,Math.round(start)));return {start:s,end:Math.min(length-1,s+Math.round(span))};}
 function svg(history,options={}){
  if(history.length<2)return '<p>Not enough history to draw this chart.</p>';
  const bounds=windowBounds(history.length,options.start==null?Math.max(0,history.length-126):options.start,options.end==null?history.length-1:options.end),s=bounds.start,e=bounds.end,pts=history.slice(s,e+1),calc=series(history);
  const W=900,H=450,L=76,R=22,T=25,P=286,B=400,base=pts[0].close,percent=!!options.percent,convert=v=>percent?(v/base-1)*100:v;
  const x=i=>L+(i-s)/(e-s)*(W-L-R),overlays=options.overlays||[],values=pts.flatMap(p=>[p.low||p.close,p.high||p.close]);
  let comparison=null;if(options.compare&&options.compare.length){const lookup=new Map(options.compare.map(p=>[new Date(p.time*1000).toISOString().slice(0,10),p.close]));let anchor=null;comparison=history.map((p,i)=>{if(i<s||i>e)return null;const v=lookup.get(new Date(p.time*1000).toISOString().slice(0,10));if(v&&anchor===null)anchor=v;return anchor&&v?base*v/anchor:null;});values.push(...comparison.filter(v=>v!==null));}
  for(const key of overlays)if(calc[key])values.push(...calc[key].slice(s,e+1).filter(v=>v!==null));
  const lo0=Math.min(...values.map(convert)),hi0=Math.max(...values.map(convert)),pad=(hi0-lo0)*.08||1,lo=percent?lo0-pad:Math.max(0,lo0-pad),hi=hi0+pad,y=v=>T+(hi-convert(v))/(hi-lo)*(P-T);
  const path=(v,yy=y)=>{let active=false;return v.map((n,i)=>{if(i<s||i>e||n==null||!Number.isFinite(n)){active=false;return '';}const p=(active?'L':'M')+x(i).toFixed(2)+','+yy(n).toFixed(2);active=true;return p;}).join(' ');};
  let out=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Interactive ${escape(options.symbol||'stock')} price chart"><title>${escape(options.symbol||'Stock')} historical chart</title>`;
  for(let i=0;i<5;i++){const value=lo+(hi-lo)*i/4,yy=T+(hi-value)/(hi-lo)*(P-T);out+=`<line x1="${L}" x2="${W-R}" y1="${yy}" y2="${yy}" stroke="#e0e8dd"/><text x="${L-8}" y="${yy+4}" text-anchor="end">${value.toFixed(2)}${percent?'%':''}</text>`;}
  const candles=options.type==='candles'&&pts.every(p=>p.open>0&&p.high>0&&p.low>0),bar=Math.max(1,Math.min(12,(W-L-R)/pts.length*.6));
  if(candles){for(let i=s;i<=e;i++){const p=history[i],color=p.close>=p.open?'#16825b':'#bc4b49';out+=`<line x1="${x(i)}" x2="${x(i)}" y1="${y(p.high)}" y2="${y(p.low)}" stroke="${color}"/><rect x="${x(i)-bar/2}" y="${Math.min(y(p.open),y(p.close))}" width="${bar}" height="${Math.max(1,Math.abs(y(p.open)-y(p.close)))}" fill="${color}"/>`;}}
  else out+=`<path d="${path(history.map(p=>p.close))}" fill="none" stroke="#207653" stroke-width="2.4"/>`;
  const colors={ma50:'#c08a24',ma200:'#596eae',upper:'#a48cae',lower:'#a48cae'};
  for(const key of overlays)if(calc[key])out+=`<path d="${path(calc[key])}" fill="none" stroke="${colors[key]||'#777'}" stroke-width="1.5" ${key==='upper'||key==='lower'?'stroke-dasharray="5 4"':''}/>`;
  if(comparison)out+=`<path d="${path(comparison)}" fill="none" stroke="#bc6340" stroke-width="2" stroke-dasharray="6 3"/>`;
  const panel=options.panel||'volume';out+=`<text x="${L}" y="${P+30}">${escape(panel==='rsi'?'RSI (14)':panel==='macd'?'MACD (12,26,9)':'Daily volume')}</text>`;
  if(panel==='rsi'){const yy=v=>B-v/100*65;for(const level of [30,70])out+=`<line x1="${L}" x2="${W-R}" y1="${yy(level)}" y2="${yy(level)}" stroke="#a9b3a9" stroke-dasharray="4"/><text x="${L-8}" y="${yy(level)+4}" text-anchor="end">${level}</text>`;out+=`<path d="${path(calc.rsi,yy)}" fill="none" stroke="#7964a3" stroke-width="2"/>`;}
  else if(panel==='macd'){const max=Math.max(...calc.macd.slice(s,e+1).map(Math.abs),...calc.signal.slice(s,e+1).map(Math.abs),.001),yy=v=>B-32-v/max*30;out+=`<line x1="${L}" x2="${W-R}" y1="${yy(0)}" y2="${yy(0)}" stroke="#ddd"/>`;for(let i=s;i<=e;i++){const v=calc.macd[i]-calc.signal[i];out+=`<rect x="${x(i)-bar/2}" y="${Math.min(yy(v),yy(0))}" width="${bar}" height="${Math.max(1,Math.abs(yy(v)-yy(0)))}" fill="${v>=0?'#8bbca0':'#db9a96'}"/>`;}out+=`<path d="${path(calc.macd,yy)}" fill="none" stroke="#596eae"/><path d="${path(calc.signal,yy)}" fill="none" stroke="#c08a24"/>`;}
  else {const max=Math.max(...pts.map(p=>p.volume||0),1);for(let i=s;i<=e;i++)if(history[i].volume!=null)out+=`<rect x="${x(i)-bar/2}" y="${B-history[i].volume/max*65}" width="${bar}" height="${history[i].volume/max*65}" fill="#8bbca0"/>`;if(pts.every(p=>p.volume==null))out+=`<text x="${L}" y="${B-20}">Volume data unavailable</text>`;}
  for(const i of [s,Math.round((s+e)/2),e])out+=`<text x="${x(i)}" y="${H-15}" text-anchor="${i===s?'start':i===e?'end':'middle'}">${new Date(history[i].time*1000).toLocaleDateString()}</text>`;
  return out+`<line id="explorerCursor" x1="0" x2="0" y1="${T}" y2="${B}" stroke="#627867" stroke-dasharray="3" visibility="hidden"/></svg>`;
 }
 return {series,svg,windowBounds};
})();
if(typeof module!=='undefined')module.exports=ChartKit;
