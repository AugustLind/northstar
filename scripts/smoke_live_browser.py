"""Read-only Chrome verification with diagnostics suitable for an Actions artifact."""
import argparse
from collections import deque
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
from urllib.parse import urlsplit

from browser_client import Browser

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import release_info
import ui_assets


API_PATHS = frozenset('/api/' + name for name in (
    'health', 'release', 'state', 'research', 'daily', 'account-performance',
    'portfolio-fit', 'portfolio-risk', 'ledger', 'trade-plan', 'system-status',
    'email', 'email/history', 'archive', 'session/remember', 'session/sign-out',
))
READ_METHODS = frozenset(('GET', 'HEAD', 'OPTIONS'))
BROWSER_ERRORS = re.compile(
    r'\b(?:net::ERR_(?:ABORTED|FAILED|TIMED_OUT|CONNECTION_REFUSED|CONNECTION_RESET|'
    r'NAME_NOT_RESOLVED|CERT_AUTHORITY_INVALID|BLOCKED_BY_CLIENT)|'
    r'TypeError|ReferenceError|SyntaxError|RangeError)\b'
)
KEY_PATTERN = re.compile(r'[A-Za-z0-9_-]{40,100}')


def origin(url):
    parts = urlsplit(url)
    return parts.scheme + '://' + parts.netloc


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def startup_messages(output):
    # Chrome can print arbitrary URLs, profile paths and log text. Retain fixed
    # excerpts that identify startup and common environment problems.
    return [label for marker, label in (
        (b'DevTools listening', 'DevTools listening'),
        (b'Failed to connect to the bus', 'Failed to connect to the bus'),
        (b'No usable sandbox', 'No usable sandbox'),
        (b'Missing X server', 'Missing X server'),
        (b'error while loading shared libraries', 'Error while loading shared libraries'),
        (b'Failed to create', 'Chrome reported a resource creation failure'),
    ) if marker in output]


class Diagnostics:
    def __init__(self, page_url, api_origin):
        self.page_url = page_url
        self.api_origin = api_origin
        self.page_origin = origin(page_url)
        self.page_path = urlsplit(page_url).path
        assets = ui_assets.public_files()
        self.page_paths = {self.page_path, *(self.page_path + name for name in assets)}
        self.requests = deque(maxlen=80)
        self.console = deque(maxlen=20)
        self.pending = {}
        self.blocked = False

    def route(self, url):
        parts = urlsplit(url)
        if origin(url) == self.api_origin and parts.path in API_PATHS:
            return parts.path
        if origin(url) == self.page_origin and parts.path in self.page_paths:
            return parts.path
        return '[other path]'

    def event(self, browser, method, params):
        if method == 'Fetch.requestPaused':
            request = params['request']
            # Chrome pauses redirected requests too. Limit this profile to the
            # two checked origins and deny writes before they reach the network.
            allowed = (request['method'] in READ_METHODS
                       and origin(request['url']) in (self.page_origin, self.api_origin))
            if not allowed:
                self.blocked = True
                self.requests.append({'path': self.route(request['url']), 'status': 'blocked', 'at': utc_now()})
            browser.send('Fetch.continueRequest' if allowed else 'Fetch.failRequest',
                         {'requestId': params['requestId'], **({} if allowed else {'errorReason': 'BlockedByClient'})})
        elif method == 'Network.requestWillBeSent':
            request = params['request']
            if len(self.pending) >= 80:
                self.pending.pop(next(iter(self.pending)))
            self.pending[params['requestId']] = (self.route(request['url']), request['method'])
        elif method == 'Network.responseReceived':
            response = params['response']
            self.record_request(params, int(response['status']), self.route(response['url']))
        elif method in ('Network.loadingFailed', 'Runtime.exceptionThrown', 'Runtime.consoleAPICalled', 'Log.entryAdded'):
            if method == 'Runtime.consoleAPICalled' and params['type'] not in ('error', 'assert'):
                return
            if method == 'Log.entryAdded':
                entry = params['entry']
                if entry['level'] != 'error' or (entry['source'] == 'network' and
                    re.match(r'Failed to load resource: the server responded with a status of 401\b', entry['text'])):
                    return
            if method == 'Network.loadingFailed':
                self.record_request(params, 'failed')
            error = BROWSER_ERRORS.search(json.dumps(params))
            label = {
                'Network.loadingFailed': 'Request failed',
                'Runtime.exceptionThrown': 'Uncaught browser exception',
                'Runtime.consoleAPICalled': 'Console error',
                'Log.entryAdded': 'Browser log error',
            }[method]
            self.console.append(label + (': ' + error[0] if error else ''))

    def record_request(self, params, status, fallback='[other path]'):
        path, method = self.pending.pop(params['requestId'], (fallback, ''))
        self.requests.append({'path': path, 'method': method if method in READ_METHODS else 'other',
                              'status': status, 'at': utc_now()})


