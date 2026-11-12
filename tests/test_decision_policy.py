import copy
import unittest
from unittest.mock import patch

import advice_state
import decision_policy as policy
import portfolio_fit
import research
import trade_plan
import validation
from test_research import quote
from test_trade_plan import NOW, card, profile, snapshot
from test_validation import quotes


class SharedPolicyTests(unittest.TestCase):
    def metrics(self, **changes):
        return dict(close=110, ma50=105, ma200=100, momentum3m=5,
                    volatility=20, extension50=5, turnover20=250000,
                    turnover_days=15, **changes)

    def test_entry_boundaries_and_failure_reasons(self):
        base = self.metrics()
        self.assertTrue(policy.decide(base, 110)['rank_eligible'])
        for changes in ({'volatility': 50}, {'extension50': 15}, {'momentum3m': 0},
                        {'close': 105}, {'ma50': 100}, {'turnover_days': 14},
                        {'turnover20': 249999}, {'turnover20': float('nan')},
                        {'ma200': float('nan')}):
            with self.subTest(changes=changes):
                d = policy.decide({**base, **changes}, 110)
                self.assertFalse(d['rank_eligible'])
                self.assertNotEqual(d['action'], 'Consider buying')
                self.assertTrue(d['policy_reasons'])
        self.assertTrue(policy.decide({**base, 'volatility': 49.999, 'extension50': 14.999}, 110)['rank_eligible'])
        self.assertFalse(policy.decide(base, 110, min_turnover_nok=300000)['rank_eligible'])

    def test_hold_can_add_but_personal_sell_override_cannot_rank(self):
        held = {'shares': 10}
        d = policy.decide(self.metrics(), 110, held)
        self.assertEqual(d['action'], 'Hold / monitor')
        self.assertTrue(policy.buy_signal(d))
        for level in ({'below': 110}, {'above': 110}):
            d = policy.decide(self.metrics(), 110, {**held, **level})
            self.assertIn(d['action'], policy.SELL_SIGNALS)
            self.assertFalse(d['rank_eligible'])
            self.assertFalse(policy.buy_signal(d))

    def test_losing_entry_eligibility_alone_does_not_sell(self):
        d = policy.decide({**self.metrics(), 'momentum3m': -1}, 110, {'shares': 1})
        self.assertEqual(d['action'], 'Hold / monitor')
        self.assertFalse(d['rank_eligible'])
        d = policy.decide({**self.metrics(), 'close': 90, 'momentum3m': -1}, 90, {'shares': 1})
        self.assertEqual(d['action'], 'Consider reducing / selling')

    def test_watch_stocks_cannot_displace_entries_before_limit(self):
        watches = [card('W'+str(i)+'.OL', i, 'Wait / watch') for i in range(25)]
        candidate = card('B.OL', 30)
        selected = policy.entries(watches+[candidate])
        self.assertEqual([c['symbol'] for c in selected], ['B.OL'])
        plan = trade_plan.build(snapshot(), {'generated': NOW, 'policy_version': policy.VERSION,
                                           'cards': watches+[candidate]}, profile(), NOW)
        self.assertEqual([r['symbol'] for r in plan['buys']], ['B.OL'])

    def test_report_ranks_only_real_entries_and_preserves_scores(self):
        up = quote(); up['currency'] = 'NOK'
        down = quote(False); down['currency'] = 'NOK'
        snap = {'positions': [], 'quotes': {'UP.OL': up, 'DOWN.OL': down}}
        report = research.build_report(snap, ['UP.OL', 'DOWN.OL'])
        cards = {c['symbol']: c for c in report['cards']}
        self.assertEqual(report['top20'], ['UP.OL'])
        self.assertEqual(cards['UP.OL']['rank'], 1)
        self.assertNotIn('rank', cards['DOWN.OL'])
        self.assertIsNotNone(cards['DOWN.OL']['composite'])
        self.assertEqual(report['policy_version'], policy.VERSION)

    def test_old_reports_and_old_confirmation_evidence_do_not_authorize_buys(self):
        report = {'generated': NOW, 'cards': [card()]}
        for version in (None, 'old'):
            r = copy.deepcopy(report)
            if version:
                r['policy_version'] = version
            self.assertEqual(trade_plan.build(snapshot(), r, profile(), NOW)['buys'], [])
            self.assertFalse(portfolio_fit.view(snapshot(), r, profile(), NOW)['candidates'][0]['buy_candidate'])
        previous = {'B.OL': {'intent': 'buy', 'since': NOW-86400, 'sessions': ['old']}}
        state = advice_state.observe(report, previous, NOW)
        self.assertEqual(len(state['B.OL']['sessions']), 1)
        self.assertEqual(state['B.OL']['since'], NOW)
        self.assertEqual(state['B.OL']['policy_version'], policy.VERSION)

    def test_experiment_excludes_watch_and_uses_shared_exit_for_held_stock(self):
        calls = []
        def screen(symbol, q, position=None, **kwargs):
            calls.append(bool(position))
            n = len(calls)
            action = ('Consider buying' if n == 1 else 'Hold / monitor' if n < 4
                      else 'Consider reducing / selling' if position else 'Wait / watch')
            return {'symbol': symbol, 'composite': 90, 'action': action,
                    'rank_eligible': n == 1}
        with patch('research.screen', side_effect=screen):
            result = validation.evaluate(quotes(400), ['A.OL'])
        self.assertGreater(len(calls), 4)
        self.assertEqual(calls[:5], [False, True, True, True, False])
        self.assertEqual(result['buy_orders'], 1)
        self.assertEqual(result['trades'], 2)
        self.assertEqual(result['policy_version'], policy.VERSION)

    def test_high_score_watch_never_enters_experiment(self):
        def screen(symbol, q, **kwargs):
            return {'symbol': symbol, 'composite': 100, 'rank_eligible': True,
                    'action': 'Wait / watch'}
        with patch('research.screen', side_effect=screen):
            result = validation.evaluate(quotes(), ['A.OL'])
        self.assertEqual(result['buy_orders'], 0)
        self.assertEqual(result['return_pct'], 0)
