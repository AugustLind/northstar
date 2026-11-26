import copy
import unittest
from unittest.mock import patch
from northstar import company_data as cd
from northstar import advice_state as ads
from northstar import daily_board as daily
from northstar import portfolio_fit as pf
from northstar import trade_plan as tp
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
        v=tp.build(s,{'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[]},p,NOW)
        self.assertEqual(sum(r['sell_shares'] for r in v['holdings']),16)
        self.assertEqual(len(pf.context(s,p,NOW)['issuer_exposure']),1)

    def test_peer_comparison_requires_three_same_year_companies(self):
        f={'status':'available','metrics':{'annual_pe_proxy':{'value':10,'period':'2025-12-31'}}}
        records={s:{} for s in ('B.OL','C.OL','D.OL')};sectors={s:'Energy' for s in ('A.OL','B.OL','C.OL','D.OL')}
        with patch('northstar.fundamentals.analyse',return_value=f):
            result=cd.peer_valuation('A.OL',f,records,{},sectors,NOW)
        self.assertEqual(result['median_annual_pe_proxy'],10)
        with patch('northstar.fundamentals.analyse',return_value={**f,'metrics':{'annual_pe_proxy':{'value':10,'period':'2024-12-31'}}}):
            self.assertIsNone(cd.peer_valuation('A.OL',f,records,{},sectors,NOW)['median_annual_pe_proxy'])

class AdviceTests(unittest.TestCase):
    def holding_advice(self,snapshot,report,preferences,now=NOW):
        snapshot.update(portfolio_preferences=preferences,
                        portfolio_context=pf.context(snapshot,preferences,now))
        plan=tp.build(snapshot,report,preferences,now)
        return daily.build(snapshot,report,plan,{},None,now)['holding_assessments'][0]['advice']

    def test_saved_price_change_requires_fresh_confirmation_sessions(self):
        s=snapshot(10)
        p=profile(confirm_sessions=2,signal_wait_hours=0)
        s['positions'][0]['below']=100
        first={**card('A.OL',action='Review sell threshold'),'review_price':100,'asof':NOW-86400}
        report={'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[first]}
        s['signal_state']=ads.observe(report,{},NOW-86400)
        report['cards']=[{**first,'asof':NOW}]
        s['signal_state']=ads.observe(report,s['signal_state'],NOW)
        self.assertEqual(self.holding_advice(s,report,p)['review_price'],100)

        s['positions'][0]['below']=105
        s['quotes']['A']['price']=103
        self.assertEqual(self.holding_advice(s,report,p)['label'],'Insufficient data')
        report['cards']=[{**first,'asof':NOW,'price':103,'review_price':105}]
        s['signal_state']=ads.observe(report,s['signal_state'],NOW)
        self.assertEqual(self.holding_advice(s,report,p)['label'],'Insufficient data')
        later=NOW+86400
        report['generated']=later
        report['cards'][0]['asof']=later
        s['quotes']['A']['asof']=later
        s['signal_state']=ads.observe(report,s['signal_state'],later)
        self.assertEqual(self.holding_advice(s,report,p,later)['review_price'],105)

    def test_quote_crossing_saved_price_after_report_withholds_hold(self):
        s=snapshot(10)
        s['positions'][0]['below']=95
        p=profile()
        report={'generated':NOW,'policy_version':tp.policy.VERSION,
                'cards':[card('A.OL',action='Hold / monitor')]}
        self.assertEqual(self.holding_advice(s,report,p)['label'],'Hold')

        s['quotes']['A']['price']=90
        advice=self.holding_advice(s,report,p)
        self.assertEqual(advice['label'],'Insufficient data')
        self.assertIn('confirm the current saved review price',advice['reason'])

    def test_reserve_breach_keeps_sell_review_when_reconciliation_blocks_sizing(self):
        s=snapshot(10)
        p=profile(cash_nok=0,reserve_pct=25)
        report={'generated':NOW,'policy_version':tp.policy.VERSION,
                'cards':[card('A.OL',action='Hold / monitor')]}
        self.assertEqual(self.holding_advice(s,report,p)['shares'],3)

        s['ledger_reconciled']=False
        advice=self.holding_advice(s,report,p)
        self.assertEqual(advice['label'],'Sell review')
        self.assertIn('25.0% cash reserve',advice['reason'])
        self.assertIsNone(advice['shares'])
        self.assertIn('Reconcile holdings and cash',advice['sizing_blocker'])

    def test_holding_advice_explains_multiple_limits_that_add_shares(self):
        s=snapshot(10)
        p=profile(cash_nok=0,max_stock_pct=40,max_sector_pct=20)
        report={'generated':NOW,'policy_version':tp.policy.VERSION,
                'cards':[card('A.OL',action='Hold / monitor')]}
        advice=self.holding_advice(s,report,p)
        self.assertEqual(advice['shares'],8)
        self.assertEqual(advice['percent'],80)
        self.assertIn('40.0% position limit',advice['reason'])
        self.assertIn('20.0% sector limit',advice['reason'])

    def test_daily_board_preserves_existing_holding_policy_assessments_and_marks_stale_evidence(self):
        s=snapshot(4);p=profile();s.update(portfolio_preferences=p,portfolio_context=pf.context(s,p,NOW),fundamentals={},signal_state={},last_trades={})
        held=card('A.OL',1,'Hold / monitor');held['reasons']=['Existing technical screen reason.']
        report={'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[held],'top20':[],'coverage':{'analysed':1,'requested':1}}
        plan=tp.build(s,report,p,NOW)
        current=daily.build(s,report,plan,{},None,NOW)['holding_assessments'][0]
        self.assertEqual(current['status'],'current')
        self.assertEqual(current['action'],'Hold / monitor')
        self.assertEqual(current['reasons'],['Existing technical screen reason.'])
        stale_report={**report,'generated':NOW-2*86400}
        stale_plan=tp.build(s,stale_report,p,NOW)
        stale=daily.build(s,stale_report,stale_plan,{},None,NOW)['holding_assessments'][0]
        self.assertEqual(stale['status'],'stale')
        self.assertEqual(stale['action'],'Hold / monitor')

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
        s['signal_state']={'B.OL':{'intent':'buy','since':NOW-2*86400,'sessions':['a','b'],'policy_version':tp.policy.VERSION}}
        self.assertIsNone(ads.gate('B.OL','buy',s,p,NOW))
        s['last_trades']={'B.OL':NOW-86400}
        self.assertIn('cooldown',ads.gate('B.OL','buy',s,p,NOW))
        self.assertEqual(tp.build(s,{'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[card()]},p,NOW)['buys'],[])

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
        v=tp.build(s,{'generated':NOW,'policy_version':tp.policy.VERSION,'cards':[card()]},profile(),NOW)
        self.assertEqual(v['buys'],[]);self.assertIsNone(v['holdings'][0]['sell_shares'])
