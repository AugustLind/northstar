import copy
import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
import app
import fundamentals as f
import research
from test_research import quote

NOW=dt.datetime(2026,10,27,tzinfo=dt.timezone.utc).timestamp()


def observation(value, period='2025-12-31', currency='NOK'):
    return {'asOfDate':period,'periodType':'12M','currencyCode':currency,'reportedValue':{'raw':value}}


def payload():
    fields={'TotalRevenue':[observation(1200),observation(1000,'2024-12-31')],
            'OperatingIncome':[observation(180)],'NetIncome':[observation(120)],
            'OperatingCashFlow':[observation(200)],'CapitalExpenditure':[observation(-50)],
            'TotalDebt':[observation(300)],'CashCashEquivalentsAndShortTermInvestments':[observation(100)],
            'StockholdersEquity':[observation(600)],'DilutedEPS':[observation(2)],
            'DilutedAverageShares':[observation(110,currency=None),observation(100,'2024-12-31',None)]}
    return {'timeseries':{'result':[{'annual'+key:value} for key,value in fields.items()]}}


class FinancialCalculationTests(unittest.TestCase):
    def setUp(self):
        self.record=f.parse(payload(),'KOG.OL',NOW)
        self.quote={'price':30,'currency':'NOK','asof':NOW}

    def test_matching_period_ratios_and_cash_flow(self):
        result=f.analyse(self.record,self.quote,NOW);metrics=result['metrics']
        self.assertEqual(result['status'],'available')
        self.assertAlmostEqual(metrics['revenue_growth']['value'],20)
        self.assertEqual(metrics['operating_margin']['value'],15)
        self.assertEqual(metrics['net_margin']['value'],10)
        self.assertEqual(metrics['free_cash_flow']['value'],150)
        self.assertEqual(metrics['net_cash']['value'],-200)
        self.assertEqual(metrics['debt_to_equity']['value'],.5)
        self.assertEqual(metrics['annual_pe_proxy']['value'],15)
        self.assertAlmostEqual(metrics['share_count_change']['value'],10)
        self.assertFalse(result['changes_ranking'])
        self.assertIn('splits',metrics['share_count_change']['note'].lower())

    def test_positive_capex_uses_absolute_spend(self):
        self.record['series']['capital_expenditure'][0]['value']=50
        self.assertEqual(f.analyse(self.record,self.quote,NOW)['metrics']['free_cash_flow']['value'],150)

    def test_reported_fcf_takes_priority_over_derived_value(self):
        self.record['series']['free_cash_flow']=[{'value':160,'period':'2025-12-31','currency':'NOK'}]
        self.assertEqual(f.analyse(self.record,self.quote,NOW)['metrics']['free_cash_flow']['value'],160)

    def test_missing_and_zero_are_different(self):
        self.record['series']['operating_cash_flow'][0]['value']=0
        self.record['series']['net_income']=[]
        result=f.analyse(self.record,self.quote,NOW)
        self.assertEqual(result['metrics']['operating_cash_flow']['value'],0)
        self.assertNotIn('net_income',result['metrics'])
        self.assertIn('net_income',result['missing'])
        self.assertEqual(result['status'],'partial')

    def test_currency_mismatch_never_produces_margins_or_valuation(self):
        self.record['series']['operating_income'][0]['currency']='USD'
        self.quote['currency']='USD'
        result=f.analyse(self.record,self.quote,NOW)
        self.assertNotIn('operating_margin',result['metrics'])
        self.assertNotIn('annual_pe_proxy',result['metrics'])

    def test_unknown_currency_never_produces_ratios(self):
        self.record['series']['revenue'][0]['currency']=None
        self.assertNotIn('operating_margin',f.analyse(self.record,self.quote,NOW)['metrics'])

    def test_mismatched_dates_and_skipped_years_do_not_mix(self):
        self.record['series']['debt'][0]['period']='2024-12-31'
        self.record['series']['revenue'][1]['period']='2023-12-31'
        result=f.analyse(self.record,self.quote,NOW)
        for metric in ['net_cash','debt_to_equity','revenue_growth']:
            self.assertNotIn(metric,result['metrics'])

    def test_negative_eps_and_equity_do_not_produce_misleading_ratios(self):
        self.record['series']['diluted_eps'][0]['value']=-2
        self.record['series']['equity'][0]['value']=-100
        result=f.analyse(self.record,self.quote,NOW)
        self.assertNotIn('annual_pe_proxy',result['metrics'])
        self.assertNotIn('debt_to_equity',result['metrics'])
        self.assertTrue(any('non-positive' in s for s in result['signals']))

    def test_stale_quote_and_financial_record_are_labelled(self):
        self.quote['asof']=NOW-5*86400
        self.assertNotIn('annual_pe_proxy',f.analyse(self.record,self.quote,NOW)['metrics'])
        self.record['fetched']=NOW-8*86400
        self.assertEqual(f.analyse(self.record,self.quote,NOW)['status'],'stale')

    def test_future_nonannual_and_nonfinite_rows_are_rejected(self):
        data=payload();data['timeseries']['result'][0]['annualTotalRevenue'] += [
            observation(999,'2027-12-31'),observation(float('nan'),'2023-12-31'),
            {**observation(999,'2026-06-30'),'periodType':'3M'}]
        result=f.parse(data,'KOG.OL',NOW)
        self.assertEqual(len(result['series']['revenue']),2)
        with self.assertRaises(ValueError):
            f.parse({'timeseries':{'result':[]}},'KOG.OL',NOW)

    def test_canonical_rejects_urls_and_other_exchanges(self):
        self.assertEqual(f.canonical('kog'),'KOG.OL')
        for value in ['', '../data', 'https://example.com','MSFT.US']:
            with self.assertRaises(ValueError): f.canonical(value)

    def test_financials_do_not_change_technical_rank(self):
        market=quote();market['currency']='NOK'
        snap={'positions':[],'quotes':{'KOG.OL':market}}
        before=research.build_report(snap,['KOG.OL'])
        snap['fundamentals']={'KOG.OL':self.record}
        after=research.build_report(snap,['KOG.OL'])
        self.assertEqual(before['top20'],after['top20'])
        self.assertEqual(before['cards'][0]['composite'],after['cards'][0]['composite'])
        self.assertIn('fundamentals',after['cards'][0])


