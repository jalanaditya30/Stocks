"""Versioned exchange-session calendar independent of market-price frames."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import pandas_market_calendars as mcal

ROOT = Path(__file__).resolve().parents[1]
OVERRIDES = ROOT / 'config' / 'exchange_calendar_overrides.json'


def calendar_metadata():
    data = json.loads(OVERRIDES.read_text())
    return {key:data[key] for key in ['version','source','verified_against','verified_on'] if key in data}


def exchange_sessions(start, end):
    """Return the configured NSE sessions, including explicit reviewed overrides."""
    data = json.loads(OVERRIDES.read_text())
    schedule = mcal.get_calendar('NSE').schedule(start_date=pd.Timestamp(start).date(),
                                                 end_date=pd.Timestamp(end).date())
    sessions = pd.DatetimeIndex(schedule.index).tz_localize(None).normalize()
    remove = pd.DatetimeIndex(pd.to_datetime(data.get('remove_sessions', [])))
    add = pd.DatetimeIndex(pd.to_datetime(data.get('add_sessions', [])))
    if len(remove):
        sessions = sessions.difference(remove)
    if len(add):
        sessions = sessions.union(add)
    return sessions.sort_values()


def recent_sessions(asof, count, lookback_days=None):
    lookback_days = lookback_days or max(count * 2, 365)
    sessions = exchange_sessions(pd.Timestamp(asof) - pd.Timedelta(days=lookback_days), asof)
    if len(sessions) < count:
        raise RuntimeError(f'Calendar contains only {len(sessions)} sessions; {count} required')
    return sessions[-count:]
