import copy
import unittest

from pipeline.ranking import SCORE_VERSION, score_rows


def row(i, r20=12, candidate=True):
    return {'isin':f'INE{i:09d}','sector':'Industry','r20':r20,'r60':24,'atr_pct':2,
            'efficiency_20':.5 if r20 > 0 else -.5,'participation':1.5,
            'volume_ratio_5d_30d':1.4,'up_volume_share_20':60,
            'comparison_60_complete':True,'vstop_bullish':True,'plus_di':30,'minus_di':15,
            'scanner_eligible':True,'candidate':candidate,'exit_review':False,
            'extension_atr':1,'invalidation_atr':2.5,'max_gap_atr_5d':.4}


class RankingTests(unittest.TestCase):
    def test_deterministic_ties_and_no_forced_priority(self):
        rows=[row(i) for i in range(6)]
        rows[-1]['candidate']=False
        score_rows(rows)
        ranked=sorted(rows,key=lambda r:r['strength_rank'])
        self.assertEqual([r['isin'] for r in ranked],sorted(r['isin'] for r in rows))
        self.assertEqual(sum(r['priority_rank'] is not None for r in rows),5)
        self.assertEqual(rows[-1]['priority_na_reason'],'Not a confirmed eligible setup')
        self.assertEqual(rows[0]['score_version'],SCORE_VERSION)

    def test_decline_does_not_receive_positive_efficiency_credit(self):
        rising=[row(i,10+i) for i in range(5)]
        falling=row(9,-10);rows=rising+[falling]
        score_rows(rows)
        self.assertLess(falling['score_components']['trend_quality'],rising[0]['score_components']['trend_quality'])

    def test_missing_values_are_na_not_zero(self):
        rows=[row(i) for i in range(6)];rows[0]['atr_pct']=None
        score_rows(rows)
        self.assertIsNone(rows[0]['strength_score'])
        self.assertIn('atr_pct',rows[0]['strength_na_reason'])

    def test_dual_negative_blocks_fresh_entry_priority(self):
        rows=[row(i) for i in range(6)];rows[0]['exit_review']=True
        score_rows(rows)
        self.assertIsNone(rows[0]['priority_score'])
        self.assertIn('Dual-negative',rows[0]['priority_na_reason'])


if __name__=='__main__':
    unittest.main()
