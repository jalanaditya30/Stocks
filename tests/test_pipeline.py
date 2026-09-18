import copy
import json
from pathlib import Path
import unittest
import numpy as np
import pandas as pd

from pipeline.engine import normalized, analyze, crossed_and_held, theme_summary
from pipeline.refresh import build, track, expected_session

CFG=json.loads((Path(__file__).resolve().parents[1]/'config/model.json').read_text())
META={'isin':'INE000000001','nse':'TEST','yahoo':'TEST.NS','name':'Test company','industry_group':'Test industry'}


def fixture(n=300):
    dates=pd.bdate_range(end='2026-09-18',periods=n)
    c=np.linspace(100,110,n);c[-5:]=[110.1,110.3,112,113,114]
    volume=np.full(n,1000000.);volume[-5:]*=2
    raw=pd.DataFrame({'Open':c-.3,'High':c+.5,'Low':c-1.5,'Close':c,'Adj Close':c,'Volume':volume},index=dates)
    bc=np.linspace(100,102,n)
    bench=pd.DataFrame({'Open':bc-.1,'High':bc+.5,'Low':bc-.5,'Close':bc,'Adj Close':bc,'Volume':1000000.},index=dates)
    return raw,bench,str(dates[-1].date())


class ConfirmationTests(unittest.TestCase):
    def setUp(self):
        self.raw,self.bench,self.asof=fixture()
        self.d=normalized(self.raw,self.asof);self.b=normalized(self.bench,self.asof)

    def test_held_breakout_qualifies_with_explainable_reasons(self):
        row,error=analyze(META,self.d,self.b,self.asof,CFG)
        self.assertIsNone(error);self.assertTrue(row['candidate'])
        self.assertEqual(row['setup'],'Confirmed moves')
        self.assertLess(row['anchor'],row['last']);self.assertEqual(len(row['reasons']),4)

    def test_pre_breakout_never_qualifies(self):
        self.d.iloc[-20,self.d.columns.get_loc('High')]=120
        row,_=analyze(META,self.d,self.b,self.asof,CFG)
        self.assertFalse(row['candidate']);self.assertIsNone(row['anchor'])

    def test_single_close_is_not_confirmation(self):
        raw,bench,asof=fixture()
        raw.loc[raw.index[-3:-1],['Open','High','Low','Close','Adj Close']]=[109,110,108,109.5,109.5]
        row,_=analyze(META,normalized(raw,asof),normalized(bench,asof),asof,CFG)
        self.assertFalse(row['candidate'])

    def test_failed_hold_is_not_a_candidate(self):
        d=self.d.copy();d.loc[d.index[-1],'Close']=108
        row,_=analyze(META,d,self.b,self.asof,CFG)
        self.assertFalse(row['candidate'])

    def test_stale_and_missing_sessions_are_excluded(self):
        row,reason=analyze(META,self.d.iloc[:-1],self.b,self.asof,CFG)
        self.assertIsNone(row);self.assertEqual(reason,'latest session missing')
        row,reason=analyze(META,self.d.drop(self.d.index[-8]),self.b,self.asof,CFG)
        self.assertIsNone(row);self.assertEqual(reason,'recent sessions missing')

    def test_cash_turnover_not_dividend_adjusted(self):
        self.raw['Adj Close']=self.raw.Close*.5
        d=normalized(self.raw,self.asof)
        self.assertAlmostEqual(d.CashTurnover.iloc[-1],self.raw.Close.iloc[-1]*self.raw.Volume.iloc[-1]/1e7)
        row,_=analyze(META,d,self.b,self.asof,CFG)
        self.assertAlmostEqual(row['last'],self.raw.Close.iloc[-1],places=2)

    def test_current_bar_and_future_prices_are_removed(self):
        old_date=str(self.raw.index[-2].date())
        d=normalized(self.raw,old_date)
        self.assertEqual(str(d.index[-1].date()),old_date)

    def test_low_participation_or_thin_market_does_not_qualify(self):
        raw=self.raw.copy();raw['Volume']=1000000
        row,_=analyze(META,normalized(raw,self.asof),self.b,self.asof,CFG)
        self.assertFalse(row['candidate'])
        raw['Volume']=100
        row,reason=analyze(META,normalized(raw,self.asof),self.b,self.asof,CFG)
        self.assertIsNone(row);self.assertEqual(reason,'below liquidity requirement')

    def test_no_chasing_an_extended_move(self):
        raw=self.raw.copy()
        for i,c in zip(raw.index[-3:],[115.,123.,132.]):
            raw.loc[i,['Open','High','Low','Close','Adj Close']]=[c-.3,c+.5,c-1.5,c,c]
        row,_=analyze(META,normalized(raw,self.asof),self.b,self.asof,CFG)
        self.assertFalse(row['candidate']);self.assertEqual(row['setup'],'Extended / event')

    def test_leader_resumption_requires_prior_advance_and_consolidation(self):
        d=self.d.copy();c=np.linspace(60,100,len(d))
        i=len(d)-3
        c[i-51:i-10]=np.linspace(75,100,41)
        c[i-10:i]=[100,101,100,102,101,102,101,102,101,102]
        c[i:]=[104,105,106]
        for col,delta in [('Open',-.3),('High',.5),('Low',-1.5),('Close',0),('Adj Close',0),('RawClose',0)]:d[col]=c+delta
        d['CashTurnover']=d.Close*d.Volume/1e7
        anchor=crossed_and_held(d,20,CFG,True)
        self.assertIsNotNone(anchor)
        row,_=analyze(META,d,self.b,self.asof,CFG)
        self.assertTrue(row['candidate']);self.assertEqual(row['setup'],'Leaders resuming')

    def test_momentum_uses_t_minus_252_to_t_minus_21(self):
        row,_=analyze(META,self.d,self.b,self.asof,CFG)
        expected=(self.d.Close.iloc[-22]/self.d.Close.iloc[-253]-1)*100
        self.assertAlmostEqual(row['momentum_12_1'],expected,places=2)


