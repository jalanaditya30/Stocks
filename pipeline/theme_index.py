"""Equal-weight theme indices (StockScans custom-index method).

Method, as StockScans documents for its custom indexes:
- every member gets an equal share (not market-cap weighted);
- the index is pinned at 10,000 on a recent starting date;
- weights are reset to equal once a month (monthly rebalance).

Implementation details chosen here (StockScans does not publish them):
- adjusted closes; rebalance at the close of the last session of each calendar
  month, so each new month starts equal-weighted;
- between rebalances each member's weight drifts with its price (buy-and-hold);
- a member joins at the first rebalance at which it has a price; a missing bar is
  carried forward from that member's previous close;
- the shared session calendar is the benchmark's, so every index has the same dates.

Kept outside engine.py on purpose: engine.py is fingerprinted for historical
evidence compatibility, and this display feature must not invalidate it.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

BASE = 10_000.0
METHOD = {'weighting': 'equal', 'rebalance': 'monthly (month-end close)', 'base': BASE,
          'source': 'StockScans custom-index method: equal shares, pinned at 10,000, rebalanced monthly'}


def equal_weight_index(closes: pd.DataFrame, base: float = BASE):
    """Return (values, last_rebalance_position, members_at_rebalance, weights).

    closes: DataFrame indexed by session, one column per member (NaN = no price).
    """
    if closes.empty:
        return None
    c = closes.ffill()
    arr = c.to_numpy(float)
    months = c.index.to_period('M')
    n = len(c)
    values = np.full(n, np.nan)
    level = base
    ref = None          # prices at the last rebalance
    active = None       # members with a price at the last rebalance
    reb_pos = None
    for i in range(n):
        if ref is None:
            valid = np.isfinite(arr[i])
            if valid.any():
                ref, active, reb_pos, level = arr[i].copy(), valid, i, base
                values[i] = base
            continue
        rel = arr[i, active] / ref[active]
        values[i] = level * float(np.nanmean(rel))
        month_end = i == n - 1 or months[i] != months[i + 1]
        if month_end and i < n - 1:
            valid = np.isfinite(arr[i])
            if valid.any():
                ref, active, reb_pos, level = arr[i].copy(), valid, i, values[i]
    if reb_pos is None:
        return None
    last_rel = arr[-1, active] / ref[active]
    total = float(np.nansum(last_rel))
    cols = np.array(c.columns)[active]
    weights = sorted(
        ([str(col), round(float(r / total * 100), 2), round(float((r - 1) * 100), 2)]
         for col, r in zip(cols, last_rel) if np.isfinite(r)),
        key=lambda x: -x[1])
    return values, reb_pos, int(active.sum()), weights


def build_theme_indexes(universe, frames, benchmark, groups, asof, lookback_days=366):
    """groups: list of (taxonomy, name, member_isins). Returns a compact payload."""
    calendar = benchmark.index[benchmark.index >= pd.Timestamp(asof) - pd.Timedelta(days=lookback_days)]
    if len(calendar) < 2:
        return None
    ticker = {r['isin']: r['yahoo'] for r in universe}
    close_cache = {}

    def close(isin):
        if isin not in close_cache:
            f = frames.get(ticker.get(isin))
            close_cache[isin] = None if f is None else f['Close'].reindex(calendar)
        return close_cache[isin]

    out = {}
    for taxonomy, name, members in groups:
        series = {i: s for i in sorted(members) if (s := close(i)) is not None and s.notna().any()}
        if len(series) < 2:
            continue
        result = equal_weight_index(pd.DataFrame(series, index=calendar))
        if result is None:
            continue
        values, reb_pos, used, weights = result
        out[f'{taxonomy}|{name}'] = {
            'values': [None if not np.isfinite(v) else round(float(v), 1) for v in values],
            'members_used': used, 'members_total': len(members),
            'rebalanced': str(calendar[reb_pos].date()), 'weights': weights}
    return {'schema': 1, 'asof': asof, 'dates': [str(d.date()) for d in calendar],
            **METHOD, 'indexes': out}
