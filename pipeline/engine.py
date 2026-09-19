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


def _ema(values, length):
    return pd.Series(values, dtype=float).ewm(span=length, adjust=False, min_periods=1).mean().to_numpy()


def _dema(values, length):
    first = _ema(values, length)
    second = _ema(first, length)
    return 2 * first - second


def vstop_series(d, length=10, factor=2.0):
    """TradingView ta.vStop using daily close, ATR length and multiplier."""
    high, low, close = (d[k].to_numpy(float) for k in ['High','Low','Close'])
    previous = np.r_[close[0], close[:-1]]
    tr = np.maximum(high-low, np.maximum(np.abs(high-previous), np.abs(low-previous)))
    atr=np.full(len(tr),np.nan)
    if len(tr)>=length:
        atr[length-1]=np.mean(tr[:length])
        for i in range(length,len(tr)):atr[i]=(atr[i-1]*(length-1)+tr[i])/length
    stop=np.full(len(close),np.nan);trend=np.ones(len(close),dtype=int)
    running_max=running_min=close[0];previous_stop=0.0;previous_trend=1
    for i,src in enumerate(close):
        atr_multiple=(atr[i]*factor) if np.isfinite(atr[i]) else tr[i]
        running_max=max(running_max,src);running_min=min(running_min,src)
        current_stop=max(previous_stop,running_max-atr_multiple) if previous_trend==1 else min(previous_stop,running_min+atr_multiple)
        current_trend=1 if src-current_stop>=0 else -1
        if i and current_trend!=previous_trend:
            running_max=running_min=src
            current_stop=src-atr_multiple if current_trend==1 else src+atr_multiple
        stop[i]=current_stop;trend[i]=current_trend
        previous_stop=current_stop;previous_trend=current_trend
    return stop, trend, atr


def obv_macd_series(d):
    """RafaelZioni OBV MACD defaults visible in the supplied TradingView charts.

    OBV length 1, DEMA 9, slow EMA 26 and linear slope length 2. The final
    blue/red state follows the script's adaptive T-channel. Pivots (50) are a
    display option and do not alter the line state.
    """
    high, low, close, volume = (d[k].to_numpy(float) for k in ['High','Low','Close','Volume'])
    direction=np.sign(np.r_[0,np.diff(close)])
    obv=np.cumsum(direction*volume)
    smooth=pd.Series(obv).rolling(14,min_periods=14).mean().to_numpy()
    price_spread=pd.Series(high-low).rolling(28,min_periods=28).std(ddof=0).to_numpy()
    v_spread=pd.Series(obv-smooth).rolling(28,min_periods=28).std(ddof=0).to_numpy()
    shadow=np.divide(obv-smooth,v_spread,out=np.full(len(obv),np.nan),where=v_spread!=0)*price_spread
    transformed=np.where(shadow>0,high+shadow,low+shadow)
    source=_ema(transformed,1)
    macd=_dema(source,9)-_ema(close,26)
    # Linear-regression endpoint for the script's default len5=2.
    endpoint=np.full(len(macd),np.nan)
    for i in range(1,len(macd)):
        if np.isfinite(macd[i-1:i+1]).all():
            endpoint[i]=macd[i]
    channel=np.full(len(macd),np.nan); state=np.zeros(len(macd),dtype=int)
    cumulative=0.0; count=0; prior=None; prior_state=0
    for i,x in enumerate(endpoint):
        if not np.isfinite(x):continue
        if prior is None:
            prior=x;channel[i]=x;state[i]=1;prior_state=1;continue
        cumulative += abs(x-prior); count += 1
        threshold=cumulative/count
        current=x if x>prior+threshold or x<prior-threshold else prior
        current_state=1 if current>prior else -1 if current<prior else prior_state
        channel[i]=current;state[i]=current_state
        prior=current;prior_state=current_state
    return channel,state,macd


def directional_indicators(d, length=14):
    high, low, close = (d[k].to_numpy(float) for k in ['High','Low','Close'])
    up=np.r_[0,np.diff(high)];down=np.r_[0,-np.diff(low)]
    plus=np.where((up>down)&(up>0),up,0);minus=np.where((down>up)&(down>0),down,0)
    previous=np.r_[close[0],close[:-1]]
    tr=np.maximum(high-low,np.maximum(np.abs(high-previous),np.abs(low-previous)))
    smooth=lambda x:pd.Series(x).ewm(alpha=1/length,adjust=False,min_periods=length).mean().to_numpy()
    atr=smooth(tr);plus_di=np.divide(100*smooth(plus),atr,out=np.zeros(len(atr)),where=atr>0)
    minus_di=np.divide(100*smooth(minus),atr,out=np.zeros(len(atr)),where=atr>0)
    dx=np.divide(100*np.abs(plus_di-minus_di),plus_di+minus_di,out=np.zeros(len(atr)),where=(plus_di+minus_di)>0)
    return smooth(dx),plus_di,minus_di,atr