class PublicationAndTrackingTests(unittest.TestCase):
    def setUp(self):
        raw,bench,self.asof=fixture()
        self.frames={'TEST.NS':normalized(raw,self.asof),'^NSEI':normalized(bench,self.asof)}
        self.row,_=analyze(META,self.frames['TEST.NS'],self.frames['^NSEI'],self.asof,CFG)

    def test_low_coverage_aborts_publication(self):
        universe=[META,{**META,'isin':'INE000000002','yahoo':'MISS.NS'}]
        with self.assertRaisesRegex(RuntimeError,'coverage'):
            build(universe,self.frames,self.asof,CFG,[],[])

    def test_no_same_close_profit_and_no_duplicate_detection(self):
        ledger,tracking,summary=track([], [self.row],self.frames,self.frames['^NSEI'],self.asof,CFG)
        self.assertEqual(len(ledger),1);self.assertEqual(tracking[0]['outcomes'],{})
        ledger2,_,_=track(copy.deepcopy(ledger),[self.row],self.frames,self.frames['^NSEI'],self.asof,CFG)
        self.assertEqual(ledger,ledger2)

    def test_forward_returns_start_next_open_and_need_complete_horizon(self):
        seen=str(self.frames['TEST.NS'].index[-6].date())
        signal={'id':'x','isin':META['isin'],'symbol':'TEST','yahoo':'TEST.NS','setup':'Confirmed moves',
                'first_seen':seen,'breakout_date':seen,'window':60,'model':CFG['version']}
        _,tracking,_=track([signal],[],self.frames,self.frames['^NSEI'],self.asof,CFG)
        o=tracking[0]['outcomes'];self.assertIn('5',o);self.assertNotIn('10',o)
        d=self.frames['TEST.NS'];expected=(d.Close.iloc[-1]/d.Open.iloc[-5]-1)*100
        self.assertAlmostEqual(o['5']['gross'],expected,places=2)
        self.assertLess(o['5']['net'],o['5']['gross'])

    def test_rising_breakout_reference_does_not_duplicate_same_move(self):
        old={**self.row,'breakout_date':str(self.frames['TEST.NS'].index[-3].date())}
        ledger,_,_=track([], [old],self.frames,self.frames['^NSEI'],self.asof,CFG)
        newer={**self.row,'breakout_date':str(self.frames['TEST.NS'].index[-2].date())}
        ledger,_,_=track(ledger,[newer],self.frames,self.frames['^NSEI'],self.asof,CFG)
        self.assertEqual(len(ledger),1)

    def test_completed_observations_survive_missing_provider_history(self):
        seen=str(self.frames['TEST.NS'].index[-6].date())
        signal={'id':'x','isin':META['isin'],'symbol':'TEST','yahoo':'TEST.NS','setup':'Confirmed moves',
                'first_seen':seen,'breakout_date':seen,'window':60,'model':CFG['version']}
        ledger,tracking,_=track([signal],[],self.frames,self.frames['^NSEI'],self.asof,CFG)
        _,missing,summary=track(ledger,[],{},self.frames['^NSEI'],self.asof,CFG)
        self.assertEqual(missing[0]['outcomes'],tracking[0]['outcomes'])
        self.assertEqual(summary[0]['n'],1)

    def test_low_theme_coverage_does_not_claim_improvement(self):
        result=theme_summary([self.row],{META['isin'],'x','y','z'},'Theme','Curated theme')
        self.assertEqual(result['status'],'Insufficient coverage');self.assertEqual(result['coverage'],25)

    def test_payload_is_strict_json_serializable(self):
        payload,charts,ledger=build([META],self.frames,self.asof,CFG,[],[])
        json.dumps([payload,charts,ledger],allow_nan=False)
        self.assertEqual(payload['coverage']['eligible'],1)

    def test_weekend_and_intraday_use_completed_session(self):
        self.assertEqual(expected_session('2026-09-19T12:00:00Z'),'2026-09-18')
        self.assertEqual(expected_session('2026-09-18T09:00:00Z'),'2026-09-17')


if __name__=='__main__':unittest.main()
