"""Chronological, five-year evaluation. See research/PROTOCOL.md before changing."""
from __future__ import annotations
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import csv
import numpy as np
import pandas as pd

from pipeline.refresh import ROOT, fetch, read, write, expected_session, provenance
from pipeline.engine import vstop_series, obv_macd_series
from pipeline.calendar import exchange_sessions

BENCH='^CRSLDX'
HORIZONS=[5,10,20,40,60]
VARIANTS=['baseline','no_chase','market_trend','combined']


def benchmark_calendar_gaps(raw, start, end):
    """Detect absences against the independent configured exchange calendar."""
    sessions=exchange_sessions(start,end)
    return [str(x.date()) for x in sessions if x not in raw.index or
            pd.isna(raw.loc[x,'Close'])]


def features(d,b,cfg):
    """Vectorised version of engine.analyze, with the same backward-only inputs."""
    d=d.reindex(b.index)
    c,h,l,v,cash=(d[k] for k in ['Close','High','Low','Volume','CashTurnover'])
    r=lambda s,n:(s/s.shift(n)-1)*100
    r5,r20,r60=(r(c,n) for n in [5,20,60])
    rs20,rs60=r20-r(b.Close,20),r60-r(b.Close,60)
    s20,s50=c.rolling(20).mean(),c.rolling(50).mean()
    turn=cash.rolling(60).median()
    part=cash.rolling(5).median()/cash.shift(5).rolling(20).median()
    location=((c-l)/(h-l)).where(h!=l,.5).rolling(3).mean()
    largest=r(c,1).abs().rolling(5).max()
    valid=c.notna().rolling(cfg['min_history']).sum().eq(cfg['min_history'])
    valid &= (turn>=cfg['min_turnover_cr']) & (v.gt(0).rolling(60).sum()>=55)
    technical=(c>s20)&(s20>s50)&(s20>s20.shift(5))&(r5>0)&(r20>0)
    participation=(part>=cfg['min_participation'])&(location>=.55)
    def anchors(window,continuation):
        level=h.shift(1).rolling(window).max()
        crossed=(c>level)&(c.shift(1)<=level)
        if continuation:
            prior=(c.shift(11)/c.shift(51)-1)*100
            width=(h.shift(1).rolling(10).max()/l.shift(1).rolling(10).min()-1)*100
            down=c.diff().lt(0).shift(1).rolling(10).sum()
            crossed &= (prior>=10)&(width<=12)&(down>=3)
        chosen=pd.Series(np.nan,index=d.index);ages=pd.Series(np.nan,index=d.index)
        for age in range(cfg['lookback_breakout_sessions']-1,cfg['confirmation_closes']-2,-1):
            a=level.shift(age)
            ok=crossed.shift(age,fill_value=False)&(c.rolling(age+1).min()>a)&chosen.isna()
            # engine.crossed_and_held also requires >=60 bars before the crossing.
            ok &= np.arange(len(d))>=max(window,60)+age
            chosen.loc[ok]=a.loc[ok];ages.loc[ok]=age
        return chosen,ages
    cont,ca=anchors(20,True);normal,na=anchors(60,False)
    continuation=cont.notna()&(r60>0)
    level=normal.where(~continuation,cont);age=na.where(~continuation,ca)
    extension=(c/level-1)*100
    extended=(r5>cfg['max_return_5d_pct'])|((c/s20-1)*100>cfg['max_sma_extension_pct'])|(extension>cfg['max_extension_pct'])
    candidate=valid&technical&participation&level.notna()&~extended&(largest<=cfg['event_day_pct'])
    return pd.DataFrame({'candidate':candidate,'continuation':continuation,'level':level,'age':age,
        'r5':r5,'r20':r20,'r60':r60,'rs20':rs20,'rs60':rs60,
        'participation':part,'extension':extension,'eligible':valid},index=d.index)


def industry_medians(universe, frames, b, cfg):
    """Backward-only eligible-stock return medians for each current industry."""
    groups={}
    for meta in universe:
        d=frames.get(meta['yahoo'])
        if d is None:
            continue
        f=features(d,b,cfg)
        groups.setdefault(meta['industry_group'],[]).append(
            pd.DataFrame({'r20':f.r20.where(f.eligible),'r60':f.r60.where(f.eligible)}))
    out={}
    for industry,parts in groups.items():
        r20=pd.concat([x.r20 for x in parts],axis=1)
        r60=pd.concat([x.r60 for x in parts],axis=1)
        # Very small peer sets are unstable and therefore left unranked.
        out[industry]={'r20':r20.median(axis=1).where(r20.count(axis=1)>=3),
                       'r60':r60.median(axis=1).where(r60.count(axis=1)>=3)}
    return out


