const assert=require('assert'),Chart=require('../static/charts.js');
const now=Date.now()/1000,h=Array.from({length:300},(_,i)=>({time:now-(299-i)*86400,close:100+i/10,open:100+i/10-.1,high:101+i/10,low:99+i/10,volume:1000+i}));
const s=Chart.series(h);
assert.strictEqual(s.ma200[198],null);assert(Math.abs(s.ma200[199]-109.95)<1e-10);
assert.strictEqual(s.rsi[100],100);assert.strictEqual(Chart.series(h.map(p=>({...p,close:100}))).rsi[100],50);
for(const start of [-100,0,290,1000]){const w=Chart.windowBounds(300,start,start+50);assert(w.start>=0&&w.end<300&&w.end>w.start);}
for(const panel of ['rsi','macd','volume']){const svg=Chart.svg(h,{symbol:'<unsafe>',type:'candles',panel,overlays:['ma50','ma200','upper','lower'],percent:true,start:100,end:299,compare:h.map(p=>({...p,close:p.close*1.2}))});assert(svg.includes('<rect'));assert(!svg.includes('NaN'));assert(!svg.includes('<unsafe>'));assert(svg.includes('&lt;unsafe&gt;'));assert(svg.includes('explorerCursor'));}
const single=Chart.svg([h[0]],{});assert(single.includes('Not enough history'));
console.log('Chart indicators, ranges, candle rendering and comparison checks passed.');
