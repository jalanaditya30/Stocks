"""Transparent confirmed-move rules. No pre-breakout selection or fitted score."""
from __future__ import annotations

import numpy as np
import pandas as pd


def normalized(raw, asof):
    if raw is None or raw.empty:
        return None
    d = raw.copy()
    d.index = pd.DatetimeIndex(d.index).tz_localize(None).normalize()
    d = d[~d.index.duplicated(keep='last')].sort_index().loc[:asof]
    needed = ['Open', 'High', 'Low', 'Close', 'Volume', 'Adj Close']
    if not set(needed).issubset(d.columns):
        return None
    # Do not silently fill a missing adjusted close or broken price bar.
    d = d[needed].replace([np.inf, -np.inf], np.nan).dropna()
    d = d[(d[['Open','High','Low','Close','Adj Close']] > 0).all(axis=1) & (d.Volume >= 0)]
    d = d[(d.High >= d[['Open','Close','Low']].max(axis=1)) &
          (d.Low <= d[['Open','Close','High']].min(axis=1))]
    if d.empty:
        return None
    d['RawClose'] = d.Close
    d['CashTurnover'] = d.Close * d.Volume / 1e7
    factor = d['Adj Close'] / d.Close
    for col in ['Open','High','Low','Close']:
        d[col] *= factor
    return d


def pct(c, n):
    return float((c[-1] / c[-n-1] - 1) * 100)


def crossed_and_held(d, window, cfg, continuation=False):
    """Fixed prior-high anchor, crossed recently and held for >=2 closes.

    The anchor excludes the breakout bar. Every close since the breakout must
    hold it. The first eligible crossing is retained, rather than moving the
    reference up with every new high. Only past bars are inspected.
    """
    c, h, l = (d[k].to_numpy(float) for k in ['Close','High','Low'])
    for age in range(cfg['lookback_breakout_sessions'] - 1,
                     cfg['confirmation_closes'] - 2, -1):
        i = len(d) - 1 - age
        if i < max(window, 60):
            continue
        level = float(np.max(h[i-window:i]))
        if c[i-1] > level or not np.all(c[i:] > level):
            continue
        if continuation:
            # A prior advance, a 10-session consolidation, then renewed strength.
            prior_return = (c[i-11] / c[i-51] - 1) * 100
            width = (max(h[i-10:i]) / min(l[i-10:i]) - 1) * 100
            down_days = int(np.sum(np.diff(c[i-11:i]) < 0))
            if prior_return < 10 or width > 12 or down_days < 3:
                continue
        return {'level': level, 'breakout_date': str(d.index[i].date()),
                'held_sessions': age + 1, 'window': window}
    return None


