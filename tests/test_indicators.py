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
        self.assertEqual(q['history'][0],{'time':1,'close':10,'open':9,'high':11,'low':8,'volume':100})
        self.assertEqual(q['history_version'],3)
