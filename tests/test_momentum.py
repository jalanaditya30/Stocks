import unittest
import numpy as np
import pandas as pd

from test_pipeline import CFG, META, fixture
from pipeline.engine import normalized, momentum_indicators, vstop_series, theme_summary, _rma
from pipeline.refresh import attach_rotation_context, build, rank_themes


def trending_frame(n=300):
    dates=pd.bdate_range(end='2026-09-18',periods=n)
    x=np.arange(n);close=100+x*.3+np.sin(x/4)*2
    volume=1_000_000*(1+.3*np.sin(x/7))
    raw=pd.DataFrame({'Open':close-.2,'High':close+1,'Low':close-1,
        'Close':close,'Adj Close':close,'Volume':volume},index=dates)
    return normalized(raw,str(dates[-1].date()))


class MomentumIndicatorTests(unittest.TestCase):
    def test_wilder_rma_uses_sma_seed(self):
        result=_rma([1,2,3,4,5],3)
        self.assertTrue(np.isnan(result[1]))
        self.assertAlmostEqual(result[2],2)
        self.assertAlmostEqual(result[3],8/3)

    def test_vstop_waits_for_atr_before_trailing(self):
        d=trending_frame(30);stop,state,atr=vstop_series(d,10,2)
        np.testing.assert_allclose(stop[:9],d.Close.to_numpy()[:9])
        self.assertTrue(np.isnan(atr[:9]).all())
        self.assertTrue((state[:9]==1).all())

    def test_vstop_is_bullish_and_below_an_orderly_uptrend(self):
        d=trending_frame();stop,state,_=vstop_series(d,10,2)
        self.assertEqual(state[-1],1)
        self.assertLess(stop[-1],d.Close.iloc[-1])

    def test_indicator_values_do_not_use_future_bars(self):
        d=trending_frame();cut=240
        full_stop,full_state,_=vstop_series(d,10,2)
        short_stop,short_state,_=vstop_series(d.iloc[:cut],10,2)
        self.assertAlmostEqual(full_stop[cut-1],short_stop[-1],places=10)
        self.assertEqual(full_state[cut-1],short_state[-1])
        full=momentum_indicators(d.iloc[:cut],CFG)
        repeated=momentum_indicators(d.iloc[:cut].copy(),CFG)
        self.assertEqual(full,repeated)

    def test_momentum_bundle_is_finite_and_explainable(self):
        values=momentum_indicators(trending_frame(),CFG)
        for key in ['vstop','obv_macd','adx','plus_di','minus_di','atr_pct','efficiency_20']:
            self.assertTrue(np.isfinite(values[key]),key)
        self.assertGreaterEqual(values['efficiency_20'],0)
        self.assertLessEqual(values['efficiency_20'],1)

    def test_flat_directional_input_does_not_publish_nan(self):
        d=trending_frame();d[['Open','High','Low','Close','Adj Close']]=100
        values=momentum_indicators(d,CFG)
        for key in ['adx','plus_di','minus_di','atr_pct']:
            self.assertTrue(np.isfinite(values[key]),key)


