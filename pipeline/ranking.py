"""Deterministic shadow ranking; scores allocate attention, not probability."""
from __future__ import annotations

from collections import defaultdict
import math

import numpy as np

SCORE_VERSION = 'review-priority-v1-shadow'


def _finite(value):
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def _clip(value, low=0.0, high=100.0):
    return float(np.clip(value, low, high))


def _percentiles(rows, key):
    values = sorted((float(r[key]), r['isin']) for r in rows if _finite(r.get(key)))
    if len(values) < 5:
        return {}
    out = {}
    start = 0
    while start < len(values):
        end = start + 1
        while end < len(values) and values[end][0] == values[start][0]:
            end += 1
        average_position = (start + end - 1) / 2
        percentile = round(100 * average_position / (len(values) - 1), 4)
        for _, isin in values[start:end]:
            out[isin] = percentile
        start = end
    return out


def _band(value, ideal_low, ideal_high, hard_low, hard_high):
    """100 in the declared plateau, declining linearly toward hard bounds."""
    if not _finite(value) or value <= hard_low or value >= hard_high:
        return 0.0
    if ideal_low <= value <= ideal_high:
        return 100.0
    if value < ideal_low:
        return 100 * (value - hard_low) / (ideal_low - hard_low)
    return 100 * (hard_high - value) / (hard_high - ideal_high)


def _component_inputs(row):
    required = ['r20', 'r60', 'atr_pct', 'efficiency_20', 'participation',
                'volume_ratio_5d_30d', 'up_volume_share_20']
    missing = [k for k in required if not _finite(row.get(k))]
    if not row.get('comparison_60_complete'):
        missing.append('complete 60-session comparison window')
    return sorted(set(missing))


def score_rows(rows):
    """Mutate published rows with transparent shadow scores and deterministic ranks."""
    comparable = [r for r in rows if not _component_inputs(r)]
    for r in comparable:
        atr = max(float(r['atr_pct']), .01)
        r['vol_adjusted_r20'] = round(float(r['r20']) / atr, 4)
        r['vol_adjusted_r60'] = round(float(r['r60']) / (atr * math.sqrt(3)), 4)
    p20, p60 = _percentiles(comparable, 'vol_adjusted_r20'), _percentiles(comparable, 'vol_adjusted_r60')
    industries = defaultdict(list)
    for r in comparable:
        industries[r.get('sector')].append(r)
    peer_percentiles = {name: _percentiles(group, 'vol_adjusted_r20') for name, group in industries.items()}

    for row in rows:
        row['score_version'] = SCORE_VERSION
        row['strength_score'] = row['strength_rank'] = row['strength_denominator'] = None
        row['priority_score'] = row['priority_rank'] = row['priority_denominator'] = None
        row['score_components'] = None
        row['score_positives'] = []
        row['score_concerns'] = []
        missing = _component_inputs(row)
        if missing:
            row['strength_na_reason'] = 'Missing ' + ', '.join(missing)
            row['priority_na_reason'] = row['strength_na_reason']
            continue
        if row['isin'] not in p20 or row['isin'] not in p60:
            row['strength_na_reason'] = 'Fewer than five date-comparable analysed stocks'
            row['priority_na_reason'] = row['strength_na_reason']
            continue

        # Trend budget: direction is explicit, and overlapping trend indicators
        # share a capped 25-point support sub-budget.
        signed_efficiency = float(row['efficiency_20']) if float(row['r20']) > 0 else -float(row['efficiency_20'])
        efficiency = _clip(signed_efficiency / .60 * 100)
        directional_return = (_clip(float(row['r20']) / (float(row['atr_pct']) * 4) * 100) +
                              _clip(float(row['r60']) / (float(row['atr_pct']) * 8) * 100)) / 2
        support = 50 * bool(row.get('vstop_bullish')) + 50 * bool(float(row.get('plus_di', 0)) > float(row.get('minus_di', 0)))
        q = .45 * efficiency + .30 * directional_return + .25 * support

        peer = peer_percentiles[row.get('sector')]
        peer_value = peer.get(row['isin'])
        peer_basis = 'industry'
        if peer_value is None:
            peer_value = p20.get(row['isin'])
            peer_basis = 'universe fallback'
        l = .35 * p20[row['isin']] + .25 * p60[row['isin']] + .40 * peer_value

        participation = _clip((float(row['participation']) - .8) / 1.2 * 100)
        volume = _clip((float(row['volume_ratio_5d_30d']) - .8) / 1.2 * 100)
        up_volume = _clip((float(row['up_volume_share_20']) - 45) / 25 * 100)
        p = .45 * participation + .30 * volume + .25 * up_volume

        q, l, p = (round(_clip(x), 2) for x in (q, l, p))
        strength = round((30*q + 25*l + 15*p) / 70, 2)
        row['score_components'] = {'trend_quality': q, 'leadership': l,
                                   'entry_geometry': None, 'participation': p,
                                   'leadership_peer_basis': peer_basis}
        row['strength_score'] = strength
        row['strength_na_reason'] = None

        positives = sorted([('trend quality', q), ('leadership', l), ('participation', p)],
                           key=lambda x: (-x[1], x[0]))
        row['score_positives'] = [f'{name}: {value:.0f}/100' for name, value in positives[:2]]

        if not row.get('candidate'):
            row['priority_na_reason'] = ('Not a confirmed eligible setup' if row.get('scanner_eligible')
                                         else row.get('eligibility_reason') or 'Not scanner eligible')
            continue
        if row.get('exit_review'):
            row['priority_na_reason'] = 'Dual-negative exit review is active'
            row['score_concerns'] = ['VStop and OBV MACD are both bearish']
            continue
        geometry_required = ['extension_atr', 'invalidation_atr', 'max_gap_atr_5d']
        absent = [k for k in geometry_required if not _finite(row.get(k))]
        if absent:
            row['priority_na_reason'] = 'Missing ' + ', '.join(absent)
            continue
        extension = _band(float(row['extension_atr']), .35, 1.75, -.01, 4.0)
        invalidation = _band(float(row['invalidation_atr']), 1.5, 4.0, .5, 7.0)
        gap = _clip(100 - max(0, float(row['max_gap_atr_5d']) - .5) / 2.5 * 100)
        e = round(.45 * extension + .35 * invalidation + .20 * gap, 2)
        row['score_components']['entry_geometry'] = e
        row['priority_score'] = round(.30*q + .25*l + .30*e + .15*p, 2)
        row['priority_na_reason'] = None
        concerns = sorted([('trend quality', q), ('leadership', l), ('entry geometry', e),
                           ('participation', p)], key=lambda x: (x[1], x[0]))
        row['score_concerns'] = [f'{concerns[0][0]}: {concerns[0][1]:.0f}/100']

    ranked = sorted((r for r in rows if _finite(r.get('strength_score'))),
                    key=lambda r: (-r['strength_score'], r['isin']))
    for rank, row in enumerate(ranked, 1):
        row['strength_rank'], row['strength_denominator'] = rank, len(ranked)
    priority = sorted((r for r in rows if _finite(r.get('priority_score'))),
                      key=lambda r: (-r['priority_score'], r['isin']))
    for rank, row in enumerate(priority, 1):
        row['priority_rank'], row['priority_denominator'] = rank, len(priority)
    return rows
