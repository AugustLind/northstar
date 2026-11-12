const assert=require('assert'),Chart=require('../static/charts.js');
const now=Date.now()/1000,h=Array.from({length:300},(_,i)=>({time:now-(299-i)*86400,close:100+i/10,open:100+i/10-.1,high:101+i/10,low:99+i/10,volume:1000+i}));
const s=Chart.series(h);
assert.strictEqual(s.ma200[198],null);assert(Math.abs(s.ma200[199]-109.95)<1e-10);
assert.strictEqual(s.rsi[100],100);assert.strictEqual(Chart.series(h.map(p=>({...p,close:100}))).rsi[100],50);
for(const start of [-100,0,290,1000]){const w=Chart.windowBounds(300,start,start+50);assert(w.start>=0&&w.end<300&&w.end>w.start);}
for(const panel of ['rsi','macd','volume']){const svg=Chart.svg(h,{symbol:'<unsafe>',type:'candles',panel,overlays:['ma50','ma200','upper','lower'],percent:true,start:100,end:299,compare:h.map(p=>({...p,close:p.close*1.2}))});assert(svg.includes('<rect'));assert(!svg.includes('NaN'));assert(!svg.includes('<unsafe>'));assert(svg.includes('&lt;unsafe&gt;'));assert(svg.includes('explorerCursor'));}
const single=Chart.svg([h[0]],{});assert(single.includes('Not enough history'));
console.log('Chart indicators, ranges, candle rendering and comparison checks passed.');

// Selected-period calculations against known returns and flat data.
const flat=h.map(p=>({...p,close:100})),flatStats=Chart.analytics(flat);
assert.strictEqual(flatStats.returnPct,0);assert.strictEqual(flatStats.volatility,0);
assert.strictEqual(flatStats.maxDrawdown,0);assert.strictEqual(flatStats.sharpe,null);
assert.strictEqual(flatStats.var95,0);assert.strictEqual(flatStats.expectedShortfall95,0);
const loss=Array.from({length:21},(_,i)=>({time:now+i*86400,close:i===0?100:80}));
const lossStats=Chart.analytics(loss);
assert(Math.abs(lossStats.var95-1)<1e-10);assert(Math.abs(lossStats.expectedShortfall95-20)<1e-10);
assert(Math.abs(lossStats.maxDrawdown+20)<1e-10);
assert.strictEqual(Chart.analytics(h.slice(0,10)).var95,null);
const matched=Chart.comparison(h,h.map(p=>({...p,close:p.close*3})));
assert(Math.abs(matched.correlation-1)<1e-10);assert(Math.abs(matched.beta-1)<1e-10);assert(Math.abs(matched.excess)<1e-10);
const late=Chart.comparison(h,h.slice(40).map(p=>({...p,close:p.close*2})));
assert.strictEqual(late.values[0],null);assert.strictEqual(late.values[39],null);
assert(Math.abs(late.values[40]-h[40].close)<1e-10);
assert.strictEqual(Chart.comparison(h,[]).correlation,null);
assert.strictEqual(Chart.comparison(h.slice(0,10),h).beta,null);
assert.strictEqual(Chart.series(h).macd[24],null);assert.strictEqual(Chart.series(h).signal[32],null);
assert.strictEqual(Chart.series(h).volatility20[19],null);
assert.strictEqual(Chart.series(flat).volatility20[20],0);
for(const panel of ['drawdown','volatility'])for(const log of [true,false]){
 const svg=Chart.svg(flat,{panel,log,overlays:['ema20','ma50','upper','lower'],compare:h});
 assert(!/NaN|Infinity/.test(svg));assert(svg.includes('<path'));
}
assert(Chart.navigator(h,40,200).includes('<rect'));
assert.strictEqual(Chart.navigator([],0,0),'');
console.log('Period risk statistics, shared-date comparison, log scales and new panels passed.');

const compact=Chart.svg(h,{compact:true,log:true,panel:'drawdown'});
assert(compact.includes('viewBox="0 0 600 440"'));assert(!/NaN|Infinity/.test(compact));