def episodes(meta,d,b,cfg,start,end,midcap,industry=None):
    f=features(d,b,cfg);aligned=d.reindex(b.index);c=aligned.Close.to_numpy();last={};records=[]
    trend=midcap.Close>midcap.Close.rolling(200).mean()
    for i in np.flatnonzero(f.candidate.to_numpy()):
        row=f.iloc[i];setup='Leaders resuming' if row.continuation else 'Confirmed moves'
        crossing=i-int(row.age);previous=last.get(setup)
        if previous:
            pi,pl=previous
            segment=c[pi+1:crossing]
            if not np.any(segment<pl):continue
        last[setup]=(i,float(row.level))
        if not start<=b.index[i]<=end:continue
        peer20=industry['r20'].iloc[i] if industry else np.nan
        peer60=industry['r60'].iloc[i] if industry else np.nan
        record={'isin':meta['isin'],'symbol':meta['nse'],'ticker':meta['yahoo'],
            'industry':meta['industry_group'],'setup':setup,'signal':str(b.index[i].date()),
            'i':int(i),'rs20':float(row.rs20),'participation':float(row.participation),
            'stock_vs_industry_r20':float(row.r20-peer20) if np.isfinite(peer20) else None,
            'stock_vs_industry_r60':float(row.r60-peer60) if np.isfinite(peer60) else None,
            'extension':float(row.extension),'r5':float(row.r5),
            'market_trend':bool(trend.iloc[i])}
        record['outcomes']={str(h):outcome(aligned,midcap,i,h) for h in HORIZONS}
        records.append(record)
    return records,f.eligible


def outcome(d,b,i,h):
    entry=i+1;end=i+h
    if end>=len(b):return {'status':'immature'}
    segment=d.iloc[entry:end+1];bench=b.iloc[entry:end+1]
    needed=['Open','High','Low','Close']
    if segment[needed].isna().any().any() or bench[['Open','Close']].isna().any().any():
        return {'status':'missing_prices'}
    o=float(segment.Open.iloc[0]);bo=float(bench.Open.iloc[0]);ratio=float(segment.Close.iloc[-1]/o)
    benchmark=float((bench.Close.iloc[-1]/bo-1)*100)
    net=(ratio*.9975/1.0025-1)*100
    stress=(ratio*.995/1.005-1)*100
    late=(ratio/1.01*.9975/1.0025-1)*100
    dividend_allowance=((1+benchmark/100)*1.02**(h/252)-1)*100
    up=np.flatnonzero((segment.High/o-1).to_numpy()>=.10)
    down=np.flatnonzero((segment.Low/o-1).to_numpy()<=-.05)
    first=('ambiguous' if len(up) and len(down) and up[0]==down[0] else
           'target_first' if len(up) and (not len(down) or up[0]<down[0]) else
           'risk_first' if len(down) else 'neither')
    return {'status':'resolved','entry':str(b.index[entry].date()),'exit':str(b.index[end].date()),
        'gross':(ratio-1)*100,'net':net,'benchmark':benchmark,'excess':net-benchmark,
        'excess_yield_adjusted':net-dividend_allowance,'stress_net':stress,'late_net':late,
        'mfe':float((segment.High.max()/o-1)*100),'mae':float((segment.Low.min()/o-1)*100),
        'first_passage':first}


def selected(r,variant):
    chase=r['extension']<=5 and r['r5']<=10
    return variant=='baseline' or variant=='no_chase' and chase or variant=='market_trend' and r['market_trend'] or variant=='combined' and chase and r['market_trend']


def block_interval(obs,key):
    if len(obs)<2:return None
    groups={}
    for r,o in obs:
        month=o['entry'][:7];groups.setdefault(month,[]).append(o[key])
    if len(groups)<6:return None
    sums=np.array([sum(v) for v in groups.values()]);counts=np.array([len(v) for v in groups.values()])
    rng=np.random.default_rng(173);draw=rng.integers(0,len(sums),size=(1000,len(sums)))
    estimates=sums[draw].sum(axis=1)/counts[draw].sum(axis=1)
    return [round(float(x),2) for x in np.quantile(estimates,[.025,.975])]


