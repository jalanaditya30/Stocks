import copy
import unittest
import numpy as np
import pandas as pd
from test_pipeline import CFG,META,fixture
from pipeline.engine import normalized,analyze
from pipeline.backtest import features,outcome,choose,portfolio,episodes

class HistoricalTests(unittest.TestCase):
    def setUp(self):
        raw,bench,asof=fixture(500)
        rng=np.random.default_rng(19)
        c=100*np.exp(np.cumsum(rng.normal(.001,.016,500)))
        for k,delta in [('Open',-.003),('High',.008),('Low',-.012),('Close',0),('Adj Close',0)]:raw[k]=c*(1+delta)
        raw['Volume']=rng.uniform(1e6,4e6,500)
        self.d=normalized(raw,asof);self.b=normalized(bench,asof)

    def test_vectorized_signals_match_live_engine(self):
        f=features(self.d,self.b,CFG)
        self.assertGreater(int(f.candidate.sum()),0)
        for i in range(130,500):
            r,_=analyze(META,self.d.iloc[:i+1],self.b.iloc[:i+1],str(self.b.index[i].date()),CFG)
            self.assertEqual(bool(f.candidate.iloc[i]),bool(r and r['candidate']),f'date {i}')
            if r and r['candidate']:
                self.assertEqual('Leaders resuming' if f.continuation.iloc[i] else 'Confirmed moves',r['setup'])
                self.assertAlmostEqual(f.level.iloc[i],r['anchor_adjusted'])

    def test_future_changes_cannot_change_past_signals(self):
        before=features(self.d,self.b,CFG).iloc[:350]
        changed=self.d.copy();changed.iloc[350:,changed.columns.get_loc('Close')]*=3
        after=features(changed,self.b,CFG).iloc[:350]
        pd.testing.assert_frame_equal(before,after)

    def test_missing_history_excludes_signals(self):
        changed=self.d.drop(self.d.index[350]);f=features(changed,self.b,CFG)
        self.assertFalse(f.eligible.iloc[350:480].any())

    def test_outcome_does_not_skip_missing_next_open(self):
        changed=self.d.reindex(self.b.index).copy();changed.loc[changed.index[301],'Open']=np.nan
        self.assertEqual(outcome(changed,self.b,300,20)['status'],'missing_prices')
        self.assertEqual(outcome(self.d,self.b,490,20)['status'],'immature')

    def test_target_and_risk_same_bar_is_ambiguous(self):
        d=self.d.copy();i=300;opening=d.Open.iloc[i+1]
        d.loc[d.index[i+1],'High']=opening*1.11;d.loc[d.index[i+1],'Low']=opening*.94
        self.assertEqual(outcome(d,self.b,i,20)['first_passage'],'ambiguous')

    def test_variant_selection_has_no_holdout_dependency(self):
        variants={n:{'development':{'n':200,'mean_excess_yield_adjusted':1},'validation':{'n':200,'mean_excess_yield_adjusted':1}} for n in ['baseline','no_chase','market_trend','combined']}
        variants['no_chase']['validation']['mean_excess_yield_adjusted']=2
        variants['no_chase']['holdout']={'mean_excess_yield_adjusted':-100}
        self.assertEqual(choose(variants),'no_chase')
        variants['no_chase']['validation']['n']=2;self.assertEqual(choose(variants),'baseline')

    def test_no_signals_means_cash_not_index_returns(self):
        p=portfolio([],{},self.b,str(self.b.index[130].date()),str(self.b.index[-1].date()))
        self.assertEqual(p['cagr'],0);self.assertEqual(p['trades'],0);self.assertEqual(p['average_exposure'],0)

    def test_portfolio_allocates_one_sleeve_and_charges_both_sides(self):
        i=300
        signal={'ticker':'TEST.NS','industry':'Test industry','i':i,'signal':str(self.b.index[i].date()),
                'symbol':'TEST','extension':2,'r5':4,'market_trend':True,'rs20':5,'participation':2}
        p=portfolio([signal],{'TEST.NS':self.d},self.b,str(self.b.index[i].date()),str(self.b.index[i+22].date()))
        net=outcome(self.d,self.b,i,20)['net']
        self.assertEqual(p['trades'],1)
        self.assertAlmostEqual(p['curve'][-1]['strategy'],100+net*.1,places=3)

if __name__=='__main__':unittest.main()
