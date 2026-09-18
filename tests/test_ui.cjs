// DOM integration tests; fixtures are deliberately synthetic, never published as market data.
const {JSDOM}=require('jsdom');
const fs=require('node:fs');
const assert=require('node:assert/strict');
const html=fs.readFileSync('index.html','utf8'),code=fs.readFileSync('app.js','utf8');
const base={isin:'INE000000001',symbol:'TEST',name:'Synthetic Test Company',sector:'Test industry',asof:'2026-09-18',last:114,r5:4,r20:12,rs20:10,rs60:15,turnover_cr:12,participation:2,extension:3,candidate:true,setup:'Confirmed moves',anchor:110,anchor_adjusted:110,leader:true,reasons:['Held above reference'],risks:['Synthetic test'],tracking:null};
const snapshot={schema:1,status:'ready',asof:'2026-09-18',rows:[base,{...base,isin:'INE000000002',symbol:'OTHER',name:'Other Test Company',candidate:false,setup:'Other',leader:false}],themes:[{name:'Test theme',taxonomy:'Curated theme',members:[base.isin],status:'Improving',r20:12,breadth:80,breadth_change:10,resolved:3,total:3,rs20:10}],summary:[],tracking:[],market:{r20:2,breadth:60},coverage:{fresh:2,universe:2,eligible:2,reasons:{}},excluded:[]};
async function boot(data=snapshot,chartDate=data.asof){
 const dom=new JSDOM(html,{url:'https://example.test/Stocks/',runScripts:'outside-only'}),w=dom.window;
 w.HTMLDialogElement.prototype.showModal=function(){this.open=true};
 w.HTMLDialogElement.prototype.close=function(){this.open=false;this.dispatchEvent(new w.Event('close'))};
 w.fetch=async url=>({ok:true,json:async()=>url.includes('latest')?data:url.includes('health')?{status:'ok'}:{asof:chartDate,charts:{[base.isin]:{dates:['2026-09-18'],o:[112],h:[115],l:[110],c:[114],v:[1000]}}}});
 w.eval(code);await new Promise(r=>setImmediate(r));return {dom,w,d:w.document};
}
(async()=>{
 let {dom,w,d}=await boot();
 assert.equal(d.querySelectorAll('#stock-rows tr').length,1,'default only confirmed');
 d.querySelector('[data-watch]').click();assert.equal(JSON.parse(w.localStorage.getItem('stocks-workspace-v1'))[base.isin].watch,true);
 d.querySelector('[data-stock]').click();await new Promise(r=>setImmediate(r));
 assert.equal(d.querySelector('#stock-dialog').open,true);assert.ok(d.querySelector('#detail-chart svg'));
 let note=d.querySelector('#stock-note');note.value='Check earnings';note.dispatchEvent(new w.Event('input'));
 assert.equal(JSON.parse(w.localStorage.getItem('stocks-workspace-v1'))[base.isin].note,'Check earnings');
 d.querySelector('[data-review="dismissed"]').click();assert.equal(d.querySelectorAll('#stock-rows tr').length,0);
 d.querySelector('[data-review="unreviewed"]').click();d.querySelector('#stock-dialog').close();
 d.querySelector('[data-view="watchlist"]').click();assert.equal(d.querySelectorAll('#stock-rows tr').length,1);
 d.querySelector('[data-view="themes"]').click();d.querySelector('#theme-grid [data-theme]').click();assert.equal(d.querySelectorAll('#stock-rows tr').length,1);
 d.querySelector('#clear-theme').click();assert.equal(d.querySelectorAll('#stock-rows tr').length,2);
 let search=d.querySelector('#search');search.value='OTHER';search.dispatchEvent(new w.Event('input'));assert.equal(d.querySelectorAll('#stock-rows tr').length,1);assert.match(d.querySelector('#stock-rows').textContent,/Other Test/);
 dom.window.close();
 ({dom,w,d}=await boot({schema:1,status:'awaiting_first_scan',asof:null,rows:[],themes:[],tracking:[],summary:[]}));
 assert.match(d.querySelector('#empty').textContent,/Waiting for the first/);assert.equal(d.querySelectorAll('#stock-rows tr').length,0);assert.match(d.querySelector('#stats').textContent,/—/);dom.window.close();
 ({dom,w,d}=await boot(snapshot,'2026-09-17'));d.querySelector('[data-stock]').click();await new Promise(r=>setImmediate(r));assert.match(d.querySelector('#detail-chart').textContent,/sessions differ/);dom.window.close();
 console.log('UI integration passed: confirmed defaults, watchlist, notes, review, theme filter, search, pending state and mismatched charts.');
})().catch(e=>{console.error(e);process.exitCode=1});
