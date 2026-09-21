"""Repair concentrated Yahoo session gaps from official NSE UDiFF bhavcopies."""
from __future__ import annotations

from collections import Counter
from io import BytesIO
import urllib.request
import zipfile

import numpy as np
import pandas as pd


SOURCE = "NSE CM-UDiFF Common Bhavcopy Final"
URL = "https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{date}_F_0000.csv.zip"


def concentrated_internal_gaps(universe, frames, required, threshold=.10):
    """Return required sessions absent inside many otherwise usable histories."""
    required = pd.DatetimeIndex(required).tz_localize(None).normalize()
    counts = Counter()
    for meta in universe:
        frame = frames.get(meta['yahoo'])
        if frame is None or frame.empty:
            continue
        first, last = frame.index[0], frame.index[-1]
        for day in required:
            if first < day < last and day not in frame.index:
                counts[day] += 1
    minimum = max(1, int(np.ceil(len(universe) * threshold)))
    return {day: count for day, count in sorted(counts.items()) if count >= minimum}


def _column(frame, name):
    lookup = {str(c).strip().lower(): c for c in frame.columns}
    if name.lower() not in lookup:
        raise ValueError(f'NSE bhavcopy is missing {name}')
    return lookup[name.lower()]


def parse_bhavcopy(blob, expected_session):
    """Parse one official UDiFF archive into unique, validated ISIN price rows."""
    expected = pd.Timestamp(expected_session).normalize()
    try:
        with zipfile.ZipFile(BytesIO(blob)) as archive:
            names = [n for n in archive.namelist() if n.lower().endswith('.csv')]
            if len(names) != 1:
                raise ValueError('NSE bhavcopy archive must contain exactly one CSV')
            frame = pd.read_csv(archive.open(names[0]), low_memory=False)
    except zipfile.BadZipFile as exc:
        raise ValueError('NSE bhavcopy response is not a ZIP archive') from exc

    cols = {name: _column(frame, name) for name in
            ['TradDt','ISIN','TckrSymb','SctySrs','OpnPric','HghPric','LwPric','ClsPric','TtlTradgVol']}
    dates = pd.to_datetime(frame[cols['TradDt']], errors='coerce').dt.normalize()
    if dates.notna().sum() == 0 or not (dates.dropna() == expected).all():
        raise ValueError(f'NSE bhavcopy trade date does not match {expected.date()}')

    numeric = ['OpnPric','HghPric','LwPric','ClsPric','TtlTradgVol']
    for name in numeric:
        frame[cols[name]] = pd.to_numeric(frame[cols[name]], errors='coerce')
    rows = {}
    for isin, group in frame.groupby(cols['ISIN'], dropna=True):
        group = group.dropna(subset=[cols[x] for x in numeric])
        if group.empty:
            continue
        eq = group[group[cols['SctySrs']].astype(str).str.strip().eq('EQ')]
        chosen = eq.iloc[0] if len(eq) == 1 else group.iloc[0] if len(group) == 1 else None
        if chosen is None:
            continue
        o, h, l, c, v = (float(chosen[cols[x]]) for x in numeric)
        if min(o,h,l,c) <= 0 or v < 0 or h < max(o,l,c) or l > min(o,h,c):
            continue
        rows[str(isin).strip()] = {'symbol':str(chosen[cols['TckrSymb']]).strip(),
                                  'open':o,'high':h,'low':l,'close':c,'volume':v}
    if not rows:
        raise ValueError('NSE bhavcopy contains no valid cash-market rows')
    return rows


def download_bhavcopy(session):
    day = pd.Timestamp(session).strftime('%Y%m%d')
    request = urllib.request.Request(URL.format(date=day), headers={
        'User-Agent':'Mozilla/5.0 (compatible; StocksResearch/1.0)',
        'Accept':'application/zip,application/octet-stream,*/*'})
    with urllib.request.urlopen(request, timeout=30) as response:
        if getattr(response, 'status', 200) != 200:
            raise RuntimeError(f'NSE bhavcopy returned HTTP {response.status}')
        return parse_bhavcopy(response.read(), session)


def repair_concentrated_gaps(universe, frames, required, threshold=.10, loader=download_bhavcopy):
    """Insert only validated missing bars; never replace Yahoo observations."""
    gaps = concentrated_internal_gaps(universe, frames, required, threshold)
    report = {'source':SOURCE,'url_template':URL,'attempted_sessions':[],
              'repaired_bars':0,'skipped_bars':0,'errors':[]}
    for day, detected in gaps.items():
        item = {'session':str(day.date()),'detected_internal_gaps':detected,
                'available_rows':0,'repaired_bars':0,'skipped_bars':0}
        report['attempted_sessions'].append(item)
        try:
            official = loader(day)
            item['available_rows'] = len(official)
        except Exception as exc:
            report['errors'].append({'session':str(day.date()),
                                     'error':f'{type(exc).__name__}: {exc}'})
            continue
        for meta in universe:
            ticker, isin = meta['yahoo'], meta['isin']
            frame = frames.get(ticker)
            if (frame is None or frame.empty or day in frame.index or
                    not (frame.index[0] < day < frame.index[-1])):
                continue
            row = official.get(isin)
            if row is None:
                item['skipped_bars'] += 1
                continue
            before, after = frame.loc[frame.index < day].iloc[-1], frame.loc[frame.index > day].iloc[0]
            factors = [before.Close / before.RawClose, after.Close / after.RawClose]
            if (not np.isfinite(factors).all() or factors[0] <= 0 or
                    not np.isclose(factors[0], factors[1], rtol=1e-7, atol=1e-10)):
                item['skipped_bars'] += 1
                continue
            factor = float(factors[0])
            values = {c:np.nan for c in frame.columns}
            values.update({'Open':row['open']*factor,'High':row['high']*factor,
                           'Low':row['low']*factor,'Close':row['close']*factor,
                           'Adj Close':row['close']*factor,'Volume':row['volume'],
                           'RawClose':row['close'],
                           'CashTurnover':row['close']*row['volume']/1e7})
            addition = pd.DataFrame([values], index=pd.DatetimeIndex([day]))
            frames[ticker] = pd.concat([frame, addition]).sort_index()
            item['repaired_bars'] += 1
        report['repaired_bars'] += item['repaired_bars']
        report['skipped_bars'] += item['skipped_bars']
    remaining = concentrated_internal_gaps(universe, frames, required, threshold)
    report['remaining_concentrated_gaps'] = {str(k.date()):v for k,v in remaining.items()}
    return report
