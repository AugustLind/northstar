"""Hand-calculated examples: inputs and expected values do not use production helpers."""
import datetime as dt
import unittest
import account_performance
import validation

def timestamp(date):
    return dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp()

def quote(values):
    return {'currency':'NOK','account_history_version':1,'history':[
        {'time':timestamp(d),'account_close':v,'close':v} for d,v in values]}

class IndependentAccountingExamples(unittest.TestCase):
    def test_deposit_then_withdrawal_with_two_price_moves(self):
        # 10 shares at 100 + 100 cash = 1,100 opening value.
        # Day 2: shares rise to 110; deposit 500 at day end -> 1,700.
        # Day 3: shares fall to 99; withdraw 200 -> 1,390.
        # P&L = 1390 - 1100 - 300 = -10.
        # Linked factors: 1200/1100 and 1590/1700.
        # Dietz capital: 1100 + 500*(1/2) - 200*0 = 1350.
        p={'symbol':'REF.OL','currency':'NOK','shares':10,'cost':100}
        events=[{'id':1,'date':'2025-01-02','type':'deposit','currency':'NOK','net_cash':500},
                {'id':2,'date':'2025-01-03','type':'withdrawal','currency':'NOK','net_cash':-200}]
        baseline={'cutoff_date':'2025-01-01','opening_cash_nok':100,'opening_positions':[p]}
        snapshot={'positions':[p],'quotes':{'REF.OL':quote([('2025-01-01',100),('2025-01-02',110),('2025-01-03',99)])},
                  'ledger_reconciled':True,'manual_portfolio_preferences':{'cash_nok':400}}
        result=account_performance.view(snapshot,baseline,events,timestamp('2025-01-05'))
        self.assertEqual(result['status'],'available')
        self.assertEqual([x['value_nok'] for x in result['curve']],[1100,1700,1390])
        self.assertEqual(result['investment_pnl_nok'],-10)
        self.assertAlmostEqual(result['daily_linked_return_pct'],2.032085561497321)
        self.assertAlmostEqual(result['modified_dietz_pct'],-0.7407407407407407)

    def test_reverse_split_dividend_and_broker_fee(self):
        # 20 shares at 10 -> 10 shares at 20 after a 1-for-2 split.
        # Dividend of 1/share lowers price to 19 and adds 10 cash; fee costs 2.
        # 10*19 + 10 - 2 = 198; total loss 2, or 1%.
        opening={'symbol':'REF.OL','currency':'NOK','shares':20,'cost':10}
        current={'symbol':'REF.OL','currency':'NOK','shares':10,'cost':20}
        events=[{'id':1,'date':'2025-01-02','type':'split','symbol':'REF.OL','currency':'NOK','net_cash':0,'split_ratio':0.5},
                {'id':2,'date':'2025-01-03','type':'dividend','currency':'NOK','net_cash':10},
                {'id':3,'date':'2025-01-03','type':'fee','currency':'NOK','net_cash':-2,'fee':2}]
        q=quote([('2025-01-01',10),('2025-01-02',20),('2025-01-03',19)])
        q['events']=[{'time':timestamp('2025-01-02'),'kind':'split','ratio':0.5}]
        baseline={'cutoff_date':'2025-01-01','opening_cash_nok':0,'opening_positions':[opening]}
        snapshot={'positions':[current],'quotes':{'REF.OL':q},'ledger_reconciled':True,
                  'manual_portfolio_preferences':{'cash_nok':8}}
        result=account_performance.view(snapshot,baseline,events,timestamp('2025-01-05'))
        self.assertEqual(result['ending_value_nok'],198)
        self.assertEqual(result['investment_pnl_nok'],-2)
        self.assertEqual(result['income_nok'],10)
        self.assertEqual(result['reported_fees_nok'],2)
        self.assertAlmostEqual(result['daily_linked_return_pct'],-1)
        self.assertAlmostEqual(result['modified_dietz_pct'],-1)

class ForwardBenchmarkExamples(unittest.TestCase):
    def results(self):
        return [{'entry_time':timestamp('2025-01-02'),'asof':timestamp('2025-01-03'),'return_pct':8},
                {'entry_time':timestamp('2025-01-02'),'asof':timestamp('2025-01-03'),'return_pct':2}]
    def test_five_percent_cohort_minus_two_percent_index(self):
        result=validation.paper_benchmark(self.results(),{'OSEBX.OL':quote([('2025-01-02',100),('2025-01-03',102)])})
        self.assertEqual(result['status'],'available')
        self.assertAlmostEqual(result['return_pct'],2)
        self.assertAlmostEqual(result['excess_percentage_points'],3)
    def test_missing_or_misaligned_dates_and_pending_never_report_excess(self):
        index={'OSEBX.OL':quote([('2025-01-02',100),('2025-01-04',102)])}
        rows=self.results()
        self.assertIsNone(validation.paper_benchmark(rows,index)['excess_percentage_points'])
        rows[1]['asof']=timestamp('2025-01-04')
        self.assertIsNone(validation.paper_benchmark(rows,index)['return_pct'])
        rows[1]['return_pct']=None
        self.assertEqual(validation.paper_benchmark(rows,index)['status'],'pending')

    def test_saved_cohort_exposes_comparison_without_rewriting_capture(self):
        import sqlite3
        db=sqlite3.connect(':memory:');db.row_factory=sqlite3.Row
        report={'generated':1,'top20':['REF.OL'],'cards':[{'symbol':'REF.OL','action':'buy'}],
                'portfolio_limits':{'purchase_nok':1000}}
        validation.capture(db,report,timestamp('2025-01-01'))
        before=db.execute('SELECT payload FROM paper_snapshots').fetchone()[0]
        quotes={'REF.OL':quote([('2025-01-02',100),('2025-01-03',102)]),
                'OSEBX.OL':quote([('2025-01-02',100),('2025-01-03',102)])}
        result=validation.paper_view(db,quotes,timestamp('2025-01-04'))['snapshots'][0]
        # Nine shares, 79 fee and 21 residual cash -> 939 ending value.
        self.assertAlmostEqual(result['return_pct'],-6.1)
        self.assertAlmostEqual(result['benchmark']['excess_percentage_points'],-8.1)
        self.assertEqual(db.execute('SELECT payload FROM paper_snapshots').fetchone()[0],before)
        db.close()
