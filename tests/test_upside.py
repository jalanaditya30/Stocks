import copy
import unittest
from unittest.mock import patch
import numpy as np
from test_pipeline import CFG, META, fixture
from pipeline.engine import normalized
from pipeline.refresh import track, upside_metrics, fetch


class UpsideTests(unittest.TestCase):
    def setUp(self):
        raw,bench,self.asof=fixture()
        self.d=normalized(raw,self.asof)
        self.b=normalized(bench,self.asof)
        seen=str(self.d.index[-6].date())
        self.signal={'id':'x','isin':META['isin'],'symbol':'TEST','yahoo':'TEST.NS',
                     'setup':'Confirmed moves','first_seen':seen,'breakout_date':seen,
                     'window':60,'model':CFG['version']}

    def test_opportunity_and_same_bar_order_are_not_realized_profit(self):
        d=self.d.tail(5).copy()
        d['High']=[104,106,111,108,109];d['Low']=[98,94,99,97,98]
        o=upside_metrics(d,100)
        self.assertEqual(o['best_excursion'],11)
        self.assertEqual(o['sessions_to_5'],2)
        self.assertEqual(o['sessions_to_10'],3)
        self.assertEqual(o['5_before_minus5'],'ambiguous_same_session')
        self.assertEqual(o['10_before_minus5'],'downside_first')

    def test_unreached_targets_are_not_missing_or_wins(self):
        d=self.d.tail(5).copy();d['High']=102;d['Low']=98
        o=upside_metrics(d,100)
        self.assertFalse(o['reach_5']);self.assertIsNone(o['sessions_to_5'])
        self.assertEqual(o['5_before_minus5'],'neither')

    def test_missing_bars_do_not_award_a_horizon(self):
        d=self.d.drop(self.d.index[-3])
        _,items,summary=track([self.signal],[],{'TEST.NS':d},self.b,self.asof,CFG)
        self.assertEqual(items[0]['outcomes'],{})
        self.assertEqual(summary[0]['total'],1);self.assertEqual(summary[0]['upside_n'],0)

    def test_rolloff_cannot_create_a_new_entry(self):
        _,items,_=track([self.signal],[],{'TEST.NS':self.d.tail(5)},self.b.tail(5),self.asof,CFG)
        self.assertEqual(items[0]['outcomes'],{})
        self.assertNotIn('entry_date',items[0])

    def test_stale_price_cannot_claim_current_hold(self):
        _,items,_=track([self.signal],[],{'TEST.NS':self.d.iloc[:-1]},self.b,self.asof,CFG)
        self.assertEqual(items[0]['state'],'Awaiting prices')
        self.assertIsNone(items[0]['since_detection'])

    def test_no_future_bar_influence(self):
        earlier=str(self.d.index[-2].date())
        _,items,_=track([self.signal],[],{'TEST.NS':self.d},self.b,earlier,CFG)
        self.assertEqual(items[0]['outcomes'],{})
        self.assertEqual(items[0]['price_asof'],earlier)

    def test_outcomes_persist_and_old_returns_are_preserved(self):
        old=copy.deepcopy(self.signal);old['outcomes']={'5':{'net':42}}
        ledger,items,summary=track([old],[],{'TEST.NS':self.d},self.b,self.asof,CFG)
        self.assertEqual(items[0]['outcomes']['5']['net'],42)
        self.assertEqual(summary[0]['upside_n'],1)
        _,missing,_=track(ledger,[],{},self.b,self.asof,CFG)
        self.assertEqual(missing[0]['outcomes'],items[0]['outcomes'])

    def test_stale_download_is_retried_without_losing_fallback(self):
        raw,_,asof=fixture()
        with patch('pipeline.refresh.yf.download',side_effect=[raw.iloc[:-1],raw]),patch('pipeline.refresh.time.sleep'):
            out=fetch(['TEST.NS'],asof,require_current=False)
        self.assertEqual(str(out['TEST.NS'].index[-1].date()),asof)
