import copy
import math
import time
import unittest
from unittest.mock import patch
import portfolio_fit as pf
import research

NOW=1800000000


def quote(price=100,currency='NOK',asof=NOW):
    return {'price':price,'currency':currency,'asof':asof}


def snapshot():
    return {'positions':[{'symbol':'A','currency':'NOK','shares':10}],
            'quotes':{'A':quote(),'A.OL':quote(),'B.OL':quote()}}


def profile(**kw):
    return pf.preferences({'cash_nok':9000,'purchase_nok':1000,'max_stock_pct':30,'max_sector_pct':50,
                           'reserve_pct':10,'cost_bps':20,'sectors':{'A.OL':'Energy','B.OL':'Industrials'},**kw})


class PortfolioFitTests(unittest.TestCase):
    def test_limits_validate_and_reject_nonfinite(self):
        for change in ({'cash_nok':True},{'cash_nok':float('nan')},{'purchase_nok':-1},{'max_stock_pct':0},
                       {'max_sector_pct':101},{'cost_bps':201},{'sectors':[]},{'sectors':{'A.OL':'Made up'}},
                       {'sectors':{'<script>':'Energy'}},{'reserve_pct':None}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                profile(**change)
        self.assertEqual(profile(sectors={'MSFT':'Information technology'})['sectors']['MSFT'],'Information technology')

    def test_cash_is_part_of_denominator(self):
        v=pf.context(snapshot(),profile(),NOW)
        self.assertEqual(v['total_nok'],10000)
        self.assertEqual(v['holdings'][0]['weight_pct'],10)
        self.assertEqual(v['cash_pct'],90)

    def test_aliases_aggregate_and_watchlists_do_not_consume_limits(self):
        s=snapshot();s['positions'] += [{'symbol':'A.OL','currency':'NOK','shares':5},
                                       {'symbol':'B.OL','currency':'NOK','shares':0}]
        v=pf.context(s,profile(),NOW)
        self.assertEqual(len(v['holdings']),1)
        self.assertEqual(v['holdings'][0]['shares'],15)
        self.assertEqual(v['holdings'][0]['value_nok'],1500)
        self.assertEqual(v['total_nok'],10500)

    def test_missing_price_blocks_total_weights_and_preview(self):
        s=snapshot();s['quotes']['A']['asof']-=5*86400
        v=pf.context(s,profile(),NOW)
        self.assertIsNone(v['total_nok'])
        self.assertIsNone(v['holdings'][0]['weight_pct'])
        self.assertFalse(pf.preview('B',1000,s,profile(),now=NOW)['ready'])

    def test_usd_holdings_require_fresh_fx(self):
        s=snapshot();s['positions'].append({'symbol':'US','currency':'USD','shares':2})
        s['quotes']['US']=quote(100,'USD');s['quotes']['NOK=X']=quote(10)
        p=profile(sectors={'US':'Financials','A.OL':'Energy','B.OL':'Industrials'})
        self.assertEqual(pf.context(s,p,NOW)['total_nok'],12000)
        s['quotes']['NOK=X']['asof']-=5*86400
        self.assertFalse(pf.context(s,p,NOW)['complete'])

    def test_whole_shares_budget_includes_costs_and_no_mutation(self):
        s=snapshot();before=copy.deepcopy(s);p=profile()
        v=pf.preview('B',1000,s,p,now=NOW)
        self.assertEqual(v['shares'],9)
        self.assertEqual(v['purchase_nok'],900)
        self.assertAlmostEqual(v['fees_nok'],1.8)
        self.assertLessEqual(v['purchase_nok']+v['fees_nok'],1000)
        self.assertAlmostEqual(v['after_stock_pct'],900/9998.2*100)
        self.assertAlmostEqual(v['after_cash_nok'],8098.2)
        self.assertTrue(v['ready'])
        self.assertEqual(s,before)

    def test_unknown_sector_never_clears(self):
        for sectors in ({'A.OL':'Energy'},{'B.OL':'Industrials'},{}):
            v=pf.preview('B',1000,snapshot(),profile(sectors=sectors),now=NOW)
            self.assertFalse(v['ready'])
            self.assertIsNone(v['max_purchase_nok'])
            self.assertIsNone(v['after_sector_pct'])
            self.assertIsNotNone(v['after_stock_pct'])

    def test_sector_and_position_caps_include_fee_denominator(self):
        p=profile(max_stock_pct=10,max_sector_pct=20,sectors={'A.OL':'Energy','B.OL':'Energy'})
        v=pf.preview('A',500,snapshot(),p,now=NOW)
        self.assertFalse(v['ready'])
        self.assertEqual(v['max_purchase_nok'],0)
        v=pf.preview('B',1100,snapshot(),p,now=NOW)
        self.assertFalse(v['ready'])
        self.assertGreater(v['after_stock_pct'],10)
        self.assertGreater(v['after_sector_pct'],20)
        self.assertAlmostEqual(v['max_purchase_nok'],1000/(1+.2*.002))

    def test_cash_reserve_counts_costs(self):
        p=profile(max_stock_pct=100,max_sector_pct=100,reserve_pct=85)
        v=pf.preview('B',1000,snapshot(),p,now=NOW)
        self.assertFalse(v['ready'])
        self.assertLess(v['after_cash_pct'],85)
        self.assertTrue(any('reserve' in w for w in v['warnings']))
        self.assertAlmostEqual(v['max_purchase_nok'],500/(1+.002*.15))

    def test_zero_budget_and_full_reserve_block(self):
        self.assertFalse(pf.preview('B',0,snapshot(),profile(),now=NOW)['ready'])
        v=pf.preview('B',1000,snapshot(),profile(reserve_pct=100),now=NOW)
        self.assertFalse(v['ready'])
        self.assertEqual(v['max_purchase_nok'],0)

    def test_cash_only_portfolio_can_preview(self):
        s=snapshot();s['positions']=[]
        self.assertTrue(pf.preview('B',1000,s,profile(),now=NOW)['ready'])

    def test_stale_wrong_currency_future_prices_block(self):
        for q in (quote(asof=NOW-5*86400),quote(currency='USD'),quote(asof=NOW+1000),quote(float('nan'))):
            s=snapshot();s['quotes']['B.OL']=q
            self.assertFalse(pf.preview('B',1000,s,profile(),now=NOW)['ready'])
        with self.assertRaises(ValueError):
            pf.preview('B',float('inf'),snapshot(),profile(),now=NOW)
        with self.assertRaises(ValueError):
            pf.preview('<script>',100,snapshot(),profile(),now=NOW)

    def test_rank_never_changes_and_stale_report_cannot_clear(self):
        card={'symbol':'B.OL','price':100,'asof':NOW,'action':'Consider buying','rank_eligible':True,'rank':1,'composite':90}
        report={'generated':NOW,'cards':[card]};saved=copy.deepcopy(report)
        v=pf.view(snapshot(),report,profile(),NOW)
        self.assertTrue(v['candidates'][0]['buy_candidate'])
        self.assertEqual(report,saved)
        for change in ({'generated':NOW-2*86400},{'generated':NOW+1000},
                       {'cards':[{**card,'action':'Wait / watch'}]}, {'cards':[{**card,'asof':NOW-5*86400}]}):
            v=pf.view(snapshot(),{**report,**change},profile(),NOW)
            self.assertFalse(v['candidates'][0]['buy_candidate'])

    def test_correlation_exact_alignment_and_missing_history(self):
        def series(sign):
            price=100.;out=[]
            for i in range(100):
                price*=1+sign*(.005*math.sin(i)+.001)
                out.append({'time':NOW-(100-i)*86400,'close':price})
            return {'history':out}
        a=series(1);b=series(-1)
        self.assertAlmostEqual(pf.correlation(a,a)['value'],1)
        self.assertAlmostEqual(pf.correlation(a,b)['value'],-1)
        self.assertIsNone(pf.correlation(a,{'history':a['history'][:50]}))
        b['history'].pop(50)
        self.assertEqual(pf.correlation(a,b)['observations'],97)
        self.assertIsNone(pf.correlation(a,{'history':[{'time':p['time'],'close':100} for p in a['history']]}))

    def test_ai_explains_chosen_limits(self):
        with patch('time.time',return_value=NOW):
            report=research.build_report({**snapshot(),'portfolio_preferences':profile()},[])
        evidence=research.compact_evidence(report,'Explain my concentration')
        self.assertEqual(evidence['portfolio_limits']['max_stock_pct'],30)
        self.assertEqual(evidence['portfolio_context']['total_nok'],10000)
