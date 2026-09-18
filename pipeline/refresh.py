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

from pipeline.engine import normalized, analyze, theme_summary

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


def fetch(tickers, asof):
    out = {}
    # Small batches, a single shared pull, and one retry for missing symbols.
    for attempt in range(2):
        pending = [t for t in tickers if t not in out]
        for start in range(0,len(pending),30):
            chunk = pending[start:start+30]
            print(f"fetch pass {attempt+1}: {start+1}-{start+len(chunk)}/{len(pending)}",flush=True)
            try:
                raw = yf.download(chunk,period='2y',auto_adjust=False,
                                  group_by='ticker',progress=False,threads=4,timeout=20)
                for t in chunk:
                    try:
                        frame = raw[t] if isinstance(raw.columns,pd.MultiIndex) else raw
                        d = normalized(frame,asof)
                        if d is not None and str(d.index[-1].date())==asof:
                            out[t]=d
                        else:
                            raw_latest=str(frame.index[-1]) if not frame.empty else 'empty'
                            valid_latest=str(d.index[-1].date()) if d is not None else 'none'
                            print(f'{t}: expected {asof}, provider latest {raw_latest}, valid latest {valid_latest}',flush=True)
                            if t=='^NSEI' and not frame.empty:
                                print('Benchmark provider bar:',frame.tail(1).to_json(orient='records'),flush=True)
                    except (KeyError,ValueError,TypeError) as exc:
                        print(f'{t}: unusable response ({type(exc).__name__}: {exc})',flush=True)
                        continue
            except Exception as exc:
                print('batch unavailable:',type(exc).__name__,flush=True)
            time.sleep(1)
        if len(out)==len(tickers):
            break
        if attempt==0:
            time.sleep(5)
    return out


def track(ledger, rows, frames, benchmark, asof, cfg, record=True):
    """First detection is immutable; next-session open is the executable baseline."""
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
                    'window':20 if r['setup']=='Leaders resuming' else 60,'model':cfg['version']})
                known.add(key)
    result=[]
    calendar=benchmark.index
    for signal in ledger:
        item={**signal,'outcomes':dict(signal.get('outcomes',{})),
              'state':'Awaiting prices','since_detection':None}
        d=frames.get(signal['yahoo'])
        if d is not None:
            day=pd.Timestamp(signal['first_seen'])
            if day in d.index:
                item['since_detection']=round(float((d.Close.iloc[-1]/d.loc[day,'Close']-1)*100),2)
            bd=pd.Timestamp(signal['breakout_date'])
            if bd in d.index:
                p=d.index.get_loc(bd)
                if p>=signal['window']:
                    level=float(d.High.iloc[p-signal['window']:p].max())
                    item['state']='Below breakout level' if d.Close.iloc[-1]<level else 'Holding breakout level'
            # Never award returns at the same close that generated the signal.
            entry=int(calendar.searchsorted(day,side='right'))
            if entry<len(calendar) and calendar[entry] in d.index:
                ed=calendar[entry]
                stock_open=float(d.loc[ed,'Open']); bench_open=float(benchmark.loc[ed,'Open'])
                item['entry_date']=str(ed.date())
                for horizon in cfg['forward_horizons']:
                    if str(horizon) in item['outcomes']:
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
                        item['outcomes'][str(horizon)]={'gross':round(gross,2),'net':round(net,2),
                            'benchmark':round(br,2),'excess_net':round(net-br,2),
                            'worst_excursion':round(float((segment.Low.min()/stock_open-1)*100),2)}
        # Completed observations survive provider rolling-history limits and outages.
        signal['outcomes']=dict(item['outcomes'])
        if 'entry_date' in item:signal['entry_date']=item['entry_date']
        result.append(item)
    summary=[]
    for setup in ['Confirmed moves','Leaders resuming']:
        for h in cfg['forward_horizons']:
            outcomes=[r['outcomes'][str(h)] for r in result if r['setup']==setup and str(h) in r['outcomes'] and r['model']==cfg['version']]
            summary.append({'setup':setup,'horizon':h,'n':len(outcomes),
                'median_net':round(float(np.median([o['net'] for o in outcomes])),2) if outcomes else None,
                'median_excess':round(float(np.median([o['excess_net'] for o in outcomes])),2) if outcomes else None})
    return ledger,result,summary


