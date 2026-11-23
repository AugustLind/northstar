import time
import unittest
from unittest.mock import patch

import research
from research_worker import ResearchWorker


def quote():
    now = time.time()
    values = [100 + i * .1 for i in range(250)]
    return {'price': values[-1], 'currency': 'NOK', 'asof': now, 'source': 'fixture',
            'turnover20': 2000000, 'turnover_days': 20,
            'history': [{'time': now - (249 - i) * 86400, 'close': value}
                        for i, value in enumerate(values)]}


class ResearchWorkerTests(unittest.TestCase):
    def test_worker_retains_rules_when_ai_unavailable(self):
        values = {}
        config = dict(research.DEFAULT_SETTINGS, universe=['BOUV.OL'], llm_enabled=True)
        worker = ResearchWorker(lambda symbols: [],
            lambda: {'positions': [], 'quotes': {'BOUV.OL': quote()}},
            lambda key, default=None: values.get(key, default),
            lambda key, value: values.update({key: value}), lambda: config)
        with patch.object(research, 'local_answer', side_effect=OSError('offline')):
            self.assertTrue(worker.run_once())
        self.assertEqual(values['report']['cards'][0]['action'], 'Consider buying')
        self.assertIn('unavailable', values['report']['llm_status'])
        self.assertFalse(worker.view()['worker']['running'])
        self.assertTrue(worker.view()['worker']['next_run'] > time.time())


if __name__ == '__main__':
    unittest.main()