def analyze(meta, d, benchmark, asof, cfg):
    if d is None or len(d) < cfg['min_history']:
        return None, 'insufficient valid history'
    if str(d.index[-1].date()) != asof:
        return None, 'latest session missing'
    # Require identical dates for comparative features and a complete recent
    # trading calendar; missing or suspended sessions are not fresh evidence.
    required = benchmark.index[-cfg['min_history']:]
    if not required.isin(d.index).all():
        return None, 'recent sessions missing'
    d = d.loc[d.index.intersection(benchmark.index)]
    b = benchmark.reindex(d.index)
    c, h, l = (d[k].to_numpy(float) for k in ['Close','High','Low'])
    cash = d.CashTurnover.to_numpy(float)
    turn = float(np.median(cash[-60:]))
    nonzero = int(np.sum(d.Volume.to_numpy()[-60:] > 0))
    if turn < cfg['min_turnover_cr'] or nonzero < 55:
        return None, 'below liquidity requirement'
    r5, r20, r60 = (pct(c, n) for n in [5,20,60])
    bc = b.Close.to_numpy(float)
    rs20, rs60 = r20-pct(bc,20), r60-pct(bc,60)
    sma20, sma50 = float(np.mean(c[-20:])), float(np.mean(c[-50:]))
    slope = sma20 / float(np.mean(c[-25:-5])) - 1
    baseline = float(np.median(cash[-25:-5]))
    participation = float(np.median(cash[-5:]) / baseline) if baseline > 0 else 0
    location = float(np.mean(np.divide(c[-3:]-l[-3:], h[-3:]-l[-3:],
                                      out=np.full(3,.5), where=(h[-3:]-l[-3:])>0)))
    largest = float(np.max(np.abs(np.diff(c[-6:])/c[-6:-1]))*100)
    long_momentum = float((c[-22]/c[-253]-1)*100) if len(c)>=253 else None
    # Continuation receives its own label, and cannot be mistaken for a first move.
    anchor = crossed_and_held(d,20,cfg,True) if rs60>0 else None
    kind = 'Leaders resuming' if anchor else 'Confirmed moves'
    if anchor is None:
        anchor = crossed_and_held(d,60,cfg)
    extension = float((c[-1]/anchor['level']-1)*100) if anchor else None
    technical_ok = c[-1]>sma20>sma50 and slope>0 and r5>0 and rs20>0
    participation_ok = participation>=cfg['min_participation'] and location>=.55
    extended = (r5>cfg['max_return_5d_pct'] or
                (c[-1]/sma20-1)*100>cfg['max_sma_extension_pct'] or
                (extension is not None and extension>cfg['max_extension_pct']))
    event = largest>cfg['event_day_pct']
    candidate = bool(anchor and technical_ok and participation_ok and not extended and not event)
    reasons, risks = [], []
    if anchor:
        reasons.append(f"Held above the prior {anchor['window']}-session high for {anchor['held_sessions']} closes")
    if technical_ok:
        reasons.append('Above rising 20-session and 50-session averages; positive 5-session move')
    reasons += [f"20-session return exceeds Nifty 50 by {rs20:.1f} percentage points",
                f"Recent median cash turnover is {participation:.2f}× its earlier baseline"]
    if event: risks.append('Large single-session move; investigate the event')
    if extended: risks.append('Extended from the breakout or short-term trend; chase risk')
    if not participation_ok: risks.append('Participation or closing strength does not meet the confirmation rule')
    risks.append('ASM/GSM, circuit restrictions and corporate news require a separate check')
    # Quotes and levels use the latest raw-price scale, charts use adjusted prices.
    raw_factor = float(d['Adj Close'].iloc[-1] / d.RawClose.iloc[-1])
    raw_factor = raw_factor if np.isfinite(raw_factor) and raw_factor>0 else 1
    row = {'isin':meta['isin'],'symbol':meta['nse'],'yahoo':meta['yahoo'],
           'name':meta['name'],'sector':meta['industry_group'],'asof':asof,
           'last':round(float(c[-1]/raw_factor),2),'r5':round(r5,2),'r20':round(r20,2),
           'r60':round(r60,2),'rs20':round(rs20,2),'rs60':round(rs60,2),
           'turnover_cr':round(turn,2),'participation':round(participation,2),
           'momentum_12_1':round(long_momentum,2) if long_momentum is not None else None,
           'above50':bool(c[-1]>sma50),'above50_week_ago':bool(c[-6]>np.mean(c[-55:-5])),
           'candidate':candidate,'setup':kind if candidate else ('Extended / event' if anchor and (extended or event) else 'Other'),
           'anchor':round(anchor['level']/raw_factor,2) if anchor else None,
           'anchor_adjusted':anchor['level'] if anchor else None,
           'breakout_date':anchor['breakout_date'] if anchor else None,
           'extension':round(extension,2) if extension is not None else None,
           'reasons':reasons,'risks':risks,'leader':False}
    return row, None


def theme_summary(rows, members, name, taxonomy):
    usable = [r for r in rows if r['isin'] in members]
    coverage = len(usable)/len(members) if members else 0
    enough = len(usable)>=3 and coverage>=.7
    vals = lambda k: [r[k] for r in usable]
    breadth = float(np.mean(vals('above50'))*100) if usable else None
    prev = float(np.mean(vals('above50_week_ago'))*100) if usable else None
    median = lambda k: round(float(np.median(vals(k))),2) if usable else None
    delta = round(breadth-prev,1) if usable else None
    status = 'Insufficient coverage'
    if enough:
        status = ('Improving' if delta>=5 and median('rs20')>0 else
                  'Leading' if breadth>=60 and median('rs20')>0 else
                  'Weakening' if delta<=-5 else 'Mixed')
    return {'name':name,'taxonomy':taxonomy,'members':sorted(members),'resolved':len(usable),
            'total':len(members),'coverage':round(coverage*100,1),'status':status,
            'r5':median('r5'),'r20':median('r20'),'rs20':median('rs20'),
            'breadth':round(breadth,1) if breadth is not None else None,
            'breadth_change':delta,'candidates':sum(r['candidate'] for r in usable),
            'leaders':[r['isin'] for r in sorted(usable,key=lambda r:-r['rs20'])[:3]]}
