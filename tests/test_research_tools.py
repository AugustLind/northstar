"""Numerical, missing-data and temporal-isolation checks for research tools."""
import copy
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import company_data
import email_alerts
import financial_analysis
import fundamentals
import portfolio_fit as pf
import portfolio_risk as risk
import research
import stock_summary
import validation
from test_fundamentals import payload, NOW
from test_validation import quotes as experiment_quotes


def market(returns,currency='NOK'):
    close=100;h=[{'time':NOW-len(returns)*86400,'close':close}]
    for i,r in enumerate(returns):
        close*=1+r;h.append({'time':NOW-(len(returns)-i-1)*86400,'close':close})
    return {'history':h,'price':close,'currency':currency,'asof':NOW,'fetched':NOW}

def snapshot(a=None,b=None,cash=200):
    a=a or market([.01,-.01]*60);b=b or market([.02,-.02]*60)
    return {'positions':[{'symbol':'A.OL','currency':'NOK','shares':300/a['price']},{'symbol':'B.OL','currency':'NOK','shares':500/b['price']}],
            'quotes':{'A.OL':a,'B.OL':b},'portfolio_preferences':pf.preferences({'cash_nok':cash,'sectors':{'A.OL':'Energy','B.OL':'Industrials'}})}

class PortfolioRiskTests(unittest.TestCase):
    def test_exact_covariance_contributions_and_cash_weights(self):
        s=snapshot();v=risk.view(s,s['portfolio_preferences'],NOW)
        self.assertEqual(v['status'],'available');self.assertEqual(v['observations'],120)
        annual=math.sqrt(risk.covariance([.01,-.01]*60,[.01,-.01]*60)*252)*100
        self.assertAlmostEqual(v['volatility_pct'],1.3*annual)
        self.assertAlmostEqual(sum(r['risk_share_pct'] for r in v['risk_contributions']),100)
        self.assertAlmostEqual(v['risk_contributions'][0]['risk_share_pct'],.3/1.3*100)
        self.assertAlmostEqual(v['correlations'][0]['values'][1],1)
        self.assertAlmostEqual(v['scenarios'][0]['change_nok'],-160)
        json.dumps(v,allow_nan=False)

    def test_missing_holding_cannot_create_partial_portfolio_risk(self):
        s=snapshot();s['quotes']['B.OL']['history']=s['quotes']['B.OL']['history'][-20:]
        v=risk.view(s,s['portfolio_preferences'],NOW)
        self.assertEqual(v['status'],'unavailable');self.assertIsNone(v['volatility_pct'])
        self.assertEqual(v['risk_contributions'],[])
        self.assertTrue(v['scenarios'])
        s['quotes']['B.OL']['asof']=NOW-5*86400
        self.assertEqual(risk.view(s,s['portfolio_preferences'],NOW)['scenarios'],[])

    def test_missing_day_never_bridges_other_asset_intervals(self):
        s=snapshot();del s['quotes']['B.OL']['history'][40]
        v=risk.view(s,s['portfolio_preferences'],NOW)
        self.assertEqual(v['observations'],118)

    def test_usd_conversion_requires_both_fx_endpoints(self):
        fx=market([.01,-.01]*40);usd=market([0]*80,'USD')
        s={'positions':[{'symbol':'US','currency':'USD','shares':1}], 'quotes':{'US':usd,'NOK=X':fx}}
        p=pf.preferences({'cash_nok':0});v=risk.view(s,p,NOW)
        self.assertEqual(v['observations'],80)
        expected=math.sqrt(risk.covariance([.01,-.01]*40,[.01,-.01]*40)*252)*100
        self.assertAlmostEqual(v['volatility_pct'],expected)
        self.assertAlmostEqual(v['scenarios'][2]['change_pct'],-28)
        del s['quotes']['NOK=X']['history'][40]
        self.assertEqual(risk.view(s,p,NOW)['observations'],78)

    def test_flat_cash_and_invalid_shocks(self):
        s=snapshot(market([0]*80),market([0]*80));v=risk.view(s,s['portfolio_preferences'],NOW)
        self.assertEqual(v['volatility_pct'],0);self.assertIsNone(v['risk_contributions'][0]['risk_share_pct'])
        self.assertIsNone(v['correlations'][0]['values'][0])
        self.assertEqual(risk.view({'positions':[],'quotes':{}},pf.preferences({'cash_nok':100}),NOW)['status'],'cash_only')
        for value in (float('nan'),-101,101,True):
            with self.assertRaises(ValueError):risk.view(s,s['portfolio_preferences'],NOW,stock_shock=value)

