"""Fetch once, calculate all views on the same closed session, publish atomically."""
from __future__ import annotations
import argparse
import csv
import json
import os
from pathlib import Path
import tempfile
import time
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

import numpy as np
import pandas as pd
import pandas_market_calendars as mcal
import yfinance as yf

from pipeline.engine import normalized, analyze, theme_summary, vstop_series, pct

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT/'data'


def read(path, default):
    return json.loads(path.read_text()) if path.exists() else default


def write(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(payload, separators=(',',':'),allow_nan=False)
    with tempfile.NamedTemporaryFile(mode='w',dir=path.parent,delete=False) as f:
        f.write(content)
        temporary = f.name
    os.replace(temporary,path)


def expected_session(now=None):
    now = pd.Timestamp(now or datetime.now(timezone.utc))
    schedule = mcal.get_calendar('NSE').schedule(
        start_date=(now-timedelta(days=20)).date(),end_date=now.date())
    # Allow three hours after the exchange close for delayed EOD publication.
    closed = schedule[schedule.market_close + pd.Timedelta(hours=3) <= now]
    if closed.empty:
        raise RuntimeError('No completed exchange session in calendar')
    return str(closed.index[-1].date())


def fetch(tickers, asof, require_current=True, period='2y'):
    out = {}
    # Small batches, a single shared pull, and one retry for missing symbols.
    for attempt in range(2):
        pending = [t for t in tickers if t not in out or str(out[t].index[-1].date())!=asof]
        for start in range(0,len(pending),30):
            chunk = pending[start:start+30]
            print(f"fetch pass {attempt+1}: {start+1}-{start+len(chunk)}/{len(pending)}",flush=True)
            try:
                raw = yf.download(chunk,period=period,auto_adjust=False,
                                  group_by='ticker',progress=False,threads=4,timeout=20)
                for t in chunk:
                    try:
                        frame = raw[t] if isinstance(raw.columns,pd.MultiIndex) else raw
                        d = normalized(frame,asof)
                        if d is not None and (not require_current or str(d.index[-1].date())==asof):
                            if t not in out or d.index[-1]>=out[t].index[-1]:
                                out[t]=d
                        else:
                            raw_latest=str(frame.index[-1]) if not frame.empty else 'empty'
                            valid_latest=str(d.index[-1].date()) if d is not None else 'none'
                            print(f'{t}: expected {asof}, provider latest {raw_latest}, valid latest {valid_latest}',flush=True)
                            if t=='^CRSLDX' and not frame.empty:
                                print('Benchmark provider bar:',frame.tail(1).to_json(orient='records'),flush=True)
                    except (KeyError,ValueError,TypeError) as exc:
                        print(f'{t}: unusable response ({type(exc).__name__}: {exc})',flush=True)
                        continue
            except Exception as exc:
                print('batch unavailable:',type(exc).__name__,flush=True)
            time.sleep(1)
        if all(t in out and str(out[t].index[-1].date())==asof for t in tickers):
            break
        if attempt==0:
            time.sleep(5)
    return out


def select_session(universe,frames,benchmark,expected,minimum,max_lag=3):
    """Most recent adequately covered session; never mix dates within a scan."""
    sessions=mcal.get_calendar('NSE').schedule(
        start_date=pd.Timestamp(expected)-pd.Timedelta(days=20),end_date=expected).index
    allowed=set(sessions[-max_lag-1:])
    for day in reversed(benchmark.index):
        if day not in allowed:continue
        fresh=sum(r['yahoo'] in frames and day in frames[r['yahoo']].index for r in universe)
        if fresh/len(universe)>=minimum:return str(day.date())
    raise RuntimeError(f'No common session within {max_lag} exchange sessions meets {minimum:.0%} price coverage')


def replacing_newer_same_model(previous, asof, cfg):
    """Protect chronology within a model without blocking a benchmark migration."""
    return bool(previous.get('asof') and previous['asof']>asof and
                previous.get('model')==cfg['version'])


def track(ledger, rows, frames, benchmark, asof, cfg, record=True):
    """First detection is immutable; next-session open is the executable baseline."""
    benchmark=benchmark.loc[:asof]
    frames={ticker:d.loc[:asof] for ticker,d in frames.items() if not d.loc[:asof].empty}
    known={x['id'] for x in ledger}
    if record:
        for r in rows:
            if not r['candidate']:
                continue
            key=f"{cfg['version']}:{r['isin']}:{r['setup']}:{r['breakout_date']}"
            if key not in known:
                previous=next((s for s in reversed(ledger) if s['isin']==r['isin']
                    and s['setup']==r['setup'] and s['model']==cfg['version']),None)
                d=frames.get(r['yahoo'])
                if previous and d is not None:
                    bd=pd.Timestamp(previous['breakout_date'])
                    if bd in d.index:
                        p=d.index.get_loc(bd)
                        if p>=previous['window']:
                            level=d.High.iloc[p-previous['window']:p].max()
                            between=d.loc[(d.index>pd.Timestamp(previous['first_seen'])) &
                                          (d.index<pd.Timestamp(r['breakout_date']))]
                            # One continuing setup is one observation, even as highs rise.
                            if between.empty or not (between.Close<level).any():
                                continue
                ledger.append({'id':key,'isin':r['isin'],'symbol':r['symbol'],'yahoo':r['yahoo'],
                    'setup':r['setup'],'first_seen':asof,'breakout_date':r['breakout_date'],
                    'window':20 if r['setup']=='Leaders resuming' else 60,'model':cfg['version'],
                    'momentum_confirmations':r.get('momentum_confirmations'),
                    'momentum_checks':r.get('momentum_checks',[]),'vstop_bullish':r.get('vstop_bullish'),
                    'obv_bullish':r.get('obv_bullish'),'adx':r.get('adx'),
                    'efficiency_20':r.get('efficiency_20'),'theme_name':r.get('theme_name'),
                    'theme_state':r.get('theme_state'),'rotation_posture':r.get('rotation_posture')})
                known.add(key)
    result=[]
    calendar=benchmark.index
    for signal in ledger:
        item={**signal,'outcomes':dict(signal.get('outcomes',{})),
              'state':'Awaiting prices','since_detection':None}
        d=frames.get(signal['yahoo'])
        if d is not None:
            day=pd.Timestamp(signal['first_seen'])
            current=str(d.index[-1].date())==asof
            item['price_asof']=str(d.index[-1].date())
            if day in d.index and current:
                item['since_detection']=round(float((d.Close.iloc[-1]/d.loc[day,'Close']-1)*100),2)
            bd=pd.Timestamp(signal['breakout_date'])
            if bd in d.index and current:
                p=d.index.get_loc(bd)
                if p>=signal['window']:
                    level=float(d.High.iloc[p-signal['window']:p].max())
                    item['state']='Below breakout level' if d.Close.iloc[-1]<level else 'Holding breakout level'
            # Never award returns at the same close that generated the signal.
            # An older model's unfinished outcomes are frozen: recalculating them
            # with this model's benchmark would mix two definitions in one record.
            if signal.get('model')==cfg['version']:
                entry=int(calendar.searchsorted(day,side='right')) if day in calendar else len(calendar)
                if entry<len(calendar) and calendar[entry] in d.index:
                    ed=calendar[entry]
                    stock_open=float(d.loc[ed,'Open']); bench_open=float(benchmark.loc[ed,'Open'])
                    item['entry_date']=str(ed.date())
                    for horizon in cfg['forward_horizons']:
                        if item['outcomes'].get(str(horizon),{}).get('upside_version')==1:
                            continue
                        end=entry+horizon-1
                        if end<len(calendar):
                            sessions=calendar[entry:end+1]
                            if not sessions.isin(d.index).all():
                                continue
                            segment=d.loc[sessions]
                            gross=float((segment.Close.iloc[-1]/stock_open-1)*100)
                            br=float((benchmark.Close.iloc[end]/bench_open-1)*100)
                            # Assumed 0.5% total dealing cost, not measured execution.
                            net=float(((segment.Close.iloc[-1]/stock_open)*(1-.0025)/(1+.0025)-1)*100)
                            outcome={'gross':round(gross,2),'net':round(net,2),
                                'benchmark':round(br,2),'excess_net':round(net-br,2),
                                'worst_excursion':round(float((segment.Low.min()/stock_open-1)*100),2)}
                            outcome.update(upside_metrics(segment,stock_open))
                            # Existing completed returns are immutable when adding metrics.
                            item['outcomes'][str(horizon)]={**outcome,**item['outcomes'].get(str(horizon),{})}
        # Completed observations survive provider rolling-history limits and outages.
        signal['outcomes']=dict(item['outcomes'])
        if 'entry_date' in item:signal['entry_date']=item['entry_date']
        result.append(item)
    summary=[]
    for setup in ['Confirmed moves','Leaders resuming']:
        for h in cfg['forward_horizons']:
            outcomes=[r['outcomes'][str(h)] for r in result if r['setup']==setup and str(h) in r['outcomes'] and r['model']==cfg['version']]
            summary.append({'setup':setup,'horizon':h,'n':len(outcomes),
                'total':sum(r['setup']==setup and r['model']==cfg['version'] for r in result),
                **upside_summary(outcomes),
                'median_net':round(float(np.median([o['net'] for o in outcomes])),2) if outcomes else None,
                'median_excess':round(float(np.median([o['excess_net'] for o in outcomes])),2) if outcomes else None})
    for h in cfg['forward_horizons']:
        aligned=[r['outcomes'][str(h)] for r in result if (r.get('momentum_confirmations') or 0)>=3
                 and str(h) in r['outcomes'] and r['model']==cfg['version']]
        summary.append({'setup':'3–4 current support checks','horizon':h,'n':len(aligned),
            'total':sum((r.get('momentum_confirmations') or 0)>=3 and r['model']==cfg['version'] for r in result),
            **upside_summary(aligned),
            'median_net':round(float(np.median([o['net'] for o in aligned])),2) if aligned else None,
            'median_excess':round(float(np.median([o['excess_net'] for o in aligned])),2) if aligned else None})
    return ledger,result,summary


def upside_metrics(segment,entry):
    """Observed opportunity, never an assumed exit at the subsequent high."""
    out={'upside_version':1,'best_excursion':round(float((segment.High.max()/entry-1)*100),2)}
    downside=np.flatnonzero(segment.Low.to_numpy()<=entry*.95)
    for target in (5,10):
        hits=np.flatnonzero(segment.High.to_numpy()>=entry*(1+target/100))
        first=int(hits[0]) if len(hits) else None
        out[f'reach_{target}']=first is not None
        out[f'sessions_to_{target}']=first+1 if first is not None else None
        # OHLC cannot establish intraday ordering if both levels occur together.
        out[f'{target}_before_minus5']=('neither' if first is None and not len(downside) else
            'downside_first' if first is None else 'upside_first' if not len(downside) or first<int(downside[0]) else
            'ambiguous_same_session' if first==int(downside[0]) else 'downside_first')
    return out


def upside_summary(outcomes):
    usable=[o for o in outcomes if o.get('upside_version')==1]
    out={'upside_n':len(usable),'median_best':round(float(np.median([o['best_excursion'] for o in usable])),2) if usable else None,
         'median_worst':round(float(np.median([o['worst_excursion'] for o in usable])),2) if usable else None}
    for target in (5,10):
        times=[o[f'sessions_to_{target}'] for o in usable if o[f'reach_{target}']]
        out[f'reach_{target}_pct']=round(100*len(times)/len(usable),2) if usable else None
        out[f'median_sessions_to_{target}']=float(np.median(times)) if times else None
    return out


def rank_themes(themes, previous=None):
    priority={'Leading':0,'Emerging':1,'Mature':2,'Mixed':3,'Weakening':4,'Avoid':5,'Insufficient coverage':6}
    score=lambda value,missing: missing if value is None else value
    old={(x.get('taxonomy'),x.get('name')):x for x in (previous or [])}
    for taxonomy in ['Curated theme','Industry']:
        group=[x for x in themes if x['taxonomy']==taxonomy]
        group.sort(key=lambda x:(priority.get(x['status'],9),-score(x.get('rs20'),-999),
                                 -score(x.get('rs60'),-999),-score(x.get('breadth'),-1),x['name']))
        for rank,item in enumerate(group,1):
            prior=old.get((taxonomy,item['name']),{})
            item['rank']=rank;item['previous_rank']=prior.get('rank')
            item['rank_change']=prior.get('rank')-rank if prior.get('rank') else None
            item['previous_status']=prior.get('status')
    return sorted(themes,key=lambda x:(0 if x['taxonomy']=='Curated theme' else 1,x['rank']))


def attach_rotation_context(rows, themes):
    priority={'Leading':0,'Emerging':1,'Mature':2,'Mixed':3,'Weakening':4,'Avoid':5,'Insufficient coverage':6}
    curated=[t for t in themes if t['taxonomy']=='Curated theme']
    industries={t['name']:t for t in themes if t['taxonomy']=='Industry'}
    for row in rows:
        memberships=[t for t in curated if row['isin'] in t['members']]
        memberships.sort(key=lambda t:(priority.get(t['status'],9),t['rank']))
        industry=industries.get(row['sector'])
        best=memberships[0] if memberships else industry
        row['theme_name']=best['name'] if best else None
        row['theme_state']=best['status'] if best else None
        row['theme_rank']=best['rank'] if best else None
        row['theme_taxonomy']=best['taxonomy'] if best else None
        row['theme_coverage']=best['coverage'] if best else None
        row['theme_coverage_quality']=best['coverage_quality'] if best else None
        row['theme_breadth_change']=best['breadth_change'] if best else None
        # Peer ranking is always against the stock's exchange industry. Curated
        # themes can overlap and remain useful rotation context, but are not the
        # stock's ranking denominator.
        row['industry_name']=industry['name'] if industry else row['sector']
        row['industry_state']=industry['status'] if industry else None
        row['industry_rank']=industry['rank'] if industry else None
        row['industry_coverage']=industry['coverage'] if industry else None
        peer_ready=industry and industry.get('resolved',len(industry.get('members',[])))>=3
        row['stock_vs_industry_r20']=round(row['r20']-industry['r20'],2) if peer_ready and industry.get('r20') is not None else None
        row['stock_vs_industry_r60']=round(row['r60']-industry['r60'],2) if peer_ready and industry.get('r60') is not None else None
        row['theme_memberships']=[{'name':t['name'],'state':t['status'],'rank':t['rank']} for t in memberships]
        supportive=best and best['status'] in ['Leading','Emerging']
        weak=best and best['status'] in ['Weakening','Avoid']
        if row['candidate'] and supportive:
            posture='Sector-supported setup'
        elif row['vstop_bullish'] and row['obv_bullish'] and not weak:
            posture='Hold / monitor'
        elif not row['vstop_bullish'] or weak:
            posture='Review / rotate'
        else:
            posture='Watch'
        row['rotation_posture']=posture


def build(universe,frames,asof,cfg,themes,ledger,record=True,previous_themes=None):
    benchmark=frames.get(cfg['benchmark'])
    if benchmark is None or len(benchmark)<cfg['min_history'] or str(benchmark.index[-1].date())!=asof:
        raise RuntimeError('The benchmark does not have the expected completed session')
    fresh=sum(r['yahoo'] in frames and str(frames[r['yahoo']].index[-1].date())==asof for r in universe)
    if fresh/len(universe)<cfg['min_coverage']:
        raise RuntimeError(f'Fresh coverage {fresh}/{len(universe)} is below the {cfg["min_coverage"]:.0%} publishing requirement')
    rows,excluded=[],[]
    for meta in universe:
        row,reason=analyze(meta,frames.get(meta['yahoo']),benchmark,asof,cfg)
        if row: rows.append(row)
        else: excluded.append({'isin':meta['isin'],'symbol':meta['nse'],'reason':reason})
    leaders=sorted([r for r in rows if r['momentum_12_1'] is not None],key=lambda r:-r['momentum_12_1'])
    for r in leaders[:max(1,int(np.ceil(len(leaders)*.1)))]:r['leader']=True
    groups=defaultdict(set)
    for r in universe:groups[r['industry_group']].add(r['isin'])
    theme_rows=[theme_summary(rows,ids,name,'Industry') for name,ids in groups.items()]
    theme_rows += [theme_summary(rows,set(t['members']),t['name'],'Curated theme') for t in themes]
    theme_rows=rank_themes(theme_rows,previous_themes)
    attach_rotation_context(rows,theme_rows)
    posture={'Sector-supported setup':0,'Hold / monitor':1,'Watch':2,'Review / rotate':3}
    rows.sort(key=lambda r:(not r['candidate'],-(r['stock_vs_industry_r20'] if r['stock_vs_industry_r20'] is not None else -999),-r['participation'],
                            posture[r['rotation_posture']],r['isin']))
    ledger,tracking,summary=track(ledger,rows,frames,benchmark,asof,cfg,record)
    for row in rows:
        signals=[s for s in tracking if s['isin']==row['isin'] and s['model']==cfg['version']]
        row['tracking']=signals[-1] if signals else None
    chart_ids={r['isin']:r['yahoo'] for r in rows}
    charts={}
    for isin,ticker in chart_ids.items():
        full=frames[ticker]
        full_stop,_,_=vstop_series(full,cfg.get('vstop_length',10),cfg.get('vstop_factor',2))
        start=pd.Timestamp(f'{asof[:4]}-01-01')
        mask=full.index>=start
        d=full.loc[mask]
        stop=full_stop[mask]
        charts[isin]={'dates':[str(x.date()) for x in d.index],
                      **{k[0].lower():[round(float(x),3) for x in d[k]] for k in ['Open','High','Low','Close','Volume']},
                      'vstop':[round(float(x),3) if np.isfinite(x) else None for x in stop]}
    bc=benchmark.Close.to_numpy(float)
    sma50=float(np.mean(bc[-50:]));sma200=float(np.mean(bc[-200:])) if len(bc)>=200 else None
    regime=('Bull' if bc[-1]>sma50 and (sma200 is None or bc[-1]>sma200) and pct(bc,20)>0 else
            'Defensive' if bc[-1]<sma50 and sma200 is not None and bc[-1]<sma200 else 'Mixed')
    market={'benchmark':cfg.get('benchmark_name','Nifty 500'),'ticker':cfg['benchmark'],
            'r20':round(float((bc[-1]/bc[-21]-1)*100),2),
            'breadth':round(float(np.mean([r['above50'] for r in rows]))*100,1) if rows else None,
            'regime':regime,'above50':bool(bc[-1]>sma50),'above200':bool(bc[-1]>sma200) if sma200 else None}
    rotation={'leaders':[t['name'] for t in theme_rows if t['taxonomy']=='Curated theme' and t['status'] in ['Leading','Emerging']][:5],
              'review':[t['name'] for t in theme_rows if t['taxonomy']=='Curated theme' and t['status'] in ['Weakening','Avoid']][:5]}
    payload={'schema':1,'model':cfg['version'],'asof':asof,
        'generated':datetime.now(timezone.utc).isoformat(),'status':'ready','source':'Yahoo Finance / yfinance; completed daily bars',
        'research_status':'New descriptive rules; prospective evidence accumulating. No claimed win probability.',
        'policy':cfg,'market':market,'coverage':{'universe':len(universe),'fresh':fresh,'eligible':len(rows),
             'excluded':len(excluded),'reasons':dict(Counter(x['reason'] for x in excluded))},
        'rows':rows,'themes':theme_rows,'rotation':rotation,'tracking':tracking,'summary':summary,'excluded':excluded,
        'surveillance':'Not automatically screened for ASM/GSM or price bands; verify on NSE before acting.'}
    return payload,{'asof':asof,'charts':charts},ledger


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);args=parser.parse_args()
    cfg=read(ROOT/'config/model.json',{})
    universe=[r for r in csv.DictReader(open(ROOT/'config/universe.csv')) if r['isin'] and r['nse'] and r['yahoo'].endswith('.NS')]
    if len({r['isin'] for r in universe})!=len(universe):raise RuntimeError('Duplicate ISINs in registry')
    if args.limit:universe=universe[:args.limit]
    expected=expected_session()
    asof=expected
    history=DATA/'history'/cfg['version']/f'{asof}.json'
    ledger=read(DATA/'ledger.json',[])
    # Benchmark first: abort before thousands of calls if the provider is down.
    frames=fetch([cfg['benchmark']],asof,require_current=False)
    if cfg['benchmark'] not in frames:raise RuntimeError('Benchmark unavailable; prior snapshot preserved')
    tickers=list(dict.fromkeys([r['yahoo'] for r in universe]+[r['yahoo'] for r in ledger]))
    frames.update(fetch(tickers,asof,require_current=False))
    asof=select_session(universe,frames,frames[cfg['benchmark']],expected,cfg['min_coverage'])
    history=DATA/'history'/cfg['version']/f'{asof}.json'
    frames={t:d.loc[:asof] for t,d in frames.items() if not d.loc[:asof].empty}
    previous=read(DATA/'latest.json',{})
    if replacing_newer_same_model(previous,asof,cfg):
        raise RuntimeError('Refusing to replace a newer snapshot of the same model')
    current=asof==expected
    payload,charts,ledger=build(universe,frames,asof,cfg,read(ROOT/'config/themes.json',[]),ledger,
                                current and not history.exists(),previous.get('themes',[]))
    payload['expected_session']=expected
    payload['freshness']='current' if current else 'delayed'
    if args.limit:
        # Test runs cannot replace the production universe or its records.
        write(ROOT/'tmp/limited-scan.json',payload)
        return
    # A first successful daily snapshot is immutable, including a model version.
    if current and not history.exists():
        write(history,{'asof':asof,'model':cfg['version'],'generated':payload['generated'],
                       'candidates':[r for r in payload['rows'] if r['candidate']],
                       'themes':payload['themes'],'coverage':payload['coverage']})
    write(DATA/'ledger.json',ledger)
    write(DATA/'charts.json',charts)
    write(DATA/'latest.json',payload)
    write(DATA/'health.json',{'status':'ok' if current else 'delayed','asof':asof,
        'expected_session':expected,'message':None if current else
        f'Provider coverage is incomplete for {expected}. Showing the common completed session {asof}; no new live detections recorded.',
        'checked_at':datetime.now(timezone.utc).isoformat()})
    print(f"Published {asof}: {len(payload['rows'])} eligible, {sum(r['candidate'] for r in payload['rows'])} confirmed setups",flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        write(DATA/'health.json',{'status':'error','checked_at':datetime.now(timezone.utc).isoformat(),
                                'message':str(exc),'note':'Previous successful snapshot retained.'})
        raise
