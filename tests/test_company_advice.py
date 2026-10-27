import copy
import unittest
from unittest.mock import patch
import company_data as cd
import advice_state as ads
import daily_board as daily
import portfolio_fit as pf
import trade_plan as tp
from test_trade_plan import NOW,profile,snapshot,card

class CompanyTests(unittest.TestCase):
    def test_exact_symbol_classification_and_expiry(self):
        r=cd.parse({'quotes':[{'symbol':'A.OL','quoteType':'EQUITY','sector':'Technology','longname':'Example'}]},'A.OL',NOW)
        self.assertEqual(r['sector'],'Information technology')
        p=cd.effective(profile(sectors={}),{'A.OL':r},NOW)
        self.assertEqual(p['sectors']['A.OL'],'Information technology')
        self.assertEqual(cd.effective(profile(sectors={'A.OL':'Energy'}),{'A.OL':r},NOW)['sectors']['A.OL'],'Energy')
        self.assertNotIn('A.OL',cd.effective(profile(sectors={}),{'A.OL':r},NOW+31*86400)['sectors'])
        with self.assertRaises(ValueError):cd.parse({'quotes':[{'symbol':'A.US'}]},'A.OL',NOW)

    def test_profile_fallback_validates_exchange_symbol_and_isin(self):
        html='<table><tr><td>Ticker Symbol</td><td>EXA</td></tr><tr><td>Exchange</td><td>Oslo Børs</td></tr><tr><td>Sector</td><td><a>Industrials</a></td></tr><tr><td>ISIN Number</td><td>NO0013536151</td></tr></table>'
        result=cd.parse_profile(html,'EXA.OL',NOW)
        self.assertEqual(result['sector'],'Industrials');self.assertEqual(result['isin'],'NO0013536151')
        with self.assertRaises(ValueError):cd.parse_profile(html.replace('Oslo Børs','NASDAQ'),'EXA.OL',NOW)
        with self.assertRaises(ValueError):cd.parse_profile(html,'OTHER.OL',NOW)

    def test_annual_checks_do_not_grade_stale_or_missing_and_sector_context_matters(self):
        metrics={k:{'value':v,'period':'2025-12-31'} for k,v in {'revenue_growth':3,'net_income':-2,'free_cash_flow':1,'operating_cash_flow':2,'operating_margin':5,'net_cash':3,'equity':2}.items()}
        f={'status':'available','metrics':metrics,'period':'2025-12-31'}
        self.assertEqual(cd.assessment({**f,'status':'stale'},'Energy')['covered'],0)
        self.assertEqual(cd.assessment(f,'Financials')['covered'],3)
        self.assertEqual(cd.assessment(f,'Energy')['covered'],7)
        self.assertIn('sector unknown',cd.assessment(f)['label'])
        self.assertEqual(cd.assessment({'status':'unavailable','metrics':{}},'Energy')['covered'],0)

    def test_share_class_limits_are_combined(self):
        s={'positions':[{'symbol':'WWI.OL','currency':'NOK','shares':10},{'symbol':'WWIB.OL','currency':'NOK','shares':10}],
           'quotes':{'WWI.OL':{'price':100,'currency':'NOK','asof':NOW},'WWIB.OL':{'price':100,'currency':'NOK','asof':NOW}}}
        p=profile(cash_nok=0,max_stock_pct=20,reserve_pct=0,sectors={'WWI.OL':'Industrials','WWIB.OL':'Industrials'})
        v=tp.build(s,{'generated':NOW,'cards':[]},p,NOW)
        self.assertEqual(sum(r['sell_shares'] for r in v['holdings']),16)
        self.assertEqual(len(pf.context(s,p,NOW)['issuer_exposure']),1)

    def test_peer_comparison_requires_three_same_year_companies(self):
        f={'status':'available','metrics':{'annual_pe_proxy':{'value':10,'period':'2025-12-31'}}}
        records={s:{} for s in ('B.OL','C.OL','D.OL')};sectors={s:'Energy' for s in ('A.OL','B.OL','C.OL','D.OL')}
        with patch('fundamentals.analyse',return_value=f):
            result=cd.peer_valuation('A.OL',f,records,{},sectors,NOW)
        self.assertEqual(result['median_annual_pe_proxy'],10)
        with patch('fundamentals.analyse',return_value={**f,'metrics':{'annual_pe_proxy':{'value':10,'period':'2024-12-31'}}}):
            self.assertIsNone(cd.peer_valuation('A.OL',f,records,{},sectors,NOW)['median_annual_pe_proxy'])

class AdviceTests(unittest.TestCase):
    def test_same_session_refresh_is_not_confirmation(self):
        report={'cards':[card()]};state=ads.observe(report,{},NOW)
        report['cards'][0]['asof']+=60
        state=ads.observe(report,state,NOW+60)
        self.assertEqual(len(state['B.OL']['sessions']),1)
        report['cards'][0]['asof']+=86400
        state=ads.observe(report,state,NOW+86460)
        self.assertEqual(len(state['B.OL']['sessions']),2)

    def test_wait_confirmation_and_recorded_trade_cooldown(self):
        s=snapshot();s['signal_state']={}
        p=profile(confirm_sessions=2,signal_wait_hours=24,trade_cooldown_days=7)
        self.assertIn('Waiting',ads.gate('B.OL','buy',s,p,NOW))
        s['signal_state']={'B.OL':{'intent':'buy','since':NOW-2*86400,'sessions':['a','b']}}
        self.assertIsNone(ads.gate('B.OL','buy',s,p,NOW))
        s['last_trades']={'B.OL':NOW-86400}
        self.assertIn('cooldown',ads.gate('B.OL','buy',s,p,NOW))
        self.assertEqual(tp.build(s,{'generated':NOW,'cards':[card()]},p,NOW)['buys'],[])

    def test_small_changes_keep_alert_id_until_cumulative_change_is_large(self):
        def plan(n):return {'buys':[{'symbol':'A.OL','buy_shares':n}], 'holdings':[]}
        state,rows=ads.differences(plan(100),{},20,NOW)
        oldid=state['A.OL']['change_id']
        state,rows=ads.differences(plan(101),state,20,NOW+1)
        self.assertEqual(rows[0]['change'],'Unchanged');self.assertEqual(state['A.OL']['change_id'],oldid)
        state,rows=ads.differences(plan(120),state,20,NOW+2)
        self.assertEqual(rows[0]['change'],'Updated');self.assertNotEqual(state['A.OL']['change_id'],oldid)
        state,rows=ads.differences(plan(0),state,20,NOW+3)
        _,rows=ads.differences({'buys':[],'holdings':[]},state,20,NOW+4)
        self.assertEqual(rows[0]['change'],'Withdrawn')

    def test_alert_merge_is_deduplicated_and_preserves_read_state(self):
        row={'id':'a','title':'Review','observed':NOW,'priority':80}
        old=daily.merge_alerts([], [row],NOW);old[0]['read']=True
        new=daily.merge_alerts(old,[{**row,'title':'Updated'}],NOW+60)
        self.assertEqual(len(new),1);self.assertTrue(new[0]['read']);self.assertEqual(new[0]['first_seen'],NOW)

    def test_ledger_mismatch_withholds_counts(self):
        s=snapshot(10);s['ledger_reconciled']=False
        v=tp.build(s,{'generated':NOW,'cards':[card()]},profile(),NOW)
        self.assertEqual(v['buys'],[]);self.assertIsNone(v['holdings'][0]['sell_shares'])
