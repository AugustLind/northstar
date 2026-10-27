// DOM contract smoke checks without installing a browser or packages.
const fs=require('fs'),vm=require('vm'),assert=require('assert');
const nodes={};
function element(){return {textContent:'',innerHTML:'',value:'',disabled:false,hidden:false,dataset:{},elements:{},classList:{toggle(){}},addEventListener(){},click(){if(this.onclick)this.onclick();},showModal(){},close(){}};}
const form=element();for(const name of ['universe','interval_minutes','model','min_turnover_nok','llm_enabled'])form.elements[name]=element();nodes['#researchSettings']=form;
nodes['#adviceFilter']=element();nodes['#adviceFilter'].value='all';nodes['#rankBy']=element();nodes['#rankBy'].value='composite';
const now=Date.now()/1000;
const history=Array.from({length:250},(_,i)=>({time:now-(249-i)*86400,close:100+i/10}));
const report={generated:now,errors:[],llm_status:'disabled',cards:[{symbol:'BOUV.OL',name:'Bouvet',currency:'NOK',price:125,asof:now,source:'test',held:false,action:'Consider buying',score:100,reasons:['Test measured evidence'],history,history_basis:'Adjusted close',metrics:{ma200:110,momentum3m:5,drawdown:-2,volatility:20,turnover20:1000000}}]};
const requests=[];
const context={Intl,Date,Number,String,JSON,Object,Math,URL,Blob:class{},console,window:{NORTHSTAR_CONFIG:{apiBase:'https://api.example.com'}},sessionStorage:{getItem(k){return k==='northstar-key'?'test-access-key':null;},setItem(){},removeItem(){}},location:{pathname:'/recommendations',hostname:'owner.github.io',hash:''},history:{replaceState(){}},setInterval(){},setTimeout(){},confirm(){return false;},
 document:{querySelector(s){return nodes[s]||(nodes[s]=element());},querySelectorAll(s){if(s==='[data-tab]'){const n=element();n.dataset.tab='recommendations';return [n];}return [];},createElement:element},
 fetch:async (path,options)=>{requests.push({path,options});return {ok:true,json:async()=>path.includes('/api/announcements?')?{status:'available',fetched:now,from:'2026-10-21',to:'2026-10-27',focus_symbols:['BOUV.OL'],counts:{last24h:1,priority_review:1,earnings:1},items:[{id:'1',symbol:'BOUV.OL',title:'Q3 results <untrusted>',published:now,first_seen:now,url:'https://newsweb.oslobors.no/message/1',classification:{kind:'earnings',label:'Earnings / business update',priority:3,why:'Read the source report.'},categories:[]}],last24h:[],events:[]}:path.includes('/api/fundamentals?')?{status:'available',period:'2025-12-31',fetched:now,metrics:{revenue:{value:1200,currency:'NOK',unit:'amount',period:'2025-12-31'}},signals:['Annual revenue increased.'],history:{},source:'Fixture provider',source_url:'https://finance.yahoo.com/quote/BOUV.OL/financials/'}:path.includes('/api/history?')?{history,currency:'NOK',asof:now,history_basis:'Adjusted close'}:path.endsWith('/api/state')?{positions:[],quotes:{}}:{report,worker:{running:false,next_run:now+3600},settings:{universe:['BOUV.OL'],interval_minutes:360,model:'qwen2.5:3b',min_turnover_nok:250000,llm_enabled:false}}};}};
vm.createContext(context);
vm.runInContext(fs.readFileSync('static/app.js','utf8'),context);
vm.runInContext(fs.readFileSync('static/charts.js','utf8'),context);
vm.runInContext(fs.readFileSync('static/news.js','utf8'),context);
vm.runInContext(fs.readFileSync('static/advice.js','utf8'),context);
setImmediate(()=>{
 try{
 assert(requests.length>=2);assert(requests.every(r=>r.path.startsWith('https://api.example.com/api/')));assert(requests.every(r=>r.options.headers.Authorization==='Bearer test-access-key'));
 assert(nodes['#chartPlot'].innerHTML.includes('<svg'));
 assert(nodes['#adviceCards'].innerHTML.includes('Consider buying'));
 assert(nodes['#adviceCards'].innerHTML.includes('Bouvet'));
 assert(nodes['#adviceSummary'].textContent.includes('1 buy candidate'));
 assert(nodes['#adviceCards'].innerHTML.includes('Liquidity'));
 assert(nodes['#adviceCards'].innerHTML.includes('Explore'));
 assert(nodes['#financialStatus'].textContent.includes('available'));
 assert(nodes['#financialMetrics'].innerHTML.includes('Revenue'));
 assert(nodes['#financialSignals'].innerHTML.includes('Annual revenue increased.'));
 assert(nodes['#newsCount'].textContent===1);
 assert(nodes['#newsItems'].innerHTML.includes('Q3 results &lt;untrusted&gt;'));
 assert(!nodes['#newsItems'].innerHTML.includes('<untrusted>'));
 assert(nodes['#stockNewsItems'].innerHTML.includes('Q3 results &lt;untrusted&gt;'));
 assert(vm.runInContext("officialNoticeUrl('https://attacker.example/message/1')",context)==='');
 const svg=vm.runInContext("chart({symbol:'<script>',currency:'NOK',history:"+JSON.stringify(history)+"},'3M')",context);
 assert(!svg.includes('<script>'));
 assert(svg.includes('&lt;script&gt;'));
 vm.runInContext("researchView.model_busy=true;researchView.report.llm_status='generating local briefing';renderAdvice()",context);
 assert.strictEqual(nodes['#askButton'].disabled,true);
 assert(nodes['#commentary'].textContent.includes('Ollama is writing'));
 assert(!nodes['#commentary'].textContent.includes('Install Ollama'));
 console.log('UI contract and chart rendering smoke checks passed (not browser QA).');
 }catch(error){console.error(error);process.exitCode=1;}
});