DOM = r"""(() => {
    const node = id => document.getElementById(id);
    const text = id => node(id)?.textContent.trim() || '';
    const visible = id => !!node(id)?.checkVisibility();
    const period = (id, count) => {
        const status = text(id + 'Status');
        if (!visible(id + 'Title')) return 'hidden';
        if (status.includes('Refresh failed')) return 'request failed';
        if (!status || status.startsWith('Loading')) return 'loading';
        const metrics = node(id + 'Metrics').querySelectorAll('strong');
        if (metrics.length !== count) return 'metrics missing';
        if (visible(id + 'Chart') && node(id + 'Chart').querySelector('svg')) return 'chart ready';
        return node(id + 'Chart').hidden && metrics[count - 2].textContent.startsWith('Unavailable')
            ? 'coverage unavailable' : 'chart missing';
    };
    const advice = Array.from(document.querySelectorAll('#holdings [data-holding-advice]'));
    const adviceReady = typeof state !== 'undefined' &&
        advice.length === state.positions.filter(position => position.shares > 0).length &&
        advice.every(cell => ['Hold', 'Sell review', 'Insufficient data'].includes(cell.querySelector('b')?.textContent)
            && cell.querySelector('small')?.textContent.trim());
    const candidates = text('buyCandidatesStatus');
    const cards = Array.from(document.querySelectorAll('#buyCandidates article'));
    const ranked = cards.length > 0 && cards.length <= 5 &&
        candidates.startsWith(cards.length + ' eligible candidate') &&
        cards.every(card => card.querySelector('h3')?.textContent.trim()
            && card.querySelectorAll('p')[1]?.textContent.trim()
            && card.querySelector('[data-candidate-stock]'));
    const comparison = text('switchStatus');
    return {
        sign_in: visible('connectionPanel') ? 'required' : text('accountStatus') === 'Connected' ? 'connected' : 'loading',
        workspace: ['portfolio', 'candidates'].find(id =>
            visible(id) && text('workspaceTitle').toLowerCase() === id) || 'other',
        today: period('today', 3),
        today_basis: text('todayStatus').startsWith('Session ') ? 'open session'
            : text('todayStatus').startsWith('Last completed session ') ? 'last completed session' : 'unknown',
        week: period('week', 2),
        advice: !text('dailyStatus').startsWith('Updated ') ? 'reviews pending or failed'
            : !adviceReady ? 'advice missing' : advice.length ? 'rendered' : 'no holdings',
        reviews_refreshed: typeof dailyView !== 'undefined' && dailyView !== window.smokePreviousReviews,
        candidates: ranked ? 'ranked' : cards.length ? 'invalid cards'
            : candidates.startsWith('Research is stale or unavailable.') ? 'stale or unavailable'
            : candidates.startsWith('Buying candidates unavailable') ? 'coverage unavailable'
            : candidates.startsWith('No eligible buying candidates') ? 'empty'
            : candidates.startsWith('Buying candidates could not be loaded.') ? 'request failed' : 'loading',
        switch: comparison.startsWith('No switch qualifies.') ? 'no qualifier'
            : comparison.startsWith('Comparison unavailable.') ? 'unavailable'
            : node('switchComparison')?.querySelector('tbody tr') ? 'comparison ready' : 'loading',
    };
})()"""