class FinancialWorkerTests(unittest.TestCase):
    def test_failure_retains_last_success_and_original_fetch_date(self):
        old=f.parse(payload(),'KOG.OL',NOW-2*86400)
        values={'fundamentals:KOG.OL':old}
        worker=f.Worker(lambda k,d=None:values.get(k,d),lambda k,v:values.update({k:v}),lambda:['KOG.OL'])
        worker.request('KOG.OL')
        with patch.object(f,'fetch',side_effect=HTTPError('https://example.com',429,'rate',None,None)):
            worker.run_scan()
        saved=values['fundamentals:KOG.OL']
        self.assertEqual(saved['series'],old['series'])
        self.assertEqual(saved['fetched'],old['fetched'])
        self.assertIn('rate limit',saved['error'])
        self.assertFalse(values['fundamentals_progress']['running'])
        self.assertEqual(values['fundamentals_progress']['done'],1)

    def test_recent_data_is_not_fetched_again(self):
        old=f.parse(payload(),'KOG.OL')
        values={'fundamentals:KOG.OL':old}
        worker=f.Worker(lambda k,d=None:values.get(k,d),lambda k,v:values.update({k:v}),lambda:['KOG.OL'])
        with patch.object(f,'fetch') as fetch:
            worker.run_scan()
            fetch.assert_not_called()
        self.assertEqual(values['fundamentals_progress']['done'],1)

    def test_persisted_financial_view_uses_private_database(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(app,'DB',Path(tmp)/'db.sqlite'):
            app.write_meta('fundamentals:KOG.OL',f.parse(payload(),'KOG.OL'))
            result=app.financial_view('KOG')
            self.assertEqual(result['symbol'],'KOG.OL')
            self.assertEqual(result['metrics']['revenue']['value'],1200)
            self.assertIn('fundamentals',app.state(True))
            self.assertNotIn('fundamentals',app.state())