class RotationTests(unittest.TestCase):
    def row(self,isin,rs20,rs60,breadth=True,vstop=True):
        return {'isin':isin,'candidate':False,'r5':2,'r20':4,'r60':8,'rs20':rs20,'rs60':rs60,
            'above20':breadth,'above50':breadth,'above200':breadth,'above50_week_ago':False,
            'vstop_bullish':vstop,'obv_bullish':True,'new_high20':False,'new_high60':False,
            'adx':25,'efficiency_20':.4}

    def test_theme_state_uses_breadth_relative_strength_and_vstop(self):
        rows=[self.row(str(i),5,8) for i in range(4)]
        theme=theme_summary(rows,{str(i) for i in range(4)},'Strong','Curated theme')
        self.assertEqual(theme['status'],'Leading')
        self.assertEqual(theme['vstop_bullish'],100)
        weak=[self.row(str(i),-5,-8,False,False) for i in range(4)]
        theme=theme_summary(weak,{str(i) for i in range(4)},'Weak','Curated theme')
        self.assertEqual(theme['status'],'Avoid')

    def test_rank_change_compares_previous_successful_scan(self):
        themes=[{'taxonomy':'Curated theme','name':'A','status':'Leading','rs20':5,'rs60':8,'breadth':80},
                {'taxonomy':'Curated theme','name':'B','status':'Emerging','rs20':7,'rs60':2,'breadth':55}]
        old=[{'taxonomy':'Curated theme','name':'A','rank':2,'status':'Mature'},
             {'taxonomy':'Curated theme','name':'B','rank':1,'status':'Leading'}]
        ranked=rank_themes(themes,old)
        a=next(x for x in ranked if x['name']=='A')
        self.assertEqual(a['rank'],1);self.assertEqual(a['rank_change'],1)

    def test_same_session_rerun_preserves_prior_rank_comparison(self):
        themes=[{'taxonomy':'Curated theme','name':'A','status':'Leading','rs20':5,'rs60':8,'breadth':80}]
        current=[{'taxonomy':'Curated theme','name':'A','rank':1,'status':'Leading',
                  'previous_rank':3,'rank_change':2,'previous_status':'Mature'}]
        item=rank_themes(themes,current,True)[0]
        self.assertEqual(item['previous_rank'],3)
        self.assertEqual(item['rank_change'],2)
        self.assertEqual(item['previous_status'],'Mature')

    def test_detection_stores_indicator_state_for_future_evidence(self):
        raw,bench,asof=fixture();frames={'TEST.NS':normalized(raw,asof),CFG['benchmark']:normalized(bench,asof)}
        payload,_,ledger=build([META],frames,asof,CFG,[],[])
        self.assertTrue(payload['rows'][0]['candidate'])
        self.assertIn('momentum_confirmations',ledger[0])
        self.assertIn('vstop_bullish',ledger[0])

    def test_industry_fallback_and_overlapping_memberships_are_visible(self):
        row={**self.row('1',7,8),'sector':'Test industry','momentum_confirmations':4,
             'vstop_bullish':True,'obv_bullish':True}
        themes=[
            {'taxonomy':'Curated theme','name':'Theme A','members':['1'],'status':'Emerging','rank':2,
             'coverage':80,'coverage_quality':'Broad','breadth_change':5,'r20':5,'r60':7,'rs20':4},
            {'taxonomy':'Curated theme','name':'Theme B','members':['1'],'status':'Leading','rank':1,
             'coverage':60,'coverage_quality':'Partial','breadth_change':8,'r20':6,'r60':9,'rs20':5},
            {'taxonomy':'Industry','name':'Test industry','members':['1','2','3'],'resolved':3,'status':'Mixed','rank':1,
             'coverage':100,'coverage_quality':'Broad','breadth_change':0,'r20':3,'r60':6,'rs20':2}]
        attach_rotation_context([row],themes)
        self.assertEqual(row['theme_name'],'Theme B')
        self.assertEqual(len(row['theme_memberships']),2)
        self.assertEqual(row['stock_vs_industry_r20'],1)
        self.assertEqual(row['stock_vs_industry_r60'],2)
        self.assertEqual(row['industry_name'],'Test industry')
        self.assertEqual(row['rotation_posture'],'Hold / monitor')
        other={**row,'isin':'2','theme_memberships':[]}
        attach_rotation_context([other],themes)
        self.assertEqual(other['theme_name'],'Test industry')
        self.assertEqual(other['theme_taxonomy'],'Industry')

    def test_exit_review_requires_both_stock_indicators_bearish(self):
        themes=[{'taxonomy':'Industry','name':'Test industry','members':['1','2','3'],'resolved':3,
                 'status':'Mixed','rank':1,'coverage':100,'coverage_quality':'Broad',
                 'breadth_change':0,'r20':3,'r60':6,'rs20':2}]
        one={**self.row('1',2,3),'sector':'Test industry','vstop_bullish':False,'obv_bullish':True}
        both={**self.row('2',2,3),'sector':'Test industry','vstop_bullish':False,'obv_bullish':False}
        attach_rotation_context([one,both],themes)
        self.assertFalse(one['exit_review']);self.assertEqual(one['rotation_posture'],'Watch')
        self.assertTrue(both['exit_review']);self.assertEqual(both['rotation_posture'],'Exit review')


if __name__=='__main__':unittest.main()