def run(page_url, api_origin, key, evidence, wait_seconds=15):
    diagnostics = Diagnostics(page_url, api_origin)
    browser = Browser(on_event=diagnostics.event)
    expected = evidence['source_fingerprint']
    configured_api = api_origin if api_origin != diagnostics.page_origin else ''

    def stage(name, assertion=None):
        if 'stage' in evidence:
            evidence['timings'].append({'stage': evidence['stage'], 'seconds': round(time.monotonic() - stage.started, 2)})
        evidence.update(stage=name, assertion=assertion)
        stage.started = time.monotonic()

    def wait_state(ready):
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            evidence['readiness'] = browser.evaluate(DOM)
            if ready(evidence['readiness']):
                return
            time.sleep(.2)
        raise RuntimeError('Render state deadline exceeded')

    stage('browser startup', 'Chrome DevTools connects')
    try:
        with browser:
            stage('public navigation', 'Pages loads with the verified API configuration')
            browser.call('Network.enable')
            browser.call('Log.enable')
            browser.call('Fetch.enable')
            browser.call('Page.navigate', {'url': page_url + '?release=' + expected[:12]})
            browser.wait(
                f"location.href === {json.dumps(page_url + '?release=' + expected[:12])} && "
                f"typeof configuredApi !== 'undefined' && configuredApi === {json.dumps(configured_api)}",
                'public Pages and API configuration', seconds=wait_seconds,
            )

            stage('anonymous denial', 'Sign-in is required and anonymous /api/state returns 401')
            wait_state(lambda view: view['sign_in'] == 'required')
            if browser.evaluate("fetch(configuredApi + '/api/state', {redirect:'error'}).then(r => r.status)") != 401:
                raise RuntimeError('Anonymous response did not deny access')

            stage('authenticated landing', 'Sign-in opens Portfolio directly')
            browser.fill_key(key, configured_api)
            wait_state(lambda view: view['sign_in'] == 'connected' and view['workspace'] == 'portfolio')

            stage('release identity', 'Browser API fingerprint matches the checked-out release')
            if browser.evaluate(f"api('release').then(r => r.source_fingerprint === {json.dumps(expected)})") is not True:
                raise RuntimeError('Browser source fingerprint did not match')

            terminal_periods = ('chart ready', 'coverage unavailable')
            for period, title in (('today', 'Today'), ('week', 'Last 7 days')):
                stage(title, 'Performance metrics and chart or explicit coverage state render')
                wait_state(lambda view: view[period] in terminal_periods)

            stage('holding advice', 'Every held position has an advice label and reason')
            wait_state(lambda view: view['advice'] in ('rendered', 'no holdings'))

            stage('Candidates', 'Candidates and keep-or-switch reach valid terminal states')
            browser.evaluate("window.smokePreviousReviews = dailyView; document.querySelector('[data-tab=candidates]').click()")
            wait_state(lambda view: view['workspace'] == 'candidates' and view['reviews_refreshed']
                       and view['candidates'] in ('ranked', 'stale or unavailable', 'coverage unavailable', 'empty')
                       and view['switch'] in ('comparison ready', 'no qualifier', 'unavailable'))

            stage('return to Portfolio', 'Portfolio is visible with both performance sections')
            browser.evaluate("document.querySelector('[data-tab=portfolio]').click()")
            wait_state(lambda view: view['workspace'] == 'portfolio' and
                       all(view[period] in terminal_periods for period in ('today', 'week')))
            stage('browser integrity', 'No uncaught exceptions or blocked requests')
            if browser.errors or diagnostics.blocked:
                raise RuntimeError('Browser reported an exception or blocked request')
        stage('complete')
        evidence['result'] = 'passed'
    except Exception as error:
        # DevTools exceptions can embed arbitrary script text. Record only the
        # exception type and the independently assigned assertion.
        evidence.update(result='failed', error=type(error).__name__)
        if evidence['stage'] == 'browser startup':
            evidence['chrome_exit_code'] = browser.startup_exit_code
    finally:
        evidence['timings'].append({'stage': evidence['stage'], 'seconds': round(time.monotonic() - stage.started, 2)})
        evidence.update(finished_at=utc_now(), requests=list(diagnostics.requests),
                        console_errors=list(diagnostics.console), browser_startup=startup_messages(browser.startup_output))
    return evidence['result'] == 'passed'


