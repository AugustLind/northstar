"""The production artifact contains bounded, allowlisted diagnostics."""
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
import sys
import time
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from smoke_live_browser import Diagnostics, journal


class LiveBrowserDiagnosticsTests(unittest.TestCase):
    def test_write_and_other_origin_are_blocked_and_queries_are_omitted(self):
        diagnostics = Diagnostics('https://pages.example/northstar/', 'https://api.example')
        browser = Mock()
        for method, url, expected_path in (
            ('POST', 'https://api.example/api/state?auth=private', '/api/state'),
            ('GET', 'https://other.example/private-holding', '[other path]'),
        ):
            diagnostics.event(browser, 'Fetch.requestPaused',
                              {'requestId': '1', 'request': {'method': method, 'url': url}})
            browser.send.assert_called_with('Fetch.failRequest',
                                            {'requestId': '1', 'errorReason': 'BlockedByClient'})
            self.assertEqual(diagnostics.requests[-1]['path'], expected_path)
        self.assertTrue(diagnostics.blocked)
        self.assertNotIn('private', json.dumps(list(diagnostics.requests)))

    def test_only_allowlisted_service_access_fields_leave_oracle(self):
        timestamp = int(time.time() * 1_000_000)
        lines = [json.dumps({'__REALTIME_TIMESTAMP': timestamp, 'MESSAGE': line}) for line in (
            'private-ip - - [25/Nov/2026 10:00:00] "GET /api/account-performance?symbol=PRIVATE HTTP/1.1" 500 -',
            'private-ip - - [25/Nov/2026 10:00:00] "GET /api/private-route HTTP/1.1" 200 -',
            'other-client - - [25/Nov/2026 10:00:00] "GET /api/account-performance HTTP/1.1" 200 -',
            'Exception reported private holding',
        )] * 50
        with patch('smoke_live_browser.subprocess.run',
                   return_value=subprocess.CompletedProcess([], 0, stdout='\n'.join(lines))):
            evidence = journal(0, int(time.time()), [
                {'method': 'GET', 'path': '/api/account-performance', 'status': 500,
                 'at': datetime.fromtimestamp(timestamp / 1e6, timezone.utc).isoformat()},
            ])
        self.assertTrue(evidence['matched_browser_requests'])
        self.assertTrue(evidence['available'])
        self.assertEqual(len(evidence['entries']), 40)
        self.assertEqual({r['status'] for r in evidence['entries']}, {500})
        self.assertNotIn('private', json.dumps(evidence).lower())
