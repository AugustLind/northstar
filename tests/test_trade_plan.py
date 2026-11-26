import copy
import random
import unittest
from northstar import portfolio_fit as pf
from northstar import trade_plan as tp

NOW=1800000000

def q(price=100):
    return {'price':price,'asof':NOW,'currency':'NOK'}

def card(symbol='B.OL',rank=1,action='Consider buying'):
    return {'symbol':symbol,'rank':rank,'composite':100-rank,'rank_eligible':True,'price':100,'asof':NOW,
            'action':action,'score':100,'metrics':{'volatility':20,'extension50':5}}

def profile(**kw):
    return pf.preferences({'cash_nok':10000,'purchase_nok':1000,'max_stock_pct':100,'max_sector_pct':100,
                           'reserve_pct':0,'max_buy_fee_pct':100,'review_sell_pct':25,
                           'sectors':{'A.OL':'Energy','B.OL':'Industrials','C.OL':'Health care'},**kw})

def snapshot(shares=0):
    return {'positions':[{'symbol':'A','currency':'NOK','shares':shares}],
            'quotes':{'A':q(),'A.OL':q(),'B.OL':q(),'C.OL':q()}}

class TradePlanTests(unittest.TestCase):
    def plan(self,s=None,cards=None,p=None):
        return tp.build(s or snapshot(),{'generated':NOW,'policy_version':tp.policy.VERSION,'cards':cards if cards is not None else [card()]},p or profile(),NOW)

    def test_candidate_preview_explains_best_evaluated_option_when_no_buy_qualifies(self):
        account = {**snapshot(), 'portfolio_preferences': profile(max_buy_fee_pct=5)}
        report = {'generated': NOW, 'policy_version': tp.policy.VERSION,
                  'cards': [card(), {**card('C.OL', 2), 'rank_eligible': False}],
                  'coverage': {'unavailable': 1}}
        review = self.plan(account, report['cards'], account['portfolio_preferences'])
        preview = tp.candidate_plan(account, report, cash=1000, review_plan=review)
        self.assertEqual(preview['buy_candidates'], [])
        self.assertEqual(preview['buy_candidate_watch']['symbol'], 'B.OL')
        self.assertIn('purchase-fee limit', preview['buy_candidate_watch']['reason'])

        report['cards'] = [{**card(), 'rank_eligible': False, 'action': 'Wait / watch',
                            'reasons': ['The trend screen is not met.']}]
        preview = tp.candidate_plan(account, report, cash=1000, review_plan=review)
        self.assertEqual(preview['buy_candidate_watch']['reason'], 'The trend screen is not met.')

        report['generated'] -= 2 * 86400
        preview = tp.candidate_plan(account, report, cash=1000, review_plan=review)
        self.assertIsNone(preview['buy_candidate_watch'])

    def test_explicit_whole_shares_one_fixed_fee_and_shared_budget(self):
        v=self.plan(cards=[card(),card('C.OL',2)])
        self.assertEqual(len(v['buys']),1)
        self.assertEqual(v['buys'][0]['buy_shares'],9)
        self.assertEqual(v['buys'][0]['fee_nok'],79)
        self.assertEqual(v['spent_nok'],979)
        self.assertEqual(v['unallocated_budget_nok'],21)
        self.assertEqual(v['cash_after_buys_nok'],9021)
        self.assertIn('shared budget',v['buys'][0]['portfolio_reason'])
        self.assertIn('Industrials sector',v['buys'][0]['portfolio_reason'])
        self.assertIsNone(v['cash_after_sell_scenario_nok'])
        self.assertIn('unknown until you enter',v['method'])

    def test_entered_fee_assumptions_change_buy_and_sale_guidance(self):
        p=profile(buy_fee_nok=25,sell_fee_nok=12)
        s=snapshot(10);s['positions'][0]['above']=100
        v=self.plan(s,[{**card('A.OL',action='Consider taking profits'),'review_price':100},card('B.OL',2)],p)
        self.assertEqual(v['buys'][0]['fee_nok'],25)
        sale=next(r for r in v['holdings'] if r['symbol']=='A.OL')
        self.assertEqual(sale['gross_proceeds_nok'],300)
        self.assertEqual(sale['fee_nok'],12)
        self.assertEqual(sale['net_proceeds_nok'],288)
        self.assertEqual(v['sell_fees_nok'],12)
        self.assertEqual(v['cash_after_sell_scenario_nok'],10288)

    def test_sell_review_prices_use_basis_and_both_fee_assumptions(self):
        s=snapshot(10);s['positions'][0].update(cost=100,above=150)
        s['quotes']['A']['source']='Independent quote fixture'
        v=self.plan(s,p=profile(buy_fee_nok=25,sell_fee_nok=12))
        row=v['holdings'][0]
        self.assertEqual(row['break_even_price'],103.7)
        self.assertEqual(row['limit_reference_price'],100)
        self.assertEqual(row['quote_source'],'Independent quote fixture')
        self.assertEqual(row['quote_age_seconds'],0)
        self.assertEqual(row['target_price'],150)
        self.assertEqual(row['target_reason'],'Your saved upper review level.')
        second=snapshot(4);second['positions'][0]['cost']=200
        row=self.plan(second,p=profile(buy_fee_nok=30,sell_fee_nok=10))['holdings'][0]
        self.assertEqual(row['break_even_price'],210)

    def test_missing_basis_unknown_sell_fee_and_stale_quote_withhold_precise_prices(self):
        s=snapshot(10)
        row=self.plan(s,p=profile(sell_fee_nok=12))['holdings'][0]
        self.assertIsNone(row['break_even_price'])
        self.assertIn('positive cost basis',row['break_even_status'])
        s['positions'][0]['cost']=100
        row=self.plan(s)['holdings'][0]
        self.assertIsNone(row['break_even_price'])
        self.assertIn('sell-fee assumption',row['break_even_status'])
        s['quotes']['A']['asof']=NOW-5*86400
        s['quotes']['A']['source']='Independent quote fixture'
        row=self.plan(s,p=profile(sell_fee_nok=12))['holdings'][0]
        self.assertIsNone(row['break_even_price'])
        self.assertIsNone(row['limit_reference_price'])
        self.assertEqual(row['quote_source'],'Independent quote fixture')
        self.assertEqual(row['quote_age_seconds'],5*86400)
        self.assertIsNone(row['sell_shares'])

    def test_reconciliation_constraint_withholds_sell_quantity(self):
        s=snapshot(10);s['ledger_reconciled']=False
        row=self.plan(s,p=profile(sell_fee_nok=12))['holdings'][0]
        self.assertIsNone(row['sell_shares'])
        self.assertIn('Reconcile',row['reasons'][0])

    def test_budget_above_cash_does_not_reserve_unaffordable_orders(self):
        v=self.plan(cards=[card(),card('C.OL',2)],p=profile(cash_nok=5000,purchase_nok=100000,max_buy_fee_pct=2))
        self.assertEqual(len(v['buys']),1)
        self.assertEqual(v['buys'][0]['buy_shares'],49)
        self.assertEqual(v['spent_nok'],4979)

    def test_fee_limit_blocks_small_orders_and_can_be_changed(self):
        v=self.plan(p=profile(max_buy_fee_pct=2))
        self.assertEqual(v['buys'],[])
        self.assertIn('4029.0 NOK',v['blocked_buys'][0]['reason'])
        self.assertTrue(self.plan(p=profile(max_buy_fee_pct=10))['buys'])

    def test_zero_buy_fee_is_a_valid_explicit_assumption(self):
        v=self.plan(p=profile(buy_fee_nok=0))
        self.assertEqual(v['buys'][0]['fee_nok'],0)
        self.assertEqual(v['buy_fees_nok'],0)

    def test_ceil_sale_size_and_merge_reasons_without_double_selling(self):
        s=snapshot(10);p=profile(cash_nok=0,purchase_nok=10000,max_stock_pct=60,review_sell_pct=25)
        v=self.plan(s,[card('A.OL',action='Consider reducing / selling')],p)
        row=v['holdings'][0]
        self.assertEqual(row['sell_shares'],4)  # max(ceil(25%*10), 10-6), not 3+4.
        self.assertEqual(row['remaining_shares'],6)
        self.assertEqual(row['gross_proceeds_nok'],400)
        self.assertIsNone(row['fee_nok'])
        self.assertIsNone(row['net_proceeds_nok'])
        self.assertEqual(v['buys'],[])  # Neither hypothetical sale proceeds nor the same ticker can fund a buy.
        self.assertEqual(v['cash_after_buys_nok'],0)
        self.assertIsNone(v['cash_after_sell_scenario_nok'])

    def test_sale_never_exceeds_owned_and_zero_review_is_explicit(self):
        s=snapshot(1);s['positions'][0].update(below=100,above=100)
        v=self.plan(s,[{**card('A.OL',action='Review sell threshold'),'review_price':100}],profile(review_sell_pct=100))
        self.assertEqual(v['holdings'][0]['sell_shares'],1)
        self.assertEqual(v['holdings'][0]['remaining_shares'],0)
        s['positions'][0]['below']=None
        v=self.plan(s,[{**card('A.OL',action='Consider taking profits'),'review_price':100}],profile(review_sell_pct=0))
        self.assertEqual(v['holdings'][0]['sell_shares'],0)
        self.assertTrue(any('0%' in r for r in v['holdings'][0]['reasons']))

    def test_sector_trim_and_reserve_are_coordinated(self):
        s=snapshot(10);s['positions'].append({'symbol':'B.OL','currency':'NOK','shares':5})
        p=profile(cash_nok=0,max_stock_pct=100,max_sector_pct=50,reserve_pct=60,
                  sectors={'A.OL':'Energy','B.OL':'Energy'})
        v=self.plan(s,[],p)
        self.assertEqual(sum(r['sell_shares'] for r in v['holdings']),9)
        self.assertIsNone(v['cash_after_sell_scenario_nok'])
        self.assertTrue(all(0<=r['sell_shares']<=r['owned'] for r in v['holdings']))
        self.assertTrue(any('sector' in reason for r in v['holdings'] for reason in r['reasons']))
        self.assertTrue(any('cash reserve' in reason for r in v['holdings'] for reason in r['reasons']))

    def test_stale_report_suppresses_signals_but_not_fresh_allocation_math(self):
        s=snapshot(10);s['positions'][0]['above']=100;p=profile(cash_nok=0,max_stock_pct=60)
        v=tp.build(s,{'generated':NOW-2*86400,'cards':[{**card('A.OL',action='Consider taking profits'),'review_price':100},card()]},p,NOW)
        self.assertEqual(v['buys'],[])
        self.assertEqual(v['holdings'][0]['sell_shares'],4)
        self.assertFalse(any('sale-review setting' in r for r in v['holdings'][0]['reasons']))

    def test_unknown_sector_missing_price_and_fractional_holdings(self):
        s=snapshot(10)
        v=self.plan(s,p=profile(sectors={}))
        self.assertEqual(v['buys'],[])
        s['quotes']['A']['asof']-=5*86400
        v=self.plan(s)
        self.assertIsNone(v['holdings'][0]['sell_shares'])
        self.assertEqual(v['buys'],[])
        v=self.plan(snapshot(.5),[card('A.OL',action='Hold / monitor')])
        self.assertIsNone(v['holdings'][0]['sell_shares'])
        self.assertEqual(v['buys'],[])

    def test_holdings_that_meet_buy_screen_can_add_without_sell_conflict(self):
        v=self.plan(snapshot(1),[card('A.OL',action='Hold / monitor')])
        self.assertEqual(v['holdings'][0]['sell_shares'],0)
        self.assertEqual(v['buys'][0]['buy_shares'],9)
        self.assertEqual(v['after_buys']['holdings'][0]['shares'],10)

    def test_duplicate_aliases_do_not_generate_conflicting_quantities(self):
        s=snapshot(10);s['positions'].append({'symbol':'A.OL','currency':'NOK','shares':0})
        v=self.plan(s,[card('A.OL',action='Hold / monitor')])
        self.assertIsNone(v['holdings'][0]['sell_shares'])
        self.assertEqual(v['buys'],[])

    def test_inputs_unchanged(self):
        s=snapshot(5);r={'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[card(),card('A.OL',action='Consider taking profits')]};p=profile()
        before=copy.deepcopy((s,r,p))
        tp.build(s,r,p,NOW)
        self.assertEqual((s,r,p),before)

    def test_purchase_plan_respects_combined_cash_position_sector_and_fee_constraints(self):
        rng=random.Random(12)
        for iteration in range(50):
            s={'positions':[],'quotes':{}}
            sectors={};cards=[]
            for i in range(12):
                symbol='S'+str(i)+'.OL';price=rng.uniform(10,1000)
                s['quotes'][symbol]=q(price);sectors[symbol]=['Energy','Industrials','Health care'][i%3]
                cards.append({**card(symbol,i+1),'price':price})
            p=profile(cash_nok=rng.uniform(5000,100000),purchase_nok=rng.uniform(1000,200000),
                      max_stock_pct=20,max_sector_pct=35,reserve_pct=10,max_buy_fee_pct=5,sectors=sectors)
            v=self.plan(s,cards,p)
            self.assertLessEqual(v['spent_nok'],p['purchase_nok']+1e-6)
            self.assertAlmostEqual(v['buy_fees_nok'],p['buy_fee_nok']*len(v['buys']))
            after=v['after_buys']
            self.assertGreaterEqual(after['cash_pct'],p['reserve_pct']-1e-8)
            self.assertTrue(all(h['weight_pct']<=20+1e-8 for h in after['holdings']))
            self.assertTrue(all(h['weight_pct']<=35+1e-8 for h in after['sectors']))
            self.assertTrue(all(r['fee_pct']<=5+1e-8 and isinstance(r['buy_shares'],int) for r in v['buys']))

    def test_new_sizing_settings_are_validated(self):
        for change in ({'review_sell_pct':101},{'max_buy_fee_pct':0},{'max_buy_fee_pct':float('nan')}):
            with self.assertRaises(ValueError):
                profile(**change)