def journal(since):
    # Emit matching HTTP access entries only. Strip client addresses, queries
    # and message text on Oracle before anything crosses SSH.
    start = max(since, int(time.time()) - 300)
    result = subprocess.run(
        ['sudo', '-n', 'journalctl', '-u', 'northstar.service', '--since', f'@{start}',
         '--lines', '200', '--output', 'json', '--no-pager'],
        capture_output=True, text=True, timeout=10,
    )
    entries = deque(maxlen=40)
    for line in result.stdout.splitlines():
        row = json.loads(line)
        match = re.search(r'\] "(GET|HEAD|OPTIONS) (/api/[a-z/-]+)(?:\?[^ ]*)? HTTP/1\.[01]" ([1-5][0-9]{2}) ', row.get('MESSAGE', ''))
        if match and match[2] in API_PATHS:
            timestamp = datetime.fromtimestamp(int(row['__REALTIME_TIMESTAMP']) / 1e6, timezone.utc)
            entries.append({'at': timestamp.isoformat(timespec='seconds'),
                            'method': match[1], 'path': match[2], 'status': int(match[3])})
    return {'since_epoch': start, 'available': result.returncode == 0, 'entries': list(entries)}


def probe_deadline(signum, frame):
    raise TimeoutError('Live browser probe deadline exceeded')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--page-url')
    parser.add_argument('--api-origin')
    parser.add_argument('--evidence', type=Path)
    parser.add_argument('--journal-since', type=int)
    args = parser.parse_args()
    if args.journal_since is not None:
        try:
            print(json.dumps(journal(args.journal_since), indent=2))
        except (OSError, ValueError, subprocess.TimeoutExpired):
            print(json.dumps({'available': False, 'entries': []}))
        return
    page = urlsplit(args.page_url or '')
    api = urlsplit(args.api_origin or '')
    if (not args.evidence or page.scheme != 'https' or not page.hostname or not page.path.endswith('/')
            or api.scheme != 'https' or not api.hostname or api.path not in ('', '/')
            or any(part.username or part.password or part.query or part.fragment for part in (page, api))):
        parser.error('Supply the HTTPS Pages URL, HTTPS API origin and evidence destination.')
    evidence = {'source_fingerprint': release_info.fingerprint(), 'started_at': utc_now(), 'timings': []}
    key = sys.stdin.readline(1024).strip()
    if not KEY_PATTERN.fullmatch(key):
        evidence.update(result='failed', stage='browser credential', assertion='Private access key is available')
    else:
        signal.signal(signal.SIGALRM, probe_deadline)
        signal.alarm(145)
        try:
            run(args.page_url, origin(args.api_origin), key, evidence)
        finally:
            signal.alarm(0)
    args.evidence.write_text(json.dumps(evidence, indent=2) + '\n')
    print(f"Live smoke: {evidence['result']} at {evidence['stage']}.")
    if evidence['result'] != 'passed':
        sys.exit(1)


if __name__ == '__main__':
    main()
