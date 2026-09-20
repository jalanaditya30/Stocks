"""Small public-data feed diagnostic; no credentials or personal data."""
import yfinance as yf
import pandas as pd
from pipeline.engine import normalized
from pipeline.refresh import expected_session
from pipeline.calendar import recent_sessions, exchange_sessions, calendar_metadata

asof=expected_session()
required=recent_sessions(asof,130)
print('calendar',calendar_metadata(),'required',str(required[0].date()),str(required[-1].date()),flush=True)
raw=yf.download(['^CRSLDX','RELIANCE.NS','TCS.NS','DISHTV.NS'],period='7y',auto_adjust=False,group_by='ticker',progress=False,threads=4,timeout=20)
for t in ['^CRSLDX','RELIANCE.NS','TCS.NS','DISHTV.NS']:
    frame=raw[t]
    d=normalized(frame,asof)
    print(t,'raw rows',len(frame.dropna()),'valid rows',len(d) if d is not None else 0,flush=True)
    if d is not None:
        print(t,'missing required sessions',[str(x.date()) for x in required if x not in d.index],flush=True)
        valid_calendar=set(exchange_sessions(d.index[0],d.index[-1]))
        print(t,'provider dates outside configured calendar',[str(x.date()) for x in d.index if x not in valid_calendar],flush=True)
    print(frame.tail(5).to_json(orient='table'),flush=True)
