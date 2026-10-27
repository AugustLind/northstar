import sqlite3
import unittest
from unittest.mock import patch
import validation


def quotes(n=320):
    return {'A.OL':{'currency':'NOK','history':[{'time':1600000000+i*86400,'close':100+i*.1,'volume':100000} for i in range(n)]}}


class ValidationTests(unittest.TestCase):
    def test_future_prices_never_enter_signal(self):
        seen=[]
        def screen(s,q,**kw):
            self.assertLessEqual(q['history'][-1]['time'],kw['as_of'])
            self.assertEqual(q['turnover20'],sum(p['close']*p['volume'] for p in q['history'][-20:])/20)
            seen.append(len(q['history']))
            return {'symbol':s,'composite':80,'rank_eligible':True}
        with patch('research.screen',side_effect=screen):
            v=validation.evaluate(quotes(),['A.OL'])
        self.assertTrue(seen)
        self.assertGreater(v['return_pct'],0)
        self.assertLess(v['return_pct'],v['benchmark_pct'])

    def test_costs_reduce_returns(self):
        a=validation.evaluate(quotes(),['A.OL'],0)
        b=validation.evaluate(quotes(),['A.OL'],100)
        self.assertGreater(a['return_pct'],b['return_pct'])
        with self.assertRaises(ValueError):
            validation.evaluate(quotes(),['A.OL'],float('nan'))

    def test_no_eligible_stocks_stay_cash(self):
        with patch('research.screen',return_value={'rank_eligible':False}):
            v=validation.evaluate(quotes(),['A.OL'])
        self.assertEqual(v['return_pct'],0)
        self.assertEqual(v['trades'],0)

    def test_paper_is_append_only_and_waits_for_later_prices(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        report={'generated':10,'top20':['A.OL'],'cards':[{'symbol':'A.OL','rank':1,'action':'Wait'}]}
        validation.capture(db,report,1600000000)
        validation.capture(db,{**report,'top20':[]},1600000001)
        v=validation.paper_view(db,quotes(1),1600000000)
        self.assertEqual(len(v['snapshots']),1)
        self.assertIsNone(v['snapshots'][0]['return_pct'])
        v=validation.paper_view(db,quotes(3),1600000000+3*86400)
        r=v['snapshots'][0]['symbols'][0]
        self.assertEqual(r['entry'],100.1)
        self.assertIsNotNone(r['return_pct'])
        self.assertEqual(v['snapshots'][0]['captured'],1600000000)

    def test_incomplete_cohort_has_no_total(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        validation.capture(db,{'generated':1,'top20':['A.OL','B.OL'],'cards':[{'symbol':'A.OL'},{'symbol':'B.OL'}]},1600000000)
        self.assertIsNone(validation.paper_view(db,quotes(3),1600000000+3*86400)['snapshots'][0]['return_pct'])
