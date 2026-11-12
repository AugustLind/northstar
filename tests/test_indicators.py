import copy
import math
import time
import unittest
from unittest.mock import patch
import app
import indicators
import research
import universe
from test_research import quote


class MultiAnalysisTests(unittest.TestCase):
    def test_rsi_extremes_and_flat_data(self):
        self.assertEqual(indicators.rsi([100]*30),50)
        self.assertEqual(indicators.rsi(list(range(1,31))),100)
        self.assertEqual(indicators.rsi(list(range(30,0,-1))),0)

    def test_components_are_bounded_and_weighted(self):
        result=research.screen('EXAMPLE',quote())
        self.assertEqual(len(result['analyses']),5)
        self.assertEqual(sum(p['weight'] for p in result['analyses']),100)
        for part in result['analyses']:
            self.assertTrue(0<=part['score']<=100)
        weighted=sum(p['score']*p['weight']/100 for p in result['analyses'])
        self.assertAlmostEqual(result['composite'],weighted,delta=.1)
        for name in ['rsi14','macd','macd_signal','bollinger_upper','bollinger_lower','max_drawdown']:
            self.assertTrue(math.isfinite(result['metrics'][name]))

    def test_top20_excludes_missing_and_illiquid_stocks(self):
        snapshot={'positions':[],'quotes':{}}
        symbols=[]
        for i in range(30):
            symbol=f'STOCK{i}.OL';symbols.append(symbol)
            q=quote();q['currency']='NOK';q['turnover20']=1000000+i*100000
            snapshot['quotes'][symbol]=q
        snapshot['quotes']['STOCK0.OL']['turnover20']=1
        snapshot['quotes']['STOCK1.OL']['asof']=time.time()-5*86400
        report=research.build_report(snapshot,symbols)
        self.assertEqual(len(report['top20']),20)
        self.assertNotIn('STOCK0.OL',report['top20'])
        self.assertNotIn('STOCK1.OL',report['top20'])
        self.assertEqual(report['coverage']['requested'],30)
        self.assertEqual(report['coverage']['analysed'],29)
        selected=[c for c in report['cards'] if c.get('rank')]
        self.assertEqual(sorted(c['rank'] for c in selected),list(range(1,29)))
        self.assertEqual(report['cards'][0]['composite'],max(c['composite'] for c in report['cards'] if c.get('composite') is not None))
        self.assertTrue(all(not c['history'] for c in report['cards']))
        self.assertTrue(snapshot['quotes']['STOCK2.OL']['history'])

    def test_fewer_eligible_stocks_does_not_pad_top20(self):
        q=quote();q['currency']='NOK'
        report=research.build_report({'positions':[],'quotes':{'BOUV.OL':q}},['BOUV.OL','MISSING.OL'])
        self.assertEqual(report['top20'],['BOUV.OL'])
        self.assertEqual(report['coverage']['unavailable'],1)

    def test_universe_is_broad_and_unique(self):
        self.assertEqual(len(universe.SYMBOLS),180)
        self.assertEqual(len(set(universe.SYMBOLS)),180)
        self.assertTrue(all(s.endswith('.OL') for s in universe.SYMBOLS))
        self.assertIn('KOG.OL',universe.SYMBOLS)
        self.assertIn('PHO.OL',universe.SYMBOLS)

    def test_history_aligns_adjusted_candles_and_volume(self):
        import io,json
        payload={'chart':{'result':[{'meta':{'regularMarketPrice':10,'currency':'NOK','regularMarketTime':2},'timestamp':[1,2],
            'indicators':{'quote':[{'open':[18,19],'high':[22,23],'low':[16,17],'close':[20,22],'volume':[100,200]}],
            'adjclose':[{'adjclose':[10,11]}]}}]}}
        with patch.object(app,'urlopen',return_value=io.BytesIO(json.dumps(payload).encode())):
            q=app.fetch_quote('EXAMPLE.OL')
        self.assertEqual(q['history'][0],{'time':1,'close':10,'open':9,'high':11,'low':8,'volume':100,'raw_close':20,'account_close':20})
        self.assertEqual(q['history_version'],3)


class RiskDiagnosticsTests(unittest.TestCase):
    def history(self, closes):
        return [{'time':i*86400,'close':v,'high':v+1,'low':max(.01,v-1),'volume':1000} for i,v in enumerate(closes)]

    def test_flat_data_has_zero_risk_and_unavailable_risk_ratios(self):
        m=indicators.risk_diagnostics(self.history([100]*300))
        for key in ('volatility20','volatility63','var95_loss','expected_shortfall95','max_drawdown1y','adx14','efficiency20','trend_r2'):
            self.assertEqual(m[key],0,key)
        self.assertIsNone(m['sharpe_zero_rate']);self.assertIsNone(m['sortino_zero_rate'])
        self.assertEqual(m['atr14'],2);self.assertEqual(m['relative_volume20'],1)
        self.assertEqual(m['risk_sessions'],252);self.assertEqual(m['range_position'],50)
        json=__import__('json');json.dumps(m,allow_nan=False)

    def test_empirical_tail_uses_fractional_probability_mass(self):
        m=indicators.risk_diagnostics(self.history([100]+[80]*20))
        self.assertAlmostEqual(m['var95_loss'],1)
        self.assertAlmostEqual(m['expected_shortfall95'],20)
        self.assertAlmostEqual(m['max_drawdown1y'],-20)
        self.assertAlmostEqual(m['recovery_pct'],25)
        self.assertEqual(m['underwater_sessions'],20)

    def test_return_horizons_and_directional_strength(self):
        closes=[100+i for i in range(300)]
        m=indicators.risk_diagnostics(self.history(closes))
        for key,n in [('return1w',5),('return1m',21),('return3m',63),('return6m',126),('return1y',252)]:
            self.assertAlmostEqual(m[key],(closes[-1]/closes[-n-1]-1)*100)
        self.assertAlmostEqual(m['adx14'],100)
        self.assertEqual(m['minus_di14'],0);self.assertGreater(m['plus_di14'],0)
        self.assertAlmostEqual(m['efficiency20'],100)
        self.assertEqual(m['trend_direction'],'rising')
        self.assertGreater(m['trend_r2'],.99)

    def test_missing_range_and_volume_do_not_fabricate_indicators(self):
        h=self.history([100+i*.1 for i in range(300)])
        del h[-1]['high'];del h[-1]['volume']
        m=indicators.risk_diagnostics(h)
        for key in ('atr14','atr_pct','adx14','relative_volume20'):
            self.assertIsNone(m[key],key)
        self.assertIsNotNone(m['volatility63'])
        short=indicators.risk_diagnostics(h[:10])
        self.assertIsNone(short['return1m']);self.assertIsNone(short['volatility20'])
        self.assertEqual(indicators.risk_diagnostics([]),{})

    def test_new_diagnostics_do_not_change_score_or_policy(self):
        q=quote()
        original=research.screen('EXAMPLE',q)
        with patch.object(indicators,'risk_diagnostics',return_value={}):
            baseline=research.screen('EXAMPLE',q)
        for key in ('composite','score','rank_eligible','action'):
            self.assertEqual(original[key],baseline[key])
