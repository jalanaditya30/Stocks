'use strict';
// Read the committed data directly on Pages so scheduled bot commits need no site rebuild.
const DATA_ROOT=location.hostname==='jalanaditya30.github.io'?'https://raw.githubusercontent.com/jalanaditya30/Stocks/main/data/':'data/';
const $=id=>document.getElementById(id);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const num=(v,d=1)=>v==null||!Number.isFinite(Number(v))?'—':Number(v).toLocaleString('en-IN',{minimumFractionDigits:d,maximumFractionDigits:d});
const pct=v=>v==null?'—':`${v>0?'+':''}${num(v)}%`;
const pp=v=>v==null?'—':`${v>0?'+':''}${num(v)} pp`;
const color=v=>v>0?'positive':v<0?'negative':'';
const KEY='stocks-workspace-v1';
let historical=null;
let D={rows:[],themes:[],tracking:[],summary:[]},health={},charts=null,workspace={},view='overview',theme=null,all=false,detail=null,toastTimer;
try{const saved=JSON.parse(localStorage.getItem(KEY)||'{}');if(saved&&typeof saved==='object'&&!Array.isArray(saved))workspace=saved;}catch{}
const pref=isin=>workspace[isin]||{};
function toast(message){$('toast').textContent=message;$('toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('toast').hidden=true,3200);}
function save(){try{localStorage.setItem(KEY,JSON.stringify(workspace));}catch{toast('Browser storage unavailable. Export your workspace to retain changes.');}}
function setPref(isin,update){workspace[isin]={...pref(isin),...update};save();}
function watched(isin){return pref(isin).watch===true;}
function stockById(id){return D.rows.find(r=>r.isin===id);}
function changeView(next){view=next;all=false;theme=null;if(next==='watchlist')$('setup').value='all';else $('setup').value='confirmed';render();}
const titles={overview:['THE DAILY PICTURE','Moves with follow-through.','Confirmed stock moves. Strengthening themes. A clearer place to start.'],candidates:['FROM OBSERVATION TO INVESTIGATION','Find your next research idea.','Price confirmation comes first. Then inspect participation, context and risk.'],themes:['THE BIGGER PICTURE','Follow strength as it spreads.','See the typical member, the breadth of a move, and the leaders within it.'],watchlist:['YOUR WORKING SET','Keep the ideas. Track the change.','Your saved stocks and review notes, kept privately in this browser.'],evidence:['THE PROSPECTIVE RECORD','Evidence before conviction.','First detections stay on record. Good outcomes and failed setups both count.']};

function themeCard(t){const state=t.status==='Improving'||t.status==='Leading'?'green':t.status==='Weakening'?'amber':'';
 return `<button class="theme-card" data-theme="${esc(t.taxonomy+'|'+t.name)}"><div class="theme-card-head"><span class="badge ${state}">${esc(t.status)}</span><span class="muted">↗</span></div><h3>${esc(t.name)}</h3><div class="theme-metrics"><div><b class="${color(t.r20)}">${pct(t.r20)}</b><small>Median · 20 sessions</small></div><div><b class="${color(t.breadth_change)}">${pp(t.breadth_change)}</b><small>Breadth change · 5D</small></div></div><div class="breadth-track"><i style="width:${Math.max(0,Math.min(100,t.breadth||0))}%"></i></div><div class="theme-foot"><span>${num(t.breadth,0)}% above 50D average</span><span>${t.resolved}/${t.total} eligible</span></div></button>`;
}

function filtered(){const q=$('search').value.trim().toLowerCase(),setup=$('setup').value,review=$('review-filter').value;
 let rows=D.rows.filter(r=>{
   if(view==='watchlist'&&!watched(r.isin))return false;
   if(theme&&!theme.members.includes(r.isin))return false;
   if(q&&![r.name,r.symbol,r.sector].join(' ').toLowerCase().includes(q))return false;
   if(setup==='confirmed'&&!r.candidate)return false;
   if(setup==='leaders'&&!r.leader)return false;
   if(!['confirmed','leaders','all'].includes(setup)&&r.setup!==setup)return false;
   const state=pref(r.isin).review||'unreviewed';
   if(review==='active'&&state==='dismissed')return false;
   if(!['active','all'].includes(review)&&state!==review)return false;
   return true;
 });
 const k=$('sort').value;
 rows.sort((a,b)=>k==='newest'?String(b.tracking?.first_seen||'').localeCompare(String(a.tracking?.first_seen||''))||b.rs20-a.rs20:
   (b[k]??-Infinity)-(a[k]??-Infinity)||b.participation-a.participation||a.symbol.localeCompare(b.symbol));
 return rows;
}

function renderStocks(){const rows=filtered(),limit=view==='overview'&&!all?15:100,shown=rows.slice(0,all?rows.length:limit);
 $('list-title').textContent=theme?theme.name:view==='watchlist'?'Saved for investigation':view==='overview'?'Your review list':'Stock moves';
 $('result-count').textContent=`${shown.length} of ${rows.length} matching`;
 $('theme-filter').hidden=!theme;
 $('theme-filter').innerHTML=theme?`${esc(theme.taxonomy)}: ${esc(theme.name)} <button id="clear-theme">Clear ×</button>`:'';
 $('stock-rows').innerHTML=shown.map(r=>`<tr><td><button class="company-button" data-stock="${esc(r.isin)}">${esc(r.name)}</button><div class="company-sub"><span>${esc(r.symbol)}</span><span class="badge ${r.candidate?'green':r.setup==='Extended / event'?'amber':''}">${esc(r.candidate?r.setup:r.leader?'Established leader':r.setup)}</span>${r.tracking?.first_seen===D.asof?'<span class="positive">NEW</span>':''}${pref(r.isin).review==='reviewed'?'<span>✓ reviewed</span>':''}</div></td><td>₹${num(r.last,2)}<span class="metric-sub">${esc(r.asof)}</span></td><td class="${color(r.r5)}">${pct(r.r5)}</td><td class="${color(r.rs20)}">${pp(r.rs20)}<span class="metric-sub">Stock ${pct(r.r20)}</span></td><td>${num(r.participation,2)}×<span class="metric-sub">₹${num(r.turnover_cr)}cr / day</span></td><td>${pct(r.extension)}<span class="metric-sub">${r.anchor?'Level ₹'+num(r.anchor,2):'No recent held breakout'}</span></td><td><button class="watch-button ${watched(r.isin)?'saved':''}" data-watch="${esc(r.isin)}" aria-label="${watched(r.isin)?'Remove':'Add'} ${esc(r.symbol)} ${watched(r.isin)?'from':'to'} watchlist" aria-pressed="${watched(r.isin)}">${watched(r.isin)?'★':'☆'}</button></td></tr>`).join('');
 $('empty').hidden=shown.length>0;
 $('empty').innerHTML=D.status!=='ready'?'<strong>Waiting for the first market scan.</strong><p>The workspace is ready. Stocks appear here only after a successful scan of completed sessions. No sample names are shown as live signals.</p>':view==='watchlist'?'<strong>No matching saved stocks.</strong><p>Use the star beside a company to keep it here. If a saved stock becomes ineligible or unavailable, it appears below with a warning.</p>':'<strong>No setups meet these conditions.</strong><p>That is a valid result. Try another view or clear your filters; the scanner does not relax its rules to fill a list.</p>';
 $('show-all').hidden=shown.length>=rows.length;
 if(view==='watchlist'){
   const missing=Object.keys(workspace).filter(id=>watched(id)&&!stockById(id));
   if(missing.length){$('empty').hidden=false;$('empty').innerHTML=(shown.length?'<strong>Saved stocks outside today’s eligible universe</strong>':$('empty').innerHTML)+missing.map(id=>`<div>${esc(pref(id).symbol||id)} — ${esc(D.excluded?.find(x=>x.isin===id)?.reason||'current data unavailable')} <button class="text-button" data-watch="${esc(id)}">Remove</button></div>`).join('');}
 }
}

function renderEvidence(){renderHistorical();const rows=D.summary||[];
 $('evidence-summary').innerHTML=rows.length?`<div class="table-wrap"><table><thead><tr><th>Setup</th><th>Horizon</th><th>Mature observations</th><th>Median net return</th><th>Median net excess vs Nifty</th></tr></thead><tbody>${rows.map(x=>`<tr><td>${esc(x.setup)}</td><td>${x.horizon} sessions</td><td>${x.n}${x.n<30?' · early sample':''}</td><td class="${color(x.median_net)}">${pct(x.median_net)}</td><td class="${color(x.median_excess)}">${pp(x.median_excess)}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty"><strong>No forward observations yet.</strong><p>The first successful scan starts the journal. Mature results appear naturally after 5, 10, 20 and 40 sessions.</p></div>';
 $('journal').innerHTML=[...(D.tracking||[])].reverse().slice(0,150).map(x=>`<div class="journal-item"><div><button class="company-button" data-stock="${esc(x.isin)}">${esc(x.symbol)}</button><small>${esc(x.setup)} · first seen ${esc(x.first_seen)} · ${esc(x.model)}</small></div><div>${esc(x.state)}<small>Since detection: <span class="${color(x.since_detection)}">${pct(x.since_detection)}</span></small></div></div>`).join('');
}

function render(){const t=titles[view];$('page-kicker').textContent=t[0];$('page-title').textContent=t[1];$('page-subtitle').textContent=t[2];
 document.querySelectorAll('.nav').forEach(b=>{b.classList.toggle('active',b.dataset.view===view);if(b.dataset.view===view)b.setAttribute('aria-current','page');else b.removeAttribute('aria-current');});
 $('workspace-tools').hidden=view!=='watchlist';
 $('watch-count').textContent=Object.values(workspace).filter(p=>p.watch).length;
 const ready=D.status==='ready',candidates=D.rows.filter(r=>r.candidate),themes=D.themes.filter(t=>t.taxonomy==='Curated theme'&&t.status==='Improving');
 $('stats').innerHTML=[['Confirmed moves',ready?candidates.filter(r=>r.setup==='Confirmed moves').length:'—','Price crossed and held'],['Leaders resuming',ready?candidates.filter(r=>r.setup==='Leaders resuming').length:'—','Strength after consolidation'],['Themes improving',ready?themes.length:'—','Breadth + relative strength'],['Nifty 50 · 20 sessions',pct(D.market?.r20),ready?`${num(D.market?.breadth,0)}% of eligible stocks above 50D`:'Market context appears after the scan']].map((x,i)=>`<div class="stat"><div class="stat-label">${x[0]}</div><div class="stat-value ${i===3?color(D.market?.r20):''}">${x[1]}</div><div class="stat-foot">${x[2]}</div></div>`).join('');
 $('theme-preview').hidden=view!=='overview'||!ready;
 const featured=D.themes.filter(t=>t.taxonomy==='Curated theme'&&['Improving','Leading'].includes(t.status)).slice(0,3);
 $('theme-cards').innerHTML=featured.length?featured.map(themeCard).join(''):'<p class="section-note">No sufficiently covered theme currently meets the improving or leading conditions.</p>';
 $('stock-section').hidden=!['overview','candidates','watchlist'].includes(view);
 $('themes-section').hidden=view!=='themes';$('evidence-section').hidden=view!=='evidence';
 $('theme-grid').innerHTML=D.themes.filter(t=>t.taxonomy===$('taxonomy').value).map(themeCard).join('')||'<div class="empty">Theme measurements arrive with the first successful scan.</div>';
 renderStocks();renderEvidence();renderQuality();
}

function renderQuality(){const c=D.coverage;
 $('session').textContent=D.asof?`Session · ${D.asof}`:'Awaiting first scan';
 $('coverage-note').textContent=c?`${c.fresh.toLocaleString('en-IN')} / ${c.universe.toLocaleString('en-IN')} fresh · ${c.eligible.toLocaleString('en-IN')} eligible · completed sessions only`:'Completed sessions only. No pre-breakout candidates.';
 const age=D.asof?(Date.now()-Date.parse(D.asof+'T10:00:00Z'))/86400000:0;
 const message=health.status==='delayed'?health.message:health.status==='error'?`Latest refresh failed: ${health.message}. ${D.asof?'Showing the previous successful session '+D.asof+'.':'No market snapshot is available yet.'}`:D.status!=='ready'?'First scan pending. This workspace has no live candidates yet.':age>4?`This snapshot is ${Math.floor(age)} calendar days old (${D.asof}). Check the refresh status before using it.`:'';
 $('health').hidden=!message;$('health').textContent=message;
 $('quality-detail').innerHTML=c?`<p>Session: <b>${esc(D.asof)}</b>. ${c.fresh} of ${c.universe} registry stocks have fresh prices; ${c.eligible} meet history and liquidity requirements. The registry was inherited from Sector-data; it does not claim complete exchange coverage.</p><ul>${Object.entries(c.reasons).map(([k,v])=>`<li>${esc(k)}: ${v}</li>`).join('')}</ul><p>Published: ${esc(D.generated)}. Source: ${esc(D.source)}. A scan below 85% fresh coverage is rejected. Thin, missing and stale names are excluded from the current measurements. Theme coverage is the share of registered members eligible for this scan.</p>`:'<p>No successful market scan has been published. The scheduled workflow runs after the close. Failed scans retain the last successful snapshot and report an error.</p>';
}

function chartMarkup(b,row){if(!b?.dates?.length)return '<div class="empty">Chart unavailable for this snapshot.</div>';
 const n=b.dates.length,W=800,H=260,left=50,right=15,top=15,priceBottom=180,volTop=200,bottom=240;
 const max=Math.max(...b.h,row.anchor_adjusted||0),min=Math.min(...b.l,row.anchor_adjusted||Infinity),span=max-min||1;
 const x=i=>left+i*(W-left-right)/n+(W-left-right)/n/2,y=v=>top+(max-v)/span*(priceBottom-top);
 const bar=Math.max(1,(W-left-right)/n*.6),vmax=Math.max(...b.v,1);
 let svg=`<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="Adjusted daily candlestick prices and volume for ${esc(row.symbol)}">`;
 for(let i=0;i<4;i++){let v=min+span*i/3;svg+=`<line x1="${left}" x2="${W-right}" y1="${y(v)}" y2="${y(v)}" stroke="#e3e9ec"/><text x="3" y="${y(v)+3}" fill="#768690" font-size="10">${num(v,0)}</text>`;}
 for(let i=0;i<n;i++){const fill=b.c[i]>=b.o[i]?'#168a71':'#c37269';svg+=`<g><title>${esc(b.dates[i])}: O ${num(b.o[i],2)}, H ${num(b.h[i],2)}, L ${num(b.l[i],2)}, C ${num(b.c[i],2)}, V ${num(b.v[i],0)}</title><line x1="${x(i)}" x2="${x(i)}" y1="${y(b.h[i])}" y2="${y(b.l[i])}" stroke="${fill}"/><rect x="${x(i)-bar/2}" y="${Math.min(y(b.o[i]),y(b.c[i]))}" width="${bar}" height="${Math.max(1,Math.abs(y(b.o[i])-y(b.c[i])))}" fill="${fill}"/><rect x="${x(i)-bar/2}" y="${bottom-b.v[i]/vmax*(bottom-volTop)}" width="${bar}" height="${b.v[i]/vmax*(bottom-volTop)}" fill="${fill}" opacity=".5"/></g>`;}
 if(row.anchor_adjusted)svg+=`<line x1="${left}" x2="${W-right}" y1="${y(row.anchor_adjusted)}" y2="${y(row.anchor_adjusted)}" stroke="#bc903a" stroke-dasharray="5 4"/><text x="${left+5}" y="${y(row.anchor_adjusted)-5}" font-size="10" fill="#9a7227">Breakout reference</text>`;
 const seen=b.dates.indexOf(row.tracking?.first_seen);if(seen>=0)svg+=`<line x1="${x(seen)}" x2="${x(seen)}" y1="${top}" y2="${bottom}" stroke="#456a91" stroke-dasharray="2 3"/><text x="${Math.max(left,Math.min(x(seen)-60,W-130))}" y="12" font-size="10" fill="#456a91">First detected</text>`;
 return svg+`<text x="${left}" y="257" font-size="10" fill="#768690">${esc(b.dates[0])}</text><text x="${W-80}" y="257" font-size="10" fill="#768690">${esc(b.dates[n-1])}</text></svg><p class="chart-caption">100 completed sessions · adjusted prices · volume below · hover a candle for OHLCV</p>`;
}

async function openStock(id){const r=stockById(id);if(!r){toast('This stock is outside the current eligible snapshot.');return;}detail=id;
 $('detail-sector').textContent=r.sector;$('detail-name').textContent=r.name;$('detail-label').textContent=`${r.symbol} · ${r.isin} · ${r.setup} · ${r.asof}`;
 const p=pref(id),t=r.tracking;
 $('detail-content').innerHTML=`<div class="detail-metrics"><div class="detail-metric"><small>Last close</small><b>₹${num(r.last,2)}</b></div><div class="detail-metric"><small>20D vs Nifty</small><b class="${color(r.rs20)}">${pp(r.rs20)}</b></div><div class="detail-metric"><small>Participation</small><b>${num(r.participation,2)}×</b></div><div class="detail-metric"><small>Since first detection</small><b class="${color(t?.since_detection)}">${pct(t?.since_detection)}</b></div></div><div class="chart" id="detail-chart">Loading chart…</div><div class="detail-columns"><div><h3>Why investigate?</h3><ul>${r.reasons.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div><div><h3>What could weaken the setup?</h3><ul>${r.anchor?`<li>A close below the breakout reference of ₹${num(r.anchor,2)} would weaken the observed price confirmation. This is a reference, not a guaranteed exit price.</li>`:''}${r.risks.map(x=>`<li>${esc(x)}</li>`).join('')}</ul></div></div><p class="section-note">${t?`First detected ${esc(t.first_seen)}. ${esc(t.state)}.`:'No confirmed setup has been recorded for this stock.'}</p><div class="detail-links"><a target="_blank" rel="noopener noreferrer" href="https://www.tradingview.com/chart/?symbol=${encodeURIComponent('NSE:'+r.symbol)}">Open TradingView ↗</a><a target="_blank" rel="noopener noreferrer" href="https://www.screener.in/company/${encodeURIComponent(r.symbol)}/">Open Screener ↗</a></div><div class="review-controls"><button class="action" id="detail-watch">${p.watch?'★ Saved to watchlist':'☆ Add to watchlist'}</button><button class="action secondary ${p.review==='reviewed'?'selected':''}" data-review="reviewed">✓ Reviewed</button><button class="action secondary ${p.review==='dismissed'?'selected':''}" data-review="dismissed">Dismiss</button><button class="text-button" data-review="unreviewed">Reset review</button></div><h3><label for="stock-note">Your research notes / dismissal reason</label></h3><textarea class="note-area" id="stock-note" maxlength="10000" placeholder="What matters here? What would change your view?">${esc(p.note||'')}</textarea><span class="metric-sub">Saved automatically in this browser. Export your workspace for a backup.</span>`;
 if(!$('stock-dialog').open)$('stock-dialog').showModal();
 $('detail-watch').onclick=()=>{setPref(id,{watch:!watched(id),symbol:r.symbol});$('detail-watch').textContent=watched(id)?'★ Saved to watchlist':'☆ Add to watchlist';render();};
 $('stock-note').oninput=e=>setPref(id,{note:e.target.value,symbol:r.symbol});
 document.querySelectorAll('[data-review]').forEach(b=>b.onclick=()=>{setPref(id,{review:b.dataset.review,symbol:r.symbol});document.querySelectorAll('[data-review]').forEach(x=>x.classList.toggle('selected',x.dataset.review===b.dataset.review));render();toast('Review status saved.');});
 try{if(!charts){const response=await fetch(DATA_ROOT+'charts.json',{cache:'no-store'});if(!response.ok)throw Error('Chart feed unavailable');charts=await response.json();}if(detail!==id)return;if(charts.asof!==D.asof)throw Error('Chart and scan sessions differ. Reload the snapshot.');$('detail-chart').innerHTML=chartMarkup(charts.charts[id],r);}catch(e){if(detail===id)$('detail-chart').textContent=e.message;}
}

async function load(){try{const [snapshot,status]=await Promise.all([fetch(DATA_ROOT+'latest.json',{cache:'no-store'}),fetch(DATA_ROOT+'health.json',{cache:'no-store'}).catch(()=>null)]);if(!snapshot.ok)throw Error('Market snapshot unavailable');const next=await snapshot.json();if(next.schema!==1||!Array.isArray(next.rows)||!Array.isArray(next.themes))throw Error('Unsupported market snapshot');D=next;health=status?.ok?await status.json():{};charts=null;render();}catch(e){$('health').hidden=false;$('health').textContent=`Could not load market data: ${e.message}. Try reload. No fresh signals are being inferred.`;renderStocks();}}

document.querySelectorAll('[data-view]').forEach(b=>b.onclick=()=>changeView(b.dataset.view));
for(const id of ['search','setup','sort','review-filter'])$(id).addEventListener('input',()=>{all=false;renderStocks();});
$('taxonomy').onchange=render;$('all-themes').onclick=()=>changeView('themes');$('reload').onclick=()=>{load();toast('Reloading the published market snapshot…');};$('show-all').onclick=()=>{all=true;renderStocks();};
document.addEventListener('click',e=>{const s=e.target.closest('[data-stock]'),w=e.target.closest('[data-watch]'),t=e.target.closest('[data-theme]');if(s)openStock(s.dataset.stock);else if(w){const id=w.dataset.watch;setPref(id,{watch:!watched(id),symbol:stockById(id)?.symbol||pref(id).symbol});render();}else if(t){theme=D.themes.find(x=>x.taxonomy+'|'+x.name===t.dataset.theme);view='candidates';$('setup').value='all';$('search').value='';render();}else if(e.target.id==='clear-theme'){theme=null;render();}});
for(const id of ['method-open','quality-open'])$(id).onclick=()=>$('method-dialog').showModal();
document.querySelectorAll('.close-dialog').forEach(b=>b.onclick=()=>b.closest('dialog').close());
for(const d of document.querySelectorAll('dialog'))d.addEventListener('click',e=>{if(e.target===d){const r=d.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)d.close();}});
$('stock-dialog').addEventListener('close',()=>detail=null);
$('export').onclick=()=>{const blob=new Blob([JSON.stringify({version:1,exported:new Date().toISOString(),workspace},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download='stocks-workspace.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);};
$('export-mobile').onclick=()=>$('export').click();
$('import').onchange=async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>2000000)throw Error('File is too large');const j=JSON.parse(await file.text());if(j.version!==1||!j.workspace||typeof j.workspace!=='object'||Array.isArray(j.workspace))throw Error('Not a Stocks workspace export');const safe={};for(const [id,p] of Object.entries(j.workspace)){if(!/^[A-Z0-9]{12}$/.test(id)||!p||typeof p!=='object')continue;safe[id]={watch:p.watch===true,review:['reviewed','dismissed','unreviewed'].includes(p.review)?p.review:'unreviewed',note:String(p.note||'').slice(0,10000),symbol:String(p.symbol||'').slice(0,50)};}workspace={...workspace,...safe};save();render();toast('Workspace imported.');}catch(err){toast('Import failed: '+err.message);}e.target.value='';};
render();load();loadResearch();

async function loadResearch(){try{const r=await fetch(DATA_ROOT+'backtest/report.json',{cache:'no-store'});if(!r.ok)return;const result=await r.json();if(result.schema===1&&result.status==='complete'){historical=result;renderHistorical();}}catch{/* Keep the explicit awaiting-result state. */}}
function renderHistorical(){const target=$('historical-research');if(!target)return;
 if(!historical){target.innerHTML='<div class="section-heading"><div><span class="eyebrow">FIVE-YEAR HISTORICAL RESEARCH</span><h2>Does the move continue after detection?</h2></div></div><div class="empty"><strong>Historical evaluation is awaiting a published result.</strong><p>Five years of next-session entries, trading costs and Nifty Midcap 150 comparisons. No accuracy or remaining-upside claim is made until the run completes.</p></div>';return;}
 const r=historical,v=r.selected_variant,full=r.ranges.full,hold=r.ranges.holdout,stats=r.results.holdout,twenty=stats.find(x=>x.horizon===20),pf=r.portfolios[v].holdout;
 const variants=Object.entries(r.variants).map(([name,s])=>`<tr><td>${esc(name.replaceAll('_',' '))}${name===v?' · selected on validation':''}</td><td>${num(s.development.mean_excess_yield_adjusted,2)} pp</td><td>${num(s.validation.mean_excess_yield_adjusted,2)} pp</td><td>${num(s.holdout.mean_excess_yield_adjusted,2)} pp</td><td>${s.holdout.n}</td></tr>`).join('');
 target.innerHTML=`<div class="section-heading"><div><span class="eyebrow">FIVE-YEAR HISTORICAL RESEARCH</span><h2>Does the move continue after detection?</h2></div><a class="text-button" href="https://github.com/jalanaditya30/Stocks/blob/main/research/PROTOCOL.md" target="_blank" rel="noopener">Evaluation rules ↗</a></div><p class="section-note">Replay: ${esc(full[0])} to ${esc(full[1])}. Untouched test: ${esc(hold[0])} to ${esc(hold[1])}. Benchmark: Nifty Midcap 150 price index. Current surviving registry: ${r.coverage.downloaded}/${r.coverage.registry} histories downloaded.</p><div class="notice">${esc(r.conclusion)} Stock returns include adjusted dividends; the index is price-only. The selection test also adds an assumed 2% annual benchmark yield. This is not an official total-return-index comparison.</div><h3>Untouched test · ${esc(v.replaceAll('_',' '))}</h3><p class="section-note">Entries use the next session’s open; returns deduct 0.25% each side. Win rate means a positive net return at the stated horizon. It is not a probability assigned to today’s stocks.</p><div class="table-wrap"><table><thead><tr><th>Holding period</th><th>Resolved signals</th><th>Net win rate</th><th>Beat Midcap 150</th><th>Median net return</th><th>Median excess</th></tr></thead><tbody>${stats.map(s=>`<tr><td>${s.horizon} sessions</td><td>${s.n}</td><td>${pct(s.win_rate)}</td><td>${pct(s.beat_rate)}</td><td class="${color(s.median_net)}">${pct(s.median_net)}</td><td class="${color(s.median_excess)}">${pp(s.median_excess)}</td></tr>`).join('')}</tbody></table></div><div class="detail-columns"><div><h3>Room after detection · 20 sessions</h3><p class="section-note">${pct(twenty?.reach_10pct)} reached a high at least 10% above entry. Median best subsequent high: ${pct(twenty?.median_mfe)}. Median worst low: ${pct(twenty?.median_mae)}. The best high is an opportunity statistic, not a realised sale or a price target.</p></div><div><h3>Deploying finite capital · test period</h3><p class="section-note">Ten cash sleeves; at most two holdings per industry; 20-session exits. Strategy CAGR: <b>${pct(pf?.cagr)}</b>; index CAGR: <b>${pct(pf?.benchmark_cagr)}</b> (${pct(pf?.benchmark_cagr_yield_adjusted)} with the assumed yield). Strategy drawdown: ${pct(pf?.max_drawdown)}. Average invested: ${pct(pf?.average_exposure)}.</p></div></div><h3>All predeclared alternatives · 20-session mean excess</h3><p class="section-note">These figures include the assumed benchmark-yield allowance. A research alternative is not automatically promoted to live rules.</p><div class="table-wrap"><table><thead><tr><th>Variant</th><th>Development</th><th>Validation</th><th>Untouched test</th><th>Test observations</th></tr></thead><tbody>${variants}</tbody></table></div><p class="section-note">95% interval for selected test mean excess: ${twenty?.excess_ci95?twenty.excess_ci95.map(x=>num(x,2)).join(' to ')+' pp':'insufficient independent months'}. Resampling uses entry months. Missing historical prices and immature horizons remain unresolved in the audit records.</p><details class="research-limitations"><summary>Coverage, biases and reproducible results</summary><ul>${r.limitations.map(x=>`<li>${esc(x)}</li>`).join('')}</ul><p><a href="${DATA_ROOT}backtest/report.json" target="_blank" rel="noopener">Full results JSON</a> · <a href="${DATA_ROOT}backtest/trades.csv.gz" target="_blank" rel="noopener">Download every historical observation</a></p></details><hr class="research-divider">`;
}
