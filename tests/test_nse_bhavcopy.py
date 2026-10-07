from io import BytesIO
import unittest
import zipfile

import numpy as np
import pandas as pd

from pipeline.nse_bhavcopy import (concentrated_internal_gaps, parse_bhavcopy,
                                   parse_index_close, repair_concentrated_gaps,
                                   repair_latest_session)


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

    def test_index_snapshot_parser_selects_named_index_and_checks_date(self):
        csv=('Index Name,Index Date,Open Index Value,High Index Value,Low Index Value,'
             'Closing Index Value,Points Change,Change(%),Volume,Turnover (Rs. Cr.)\n'
             'Nifty 50,17-09-2026,100,110,95,105,1,1,10,1\n'
             'Nifty 500,17-09-2026,200,210,195,205,1,1,30,3\n').encode()
        row=parse_index_close(csv,'2026-09-17','Nifty 500')
        self.assertEqual((row['open'],row['close'],row['volume']),(200,205,30))
        with self.assertRaisesRegex(ValueError,'date'):
            parse_index_close(csv,'2026-09-18','Nifty 500')

    def test_latest_session_is_appended_for_stocks_and_benchmark(self):
        complete=history();day=complete.index[-1]
        archive_day=archive(str(day.date()))
        frames={'TEST.NS':complete.iloc[:-1].copy(),'^BENCH':complete.iloc[:-1].copy()}
        index_bar={'open':1,'high':3,'low':.5,'close':2,'volume':0.}
        report=repair_latest_session([META],frames,complete.index,'^BENCH','Nifty 500',
                                     loader=lambda d:parse_bhavcopy(archive_day,d),
                                     index_loader=lambda d,name:index_bar)
        self.assertTrue(report['attempted'])
        self.assertTrue(report['benchmark_repaired'])
        self.assertEqual(report['repaired_bars'],1)
        self.assertEqual(frames['TEST.NS'].index[-1],day)
        self.assertAlmostEqual(frames['TEST.NS'].loc[day].Close,56)
        self.assertAlmostEqual(frames['TEST.NS'].loc[day].RawClose,112)
        self.assertAlmostEqual(frames['^BENCH'].loc[day].Close,2)

    def test_latest_session_skips_corporate_action_sized_moves(self):
        complete=history();day=complete.index[-1]
        csv=("TradDt,ISIN,TckrSymb,SctySrs,OpnPric,HghPric,LwPric,ClsPric,TtlTradgVol\n"
             f"{day.date()},INE000000001,TEST,EQ,56,57,55,56,2500\n")
        output=BytesIO()
        with zipfile.ZipFile(output,'w') as zipped:
            zipped.writestr('BhavCopy.csv',csv)
        frames={'TEST.NS':complete.iloc[:-1].copy()}
        report=repair_latest_session([META],frames,complete.index,'^BENCH','Nifty 500',
                                     loader=lambda d:parse_bhavcopy(output.getvalue(),d),
                                     index_loader=lambda d,name:None)
        self.assertEqual(report['skipped_bars'],1)
        self.assertNotIn(day,frames['TEST.NS'].index)

    def test_latest_session_not_attempted_when_provider_is_current(self):
        complete=history();frames={'TEST.NS':complete.copy()}
        def unexpected(*_):
            raise AssertionError('archive should not be requested')
        report=repair_latest_session([META],frames,complete.index,'^BENCH','Nifty 500',
                                     loader=unexpected,index_loader=unexpected)
        self.assertFalse(report['attempted'])
        self.assertEqual(report['errors'],[])


if __name__=='__main__':unittest.main()
