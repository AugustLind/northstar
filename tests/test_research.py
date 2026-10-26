import io
import json
import math
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch
import app
import research


def quote(up=True):
    now = time.time()
    values = [100 + i*.1 if up else 150 - i*.1 for i in range(250)]
    return {'price': values[-1], 'currency': 'USD', 'asof': now, 'source': 'fixture', 'turnover20': 2000000, 'turnover_days': 20,
            'history': [{'time': now-(249-i)*86400, 'close': v} for i,v in enumerate(values)]}


def position(**changes):
    return dict(symbol='MSFT', currency='USD', shares=5, below=None, above=None, thesis='', review='', **changes)


class ScreenTests(unittest.TestCase):
    def test_buy_requires_all_conditions(self):
        result = research.screen('MSFT', quote())
        self.assertEqual(result['action'], 'Consider buying')
        self.assertEqual(result['score'], 100)
        self.assertTrue(math.isfinite(result['metrics']['volatility']))

    def test_downtrend_holding_sell_review(self):
        result = research.screen('MSFT', quote(False), position())
        self.assertEqual(result['action'], 'Consider reducing / selling')
        self.assertEqual(result['score'], 0)

    def test_price_level_takes_priority(self):
        p = position()
        p['above'] = 110
        self.assertEqual(research.screen('MSFT', quote(), p)['action'], 'Consider taking profits')
        p['below'], p['above'] = 130, None
        self.assertEqual(research.screen('MSFT', quote(), p)['action'], 'Review sell threshold')

    def test_low_or_unknown_liquidity_never_passes_buy_screen(self):
        q = quote()
        q['turnover20'] = 50000
        self.assertEqual(research.screen('BOUV', q)['action'], 'Wait / low liquidity')
        q['turnover20'] = None
        self.assertEqual(research.screen('BOUV', q)['action'], 'Wait / liquidity unknown')

    def test_us_candidates_are_excluded(self):
        result = research.build_report({'positions': [position()], 'quotes': {'MSFT': quote()}}, ['MSFT'])
        self.assertEqual(result['cards'], [])

    def test_no_trade_signal_for_stale_or_missing_data(self):
        stale = quote()
        stale['asof'] -= 5*86400
        short = quote()
        short['history'] = short['history'][-100:]
        for q in [None, stale, short, {'price': float('nan'), 'asof': time.time()}]:
            self.assertEqual(research.screen('MSFT', q)['action'], 'Insufficient data')

    def test_currency_mismatch(self):
        q = quote()
        q['currency'] = 'NOK'
        self.assertEqual(research.screen('MSFT', q, position())['action'], 'Insufficient data')
        self.assertEqual(research.screen('KOG.OL', quote())['action'], 'Insufficient data')

    def test_collapse_norwegian_alias(self):
        p = position()
        p.update(symbol='KOG', currency='NOK')
        q = quote()
        q['currency'] = 'NOK'
        report = research.build_report({'positions': [p], 'quotes': {'KOG': q}}, ['KOG.OL'])
        self.assertEqual(len(report['cards']), 1)
        self.assertTrue(report['cards'][0]['held'])

    def test_complete_portfolio_for_concentration(self):
        q = quote()
        p = position(); p['currency'] = 'NOK'; p['symbol'] = 'BOUV'
        q['currency'] = 'NOK'
        snapshot = {'positions': [p], 'quotes': {'BOUV': q}}
        report = research.build_report(snapshot, [])
        self.assertTrue(any('concentration' in r for r in report['cards'][0]['reasons']))
        q['asof'] -= 5*86400
        report = research.build_report(snapshot, [])
        self.assertFalse(any('concentration' in r for r in report['cards'][0]['reasons']))
        q['asof'] = time.time()
        snapshot['quotes']['NOK=X'] = {'price': 10, 'currency': 'NOK', 'asof': time.time()}
        report = research.build_report(snapshot, [])
        self.assertTrue(any('concentration' in r for r in report['cards'][0]['reasons']))

    def test_llm_uses_fixed_loopback_and_excludes_chart_payload(self):
        response = io.BytesIO(json.dumps({'response': 'Measured explanation.'}).encode())
        with patch.object(research, 'urlopen', return_value=response) as request:
            text = research.local_answer('qwen2.5:3b', {'cards': [research.screen('MSFT', quote())]}, 'Explain')
        req = request.call_args.args[0]
        self.assertEqual(req.full_url, 'http://127.0.0.1:11434/api/generate')
        payload = json.loads(req.data)
        self.assertNotIn('history', json.loads(payload['prompt'])['report']['cards'][0])
        self.assertFalse(payload['stream'])
        self.assertEqual(text, 'Measured explanation.')

    def test_worker_retains_rules_when_ai_unavailable(self):
        values = {}
        config = dict(research.DEFAULT_SETTINGS, universe=['BOUV.OL'], llm_enabled=True)
        q = quote(); q['currency'] = 'NOK'
        worker = research.ResearchWorker(lambda symbols: [],
            lambda: {'positions': [], 'quotes': {'BOUV.OL': q}},
            lambda k,d=None: values.get(k,d), lambda k,v: values.update({k:v}), lambda: config)
        with patch.object(research, 'local_answer', side_effect=OSError('offline')):
            self.assertTrue(worker.run_once())
        self.assertEqual(values['report']['cards'][0]['action'], 'Consider buying')
        self.assertIn('unavailable', values['report']['llm_status'])
        self.assertFalse(worker.view()['worker']['running'])
        self.assertTrue(worker.view()['worker']['next_run'] > time.time())


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.override = patch.object(app, 'DB', Path(self.tmp.name)/'db.sqlite')
        self.override.start()

    def tearDown(self):
        self.override.stop()
        self.tmp.cleanup()

    def test_settings_validate_and_persist(self):
        app.save_settings(dict(research.DEFAULT_SETTINGS, universe=['bouv','BOUV.OL','NORBT.OL']))
        self.assertEqual(app.settings()['universe'], ['BOUV.OL', 'NORBT.OL'])
        with self.assertRaises(ValueError):
            app.save_settings(dict(research.DEFAULT_SETTINGS, interval_minutes=1))

    def test_previous_universe_migrates_without_deleting_holdings(self):
        app.write_meta('settings', {'universe': ['MSFT', 'EQNR.OL'], 'llm_enabled': True})
        app.save_position(dict(symbol='KOG', currency='NOK', shares=5, cost=306))
        self.assertEqual(app.settings()['universe'], research.DEFAULT_UNIVERSE)
        self.assertTrue(app.settings()['llm_enabled'])
        self.assertNotIn('EQNR.OL', app.settings()['universe'])
        self.assertEqual(app.state()['positions'][0]['symbol'], 'KOG')

    def test_research_and_holdings_share_one_provider_request(self):
        app.save_position(dict(symbol='KOG', currency='NOK', shares=5, cost=306))
        with patch.object(app, 'fetch_quote', return_value={'price': 310, 'currency': 'NOK', 'asof': time.time()}) as fetch:
            self.assertEqual(app.refresh(['KOG.OL']), [])
        self.assertEqual(fetch.call_count, 2)  # KOG.OL plus FX, no duplicate KOG request
        self.assertEqual(app.state()['quotes']['KOG'], app.state()['quotes']['KOG.OL'])

    def test_quote_parser_preserves_timestamp_price_pairs(self):
        fixture = {'chart': {'result': [{'meta': {'regularMarketPrice': 12, 'currency': 'USD', 'regularMarketTime': 3},
          'timestamp': [1,2,3], 'indicators': {'quote': [{'close': [10,None,12]}], 'adjclose': [{'adjclose': [9,None,12]}]}}]}}
        with patch.object(app, 'urlopen', return_value=io.BytesIO(json.dumps(fixture).encode())):
            q = app.fetch_quote('MSFT')
        self.assertEqual(q['history'], [{'time': 1, 'close': 9}, {'time': 3, 'close': 12}])
        self.assertEqual(q['history_basis'], 'Dividend/split adjusted close')


if __name__ == '__main__':
    unittest.main()
