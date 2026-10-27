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
        self.assertAlmostEqual(v['return_pct'],v['benchmark_pct'])

    def test_costs_reduce_returns(self):
        a=validation.evaluate(quotes(),['A.OL'],0)
        b=validation.evaluate(quotes(),['A.OL'],100)
        self.assertGreater(a['return_pct'],b['return_pct'])
        with self.assertRaises(ValueError):
            validation.evaluate(quotes(),['A.OL'],float('nan'))

    def test_fixed_fee_once_per_buy_order_not_per_share_or_month(self):
        a=validation.evaluate(quotes(),['A.OL'],initial_capital=100000)
        b=validation.evaluate(quotes(),['A.OL'],initial_capital=10000)
        self.assertEqual(a['buy_orders'],1)
        self.assertEqual(b['buy_orders'],1)
        self.assertAlmostEqual(a['fixed_fees_nok'],79)
        self.assertAlmostEqual(b['fixed_fees_nok'],79)
        self.assertGreater(a['return_pct'],b['return_pct'])
        q=quotes();q['B.OL']=q['A.OL']
        c=validation.evaluate(q,['A.OL','B.OL'])
        self.assertEqual(c['buy_orders'],2)
        self.assertAlmostEqual(c['fixed_fees_nok'],158)
        for capital in (0,float('nan'),1000000001):
            with self.assertRaises(ValueError):
                validation.evaluate(quotes(),['A.OL'],initial_capital=capital)

    def test_flat_market_has_exact_purchase_fee_loss(self):
        q=quotes()
        for bar in q['A.OL']['history']:
            bar['close']=100
        with patch('research.screen',return_value={'symbol':'A.OL','composite':50,'rank_eligible':True}):
            v=validation.evaluate(q,['A.OL'])
        self.assertAlmostEqual(v['return_pct'],-.079)
        self.assertAlmostEqual(v['benchmark_pct'],-.079)
        self.assertEqual(v['buy_orders'],1)

    def test_fixed_paper_budget_is_frozen_and_legacy_is_preserved(self):
        import json
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        report={'generated':1,'top20':['A.OL'],'cards':[{'symbol':'A.OL'}],'portfolio_limits':{'purchase_nok':1000}}
        validation.capture(db,report,1600000000)
        report['portfolio_limits']['purchase_nok']=10000
        validation.capture(db,report,1600000000)
        v=validation.paper_view(db,quotes(3),1600000000+3*86400)['snapshots'][0]
        r=v['symbols'][0]
        self.assertEqual(r['budget_nok'],1000)
        self.assertEqual(r['shares'],9)
        self.assertAlmostEqual(r['return_pct'],(9*(100.2-100.1)-79)/1000*100)
        legacy={'symbols':[{'symbol':'A.OL'}]}
        db.execute('INSERT INTO paper_snapshots VALUES (?,?,?)',(2,1600000000,json.dumps(legacy)))
        rows=validation.paper_view(db,quotes(3),1600000000+3*86400)['snapshots']
        old=next(row for row in rows if row['generated']==2)
        self.assertEqual(old['fee_model'],'legacy-percentage')
        self.assertAlmostEqual(old['symbols'][0]['return_pct'],(100.2/100.1*.998/1.002-1)*100)

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

    def test_long_window_excludes_young_history_and_compares_index_without_filling(self):
        q=quotes(1100);q['B.OL']={'currency':'NOK','history':q['A.OL']['history'][-300:]}
        q['OSEBX.OL']={'currency':'NOK','history':q['A.OL']['history']}
        v=validation.evaluate(q,['A.OL','B.OL'])
        self.assertEqual(v['sessions'],756);self.assertEqual(v['stocks'],1)
        self.assertGreaterEqual(len(v['folds']),3)
        self.assertEqual(v['oslo_index']['status'],'available')
        self.assertEqual(len(v['oslo_index']['curve']),756)
        q['OSEBX.OL']={'currency':'NOK','history':q['A.OL']['history'][:-5]}
        v=validation.evaluate(q,['A.OL'])
        self.assertIsNone(v['oslo_index']['return_pct'])

    def test_incomplete_cohort_has_no_total(self):
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        validation.capture(db,{'generated':1,'top20':['A.OL','B.OL'],'cards':[{'symbol':'A.OL'},{'symbol':'B.OL'}]},1600000000)
        self.assertIsNone(validation.paper_view(db,quotes(3),1600000000+3*86400)['snapshots'][0]['return_pct'])