class AnnualAnalysisTests(unittest.TestCase):
    def record(self):return fundamentals.parse(payload(),'A.OL',NOW)

    def test_dated_trends_and_cash_flow_derivation(self):
        r=self.record();annual=financial_analysis.timeline(r)
        self.assertEqual(annual['free_cash_flow'][0]['value'],150)
        self.assertTrue(annual['free_cash_flow'][0]['derived'])
        self.assertEqual(annual['operating_margin'][0]['value'],15)
        self.assertAlmostEqual(annual['revenue_growth'][0]['value'],20)
        self.assertIsNotNone(financial_analysis.trends(annual)[0]['cagr_pct'])
        r['series']['capital_expenditure'][0]['currency']='USD'
        self.assertNotIn('free_cash_flow',financial_analysis.timeline(r))
        r['series']['operating_income'][0]['period']='2024-12-31'
        self.assertEqual([m['period'] for m in financial_analysis.timeline(r)['operating_margin']],['2024-12-31'])
        self.assertEqual(financial_analysis.timeline(r)['operating_margin'][0]['value'],18)

    def test_no_growth_across_gaps_or_mixed_currencies(self):
        r=self.record();r['series']['revenue'][1]['period']='2022-12-31'
        self.assertNotIn('revenue_growth',financial_analysis.timeline(r))
        r=self.record();r['series']['revenue'][1]['currency']='USD'
        self.assertNotIn('revenue_growth',financial_analysis.timeline(r))
        self.assertFalse(any(x['metric']=='revenue' for x in financial_analysis.trends(financial_analysis.timeline(r))))

    def test_sector_peers_require_three_other_issuers_and_same_period(self):
        records={s:self.record() for s in ['A.OL','B.OL','C.OL','D.OL']}
        quotes={s:{'price':30,'currency':'NOK','asof':NOW} for s in records};sectors={s:'Energy' for s in records}
        subject=fundamentals.analyse(records['A.OL'],quotes['A.OL'],NOW)
        v=financial_analysis.peers('A.OL',subject,records,quotes,sectors,NOW)
        pe=next(r for r in v['metrics'] if r['metric']=='annual_pe_proxy')
        self.assertEqual(pe['peer_count'],3);self.assertEqual(pe['median'],15);self.assertEqual(pe['percentile'],50)
        sectors['D.OL']='Industrials'
        pe=next(r for r in financial_analysis.peers('A.OL',subject,records,quotes,sectors,NOW)['metrics'] if r['metric']=='annual_pe_proxy')
        self.assertIsNone(pe['median']);self.assertIsNone(pe['percentile'])
        records['C.OL']['fetched']=NOW-9*86400
        self.assertEqual(next(r for r in financial_analysis.peers('A.OL',subject,records,quotes,sectors,NOW)['metrics'] if r['metric']=='annual_pe_proxy')['peer_count'],1)

class ExperimentDiagnosticsTests(unittest.TestCase):
    def test_sale_commission_applies_once_to_a_sell_order(self):
        q=experiment_quotes()
        for p in q['A.OL']['history']:p['close']=100
        def screen(s,q,**kw):
            return {'symbol':s,'composite':50,'rank_eligible':len(q['history'])<250,
                    'action':'Consider buying' if len(q['history'])<250 else 'Consider reducing / selling'}
        with patch('research.screen',side_effect=screen):v=validation.evaluate(q,['A.OL'],selling_fee_nok=50)
        self.assertEqual(v['buy_orders'],1);self.assertEqual(v['sell_orders'],1)
        self.assertEqual(v['selling_fees_nok'],50);self.assertAlmostEqual(v['return_pct'],-.129)
        self.assertGreater(v['one_way_turnover_pct'],0)
        with self.assertRaises(ValueError):validation.evaluate(q,['A.OL'],selling_fee_nok=float('nan'))

    def test_holdout_selection_cannot_use_holdout_results(self):
        rows=[{'max_positions':20,'rebalance_months':1,'training':{'sharpe_zero_rate':1,'return_pct':5},'holdout':{'return_pct':1000}},
              {'max_positions':10,'rebalance_months':1,'training':{'sharpe_zero_rate':2,'return_pct':4},'holdout':{'return_pct':-99}}]
        self.assertIs(validation.choose_variant(rows),rows[1])
        rows[0]['holdout']['return_pct']=1e12
        self.assertIs(validation.choose_variant(rows),rows[1])

    def test_suite_dated_holdout_cache_and_sensitivity(self):
        seen=[]
        def screen(s,q,**kw):
            self.assertLessEqual(q['history'][-1]['time'],kw['as_of'])
            key=(s,q['history'][-1]['time'],bool(kw['position']));self.assertNotIn(key,seen);seen.append(key)
            return {'symbol':s,'rank_eligible':True,'composite':50,'action':'Consider buying'}
        with patch('research.screen',side_effect=screen):v=validation.evaluate_suite(experiment_quotes(650),['A.OL'])
        r=v['robustness'];self.assertEqual(len(r['variants']),4);self.assertEqual(len(r['cost_sensitivity']),2)
        self.assertLess(r['training']['to'],r['holdout']['from'])
        self.assertEqual(r['holdout_curve'][0]['close'],1)
        self.assertGreaterEqual(r['holdout']['sessions'],20)
        self.assertGreaterEqual(r['cost_sensitivity'][1]['total_costs_nok'],r['cost_sensitivity'][0]['total_costs_nok'])
        json.dumps(v,allow_nan=False)