def build(universe,frames,asof,cfg,themes,ledger,record=True):
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
    rows.sort(key=lambda r:(not r['candidate'],-r['rs20'],-r['participation'],r['isin']))
    groups=defaultdict(set)
    for r in universe:groups[r['industry_group']].add(r['isin'])
    theme_rows=[theme_summary(rows,ids,name,'Industry') for name,ids in groups.items()]
    theme_rows += [theme_summary(rows,set(t['members']),t['name'],'Curated theme') for t in themes]
    order={'Improving':0,'Leading':1,'Mixed':2,'Weakening':3,'Insufficient coverage':4}
    theme_rows.sort(key=lambda t:(order[t['status']],-(t['breadth_change'] or 0),-(t['rs20'] or 0),t['name']))
    ledger,tracking,summary=track(ledger,rows,frames,benchmark,asof,cfg,record)
    for row in rows:
        signals=[s for s in tracking if s['isin']==row['isin'] and s['model']==cfg['version']]
        row['tracking']=signals[-1] if signals else None
    chart_ids={r['isin']:r['yahoo'] for r in rows}
    charts={}
    for isin,ticker in chart_ids.items():
        d=frames[ticker].tail(100)
        charts[isin]={'dates':[str(x.date()) for x in d.index],
                      **{k[0].lower():[round(float(x),3) for x in d[k]] for k in ['Open','High','Low','Close','Volume']}}
    bc=benchmark.Close.to_numpy(float)
    market={'benchmark':'Nifty 50','r20':round(float((bc[-1]/bc[-21]-1)*100),2),
            'breadth':round(float(np.mean([r['above50'] for r in rows]))*100,1) if rows else None}
    payload={'schema':1,'model':cfg['version'],'asof':asof,
        'generated':datetime.now(timezone.utc).isoformat(),'status':'ready','source':'Yahoo Finance / yfinance; completed daily bars',
        'research_status':'New descriptive rules; prospective evidence accumulating. No claimed win probability.',
        'policy':cfg,'market':market,'coverage':{'universe':len(universe),'fresh':fresh,'eligible':len(rows),
             'excluded':len(excluded),'reasons':dict(Counter(x['reason'] for x in excluded))},
        'rows':rows,'themes':theme_rows,'tracking':tracking,'summary':summary,'excluded':excluded,
        'surveillance':'Not automatically screened for ASM/GSM or price bands; verify on NSE before acting.'}
    return payload,{'asof':asof,'charts':charts},ledger


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--limit',type=int);args=parser.parse_args()
    cfg=read(ROOT/'config/model.json',{})
    universe=[r for r in csv.DictReader(open(ROOT/'config/universe.csv')) if r['isin'] and r['nse'] and r['yahoo'].endswith('.NS')]
    if len({r['isin'] for r in universe})!=len(universe):raise RuntimeError('Duplicate ISINs in registry')
    if args.limit:universe=universe[:args.limit]
    asof=expected_session()
    history=DATA/'history'/cfg['version']/f'{asof}.json'
    ledger=read(DATA/'ledger.json',[])
    # Benchmark first: abort before thousands of calls if the provider is down.
    frames=fetch([cfg['benchmark']],asof)
    if cfg['benchmark'] not in frames:raise RuntimeError('Benchmark unavailable; prior snapshot preserved')
    tickers=list(dict.fromkeys([r['yahoo'] for r in universe]+[r['yahoo'] for r in ledger]))
    frames.update(fetch(tickers,asof))
    payload,charts,ledger=build(universe,frames,asof,cfg,read(ROOT/'config/themes.json',[]),ledger,not history.exists())
    if args.limit:
        # Test runs cannot replace the production universe or its records.
        write(ROOT/'tmp/limited-scan.json',payload)
        return
    # A first successful daily snapshot is immutable, including a model version.
    if not history.exists():
        write(history,{'asof':asof,'model':cfg['version'],'generated':payload['generated'],
                       'candidates':[r for r in payload['rows'] if r['candidate']],
                       'themes':payload['themes'],'coverage':payload['coverage']})
    write(DATA/'ledger.json',ledger)
    write(DATA/'charts.json',charts)
    write(DATA/'latest.json',payload)
    write(DATA/'health.json',{'status':'ok','asof':asof,'checked_at':datetime.now(timezone.utc).isoformat()})
    print(f"Published {asof}: {len(payload['rows'])} eligible, {sum(r['candidate'] for r in payload['rows'])} confirmed setups",flush=True)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        write(DATA/'health.json',{'status':'error','checked_at':datetime.now(timezone.utc).isoformat(),
                                'message':str(exc),'note':'Previous successful snapshot retained.'})
        raise