def momentum_indicators(d, cfg):
    close=d.Close.to_numpy(float)
    stop,trend,_=vstop_series(d,cfg.get('vstop_length',10),cfg.get('vstop_factor',2))
    obv_line,obv_state,_=obv_macd_series(d)
    adx,plus_di,minus_di,atr=directional_indicators(d,cfg.get('adx_length',14))
    change=abs(close[-1]-close[-21]);path=np.sum(np.abs(np.diff(close[-21:])))
    efficiency=float(change/path) if path else 0
    obv_value=float(obv_line[-1]) if np.isfinite(obv_line[-1]) else 0.0
    adx_value=float(adx[-1]) if np.isfinite(adx[-1]) else 0.0
    return {'vstop':float(stop[-1]),'vstop_bullish':bool(trend[-1]>0),
            'vstop_flip':bool(len(trend)>1 and trend[-1]!=trend[-2]),
            'obv_macd':obv_value,'obv_bullish':bool(obv_state[-1]>0),
            'obv_flip':bool(len(obv_state)>1 and obv_state[-1]!=0 and obv_state[-2]!=0 and obv_state[-1]!=obv_state[-2]),
            'adx':adx_value,'plus_di':float(plus_di[-1]),'minus_di':float(minus_di[-1]),
            'atr_pct':float(atr[-1]/close[-1]*100),'efficiency_20':efficiency}


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
    ind=momentum_indicators(d,cfg)
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
    checks={'VStop bullish':ind['vstop_bullish'],'OBV MACD bullish':ind['obv_bullish'],
            'Directional trend':ind['adx']>=20 and ind['plus_di']>ind['minus_di'],
            'Efficient advance':ind['efficiency_20']>=.25}
    if candidate: stage='Trend continuation' if kind=='Leaders resuming' else 'Confirmed move'
    elif anchor and (extended or event):stage='Extended / event'
    elif ind['vstop_bullish'] and c[-1]>sma20 and rs20>0:stage='Trend intact'
    elif ind['vstop_bullish'] and c[-1]>sma50:stage='Pullback / trend intact'
    elif not ind['vstop_bullish'] and rs20<0:stage='Momentum weakening'
    else:stage='Mixed'
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
           'above20':bool(c[-1]>sma20),'above20_week_ago':bool(c[-6]>np.mean(c[-25:-5])),
           'above50':bool(c[-1]>sma50),'above50_week_ago':bool(c[-6]>np.mean(c[-55:-5])),
           'above200':bool(c[-1]>np.mean(c[-200:])) if len(c)>=200 else None,
           'new_high20':bool(c[-1]>=np.max(h[-21:-1])),'new_high60':bool(c[-1]>=np.max(h[-61:-1])),
           'candidate':candidate,'setup':kind if candidate else ('Extended / event' if anchor and (extended or event) else 'Other'),
           'stage':stage,'momentum_confirmations':sum(checks.values()),
           'momentum_checks':[k for k,v in checks.items() if v],
           'vstop':round(ind['vstop']/raw_factor,2),'vstop_bullish':ind['vstop_bullish'],
           'vstop_distance':round((c[-1]/ind['vstop']-1)*100,2),'vstop_flip':ind['vstop_flip'],
           'obv_macd':round(ind['obv_macd'],2),'obv_bullish':ind['obv_bullish'],'obv_flip':ind['obv_flip'],
           'adx':round(ind['adx'],2),'plus_di':round(ind['plus_di'],2),'minus_di':round(ind['minus_di'],2),
           'atr_pct':round(ind['atr_pct'],2),'efficiency_20':round(ind['efficiency_20'],3),
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
    vals = lambda k: [r[k] for r in usable if r.get(k) is not None]
    breadth = float(np.mean(vals('above50'))*100) if vals('above50') else None
    breadth20 = float(np.mean(vals('above20'))*100) if vals('above20') else None
    breadth200 = float(np.mean(vals('above200'))*100) if vals('above200') else None
    prev = float(np.mean(vals('above50_week_ago'))*100) if vals('above50_week_ago') else None
    median = lambda k: round(float(np.median(vals(k))),2) if vals(k) else None
    delta = round(breadth-prev,1) if usable else None
    status = 'Insufficient coverage'
    vstop_share=round(float(np.mean(vals('vstop_bullish'))*100),1) if vals('vstop_bullish') else None
    obv_share=round(float(np.mean(vals('obv_bullish'))*100),1) if vals('obv_bullish') else None
    if enough:
        rs20,rs60=median('rs20'),median('rs60')
        status = ('Avoid' if rs20<0 and rs60<0 and breadth<40 else
                  'Weakening' if delta<=-5 and (rs20<0 or vstop_share<50) else
                  'Emerging' if delta>=5 and rs20>0 and breadth<60 else
                  'Mature' if rs60>0 and breadth>=60 and (delta<0 or rs20<rs60/3) else
                  'Leading' if rs20>0 and rs60>0 and breadth>=60 and vstop_share>=55 else 'Mixed')
    return {'name':name,'taxonomy':taxonomy,'members':sorted(members),'resolved':len(usable),
            'total':len(members),'coverage':round(coverage*100,1),'status':status,
            'r5':median('r5'),'r20':median('r20'),'r60':median('r60'),
            'rs20':median('rs20'),'rs60':median('rs60'),
            'breadth20':round(breadth20,1) if breadth20 is not None else None,
            'breadth200':round(breadth200,1) if breadth200 is not None else None,
            'breadth':round(breadth,1) if breadth is not None else None,
            'breadth_change':delta,'vstop_bullish':vstop_share,'obv_bullish':obv_share,
            'new_high20':sum(r['new_high20'] for r in usable),'new_high60':sum(r['new_high60'] for r in usable),
            'median_adx':median('adx'),'median_efficiency':median('efficiency_20'),
            'candidates':sum(r['candidate'] for r in usable),
            'leaders':[r['isin'] for r in sorted(usable,key=lambda r:-r['rs20'])[:3]]}