class StockSummaryTests(unittest.TestCase):
    @patch('time.time',return_value=NOW)
    def test_saved_liquidity_floor_and_stale_gates(self,clock):
        from test_research import quote
        q=quote();q['currency']='NOK'
        s={'positions':[],'quotes':{'A.OL':q},'fundamentals':{},'portfolio_preferences':pf.preferences({'cash_nok':10000,'purchase_nok':1000,'sectors':{'A.OL':'Energy'}})}
        report=research.build_report(s,['A.OL'],min_turnover_nok=5000000)
        v=stock_summary.build('A.OL',s,report,s['portfolio_preferences'])
        self.assertFalse(v['qualifies']);self.assertFalse(v['checks'][-1]['passes'])
        q['currency']='USD'
        self.assertFalse(stock_summary.build('A.OL',s,report,s['portfolio_preferences'])['current'])
        q['currency']='NOK'
        report['generated']-=2*86400
        v=stock_summary.build('A.OL',s,report,s['portfolio_preferences'])
        self.assertFalse(v['current']);self.assertTrue(all(c['passes'] is None for c in v['checks']))
        self.assertEqual(v['portfolio']['buy_shares'],0)

class EventParsingTests(unittest.TestCase):
    def test_provider_events_keep_provenance_and_reject_invalid_amounts(self):
        import io
        content={'chart':{'result':[{'meta':{'regularMarketPrice':100,'currency':'NOK','regularMarketTime':NOW},
            'timestamp':[NOW-86400,NOW],'indicators':{'quote':[{'close':[99,100]}]},
            'events':{'dividends':{'a':{'date':NOW-86400,'amount':2},'b':{'date':NOW,'amount':-1}},
                      'splits':{'s':{'date':NOW,'numerator':2,'denominator':1}}}}]}}
        with patch.object(app,'urlopen',return_value=io.BytesIO(json.dumps(content).encode())):
            q=app.fetch_quote('A.OL')
        self.assertEqual([e['kind'] for e in q['events']],['dividend','split'])
        self.assertTrue(all(e['source_url'].startswith('https://finance.yahoo.com/quote/A.OL/history/') for e in q['events']))
        self.assertEqual(q['events_version'],1)

import test_hosting as hosting

class ResearchEndpointTests(unittest.TestCase):
    setUp=hosting.HostingTests.setUp
    tearDown=hosting.HostingTests.tearDown
    request=hosting.HostingTests.request

    def test_private_endpoints_and_boolean_public_health(self):
        paths=['/api/system-status','/api/portfolio-risk','/api/stock-summary?symbol=A.OL','/api/email/history']
        for path in paths:self.assertEqual(self.request('GET',path)['status'],401,path)
        self.assertEqual(self.request('GET','/api/health')['body'],{'ok':True})
        headers={'Authorization':'Bearer test-key'}
        result=self.request('GET','/api/system-status',headers)
        self.assertEqual(result['status'],200)
        self.assertEqual(len(result['body']['components']),6)
        self.assertIn('quote_coverage',result['body'])
        self.assertEqual(self.request('GET','/api/portfolio-risk?stock_shock=nan',headers)['status'],400)
        self.assertEqual(self.request('GET','/api/stock-summary?symbol=invalid/path',headers)['status'],400)

    def test_email_history_redacts_secrets_payload_and_provider_text(self):
        from test_email_alerts import environment
        values=environment();worker=email_alerts.Worker(app.connect,app.read_meta,app.write_meta,lambda:(None,{}),values)
        with app.connect() as db:
            email_alerts.schema(db)
            db.execute("INSERT INTO email_outbox (id,target,kind,payload,status,created,updated,last_error) VALUES (?,?, 'test',?,'pending',1,1,?)",('id',worker.config()['target'],json.dumps({'private':'private-password'}),'sender@example.com private-password'))
        with patch.object(app,'EMAIL_WORKER',worker):
            result=self.request('GET','/api/system-status',{'Authorization':'Bearer test-key'})
        body=json.dumps(result['body'])
        for secret in ('private-password','sender@example.com','investor@example.com','smtp.example.com'):
            self.assertNotIn(secret,body)
        self.assertEqual(len(result['body']['email_history']),1)
        self.assertIn('Delivery attempt failed',result['body']['email_history'][0]['last_error'])

    def test_default_validation_dispatches_robustness_without_touching_real_records(self):
        class ImmediateThread:
            def __init__(self,**kwargs):self.target=kwargs['target']
            def start(self):self.target()
        headers={'Authorization':'Bearer test-key','Content-Type':'application/json'}
        with patch('app.threading.Thread',ImmediateThread),patch('validation.evaluate_suite',return_value={'generated':123}) as runner:
            response=self.request('POST','/api/validation',headers,{'selling_fee_nok':25})
        self.assertTrue(response['body']['queued'])
        self.assertEqual(runner.call_args.kwargs['selling_fee_nok'],25)
        self.assertEqual(app.state()['positions'],[])
        self.assertEqual(self.request('POST','/api/validation',headers,{'robustness':'true'})['status'],400)

