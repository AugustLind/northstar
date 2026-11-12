import copy
import datetime as dt
import unittest
import account_performance as ap

NOW=dt.datetime(2025,1,6,tzinfo=dt.timezone.utc).timestamp()
def stamp(date):return dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp()
def quote(values,currency='NOK',events=None):
    return {'currency':currency,'account_history_version':1,'history':[{'time':stamp(d),'close':v*.5,'account_close':v,'raw_close':v} for d,v in values], 'events':events or []}
def event(id,date,type,cash=0,qty=0,ratio=None):
    return {'id':id,'uid':str(id),'date':date,'type':type,'net_cash':cash,'currency':'NOK','symbol':'A.OL' if type in ('buy','sell','split') else '', 'quantity':qty,'fee':None,**({'split_ratio':ratio} if ratio is not None else {})}
def setup(events,prices,opening_shares=10,opening_cash=100,opening_cost=10,legacy=False):
    opening={'symbol':'A.OL','currency':'NOK','shares':opening_shares,'cost':opening_cost}
    positions={'A.OL':dict(opening)}
    for e in sorted(events,key=ap.event_order):ap.apply_event(positions,e)
    baseline={'cutoff_date':'2025-01-01','opening_cash_nok':opening_cash,'opening_positions':[opening]}
    if legacy:baseline.pop('opening_positions')
    snapshot={'ledger_reconciled':True,'positions':list(positions.values()),'quotes':{'A.OL':prices},
              'manual_portfolio_preferences':{'cash_nok':opening_cash+sum(e['net_cash'] for e in events)}}
    return snapshot,baseline

