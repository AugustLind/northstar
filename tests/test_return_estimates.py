import datetime as dt
import unittest
from unittest.mock import patch

from northstar import return_estimates as estimates


def market_quotes():
    start = dt.date(2020, 1, 1)
    end = dt.date(2025, 12, 31)
    days = []
    day = start
    while day <= end:
        if day.weekday() < 5:
            days.append(day)
        day += dt.timedelta(days=1)
    history = [
        {'time': int(dt.datetime.combine(day, dt.time(16), dt.timezone.utc).timestamp()),
         'close': 100 + index, 'volume': 1000}
        for index, day in enumerate(days)
    ]
    quote = {'currency': 'NOK', 'history_basis': estimates.HISTORY_BASIS,
             'source': 'fixture', 'history': history}
    return {'TST.OL': quote, 'OSEBX.OL': quote}, [int(point['time'] // 86400) for point in history]


class ReturnEstimateTests(unittest.TestCase):
    def test_percentile_interpolation_matches_documented_example(self):
        values = [-10, -5, 0, 5, 10]
        self.assertEqual(estimates._quantile(values, .1), -8)
        self.assertEqual(estimates._quantile(values, .5), 0)
        self.assertEqual(estimates._quantile(values, .9), 8)

    def test_samples_use_only_prior_bars_and_exactly_63_oslo_sessions(self):
        quotes, market_days = market_quotes()
        observed = []

        def screen(symbol, quote, min_turnover_nok, as_of):
            self.assertLessEqual(quote['history'][-1]['time'], as_of)
            self.assertTrue(all(point['time'] <= quote['asof'] for point in quote['history']))
            observed.append(quote['asof'])
            return {'rank_eligible': True, 'action': 'Consider buying', 'composite': 50}

        signals, baseline = estimates._historical_samples(
            quotes, ['TST.OL'], 250000, screen)
        samples = signals['TST.OL']
        self.assertGreaterEqual(len(samples), estimates.MIN_SIGNAL_SAMPLES)
        self.assertEqual(len(samples), len(baseline['TST.OL']))
        index_by_day = {day: index for index, day in enumerate(market_days)}
        for row in samples:
            origin_index = index_by_day[row['origin_day']]
            self.assertEqual(row['end_day'], market_days[origin_index + 63])
        self.assertTrue(observed)

    def test_nonqualifying_holding_is_not_applicable_without_estimation(self):
        card = {'symbol': 'TST.OL', 'held': True, 'rank_eligible': False,
                'action': 'Hold / monitor'}
        with patch.object(estimates, '_historical_samples', side_effect=AssertionError):
            estimates.attach([card], {}, [], 1, 250000, lambda *args, **kwargs: None)
        self.assertEqual(card['return_estimate']['status'], 'not_applicable')


if __name__ == '__main__':
    unittest.main()