def summarize(records,h,start,end,variant='baseline',setup=None):
    subset=[r for r in records if start<=r['signal']<=end and selected(r,variant) and (setup is None or r['setup']==setup)]
    obs=[];status=Counter()
    for r in subset:
        o=r['outcomes'][str(h)]
        if o['status']=='resolved' and o['exit']>end:status['boundary_purged']+=1
        elif o['status']=='resolved':obs.append((r,o));status['resolved']+=1
        else:status[o['status']]+=1
    base={'horizon':h,'detections':len(subset),'n':len(obs),'status':dict(status)}
    if not obs:return base
    arr=lambda k:np.array([o[k] for _,o in obs])
    mean=lambda k:round(float(np.mean(arr(k))),2)
    median=lambda k:round(float(np.median(arr(k))),2)
    base.update({'win_rate':round(float(np.mean(arr('net')>0)*100),1),
        'beat_rate':round(float(np.mean(arr('excess')>0)*100),1),
        'beat_rate_yield_adjusted':round(float(np.mean(arr('excess_yield_adjusted')>0)*100),1),
        'mean_net':mean('net'),'median_net':median('net'),'mean_excess':mean('excess'),
        'median_excess':median('excess'),'mean_excess_yield_adjusted':mean('excess_yield_adjusted'),
        'net_p10_p90':[round(float(x),2) for x in np.quantile(arr('net'),[.1,.9])],
        'median_mfe':median('mfe'),'median_mae':median('mae'),
        'reach_5pct':round(float(np.mean(arr('mfe')>=5)*100),1),
        'reach_10pct':round(float(np.mean(arr('mfe')>=10)*100),1),
        'mean_stress_net':mean('stress_net'),'mean_late_net':mean('late_net'),
        'first_passage':dict(Counter(o['first_passage'] for _,o in obs)),
        'excess_ci95':block_interval(obs,'excess_yield_adjusted')})
    return base


def choose(variants):
    baseline=variants['baseline']['validation'];qualified=[]
    for name in VARIANTS[1:]:
        dev,val=variants[name]['development'],variants[name]['validation']
        if dev.get('n',0)>=100 and val.get('n',0)>=100 and dev['mean_excess_yield_adjusted']>0 and val['mean_excess_yield_adjusted']>0 and val['mean_excess_yield_adjusted']>=baseline.get('mean_excess_yield_adjusted',float('inf'))+.5:
            qualified.append(name)
    return max(qualified,key=lambda k:variants[k]['validation']['mean_excess_yield_adjusted']) if qualified else 'baseline'


def dual_negative_states(frames,cfg):
    """Completed-close exit observations; execution belongs to the next open."""
    out={}
    for ticker,d in frames.items():
        if ticker==BENCH or d is None or d.empty:
            continue
        _,vtrend,_=vstop_series(d,cfg.get('vstop_length',10),cfg.get('vstop_factor',2))
        _,obv_state,_=obv_macd_series(d)
        out[ticker]=pd.Series((vtrend<0)&(obv_state<0),index=d.index)
    return out


