"""Small public-data feed diagnostic; no credentials or personal data."""
import yfinance as yf
import pandas as pd
from pipeline.engine import normalized
from pipeline.refresh import expected_session

asof=expected_session()
raw=yf.download(['^CRSLDX','RELIANCE.NS','TCS.NS','DISHTV.NS'],period='7y',auto_adjust=False,group_by='ticker',progress=False,threads=4,timeout=20)
for t in ['^CRSLDX','RELIANCE.NS','TCS.NS','DISHTV.NS']:
    frame=raw[t]
    d=normalized(frame,asof)
    print(t,'raw rows',len(frame.dropna()),'valid rows',len(d) if d is not None else 0,flush=True)
    print(frame.tail(5).to_json(orient='table'),flush=True)
