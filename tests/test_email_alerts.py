import importlib.util
import json
from pathlib import Path
import smtplib
import ssl
import tempfile
import unittest
from unittest.mock import Mock, patch

import app
import decision_policy
import email_alerts as mail
from test_trade_plan import NOW


def environment(**changes):
    return {'NORTHSTAR_EMAIL_ENABLED': '1', 'NORTHSTAR_SMTP_HOST': 'smtp.example.com',
            'NORTHSTAR_SMTP_PORT': '587', 'NORTHSTAR_SMTP_SECURITY': 'starttls',
            'NORTHSTAR_SMTP_USERNAME': 'sender@example.com', 'NORTHSTAR_SMTP_PASSWORD': 'private-password',
            'NORTHSTAR_EMAIL_FROM': 'sender@example.com', 'NORTHSTAR_EMAIL_TO': 'investor@example.com',
            'NORTHSTAR_PAGES_ORIGIN': 'https://owner.github.io', **changes}


class ConfigurationTests(unittest.TestCase):
    def test_disabled_and_incomplete_settings_cannot_send(self):
        config = mail.configuration({})
        self.assertFalse(config['enabled'])
        self.assertFalse(config['configured'])
        self.assertTrue(mail.configuration(environment())['configured'])
        for changes in ({'NORTHSTAR_SMTP_SECURITY': 'none'}, {'NORTHSTAR_SMTP_PORT': '0'},
                        {'NORTHSTAR_SMTP_PORT': 'garbage'}, {'NORTHSTAR_EMAIL_TO': 'a@example.com,b@example.com'},
                        {'NORTHSTAR_EMAIL_TO': 'a@example.com\nBcc: someone@example.com'},
                        {'NORTHSTAR_SMTP_HOST': 'https://smtp.example.com'}, {'NORTHSTAR_SMTP_PASSWORD': ''}):
            with self.subTest(changes=changes):
                self.assertFalse(mail.configuration(environment(**changes))['configured'])

    def test_setup_serializes_systemd_values_without_interpolation(self):
        path = Path(__file__).resolve().parent.parent/'scripts/setup-email.py'
        spec = importlib.util.spec_from_file_location('setup_email', path)
        setup = importlib.util.module_from_spec(spec);spec.loader.exec_module(setup)
        text = setup.environment_text({'NORTHSTAR_SMTP_PASSWORD': 'a"b\\c$%`'})
        self.assertEqual(text, 'NORTHSTAR_SMTP_PASSWORD="a\\"b\\\\c$%`"\n')
        with self.assertRaises(ValueError):
            setup.environment_text({'NORTHSTAR_SMTP_PASSWORD': 'a\nb'})

    def test_tls_precedes_authentication_and_ssl_uses_verified_context(self):
        for mode in ('starttls', 'ssl'):
            config = mail.configuration(environment(NORTHSTAR_SMTP_SECURITY=mode))
            client = Mock();client.send_message.return_value = {}
            with patch('email_alerts.smtplib.SMTP', return_value=client) as smtp, \
                 patch('email_alerts.smtplib.SMTP_SSL', return_value=client) as smtp_ssl:
                mail.deliver(config, Mock())
            methods = [call[0] for call in client.mock_calls]
            self.assertLess(methods.index('login'), methods.index('send_message'))
            if mode == 'starttls':
                self.assertLess(methods.index('starttls'), methods.index('login'))
                smtp.assert_called_once();smtp_ssl.assert_not_called()
                context = client.starttls.call_args.kwargs['context']
            else:
                smtp.assert_not_called();smtp_ssl.assert_called_once()
                context = smtp_ssl.call_args.kwargs['context']
            self.assertTrue(context.check_hostname)
            self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)

    def test_failed_quit_after_acceptance_does_not_cause_retry(self):
        client = Mock();client.send_message.return_value = {};client.quit.side_effect = OSError('quit failed')
        with patch('email_alerts.smtplib.SMTP', return_value=client):
            mail.deliver(mail.configuration(environment()), Mock())
        client.close.assert_called_once()


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = patch.object(app, 'DB', Path(self.temp.name)/'portfolio.db');self.db.start()
        self.env = environment()
        self.report = {'generated': NOW, 'policy_version': decision_policy.VERSION,
                       'recommendation_changes': [{'symbol': 'B.OL', 'direction': 'buy', 'shares': 9,
                                                   'change_id': 'first', 'change': 'New'}]}
        self.plan = {'buys': [{'symbol': 'B.OL', 'buy_shares': 9, 'price': 100, 'quote_asof': NOW,
                              'reason': 'Meets entry policy and portfolio limits.'}], 'holdings': []}
        self.worker = self.new_worker()
        self.delivery = patch('email_alerts.deliver');self.send = self.delivery.start()

    def tearDown(self):
        self.delivery.stop();self.db.stop();self.temp.cleanup()

    def new_worker(self):
        return mail.Worker(app.connect, app.read_meta, app.write_meta,
                           lambda: (self.report, self.plan), self.env)

    def rows(self):
        with app.connect() as db:
            mail.schema(db)
            return [dict(row) for row in db.execute('SELECT * FROM email_outbox ORDER BY created,id')]

    def test_send_once_across_polling_scans_and_worker_restart(self):
        self.worker.tick(NOW)
        self.report['recommendation_changes'][0]['change'] = 'Unchanged'
        self.worker.tick(NOW+60)
        self.new_worker().tick(NOW+120)
        self.send.assert_called_once()
        message = self.send.call_args.args[1]
        self.assertIn('review buy of 9 shares', message.get_content())
        self.assertIn('https://owner.github.io/northstar/#recommendations', message.get_content())
        self.assertNotIn('private-password', message.as_string())
        self.assertEqual(self.rows()[0]['status'], 'sent')

    def test_failure_retries_persistently_without_requiring_new_change(self):
        self.send.side_effect = smtplib.SMTPAuthenticationError(535, b'private-password echoed')
        self.worker.tick(NOW)
        self.assertEqual(self.rows()[0]['status'], 'pending')
        status = self.worker.status()
        self.assertIn('authentication', status['error'])
        self.assertNotIn('private-password', json.dumps(status))
        self.report['recommendation_changes'][0]['change'] = 'Unchanged'
        self.new_worker().tick(NOW+30)
        self.assertEqual(self.send.call_count, 1)
        self.send.side_effect = None
        self.new_worker().tick(NOW+60)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.rows()[0]['status'], 'sent')
        self.assertIsNone(self.worker.status()['error'])

    def test_stale_blocked_or_superseded_suggestions_are_not_retried(self):
        self.send.side_effect = TimeoutError()
        self.worker.tick(NOW)
        self.plan['buys'] = []
        self.worker.tick(NOW+60)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.rows()[0]['status'], 'cancelled')

    def test_stale_report_cancels_pending_and_sends_nothing(self):
        self.send.side_effect = TimeoutError()
        self.worker.tick(NOW)
        self.worker.tick(NOW+2*86400)
        self.assertEqual(self.send.call_count, 1)
        self.assertEqual(self.rows()[0]['status'], 'cancelled')

    def test_current_quantity_must_match_saved_recommendation(self):
        self.plan['buys'][0]['buy_shares'] = 8
        self.worker.tick(NOW)
        self.send.assert_not_called()
        self.assertEqual(self.rows(), [])

    def test_new_change_sends_but_minor_drift_does_not_resend(self):
        self.worker.tick(NOW)
        self.plan['buys'][0]['buy_shares'] = 10
        change = self.report['recommendation_changes'][0]
        change.update(shares=10, change='Unchanged')
        self.worker.tick(NOW+60)
        self.assertEqual(self.send.call_count, 1)
        change.update(change_id='second', change='Updated')
        self.worker.tick(NOW+120)
        self.assertEqual(self.send.call_count, 2)

    def test_pause_cancels_queue_and_resume_can_send_current_suggestion(self):
        self.send.side_effect = TimeoutError()
        self.worker.tick(NOW)
        self.worker.set_enabled(False)
        self.send.side_effect = None
        self.worker.tick(NOW+60)
        self.assertEqual(self.send.call_count, 1)
        self.worker.set_enabled(True)
        self.worker.tick(NOW+120)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.rows()[0]['status'], 'sent')

    def test_withdrawal_only_sends_after_original_was_sent(self):
        self.worker.tick(NOW)
        self.report['recommendation_changes'][0]['change'] = 'Withdrawn'
        self.plan['buys'] = []
        self.worker.tick(NOW+60)
        self.assertEqual(self.send.call_count, 2)
        self.assertIn('previous buy suggestion withdrawn', self.send.call_args.args[1].get_content())
        self.worker.tick(NOW+120)
        self.assertEqual(self.send.call_count, 2)

    def test_unsent_original_does_not_generate_withdrawal_email(self):
        self.report['recommendation_changes'][0]['change'] = 'Withdrawn'
        self.plan['buys'] = []
        self.worker.tick(NOW)
        self.send.assert_not_called()

    def test_withdrawal_retry_survives_a_later_scan_without_changes(self):
        self.worker.tick(NOW)
        self.report['recommendation_changes'][0]['change'] = 'Withdrawn'
        self.plan['buys'] = []
        self.send.side_effect = TimeoutError()
        self.worker.tick(NOW+60)
        self.report['recommendation_changes'] = []
        self.send.side_effect = None
        self.worker.tick(NOW+120)
        self.assertEqual(self.send.call_count, 3)
        self.assertEqual(sum(r['status'] == 'sent' for r in self.rows()), 2)

    def test_test_mail_requires_configuration_and_is_rate_limited(self):
        self.report = None;self.plan = {'buys': [], 'holdings': []}
        self.worker.queue_test(NOW)
        with self.assertRaises(ValueError):
            self.worker.queue_test(NOW+30)
        self.worker.tick(NOW)
        self.send.assert_called_once()
        self.assertEqual(self.send.call_args.args[1]['Subject'], 'Northstar: email test')
        self.worker.set_enabled(False)
        with self.assertRaises(ValueError):
            self.worker.queue_test(NOW+120)

    def test_incomplete_configuration_never_contacts_smtp(self):
        del self.env['NORTHSTAR_SMTP_PASSWORD']
        self.worker.tick(NOW)
        self.send.assert_not_called()
        with self.assertRaises(ValueError):
            self.worker.queue_test(NOW)
        self.assertFalse(self.worker.status()['active'])

    def test_server_kill_switch_cannot_be_overridden_from_dashboard(self):
        self.env['NORTHSTAR_EMAIL_ENABLED'] = '0'
        self.worker.tick(NOW)
        self.send.assert_not_called()
        with self.assertRaises(ValueError):
            self.worker.set_enabled(True)
        self.assertFalse(self.worker.status()['server_enabled'])

    def test_parallel_worker_does_not_send_claimed_events_again(self):
        def during_delivery(*args):
            self.new_worker().tick(NOW+1)
        self.send.side_effect = during_delivery
        self.worker.tick(NOW)
        self.send.assert_called_once()
        self.assertEqual(self.rows()[0]['status'], 'sent')

    def test_buy_and_sell_changes_are_grouped_and_include_their_reasons(self):
        self.plan['holdings'] = [{'symbol': 'A.OL', 'sell_shares': 4, 'price': 90,
                                 'quote_asof': NOW, 'reasons': ['Confirmed sell review.']}]
        self.report['recommendation_changes'].append({'symbol': 'A.OL', 'direction': 'sell',
                                                      'shares': 4, 'change_id': 'sale', 'change': 'New'})
        self.worker.tick(NOW)
        self.send.assert_called_once()
        content = self.send.call_args.args[1].get_content()
        self.assertIn('review buy of 9 shares', content)
        self.assertIn('review sell of 4 shares', content)
        self.assertIn('Confirmed sell review.', content)
        self.assertIn('2 portfolio review', self.send.call_args.args[1]['Subject'])

    def test_restart_recovers_expired_sending_lease(self):
        self.send.side_effect = TimeoutError()
        self.worker.tick(NOW)
        with app.connect() as db:
            db.execute("UPDATE email_outbox SET status='sending',updated=?", (NOW,))
        self.send.side_effect = None
        self.new_worker().tick(NOW+mail.LEASE_SECONDS+1)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.rows()[0]['status'], 'sent')

    def test_changed_recipient_has_its_own_deduplication_history(self):
        self.worker.tick(NOW)
        self.env['NORTHSTAR_EMAIL_TO'] = 'other@example.com'
        self.worker.tick(NOW+60)
        self.assertEqual(self.send.call_count, 2)
        self.assertEqual(self.send.call_args.args[1]['To'], 'other@example.com')

    def test_status_never_exposes_smtp_credentials_or_addresses(self):
        status = json.dumps(self.worker.status())
        for private in ('private-password', 'sender@example.com', 'investor@example.com', 'smtp.example.com'):
            self.assertNotIn(private, status)