class AccountPerformanceTests(unittest.TestCase):
    def test_dividend_cash_does_not_double_count_adjusted_prices(self):
        rows=[event(1,'2025-01-02','dividend',5)]
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',9.5)]))
        value=ap.view(s,b,rows,NOW)
        self.assertEqual(value['status'],'available');self.assertEqual(value['investment_pnl_nok'],0)
        self.assertEqual(value['daily_linked_return_pct'],0);self.assertEqual(value['income_nok'],5)

    def test_contributions_fees_and_realised_book_pnl(self):
        rows=[event(1,'2025-01-02','dividend',5),event(2,'2025-01-03','deposit',100),event(3,'2025-01-03','buy',-100,10),event(4,'2025-01-04','sell',45,5)]
        rows[2]['fee']=5;rows[3]['fee']=2.5
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',9.5),('2025-01-03',9.5),('2025-01-04',9.5)]))
        value=ap.view(s,b,rows,NOW)
        self.assertEqual(value['opening_value_nok'],200);self.assertEqual(value['ending_value_nok'],292.5)
        self.assertEqual(value['net_contributions_nok'],100);self.assertEqual(value['investment_pnl_nok'],-7.5)
        self.assertEqual(value['reported_fees_nok'],7.5);self.assertEqual(value['realized_trade_pnl_nok'],-5)
        self.assertAlmostEqual(value['modified_dietz_pct'],-7.5/(200+100/3)*100)
        self.assertAlmostEqual(value['daily_linked_return_pct'],(.975*292.5/295-1)*100)

    def test_legacy_quantities_reconstruct_but_cost_basis_is_not_invented(self):
        rows=[event(1,'2025-01-02','buy',-100,10),event(2,'2025-01-03','sell',100,5)]
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',10),('2025-01-03',10)]),legacy=True)
        value=ap.view(s,b,rows,NOW)
        self.assertEqual(value['opening_value_nok'],200);self.assertIsNone(value['realized_trade_pnl_nok'])
        self.assertIn('reconstructed',value['opening_basis'])

    def test_split_requires_ledger_ratio_and_historical_share_unit_prices(self):
        rows=[event(1,'2025-01-02','split',ratio=2)]
        q=quote([('2025-01-01',100),('2025-01-02',50)],events=[{'time':stamp('2025-01-02'),'kind':'split','ratio':2}])
        s,b=setup(rows,q,opening_shares=1,opening_cash=0,opening_cost=100)
        self.assertEqual(ap.view(s,b,rows,NOW)['investment_pnl_nok'],0)
        s,b=setup([],q,opening_shares=1,opening_cash=0,opening_cost=100)
        value=ap.view(s,b,[],NOW);self.assertEqual(value['status'],'unavailable')
        self.assertTrue(any('matching recorded ratio' in x for x in value['coverage']))

    def test_usd_opening_holdings_use_dated_fx_and_flag_missing_sessions(self):
        p={'symbol':'US','currency':'USD','shares':2,'cost':100}
        s={'ledger_reconciled':True,'positions':[p], 'quotes':{'US':quote([('2025-01-01',100),('2025-01-03',100)],'USD'),
              'NOK=X':quote([('2025-01-01',10),('2025-01-02',10.5),('2025-01-03',11)])},'manual_portfolio_preferences':{'cash_nok':0}}
        b={'cutoff_date':'2025-01-01','opening_positions':[p],'opening_cash_nok':0}
        self.assertEqual(ap.view(s,b,[],NOW)['status'],'unavailable')
        value=ap.view(s,b,[],NOW,allow_prior_close=True)
        self.assertEqual(value['status'],'estimated');self.assertEqual(value['investment_pnl_nok'],200)
        self.assertEqual(value['carried_valuations'],1)
        self.assertAlmostEqual(value['daily_linked_return_pct'],10)

    def test_unreconciled_or_old_price_basis_cannot_show_a_proxy_return(self):
        q=quote([('2025-01-01',10),('2025-01-02',11)])
        s,b=setup([],q);s['ledger_reconciled']=False
        self.assertEqual(ap.view(s,b,[],NOW)['curve'],[])
        s['ledger_reconciled']=True;s['quotes']['A.OL']['currency']='USD'
        self.assertIsNone(ap.view(s,b,[],NOW)['investment_pnl_nok'])
        s['quotes']['A.OL']['currency']='NOK';s['quotes']['A.OL'].pop('account_history_version')
        value=ap.view(s,b,[],NOW);self.assertIsNone(value['investment_pnl_nok']);self.assertEqual(value['curve'],[])

    def test_read_only_and_zero_prior_capital_are_explicit(self):
        rows=[event(1,'2025-01-02','deposit',100)]
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',10),('2025-01-03',10)]),opening_shares=0,opening_cash=0)
        old=copy.deepcopy((s,b,rows));value=ap.view(s,b,rows,NOW)
        self.assertEqual((s,b,rows),old);self.assertIsNone(value['daily_linked_return_pct'])
        self.assertEqual(value['investment_pnl_nok'],0)

    def test_new_positions_have_known_buy_basis_without_opening_cost(self):
        rows=[event(1,'2025-01-02','buy',-100,10),event(2,'2025-01-03','sell',110,10)]
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',10),('2025-01-03',11)]),opening_shares=0,opening_cash=100)
        value=ap.view(s,b,rows,NOW)
        self.assertEqual(value['realized_trade_pnl_nok'],10);self.assertEqual(value['investment_pnl_nok'],10)

    def test_standalone_fee_is_reported_once_without_double_subtraction(self):
        rows=[event(1,'2025-01-02','fee',-5)]
        rows[0]['fee']=5
        s,b=setup(rows,quote([('2025-01-01',10),('2025-01-02',10)]),opening_shares=0,opening_cash=100)
        value=ap.view(s,b,rows,NOW)
        self.assertEqual(value['reported_fees_nok'],5)
        self.assertEqual(value['investment_pnl_nok'],-5)

class AccountPriceBasisTests(unittest.TestCase):
    def test_provider_split_only_close_is_restored_to_old_share_units(self):
        import app,io,json
        from unittest.mock import patch
        dates=[stamp('2025-01-01'),stamp('2025-01-02')]
        payload={'chart':{'result':[{'meta':{'regularMarketPrice':50,'currency':'NOK','regularMarketTime':dates[-1]},'timestamp':dates,
                 'indicators':{'quote':[{'close':[50,50]}],'adjclose':[{'adjclose':[45,50]}]},
                 'events':{'splits':{'s':{'date':dates[-1],'numerator':2,'denominator':1}}}}]}}
        with patch.object(app,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):value=app.fetch_quote('A.OL')
        self.assertEqual([p['close'] for p in value['history']],[45,50])
        self.assertEqual([p['raw_close'] for p in value['history']],[50,50])
        self.assertEqual([p['account_close'] for p in value['history']],[100,50])
        payload['chart']['result'][0]['events']['splits']['s']['date']=stamp('2025-01-03')
        with patch.object(app,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):value=app.fetch_quote('A.OL')
        self.assertEqual([p['account_close'] for p in value['history']],[50,50])