def portfolio(records,frames,b,start,end,variant='baseline',exit_rule='fixed_20',exit_signals=None):
    days=b.index[(b.index>=start)&(b.index<=end)]
    if len(days)<2:return None
    if exit_rule not in ['fixed_20','dual_negative']:
        raise ValueError(f'Unknown exit rule: {exit_rule}')
    if exit_rule=='dual_negative' and exit_signals is None:
        raise ValueError('Dual-negative exit states are required')
    positions=[None]*10;cash=np.full(10,.1);equity=[];exposure=[];events={};trades=0;missing_marks=0
    rule_exits=0;holding_sessions=[];delayed_exit_opens=0
    for r in records:
        if selected(r,variant) and start<=r['signal']<=end and r['i']+1<len(b):
            events.setdefault(b.index[r['i']+1],[]).append(r)
    for day in days:
        # A bearish state is known only after the prior close. Exit at this
        # session's open, then allow that cash sleeve to accept a new signal.
        if exit_rule=='dual_negative':
            for j,p in enumerate(positions):
                if p is None or not p['exit_pending']:
                    continue
                d=frames[p['ticker']]
                valid=day in d.index and np.isfinite(d.loc[day,'Open']) and d.loc[day,'Open']>0
                if valid:
                    cash[j]=p['shares']*float(d.loc[day,'Open'])*.9975
                    holding_sessions.append(p['age']);positions[j]=None;rule_exits+=1
                else:
                    delayed_exit_opens+=1
        active={p['ticker'] for p in positions if p};industries=Counter(p['industry'] for p in positions if p)
        for r in sorted(events.get(day,[]),key=lambda x:(-(x.get('stock_vs_industry_r20') if x.get('stock_vs_industry_r20') is not None else -999),-x['participation'],-x['rs20'],x['symbol'])):
            if r['ticker'] in active or industries[r['industry']]>=2:continue
            free=next((j for j,p in enumerate(positions) if p is None),None)
            if free is None:break
            d=frames[r['ticker']]
            if day not in d.index:continue
            opening=float(d.loc[day,'Open'])
            if not np.isfinite(opening) or opening<=0:continue
            exit_i=r['i']+20
            positions[free]={'ticker':r['ticker'],'industry':r['industry'],'shares':cash[free]/(opening*1.0025),
                             'mark':opening,'exit':b.index[exit_i] if exit_i<len(b) else pd.Timestamp.max,
                             'exit_pending':False,'age':0}
            cash[free]=0;active.add(r['ticker']);industries[r['industry']]+=1;trades+=1
        deployed=0
        for j,p in enumerate(positions):
            if p is None:continue
            d=frames[p['ticker']]
            valid=day in d.index and np.isfinite(d.loc[day,'Close'])
            if valid:p['mark']=float(d.loc[day,'Close'])
            else:missing_marks+=1
            p['age']+=1
            if exit_rule=='fixed_20' and day>=p['exit'] and valid:
                cash[j]=p['shares']*p['mark']*.9975;positions[j]=None
                holding_sessions.append(p['age']);rule_exits+=1
            else:deployed+=p['shares']*p['mark']
            if positions[j] is not None and exit_rule=='dual_negative' and valid:
                signal=exit_signals.get(p['ticker'])
                if signal is not None and day in signal.index and bool(signal.loc[day]):
                    p['exit_pending']=True
        value=float(cash.sum()+deployed);equity.append(value);exposure.append(deployed/value)
    # Liquidation assumption for remaining holdings; stale marks counted explicitly.
    final=float(cash.sum()+sum(p['shares']*p['mark']*.9975 for p in positions if p));equity[-1]=final
    curve=np.array([1.]+equity);years=(days[-1]-days[0]).days/365.25
    benchmark_missing=int(b.loc[days,'Close'].isna().sum())
    # A buy-and-hold position is merely marked at its last available close on
    # a missing quote day. Individual trade comparisons never fill gaps.
    benchmark=(b.loc[days,'Close'].ffill()/b.loc[days[0],'Open']).to_numpy(float)
    growth=1.02**((days-days[0]).days.to_numpy()/365.25)
    dd=lambda a:float(np.min(a/np.maximum.accumulate(a)-1)*100)
    return {'exit_rule':exit_rule,'trades':trades,'rule_exits':rule_exits,
        'end_liquidations':sum(p is not None for p in positions),
        'delayed_exit_opens':delayed_exit_opens,
        'median_holding_sessions':round(float(np.median(holding_sessions)),1) if holding_sessions else None,
        'cagr':round((final**(1/years)-1)*100,2),
        'benchmark_cagr':round((benchmark[-1]**(1/years)-1)*100,2),
        'benchmark_cagr_yield_adjusted':round(((benchmark[-1]*growth[-1])**(1/years)-1)*100,2),
        'max_drawdown':round(dd(curve),2),'benchmark_max_drawdown':round(dd(np.r_[1,benchmark]),2),
        'average_exposure':round(float(np.mean(exposure))*100,1),'missing_price_marks':missing_marks,
        'benchmark_missing_marks':benchmark_missing,
        'unresolved_exit_positions':sum(p is not None and
            (p['exit_pending'] if exit_rule=='dual_negative' else p['exit']<=days[-1]) for p in positions),
        'curve':[{'date':str(day.date()),'strategy':round(float(e)*100,3),'benchmark':round(float(bv)*100,3)} for day,e,bv in zip(days,equity,benchmark)]}


