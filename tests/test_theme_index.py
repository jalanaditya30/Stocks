import unittest

import numpy as np
import pandas as pd

from pipeline.theme_index import BASE, build_theme_indexes, equal_weight_index


def frame(index, values):
    return pd.DataFrame(values, index=index, dtype=float)


class EqualWeightIndexTest(unittest.TestCase):
    def setUp(self):
        # Two sessions in January, two in February.
        self.idx = pd.DatetimeIndex(['2026-01-05', '2026-01-30', '2026-02-02', '2026-02-27'])

    def test_equal_shares_from_base(self):
        values, _, used, weights = equal_weight_index(
            frame(self.idx[:2], {'A': [100, 200], 'B': [50, 50]}))
        self.assertEqual(values[0], BASE)
        self.assertAlmostEqual(values[1], 15_000)  # mean(2.0, 1.0) on equal shares
        self.assertEqual(used, 2)
        self.assertEqual(weights[0][0], 'A')        # drifted weight 2/3
        self.assertAlmostEqual(weights[0][1], 66.67, places=2)

    def test_monthly_rebalance_resets_equal_shares(self):
        # Jan: A doubles. Feb: B doubles. Rebalanced at the Jan month-end close.
        values, reb, _, _ = equal_weight_index(
            frame(self.idx, {'A': [100, 200, 200, 200], 'B': [50, 50, 50, 100]}))
        self.assertAlmostEqual(values[1], 15_000)
        self.assertAlmostEqual(values[3], 22_500)    # 15,000 x mean(1, 2); buy-and-hold would give 20,000
        self.assertEqual(reb, 1)

    def test_late_member_joins_at_next_rebalance(self):
        values, _, used, _ = equal_weight_index(
            frame(self.idx, {'A': [100, 100, 100, 110], 'B': [np.nan, 80, 80, 80]}))
        self.assertAlmostEqual(values[1], BASE)      # B not in the index during January
        self.assertAlmostEqual(values[3], 10_500)    # Feb: mean(1.1, 1.0)
        self.assertEqual(used, 2)

    def test_missing_bar_carries_previous_close(self):
        values, _, _, _ = equal_weight_index(
            frame(self.idx[:3], {'A': [100, np.nan, 120], 'B': [100, 100, 100]}))
        self.assertAlmostEqual(values[1], BASE)

    def test_build_payload_shares_one_calendar(self):
        idx = pd.bdate_range('2026-01-01', periods=40)
        bench = pd.DataFrame({'Close': np.linspace(100, 110, 40)}, index=idx)
        frames = {f'{s}.NS': pd.DataFrame({'Close': np.linspace(100, 100 + k, 40)}, index=idx)
                  for k, s in enumerate(['X', 'Y', 'Z'], start=1)}
        universe = [{'isin': s, 'yahoo': f'{s}.NS'} for s in ['X', 'Y', 'Z']]
        out = build_theme_indexes(universe, frames, bench,
                                  [('Curated theme', 'T', {'X', 'Y', 'Z'}), ('Industry', 'Solo', {'X'})],
                                  str(idx[-1].date()))
        self.assertEqual(out['weighting'], 'equal')
        self.assertEqual(len(out['dates']), 40)
        self.assertIn('Curated theme|T', out['indexes'])
        self.assertNotIn('Industry|Solo', out['indexes'])   # single-member groups are skipped
        self.assertEqual(len(out['indexes']['Curated theme|T']['values']), 40)


if __name__ == '__main__':
    unittest.main()
