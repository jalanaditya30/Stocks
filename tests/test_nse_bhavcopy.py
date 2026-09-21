from io import BytesIO
import unittest
import zipfile

import numpy as np
import pandas as pd

from pipeline.nse_bhavcopy import (concentrated_internal_gaps, parse_bhavcopy,
                                   repair_concentrated_gaps)


META={'isin':'INE000000001','nse':'TEST','yahoo':'TEST.NS'}


def history(factor=.5):
    dates=pd.bdate_range('2026-09-01','2026-09-18')
    raw=np.linspace(100,113,len(dates))
    return pd.DataFrame({'Open':raw*factor,'High':(raw+2)*factor,
                         'Low':(raw-2)*factor,'Close':raw*factor,
                         'Adj Close':raw*factor,'Volume':1000.,'RawClose':raw,
                         'CashTurnover':raw*1000/1e7},index=dates)


def archive(date='2026-09-17'):
    csv=("TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
         f"{date},INE000000001,TEST,EQ,110,114,109,112,2500\n")
    output=BytesIO()
    with zipfile.ZipFile(output,'w') as zipped:
        zipped.writestr('BhavCopy.csv',csv)
    return output.getvalue()


class NseBhavcopyTests(unittest.TestCase):
    def test_parser_validates_and_indexes_official_rows_by_isin(self):
        rows=parse_bhavcopy(archive(),'2026-09-17')
        self.assertEqual(rows[META['isin']]['symbol'],'TEST')
        self.assertEqual(rows[META['isin']]['close'],112)
        with self.assertRaisesRegex(ValueError,'trade date'):
            parse_bhavcopy(archive('2026-09-16'),'2026-09-17')

    def test_concentration_counts_internal_gaps_not_new_listings(self):
        day=pd.Timestamp('2026-09-17');complete=history()
        late=complete.loc['2026-09-15':].copy()
        frames={'TEST.NS':complete.drop(day),'LATE.NS':late}
        universe=[META,{**META,'isin':'INE000000002','yahoo':'LATE.NS'}]
        gaps=concentrated_internal_gaps(universe,frames,complete.index,threshold=.5)
        self.assertEqual(gaps,{day:1})

    def test_repair_inserts_adjusted_ohlcv_without_overwriting_yahoo(self):
        day=pd.Timestamp('2026-09-17');complete=history();missing=complete.drop(day)
        frames={'TEST.NS':missing.copy()}
        report=repair_concentrated_gaps([META],frames,complete.index,threshold=1,
                                        loader=lambda _:parse_bhavcopy(archive(),day))
        repaired=frames['TEST.NS'].loc[day]
        self.assertEqual(report['repaired_bars'],1)
        self.assertEqual(report['remaining_concentrated_gaps'],{})
        self.assertAlmostEqual(repaired.RawClose,112)
        self.assertAlmostEqual(repaired.Close,56)
        self.assertAlmostEqual(repaired.Open,55)
        self.assertAlmostEqual(repaired.Volume,2500)
        self.assertAlmostEqual(repaired.CashTurnover,112*2500/1e7)

    def test_adjustment_disagreement_is_not_manufactured(self):
        day=pd.Timestamp('2026-09-17');complete=history();missing=complete.drop(day)
        missing.loc[missing.index>day,'Close']*=.9
        frames={'TEST.NS':missing}
        report=repair_concentrated_gaps([META],frames,complete.index,threshold=1,
                                        loader=lambda _:parse_bhavcopy(archive(),day))
        self.assertNotIn(day,frames['TEST.NS'].index)
        self.assertEqual(report['repaired_bars'],0)
        self.assertEqual(report['skipped_bars'],1)
        self.assertEqual(report['remaining_concentrated_gaps'],{'2026-09-17':1})

    def test_archive_failure_is_reported_and_gap_remains(self):
        day=pd.Timestamp('2026-09-17');complete=history();frames={'TEST.NS':complete.drop(day)}
        def unavailable(_):
            raise RuntimeError('archive unavailable')
        report=repair_concentrated_gaps([META],frames,complete.index,threshold=1,
                                        loader=unavailable)
        self.assertIn('archive unavailable',report['errors'][0]['error'])
        self.assertEqual(report['remaining_concentrated_gaps'],{'2026-09-17':1})


if __name__=='__main__':unittest.main()