def run():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);parser.add_argument('--cached',action='store_true');args=parser.parse_args()
    cfg=read(ROOT/'config/model.json',{});universe=list(csv.DictReader(open(ROOT/'config/universe.csv')))
    if args.limit:universe=universe[:args.limit]
    requested=expected_session();cache=ROOT/'tmp/backtest-prices';cache.mkdir(parents=True,exist_ok=True)
    tickers=list(dict.fromkeys([BENCH]+[r['yahoo'] for r in universe]))
    frames={}
    if args.cached and read(cache/'requested.json',{}).get('session')==requested:
        for p in cache.glob('*.csv.gz'):
            d=pd.read_csv(p,index_col=0,parse_dates=True);frames[p.name[:-7]]=d
        # Old caches may retain retired benchmarks. They must not inflate the
        # current-universe coverage count or enter the reproducibility manifest.
        frames={ticker:d for ticker,d in frames.items() if ticker in tickers}
    missing=[t for t in tickers if t not in frames]
    if missing:frames.update(fetch(missing,requested,require_current=False,period='7y'))
    write(cache/'requested.json',{'session':requested})
    manifests=[]
    for t,d in frames.items():
        target=cache/f'{t}.csv.gz';d.to_csv(target,compression={'method':'gzip','mtime':0})
        manifests.append({'ticker':t,'rows':len(d),'first':str(d.index[0].date()),'last':str(d.index[-1].date()),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    write(cache/'manifest.json',manifests)
    if BENCH not in frames:raise RuntimeError('Nifty 500 history is required; no substitute index used')
    raw_benchmark=frames[BENCH]
    calendar=exchange_sessions(raw_benchmark.index[0],raw_benchmark.index[-1])
    b=raw_benchmark.reindex(calendar);mid=b
    end=b.index[-1];start=end-pd.DateOffset(years=5)
    benchmark_gaps=benchmark_calendar_gaps(raw_benchmark,start,end)
    print('Benchmark missing sessions:',benchmark_gaps,flush=True)
    if b.index[0]>start-pd.DateOffset(years=1) or mid.Close.first_valid_index()>start-pd.DateOffset(years=1):
        raise RuntimeError('Benchmark history does not cover five years plus one warmup year')
    if len(benchmark_gaps)>len(mid.loc[start:end])*.01:
        raise RuntimeError('Benchmark is missing more than 1% of historical sessions')
    if mid.loc[start:end].iloc[0][['Open','Close']].isna().any():
        raise RuntimeError('The initial benchmark purchase price is missing')
    dev_end=start+pd.DateOffset(years=3)-pd.Timedelta(days=1)
    val_start=dev_end+pd.Timedelta(days=1);val_end=start+pd.DateOffset(years=4)-pd.Timedelta(days=1)
    hold_start=val_end+pd.Timedelta(days=1)
    ranges={'full':(str(start.date()),str(end.date())),'development':(str(start.date()),str(dev_end.date())),
            'validation':(str(val_start.date()),str(val_end.date())),'holdout':(str(hold_start.date()),str(end.date()))}
    peers=industry_medians(universe,frames,b,cfg)
    records=[];eligible=pd.Series(0,index=b.index);missing_symbols=[]
    for n,meta in enumerate(universe):
        d=frames.get(meta['yahoo'])
        if d is None:missing_symbols.append(meta['nse']);continue
        rs,e=episodes(meta,d,b,cfg,start,end,mid,peers.get(meta['industry_group']));records.extend(rs);eligible+=e.astype(int)
        if n%100==0:print(f'evaluated {n+1}/{len(universe)}: {len(records)} episodes',flush=True)
    if len(frames)-1<len(universe)*.85:raise RuntimeError('Historical symbol coverage below 85%; refusing a partial-universe headline result')
    variants={name:{partition:summarize(records,20,*ranges[partition],name) for partition in ['development','validation']} for name in VARIANTS}
    # This choice is completed before any holdout statistics are read.
    chosen=choose(variants)
    for name in VARIANTS:
        variants[name]['holdout']=summarize(records,20,*ranges['holdout'],name)
    results={part:[summarize(records,h,*dates,chosen) for h in HORIZONS] for part,dates in ranges.items()}
    annual=[{'year':year,**summarize(records,20,max(ranges['full'][0],f'{year}-01-01'),min(ranges['full'][1],f'{year}-12-31'),chosen)} for year in range(start.year,end.year+1)]
    setups={s:[summarize(records,h,*ranges['full'],chosen,s) for h in HORIZONS] for s in ['Confirmed moves','Leaders resuming']}
    portfolio_variants=list(dict.fromkeys(['baseline',chosen]))
    ports={name:{part:portfolio(records,frames,mid,*ranges[part],name) for part in ['full','holdout']} for name in portfolio_variants}
    exits=dual_negative_states(frames,cfg)
    exit_ports={name:{part:portfolio(records,frames,mid,*ranges[part],name,'dual_negative',exits)
                      for part in ['full','holdout']} for name in portfolio_variants}
    hold=variants[chosen]['holdout'];ci=hold.get('excess_ci95');p=ports[chosen]['holdout']
    supported=bool(hold.get('n',0)>=100 and ci and ci[0]>0 and p and p['cagr']>p['benchmark_cagr_yield_adjusted'])
    report={'schema':1,'status':'complete','model':cfg['version'],'generated':datetime.now(timezone.utc).isoformat(),
        'provenance':{**provenance(cfg),'input_manifest_sha256':hashlib.sha256(json.dumps(manifests,sort_keys=True).encode()).hexdigest()},
        'ranking_evidence':{'status':'not_run','reason':'The new shadow score requires a fresh chronological replay; the previously inspected holdout is not reused as untouched validation.'},
        'benchmark':{'name':'Nifty 500','ticker':BENCH,'type':'price index','dividend_sensitivity':'Additional 2% annual benchmark yield; not an official TRI'},
        'ranges':ranges,'selected_variant':chosen,'holdout_supports_candidate':supported,
        'selection':{'stock_qualification':'absolute price trend and confirmed move',
                     'candidate_ranking':'20-session stock return minus eligible industry median',
                     'benchmark_scope':'market regime, sector context, and portfolio outcome comparison'},
        'conclusion':'Positive holdout evidence, subject to material survivorship and execution limitations.' if supported else 'The holdout does not establish reliable index-beating performance. Do not treat confirmation as a profitable edge.',
        'variants':variants,'results':results,'annual':annual,'setups':setups,'portfolios':ports,
        'exit_portfolios':exit_ports,
        'coverage':{'registry':len(universe),'downloaded':len(frames)-1,'missing_symbols':missing_symbols,
                    'benchmark_missing_sessions':benchmark_gaps,
                    'daily_min_eligible':int(eligible.loc[start:end].min()),'daily_median_eligible':int(eligible.loc[start:end].median()),
                    'episodes':len(records),'input_manifest_sha256':hashlib.sha256(json.dumps(manifests,sort_keys=True).encode()).hexdigest()},
        'limitations':['Current surviving registry; not point-in-time exchange membership. Delisted and failed firms may be missing.',
            'Adjusted stock returns versus price-only index; yield sensitivity is an assumption, not the official TRI.',
            'Next-open execution is an assumption; circuit limits, surveillance restrictions and capacity are not reconstructed.',
            'Industry caps use current classifications. Historical classifications are unavailable.',
            'Yahoo historical revisions and corporate-action errors may remain. Raw inputs are retained as a workflow artifact.',
            'Missing benchmark quotes leave trade comparisons unresolved. The buy-and-hold curve carries the last observed mark on those dates.',
            'Historical replay assumes data were available after each close; actual publication delays are not reconstructed.',
            'The dual-negative exit overlay uses the full retained historical input for path-dependent indicators; live refreshes use a two-year download, so marginal states can differ with initialization history.',
            'MFE is the best subsequent high, not a sell rule or an achievable realised return.',
            'Month-block intervals address some clustering but do not eliminate survivorship bias or model-selection uncertainty.']}
    output=ROOT/('tmp/backtest-limited' if args.limit else 'data/backtest');output.mkdir(parents=True,exist_ok=True)
    write(output/'report.json',report)
    # Flatten full episode outcomes for independent audit; no personal user data.
    rows=[]
    for r in records:
        for horizon,o in r['outcomes'].items():rows.append({**{k:v for k,v in r.items() if k not in ['outcomes','i']},'horizon':horizon,**o})
    pd.DataFrame(rows).to_csv(output/'trades.csv.gz',index=False,compression={'method':'gzip','mtime':0})
    write(output/'inputs.json',manifests)
    print(json.dumps({'selected':chosen,'coverage':report['coverage'],'holdout':hold,'conclusion':report['conclusion']},indent=2),flush=True)


if __name__=='__main__':run()