class AdditionalResearchEdgeTests(unittest.TestCase):
    def test_hedge_contributions_can_be_negative_and_still_sum_to_total(self):
        s=snapshot(market([.01,-.01]*60),market([-.01,.01]*60))
        v=risk.view(s,s['portfolio_preferences'],NOW)
        shares=[r['risk_share_pct'] for r in v['risk_contributions']]
        self.assertLess(shares[0],0);self.assertGreater(shares[1],100)
        self.assertAlmostEqual(sum(shares),100)
        self.assertAlmostEqual(sum(r['volatility_contribution_pct'] for r in v['risk_contributions']),v['volatility_pct'])

    def test_historical_issuer_events_remain_markable_but_not_upcoming(self):
        import announcements
        import datetime as dt
        past=dt.datetime.fromtimestamp(NOW-86400,dt.timezone.utc).date().isoformat()
        future=dt.datetime.fromtimestamp(NOW+86400,dt.timezone.utc).date().isoformat()
        events=[{'date':date,'symbol':'A.OL','label':'Annual financial-report event','source_url':'https://newsweb.oslobors.no/message/1'} for date in (past,future)]
        item={'id':'1','symbol':'A.OL','title':'Financial calendar','published':NOW-3600,'classification':{'kind':'calendar','priority':1},'events':events,'calendar_checked':NOW}
        result=announcements.view({'fetched':NOW,'items':[item]},['A.OL'],NOW)
        self.assertEqual([e['date'] for e in result['chart_events']],[past,future])
        self.assertEqual([e['date'] for e in result['events']],[future])
        item['corrected_by']=2
        self.assertEqual(announcements.view({'fetched':NOW,'items':[item]},['A.OL'],NOW)['chart_events'],[])

    def test_peer_share_classes_count_as_one_issuer(self):
        records={s:fundamentals.parse(payload(),s,NOW) for s in ('A.OL','WWI.OL','WWIB.OL','C.OL')}
        quotes={s:{'price':30,'currency':'NOK','asof':NOW} for s in records};sectors={s:'Energy' for s in records}
        subject=fundamentals.analyse(records['A.OL'],quotes['A.OL'],NOW)
        values=financial_analysis.peers('A.OL',subject,records,quotes,sectors,NOW)['metrics']
        self.assertEqual(next(r for r in values if r['metric']=='annual_pe_proxy')['peer_count'],2)
        self.assertIsNone(next(r for r in values if r['metric']=='annual_pe_proxy')['median'])

    @patch('time.time',return_value=NOW)
    def test_annual_weaknesses_reach_stock_summary_without_changing_policy(self,clock):
        from test_research import quote
        q=quote();q['currency']='NOK';record=fundamentals.parse(payload(),'A.OL',NOW)
        record['series']['operating_cash_flow'][0]['value']=-20
        profile=pf.preferences({'cash_nok':10000,'sectors':{'A.OL':'Energy'}})
        s={'positions':[],'quotes':{'A.OL':q},'fundamentals':{'A.OL':record},'portfolio_preferences':profile}
        report=research.build_report(s,['A.OL'])
        v=stock_summary.build('A.OL',s,report,profile)
        self.assertTrue(any('operating cash flow was negative' in text for text in v['risks']))
        self.assertEqual(v['qualifies'],report['cards'][0]['rank_eligible'])
