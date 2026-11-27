"""Authenticated browser flow against synthetic data using the real application code."""
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from browser_fixture import Fixture, seed_candidates, seed_today, session_timestamp
from browser_client import Browser
from smoke_live_browser import run as run_live_probe
from northstar import release_info
import app
from northstar import advice_state
from northstar import research


def press_enter(browser):
    browser.call('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    browser.call('Input.dispatchKeyEvent',{'type':'char','key':'Enter','code':'Enter','text':'\r','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    browser.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})


def prove_holding_advice(browser):
    report = app.read_meta('report')
    preferences = app.read_meta('portfolio_preferences')
    signals = app.read_meta('signal_state', {})
    original = next(p for p in app.state()['positions'] if p['symbol'] == 'SYNTH.OL')
    original['long_term'] = bool(original['long_term'])
    current = {**preferences, 'max_stock_pct': 100, 'max_sector_pct': 100, 'reserve_pct': 0,
               'review_sell_pct': 50, 'confirm_sessions': 1, 'signal_wait_hours': 0}
    quote = app.state()['quotes']['SYNTH.OL']

    def report_for(position):
        return {**report, 'cards': [research.screen('SYNTH.OL', quote, position)]}

    def check(*phrases):
        browser.evaluate('loadDaily()')
        checks = ' && '.join('cell.textContent.includes(' + json.dumps(phrase) + ')' for phrase in phrases)
        browser.wait("(() => { const cell = document.querySelector('#holdings [data-holding-advice]');"
                     "return cell && cell.getClientRects().length && " + checks + "; })()",
                     'Portfolio holding advice: ' + ', '.join(phrases))

    try:
        app.write_meta('portfolio_preferences', current)
        app.write_meta('report', report_for(original))
        check('Hold', 'No confirmed sell trigger')
        browser.evaluate("document.querySelector('#holdings [data-plan-sale]').click()")
        browser.wait("document.querySelector('#salePlanner').open && document.querySelector('#salePlannerPolicy').textContent.startsWith('Current Northstar recommendation: Hold ·')",'sale planner opens from a holding marked Hold')
        browser.evaluate("document.querySelector('#closeSalePlanner').click()")
        app.write_meta('portfolio_preferences', {**current, 'max_stock_pct': 20})
        check('Sell review', '20.0% position limit', '1 share', '33.33%')
        app.write_meta('portfolio_preferences', {**current, 'max_sector_pct': 20})
        app.save_position({**original, 'shares': 3.5})
        check('Sell review', '20.0% sector limit', 'Sizing unavailable', 'Reconcile holdings and cash')
        app.write_meta('portfolio_preferences', current)
        lower = {**original, 'below': 140}
        app.save_position(lower)
        technical = report_for(lower)
        app.write_meta('report', technical)
        app.write_meta('signal_state', {})
        check('Insufficient data', 'Waiting for a matching dated signal')
        app.write_meta('signal_state', advice_state.observe(technical, {}))
        check('Sell review', 'Lower review price', '140', '2 shares', '66.67%')
        upper = {**original, 'above': 120}
        app.save_position(upper)
        technical = report_for(upper)
        app.write_meta('report', technical)
        app.write_meta('signal_state', advice_state.observe(technical, {}))
        check('Sell review', 'Upper review price', '120', '2 shares', '66.67%')
        app.write_meta('portfolio_preferences', {**current, 'review_sell_pct': 0})
        check('Sell review', 'Sizing unavailable', '0%')
        app.write_meta('report', {**report, 'cards': []})
        check('Insufficient data', 'No current technical assessment')
    finally:
        app.save_position(original)
        app.write_meta('portfolio_preferences', preferences)
        app.write_meta('report', report)
        app.write_meta('signal_state', signals)
        browser.evaluate('loadDaily()')


def check_remembered_browser(fixture):
    def visit(browser):
        browser.call('Page.navigate', {'url': fixture.origin})
        browser.wait("document.readyState==='complete' && Boolean(document.querySelector('#connectionPanel'))", 'dashboard loaded')

    with TemporaryDirectory(prefix='northstar-restart-') as profile:
        with Browser(profile) as browser:
            visit(browser)
            browser.wait("!document.querySelector('#connectionPanel').hidden", 'anonymous sign-in')
            browser.evaluate("document.querySelector('#rememberBrowser').click()")
            browser.fill_key(fixture.key)
            browser.wait("document.querySelector('#accountStatus').textContent==='Connected'", 'remembered sign-in')
            if browser.evaluate("Boolean(sessionStorage.getItem('northstar-key')) || !localStorage.getItem('northstar-remembered-session')"):
                raise RuntimeError('Remembered sign-in did not replace the access key with a session token.')
        with Browser(profile) as browser:
            visit(browser)
            browser.wait("document.querySelector('#accountStatus').textContent==='Connected' && document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#holdings').textContent.includes('SYNTH.OL')", 'remembered sign-in after complete Chrome restart')
            browser.evaluate("document.querySelector('#connectionButton').click();document.querySelector('#disconnect').click()")
            browser.wait("!document.querySelector('#connectionPanel').hidden && !localStorage.getItem('northstar-remembered-session') && !document.querySelector('#holdings').textContent.includes('SYNTH.OL')", 'remembered sign-out')
        with Browser(profile) as browser:
            visit(browser)
            browser.wait("!document.querySelector('#connectionPanel').hidden && document.querySelector('#accountStatus').textContent==='Not connected'", 'sign-in required after restarting following sign-out')
    print('Remembered sign-in and sign-out passed across complete Chrome restarts.')


def prove_funded_switch(browser, report):
    prefs = app.read_meta('portfolio_preferences')
    signals = app.read_meta('signal_state')
    original_quote = app.state()['quotes']['SYNTH.OL']
    now = time.time()
    sale = {**report['cards'][0], 'symbol': 'SYNTH.OL', 'name': 'Synthetic holding',
            'action': 'Consider reducing / selling',
            'rank_eligible': False, 'price': 100, 'asof': now}
    app.write_meta('report', {**report, 'cards': [*report['cards'], sale]})
    app.write_meta('signal_state', {**signals, 'SYNTH.OL': {
        'policy_version': app.decision_policy.VERSION, 'intent': 'sell',
        'since': now-3*86400, 'sessions': ['2026-01-02', '2026-01-05']}})
    with app.connect() as db:
        db.execute('UPDATE quotes SET payload=? WHERE symbol=?',
                   (json.dumps({**original_quote, 'price': 100, 'asof': now}), 'SYNTH.OL'))

    settings = {**prefs, 'purchase_nok': 120, 'buy_fee_nok': 2, 'sell_fee_nok': 5,
                'max_buy_fee_pct': 5, 'max_stock_pct': 90, 'max_sector_pct': 100, 'reserve_pct': 0}
    app.write_meta('portfolio_preferences', settings)
    browser.evaluate("document.querySelector('#candidateCash').value=17; document.querySelector('#candidateCashForm').requestSubmit()")
    browser.wait("""(() => {
        const comparison = document.querySelector('#switchComparison table');
        if (!comparison || !comparison.checkVisibility()) return false;
        const rows = Array.from(comparison.tBodies[0].rows,
            row => Array.from(row.cells, cell => cell.textContent));
        return JSON.stringify(rows) === JSON.stringify([
            ['SYNTH.OL shares sold', '0', '1'],
            ['IDEA1.OL shares bought', '0', '11'],
            ['Sale fee', money(0), money(5)],
            ['Purchase fee', money(0), money(2)],
            ['Cash after trades', money(17), money(0)],
            ['SYNTH.OL company weight', '94.6%', '64.5%'],
            ['IDEA1.OL company weight', '0.0%', '35.5%'],
            ['Industrials sector weight', '94.6%', '64.5%'],
            ['Energy sector weight', '0.0%', '35.5%'],
        ]);
    })()""", 'funded switch spends all preview cash including fees and respects concentration')

    if app.read_meta('portfolio_preferences')['cash_nok'] != prefs['cash_nok']:
        raise RuntimeError('Preview modified recorded cash.')
    for changes, label, reason in (
        ({'reserve_pct': 98}, 'No switch qualifies', ''),
        ({'sell_fee_nok': None}, 'Comparison unavailable', 'Enter a sell-fee assumption'),
        ({'sell_fee_nok': 100}, 'No switch qualifies', ''),
        ({'sectors': {'SYNTH.OL': 'Industrials'}}, 'Comparison unavailable', 'Classify this stock'),
        ({'max_stock_pct': 10}, 'No switch qualifies', ''),
    ):
        app.write_meta('portfolio_preferences', {**settings, **changes})
        browser.evaluate('loadDaily()')
        browser.wait("document.querySelector('#switchStatus').textContent.includes("+json.dumps(label)+
                     ") && document.querySelector('#switchStatus').textContent.includes("+json.dumps(reason)+
                     ") && !document.querySelector('#switchComparison table')", label+' '+reason+' '+str(changes))

    browser.evaluate("document.querySelector('#candidateCashReset').click()")
    app.write_meta('portfolio_preferences', prefs)
    app.write_meta('signal_state', signals)
    app.write_meta('report', report)
    with app.connect() as db:
        db.execute('UPDATE quotes SET payload=? WHERE symbol=?', (json.dumps(original_quote), 'SYNTH.OL'))


def prove_portfolio_and_candidates():
    from unittest.mock import patch

    with Fixture() as fixture, Browser() as browser:
        browser.call('Page.navigate', {'url': fixture.origin+'/'})
        browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden", 'sign-in panel')
        browser.fill_key(fixture.key)
        browser.wait("document.querySelector('#accountStatus').textContent==='Connected' && "
                     "document.querySelector('[data-tab=portfolio][aria-current=page]') && "
                     "document.querySelector('#todayTitle').checkVisibility() && !location.hash",
                     'signed-in Portfolio landing with visible Today section')
        original_report = app.read_meta('report')
        report = seed_candidates()
        browser.evaluate("document.querySelector('[data-tab=candidates]').focus()")
        press_enter(browser)
        browser.wait("document.querySelector('#workspaceTitle').textContent==='Candidates' && "
                     "document.querySelector('#buyCandidates').checkVisibility() && "
                     "document.querySelectorAll('#buyCandidates article').length===5",
                     'Portfolio to Candidates via keyboard and real shared-budget response')
        expected = [[f'IDEA{rank}.OL', str(rank), sector] for rank, sector in enumerate(
            ('Energy', 'Materials', 'Health care', 'Financials', 'Utilities'), 1)]
        cards = browser.evaluate("""Array.from(document.querySelectorAll('#buyCandidates article'), card => [
            card.querySelector('button').dataset.candidateStock,
            card.querySelector('.candidate-rank').textContent,
            card.querySelector('p').textContent
        ])""")
        if not all(actual[:2] == wanted[:2] and 'Fits your '+wanted[2]+' sector' in actual[2]
                   for actual, wanted in zip(cards, expected)):
            raise RuntimeError('Ranked candidates or portfolio reasons differ: '+str(cards))
        prove_funded_switch(browser, report)

        browser.evaluate("document.querySelector('[data-tab=portfolio]').click()")
        browser.wait("document.querySelector('#todayTitle').checkVisibility()", 'Candidates back to Portfolio')
        def candidate_state(payload, expected_status):
            app.write_meta('report', payload)
            browser.evaluate("document.querySelector('[data-tab=candidates]').click()")
            browser.wait("document.querySelector('#buyCandidatesStatus').textContent.includes("+json.dumps(expected_status)+
                         ") && !document.querySelector('#buyCandidates article')", expected_status)
        candidate_state({**report, 'generated': time.time()-2*86400}, 'Research is stale')
        candidate_state({**report, 'cards': [], 'coverage': {'unavailable': 1}}, 'lack usable research evidence')
        candidate_state({**report, 'cards': [], 'coverage': {'unavailable': 0}}, 'No eligible buying candidates')
        app.write_meta('report', report)
        browser.evaluate("document.querySelector('[data-tab=candidates]').click()")
        browser.wait("document.querySelectorAll('#buyCandidates button').length===5", 'candidates recover after fresh research')
        browser.evaluate("document.querySelector('#buyCandidates button').focus()")
        press_enter(browser)
        browser.wait("document.querySelector('#workspaceTitle').textContent==='Candidates' && "
                     "document.querySelector('#candidateMarket .plot-caption strong')?.textContent==='IDEA1.OL'",
                     'rank-one candidate opens the candlestick chart by keyboard')
        start_span = browser.evaluate("""(() => {
            const plot = workspacePlots.get(document.querySelector('#candidateMarket')).chart.timeScale();
            const range = plot.getVisibleLogicalRange();
            return range.to-range.from;
        })()""")
        browser.evaluate("document.querySelector('#candidateMarket [data-plot=fit]').click()")
        browser.wait("""(() => {
            const plot = workspacePlots.get(document.querySelector('#candidateMarket')).chart.timeScale();
            const range = plot.getVisibleLogicalRange();
            return range.to-range.from >= 119;
        })()""", 'fit spans all available market history')
        browser.evaluate("document.querySelector('#candidateMarket [data-plot=latest]').click()")
        browser.wait(f"""(() => {{
            const plot = workspacePlots.get(document.querySelector('#candidateMarket')).chart.timeScale();
            const range = plot.getVisibleLogicalRange();
            return Math.abs(range.to-range.from-{start_span}) < 1;
        }})()""", 'latest restores the initial chart window')
        browser.evaluate("document.querySelector('#candidateResearch').click()")
        browser.wait("document.querySelector('#workspaceTitle').textContent==='Research' && explorerSymbol==='IDEA1.OL'",
                     'Research tools open the selected company')
        app.write_meta('report', original_report)

        seed_today(1300, [('deposit', 10000, 0)])
        provider_quotes = app.state()['quotes']
        view = app.account_performance.view
        now = session_timestamp('2025-01-06T16:01')
        with patch.object(app.account_performance, 'view', side_effect=lambda *args, **kwargs: view(*args, **kwargs, now=now)):
            browser.evaluate("document.querySelector('[data-tab=portfolio]').click()")

            def wait_today(account, performance, percent, cash):
                assertion = f"""(() => {{
                    const metrics = Array.from(document.querySelectorAll('#todayMetrics strong'), n => n.textContent);
                    const signed = value => (value > 0 ? '+' : '') + money(value);
                    return metrics[0] === money({account}) &&
                        metrics[1] === signed({performance}) + ' · ' + {json.dumps(percent)} &&
                        metrics[2] === signed({cash}) && Boolean(document.querySelector('#todayChart canvas'));
                }})()"""
                try:
                    browser.wait(assertion, f'Today value {account}, return {performance} ({percent}), flow {cash}, and chart')
                except RuntimeError as error:
                    actual = browser.evaluate("Array.from(document.querySelectorAll('#todayStatus, #todayMetrics strong'), n => n.textContent)")
                    raise RuntimeError(f'{error}. Displayed {actual}') from error

            wait_today(111000, 1000, '+1.0%', 10000)
            browser.wait("document.querySelector('#overviewMove').textContent === money(1000) + ' · 1.00%' && document.querySelector('#overviewMoveMeta').textContent.includes('External cash flows excluded')",
                         'Overview shows the same flow-adjusted movement as Today')
            browser.wait("""document.querySelector('#todayStatus').textContent.includes('2025-01-06 (Europe/Oslo)') &&
                workspacePlots.get(document.querySelector('#todayChart')).chart.panes()[0].getSeries()[0]
                    .data().map(bar=>new Date(bar.time*1000).toISOString().slice(0,10)).join() === '2025-01-02,2025-01-03,2025-01-06' &&
                document.querySelector('#todayMetrics').textContent.includes('day end') &&
                Array.from(document.querySelectorAll('#todayHoldings tbody tr')).find(row => row.textContent.includes('USDTEST')).textContent.includes('+10.0%')
                """, 'dated close-to-quote basis, end-of-day assumption and USD FX move')

            browser.wait("document.querySelector('#todayChart .plot-window').textContent.startsWith('2 Jan')",
                         'Portfolio chart opens on the full available history')
            browser.evaluate("document.querySelector('#todayChart [data-plot=in]').click()")
            browser.wait("document.querySelector('#todayChart .plot-window').textContent.startsWith('3 Jan')",
                         'Portfolio chart zooms in')
            browser.evaluate("document.querySelector('#todayChart [data-plot=fit]').click()")
            browser.wait("document.querySelector('#todayChart .plot-window').textContent.startsWith('2 Jan')",
                         'Portfolio chart fits the full history again')

            now = session_timestamp('2025-01-06T16:30')
            seed_today(1000, [('buy', -1000, 1), ('withdrawal', -2000, 0), ('dividend', 50, 0), ('fee', -30, 0)])
            browser.evaluate('loadOverviewAccount()')
            wait_today(98120, 120, '+0.1%', -2000)
            browser.wait("""Array.from(document.querySelectorAll('#todayHoldings tbody tr'))
                .find(row => row.textContent.includes('SYNTH.OL')).cells[1].textContent === money(0)
                """, 'unchanged per-share movement after buying another share')

            seed_today(1000, [], quote_date='2025-01-03')
            for local_time in ('2025-01-05T15:00', '2025-01-06T00:30', '2025-01-06T08:50', '2025-01-06T09:05'):
                now = session_timestamp(local_time)
                browser.evaluate('loadOverviewAccount()')
                browser.wait("document.querySelector('#todayStatus').textContent.includes('Last completed session 2025-01-03')",
                             'dated completed session on closure, at Oslo date boundary and before the first quote')
                wait_today(100000, 0, '0.0%', 0)
                browser.wait("document.querySelector('#overviewMove').textContent === money(0) + ' · 0.00%' && document.querySelector('#overviewMoveMeta').textContent.includes('Last completed session 2025-01-03')",
                             'Overview identifies the completed session across closures and before opening')

            now = session_timestamp('2025-01-06T16:30')
            browser.evaluate('loadOverviewAccount()')
            browser.wait("""document.querySelector('#todayStatus').textContent.includes('missing session quote on 2025-01-06') &&
                Boolean(document.querySelector('#todayChart canvas'))""", 'missing open-session quote coverage gap')

            seed_today(1300, [('deposit', 10000, 0)], quote_date='2025-01-03')
            with patch.object(app, 'fetch_quote', side_effect=provider_quotes.__getitem__):
                browser.evaluate("document.querySelector('#refreshToday').click()")
                wait_today(111000, 1000, '+1.0%', 10000)
            now = session_timestamp('2025-01-15T17:00')
            close_dates = ('2025-01-08', '2025-01-09', '2025-01-10', '2025-01-13', '2025-01-14')
            weekly_events = [('deposit', 10000, 0, '2025-01-09'), ('buy', -1300, 1), ('withdrawal', -2000, 0),
                             ('dividend', 50, 0), ('fee', -30, 0)]
            seed_today(1300, weekly_events, quote_date='2025-01-15', session_date='2025-01-15',
                       close_dates=close_dates)
            browser.evaluate('loadOverviewAccount()')
            browser.wait("""(() => {
                const status = document.querySelector('#weekStatus').textContent;
                const metrics = Array.from(document.querySelectorAll('#weekMetrics strong'), n => n.textContent);
                const series = workspacePlots.get(document.querySelector('#weekChart'))?.chart.panes()[0].getSeries()[0];
                const points = series?.data() || [];
                const holdings = document.querySelector('#weekHoldings').textContent;
                return status.includes('2025-01-09 to 2025-01-15 (Europe/Oslo)') &&
                    status.includes('Prior closes carried on 2025-01-11, 2025-01-12') &&
                    metrics[0] === '+' + money(1020) + ' · +0.9%' &&
                    metrics[1] === '+' + money(8000) &&
                    points[0]?.time === Date.parse('2025-01-08')/1000 &&
                    points.at(-1)?.time === Date.parse('2025-01-15')/1000 &&
                    points.length === 8 && points.slice(2, 5).every(point => point.value === points[2].value) &&
                    holdings.includes('+30.0%') && holdings.includes('+10.0%');
            })()""", 'Wednesday window, carried weekend closes, cash flows, and share-count-independent NOK holding moves')

            browser.evaluate("document.querySelector('[data-tab=daily]').click()")
            browser.wait("document.querySelector('#overviewChart .trading-plot canvas')?.checkVisibility()",
                         'Overview charts the recorded account value')
            browser.wait("workspacePlots.get(document.querySelector('#overviewChart'))?.chart.panes()[0].getSeries()[0]"
                         ".data().at(-1).value === 109020", 'Overview includes recorded flows in account value')
            browser.evaluate("document.querySelector('#overviewChart .trading-plot').focus()")
            browser.call('Input.dispatchKeyEvent', {'type':'keyDown','key':'End'})
            browser.wait("document.querySelector('#overviewChart .plot-purchases').textContent.includes('Bought 1 SYNTH.OL')",
                         'ledger buy at the valuation point')

            seed_today(1300, weekly_events, quote_date='2025-01-15', session_date='2025-01-15',
                       close_dates=tuple(day for day in close_dates if day != '2025-01-13'))
            browser.evaluate('loadOverviewAccount()')
            browser.wait("""document.querySelector('#weekStatus').textContent.includes('missing close on 2025-01-13') &&
                document.querySelector('#weekMetrics strong').textContent.includes('Unavailable') &&
                !document.querySelector('#weekChart canvas')""", 'missing Monday close is a coverage gap')
            seed_today(1300, weekly_events, quote_date='2025-01-14', session_date='2025-01-15',
                       close_dates=close_dates)
            browser.evaluate('loadOverviewAccount()')
            browser.wait("""document.querySelector('#weekStatus').textContent.includes('missing session quote on 2025-01-15') &&
                !document.querySelector('#weekChart canvas')""", 'missing Wednesday session quote is a coverage gap')
        if browser.errors:
            raise RuntimeError('Uncaught browser error during Portfolio and Candidates checks.')
    print('Synthetic Portfolio landing, Today and Last 7 days figures and coverage, '
          'and Candidates navigation, ranking, and funded switch states passed.')


def prove_live_probe_evidence():
    def probe(fixture, succeeded, stage):
        evidence = {'source_fingerprint': release_info.fingerprint(), 'timings': []}
        if run_live_probe(fixture.origin + '/', fixture.origin, fixture.key, evidence, wait_seconds=5) != succeeded:
            raise RuntimeError('Unexpected result for the production probe: ' + json.dumps(evidence))
        if evidence['stage'] != stage:
            raise RuntimeError('Unexpected failure stage for the production probe: ' + json.dumps(evidence))
        encoded = json.dumps(evidence)
        if any(private in encoded for private in (fixture.key, 'SYNTH.OL', 'private-diagnostic-marker')):
            raise RuntimeError('Production probe evidence contained private fixture data.')
        return evidence

    with Fixture() as fixture, TemporaryDirectory() as directory:
        success = probe(fixture, True, 'complete')
        if not any(r['path'] == '/api/state' and r['status'] == 401 for r in success['requests']):
            raise RuntimeError('Production probe omitted anonymous denial evidence.')

        # Simulate a server response that cannot render holding advice.
        with patch.object(app, 'daily_view', return_value={'error': 'private-diagnostic-marker'}):
            failure = probe(fixture, False, 'holding advice')
        if failure['readiness']['advice'] != 'reviews pending or failed':
            raise RuntimeError('Production probe omitted the app failure state.')

        chrome = Path(directory) / 'chrome'
        chrome.write_text('#!/bin/sh\nprintf "No usable sandbox private-diagnostic-marker\\n" >&2\nexit 42\n')
        chrome.chmod(0o700)
        with patch('browser_client.shutil.which', return_value=str(chrome)):
            failure = probe(fixture, False, 'browser startup')
        if failure['browser_startup'] != ['No usable sandbox'] or failure['chrome_exit_code'] != 42:
            raise RuntimeError('Production probe omitted Chrome startup evidence.')
        if any(method == 'POST' for method, _, _ in fixture.requests):
            raise RuntimeError('The production probe sent a write to the synthetic service.')
    print('Production probe passed on synthetic data and distinguished Chrome startup from app failure.')


def run():
    prove_live_probe_evidence()
    with Fixture() as fixture:
        check_remembered_browser(fixture)
    prove_portfolio_and_candidates()
    with Fixture() as fixture,Browser() as browser:
        for width,height in ((1440,1000),(390,900)):
            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
            browser.call('Page.navigate',{'url':fixture.origin+'/?smoke_width='+str(width)})
            browser.wait("document.readyState==='complete' && location.search==='?smoke_width="+str(width)+"'",'fresh browser navigation')
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden",'sign-in panel')
            browser.fill_key(fixture.key)
            browser.wait("document.querySelector('#connectionPanel').hidden && document.querySelector('#holdings').textContent.includes('SYNTH.OL') && document.querySelector('#accountStatus').textContent==='Connected'",'authenticated account context')
            browser.evaluate('loadDaily()')
            browser.wait("document.querySelector('#dailyStatus').textContent.startsWith('Updated') && document.querySelector('#holdingAssessments').textContent.includes('Policy result:') && !document.querySelector('#buyCandidatesStatus').textContent.includes('Loading eligible candidates')",'authenticated holding assessment and buying-candidate response')
            browser.wait("!document.querySelector('#overviewAccountStatus').textContent.includes('Loading')",'current account summary response')
            browser.wait("document.querySelector('#researchStatus').textContent.includes('Last report:') && document.querySelector('#workspaceTitle').textContent==='Portfolio' && !document.querySelector('#portfolio').hidden",'authenticated Portfolio landing')
            if browser.evaluate("document.querySelector('#overviewValue').textContent==='Unavailable' || document.querySelector('#overviewValue').textContent==='—'"):
                raise RuntimeError('Current account value unavailable: '+str(browser.evaluate("document.querySelector('#overviewValueMeta').textContent+' '+document.querySelector('#overviewAccountStatus').textContent")))
            if browser.evaluate("document.querySelector('#overviewPnl').textContent==='Unavailable'"):
                raise RuntimeError('Verified historical investment P&L unavailable: '+str(browser.evaluate("document.querySelector('#overviewPnlMeta').textContent+' '+document.querySelector('#overviewAccountStatus').textContent")))
            expected_value="new Intl.NumberFormat('nb-NO',{style:'currency',currency:'NOK',maximumFractionDigits:2}).format("+str(fixture.expected_current_value_nok)+")"
            if not browser.evaluate("document.querySelector('#overviewValue').textContent==="+expected_value):
                raise RuntimeError('Current value does not match synthetic holdings plus recorded cash.')
            if not browser.evaluate("document.querySelector('#overviewValueMeta').textContent.includes('NOK cash') && document.querySelector('#overviewValueMeta').textContent.includes('reporting date') && document.querySelector('#overviewPnlMeta').textContent.includes(' to ')"):
                raise RuntimeError('Overview account dates, cash scope or price basis are missing.')
            with app.connect() as db:
                row=db.execute('SELECT payload FROM quotes WHERE symbol=?',('SYNTH.OL',)).fetchone()
                original_quote=json.loads(row['payload'])
                stale_quote={**original_quote,'asof':time.time()-5*86400}
                db.execute('UPDATE quotes SET payload=? WHERE symbol=?',(json.dumps(stale_quote),'SYNTH.OL'))
            browser.evaluate('loadOverviewAccount()')
            browser.wait("document.querySelector('#overviewValue').textContent==='Unavailable' && document.querySelector('#overviewAccountStatus').textContent.includes('refresh for a current quote')",'incomplete current quote coverage')
            with app.connect() as db:
                db.execute('UPDATE quotes SET payload=? WHERE symbol=?',(json.dumps(original_quote),'SYNTH.OL'))
            browser.evaluate('loadOverviewAccount()')
            browser.wait("document.querySelector('#overviewValue').textContent === "+expected_value, 'account valuation recovery')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.wait("!document.querySelector('#portfolio').hidden && !document.querySelector('#portfolioAdvanced').open && document.querySelector('#workspaceTitle').textContent==='Portfolio'", 'Portfolio landing page')
            prove_holding_advice(browser)
            if width==1440:
                browser.evaluate("document.querySelector('#holdings [data-edit]').click();const field=document.querySelector('#positionForm').elements.review;field.value='Unsaved reload draft';field.dispatchEvent(new Event('input',{bubbles:true}))")
                browser.reload()
                browser.wait("document.querySelector('#editor').open && document.querySelector('#positionForm').elements.review.value==='Unsaved reload draft'",'holding edit draft restoration')
                if not browser.evaluate("document.querySelector('#positionForm').elements.symbol.readOnly"):
                    raise RuntimeError('Reloaded holding edit draft lost its protected ticker field.')
                browser.evaluate("document.querySelector('#close').click()")
            browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Overview'", 'return to Overview')
            if not browser.evaluate("document.querySelector('#workspaceTitle').textContent==='Overview' && document.querySelector('#overviewMetrics').parentElement.id==='daily' && document.querySelector('[data-tab][aria-current=page]').textContent.trim()==='Overview'"):
                raise RuntimeError('Overview account/section orientation failed.')
            if not browser.evaluate("['overviewAdvanced','researchAdvanced','portfolioAdvanced','strategyAdvanced'].every(id=>{const details=document.getElementById(id);return details&&!details.open&&details.querySelector(':scope > summary').textContent.trim()==='Advanced tools'})"):
                raise RuntimeError('Each workspace must start with one collapsed Advanced tools disclosure.')
            browser.evaluate("document.querySelector('#overviewAdvanced > summary').focus()")
            press_enter(browser)
            if not browser.evaluate("document.querySelector('#overviewAdvanced').open && document.activeElement.matches('#overviewAdvanced > summary') && getComputedStyle(document.activeElement).outlineStyle==='solid'"):
                raise RuntimeError('Advanced tools disclosure did not open with visible keyboard focus.')
            press_enter(browser)
            if width<600 and not browser.evaluate("""(() => {
                const items = Array.from(document.querySelectorAll('.workspace-nav [data-tab]'),
                    button => button.getBoundingClientRect());
                return items.length === 3 && items.every(item => item.top === items[0].top &&
                    item.left >= 0 && item.right <= innerWidth);
            })()"""):
                raise RuntimeError('Mobile workspace navigation does not fit on one row.')
            browser.evaluate("openWorkspace('accountPerformance')")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#portfolioAdvanced').open && document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'Overview to detailed account performance')
            browser.wait("!!document.querySelector('[data-plan-sale=\"SYNTH.OL\"]')",'sale planner button on the loaded holding')
            browser.evaluate("document.querySelector('[data-plan-sale=\"SYNTH.OL\"]').click()")
            browser.wait("document.querySelector('#salePlanner').open && document.querySelector('#salePlannerTitle').textContent.includes('SYNTH.OL') && document.querySelector('#salePlannerPolicy').textContent.startsWith('Current Northstar recommendation: Sell review ·')",'sale planner shows the current position-limit review')
            browser.wait("document.querySelector('#salePlannerResult').textContent.includes('Shares to sell: 1.')",'trim one share to reach the configured 20% stock limit')
            browser.evaluate("""(() => {
                const form = document.querySelector('#salePlannerForm');
                form.elements.goal.value = 'cash';
                form.elements.cash.value = '200';
                form.elements.cash.dispatchEvent(new Event('input', {bubbles: true}));
            })()""")
            browser.wait("document.querySelector('#salePlannerResult').textContent.includes('Shares to sell: 2.') && document.querySelector('#salePlannerResult').textContent.includes('Net proceeds are unconfirmed')",'200 NOK gross cash goal with an unknown fee')
            browser.evaluate("""(() => {
                const form = document.querySelector('#salePlannerForm');
                form.elements.goal.value = 'exit';
                form.elements.timing.value = 'limit';
                form.elements.limit.value = '150';
                form.elements.limit.dispatchEvent(new Event('input', {bubbles: true}));
            })()""")
            browser.wait("document.querySelector('#salePlannerResult').textContent.includes('Shares to sell: 3.') && document.querySelector('#salePlannerResult').textContent.includes(money(450))",'full exit at a user-entered 150 NOK limit')
            browser.evaluate("document.querySelector('#closeSalePlanner').click()")
            if not browser.evaluate("document.querySelector('#accountPerformanceMetrics').textContent.includes(money(60))"):
                raise RuntimeError('Detailed performance did not keep the synthetic 100 NOK deposit and 40 NOK withdrawal separate as net contributions.')
            browser.wait("document.querySelector('#fitStatus').textContent.includes('Current portfolio check:') && document.querySelector('#portfolioRiskStatus').textContent.includes('Risk model:')",'portfolio allocation and risk workflows')
            browser.evaluate("document.querySelector('#stockShock').value='-15';document.querySelector('#fxShock').value='-5';document.querySelector('#riskScenarioForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            browser.wait("document.querySelector('#riskScenarios').textContent.includes('Hypothetical assumption')",'portfolio risk scenario calculation')
            browser.evaluate("const budget=document.querySelector('#fitPreferences').elements.purchase_nok;budget.value='4567';budget.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#refreshFit').click()")
            browser.wait("document.querySelector('#fitStatus').textContent.includes('Current portfolio check:') && document.querySelector('#fitPreferences').elements.purchase_nok.value==='4567'",'unsaved allocation edit during refresh')
            browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
            browser.wait("!document.querySelector('#gettingStarted') && !document.querySelector('#refreshOverviewAccount') && !document.querySelector('#daily').textContent.includes('How to use Northstar')", 'Overview omits the three removed sections')
            browser.evaluate("openWorkspace('activity')")
            browser.wait("!document.querySelector('#portfolio').hidden && document.querySelector('#activityGroup').open", 'activity remains available in Portfolio')
            browser.wait("document.querySelector('#dailyStatus').textContent.startsWith('Updated') && document.querySelector('#holdingAssessments').textContent.includes('Policy result:')",'holding assessments after workspace navigation')
            if not browser.evaluate("document.querySelector('#holdingAssessments').textContent.includes('SYNTH.OL') && document.querySelector('#holdingAssessments').textContent.includes('Policy result:') && document.querySelector('#holdingAssessments').textContent.includes('Technical evidence does not')"):
                raise RuntimeError('Holding assessment not loaded: '+str(browser.evaluate("document.querySelector('#dailyStatus').textContent+' | '+document.querySelector('#holdingAssessments').textContent"))+' | daily requests: '+str([r for r in fixture.requests if '/api/daily' in r[1]]))
            def show_reviews(reviews):
                payload={'generated':time.time(),'coverage':{'analysed':1,'requested':1},'announcement_status':'available','top3':reviews[:3],'reviews':reviews,'changes':[],'alerts':[],'email':{'configured':False,'enabled':False,'active':False,'pending':0},'method':'Synthetic review fixture'}
                browser.evaluate('renderDaily('+json.dumps(payload)+')')
            show_reviews([])
            if not browser.evaluate("document.querySelector('#dailyTop').textContent.includes('No actionable review') && document.querySelector('#portfolioReviewEntry').textContent.includes('No actionable reviews')"):
                raise RuntimeError('Successful quiet state was not explicit.')
            missing={'id':'missing','kind':'data','title':'Refresh SYNTH.OL before sizing trades','detail':'Current portfolio valuation is incomplete.'}
            show_reviews([missing])
            if not browser.evaluate("document.querySelector('#dailyTop').innerHTML.includes('data-review-action')"):
                raise RuntimeError('Missing evidence action was not rendered: '+str(browser.evaluate("document.querySelector('#dailyTop').innerHTML")))
            stale={'id':'stale','kind':'data','title':'Refresh the market report','detail':'Current signal evidence is unavailable.'}
            show_reviews([stale])
            if not browser.evaluate("document.querySelector('#portfolioReviewEntry').textContent.includes('Review research status')"):
                raise RuntimeError('Stale report did not prioritize research status.')
            ledger={'id':'ledger','kind':'ledger','title':'Reconcile holdings and cash','detail':'Verify holdings and cash before using the transaction ledger.'}
            show_reviews([ledger])
            if not browser.evaluate("document.querySelector('#dailyTop [data-review-action=ledger]') && document.querySelector('#portfolioReviewEntry').textContent.includes('Fix reconciliation')"):
                raise RuntimeError('Reconciliation blocker was not prominent.')
            browser.evaluate("document.querySelector('#dailyTop [data-review-action=ledger]').focus()")
            if width<600:
                press_enter(browser)
            else:
                browser.evaluate("document.querySelector('#dailyTop [data-review-action=ledger]').click()")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#activityGroup').open",'review action opens reconciliation')
            show_reviews([{'id':'sale','kind':'holding','title':'SYNTH.OL: review 1 share for sale','detail':'Technical sale review. Gross proceeds; sale fee unknown and tax excluded.','symbol':'SYNTH.OL'}])
            browser.evaluate("document.querySelector('#portfolio').hidden=true;document.querySelector('#daily').hidden=false")
            browser.evaluate("document.querySelector('#dailyTop [data-review-action=holding]').click()")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#holdingAssessments').textContent.includes('SYNTH.OL')",'holding review navigation')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.evaluate("document.querySelector('[data-tab=candidates]').click(); document.querySelector('#candidateResearch').closest('details').open=true; document.querySelector('#candidateResearch').focus()")
            if not browser.evaluate("document.activeElement===document.querySelector('#candidateResearch')"):
                raise RuntimeError('Workspace navigation button did not receive keyboard focus.')
            press_enter(browser)
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research' && document.querySelector('[data-tab=candidates]').getAttribute('aria-current')==='page'",'keyboard workspace navigation')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.call('Runtime.evaluate',{'expression':'history.back()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research'",'browser back navigation')
            browser.call('Runtime.evaluate',{'expression':'history.forward()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio'",'browser forward navigation')
            browser.wait("document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'account performance')
            if not browser.evaluate("document.querySelector('#fitPreferences').elements.purchase_nok.value==='4567'"):
                raise RuntimeError('Unsaved allocation edit was lost during browser history navigation.')
            browser.evaluate("openWorkspace('recommendations')")
            browser.wait("Boolean(document.querySelector('#chartPlot svg'))",'research explorer')
            browser.evaluate("document.querySelector('#adviceFilter').value='all';document.querySelector('#adviceFilter').dispatchEvent(new Event('change',{bubbles:true}))")
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click();openWorkspace('recommendations')")
            if not browser.evaluate("document.querySelector('#adviceFilter').value==='all'"):
                raise RuntimeError('Research selection was lost when changing workspaces.')
            if not browser.evaluate("document.querySelectorAll('nav [data-tab]').length===3 && !/NaN|Infinity/.test(document.querySelector('#chartPlot').innerHTML)"):
                raise RuntimeError('Research navigation/chart contract failed.')
            browser.evaluate("openWorkspace('validation')")
            if width==1440:
                started=time.time()
                browser.evaluate("document.querySelector('#validationRobustness').checked=true;document.querySelector('#runValidation').click()")
                deadline=time.time()+120
                while time.time()<deadline:
                    progress=app.read_meta('validation_progress',{})
                    if progress.get('started',0)>=started and not progress.get('running'):
                        break
                    time.sleep(.25)
                if progress.get('started',0)<started or progress.get('running'):
                    raise RuntimeError('Synthetic experiment timed out: '+str(app.read_meta('validation_progress',{})))
                if app.read_meta('validation_progress',{}).get('error'):
                    raise RuntimeError('Synthetic experiment failed: '+str(app.read_meta('validation_progress',{})))
                browser.evaluate('loadValidation()')
                browser.wait("!document.querySelector('#robustnessPanel').hidden",'completed synthetic experiment')
                report=app.read_meta('validation_report',{})
                if report.get('generated',0)<started:
                    raise RuntimeError('Browser did not complete a new experiment: '+str(app.read_meta('validation_progress',{})))
                browser.wait("document.querySelector('#validationFund').textContent.includes('Fund ') && document.querySelector('#validationFund').textContent.includes('after entry costs')",'matched investable fund comparison')
                browser.wait("document.querySelector('#promotionModel').options.length>1",'experimental promotion choices')
                browser.evaluate("document.querySelector('#promotionModel').selectedIndex=1;document.querySelector('#promoteModel').click()")
                browser.wait("document.querySelector('#promotionStatus').textContent.includes('Active model:')",'explicit experimental promotion')
                if not app.read_meta('promoted_experiment_model'):raise RuntimeError('Promotion was not saved by the application.')
                browser.evaluate("document.querySelector('#restoreBaseline').click()")
                browser.wait("document.querySelector('#promotionStatus').textContent.includes('Baseline recommendations are active.')",'restore baseline recommendations')
                if app.read_meta('promoted_experiment_model') is not None:raise RuntimeError('Baseline restoration did not clear promotion.')
                browser.wait("document.querySelector('#archiveRun').options.length>1",'archived research evidence')
                browser.evaluate("const select=document.querySelector('#archiveRun');select.selectedIndex=1;select.dispatchEvent(new Event('change'));document.querySelector('#replayArchive').click()")
                browser.wait("document.querySelector('#archiveReplayStatus').textContent.includes('0 ranking/action/score difference')",'recorded-input replay')
            else:
                browser.wait("document.querySelector('#workspaceTitle').textContent==='Strategy lab'",'mobile Strategy lab navigation')
            if not browser.evaluate('document.documentElement.scrollWidth<=innerWidth+1'):raise RuntimeError('Workspace overflows the viewport.')
            browser.call('Page.navigate',{'url':fixture.origin+'/#fit'})
            browser.wait("location.hash==='#fit'",'direct advanced-tool URL')
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#fitGroup').open",'direct advanced-tool workspace')
            if not browser.evaluate("document.querySelector('#portfolioAdvanced').open && document.activeElement.id==='fit'"):
                raise RuntimeError('Direct tool link did not reveal its parent disclosure and identify the destination: '+str(browser.evaluate("({outer:document.querySelector('#portfolioAdvanced').open,inner:document.querySelector('#fitGroup').open,focus:document.activeElement.id,hash:location.hash})")))
            browser.evaluate("const budget=document.querySelector('#fitPreferences').elements.purchase_nok;budget.value='5791';budget.dispatchEvent(new Event('input',{bubbles:true}))")
            browser.reload()
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#fitGroup').open && document.querySelector('#fitStatus').textContent.includes('Current portfolio check:') && document.querySelector('#researchStatus').textContent.includes('Last report:')",'deep-link refresh and unsaved edit restoration')
            if not browser.evaluate("document.querySelector('#fitPreferences').elements.purchase_nok.value==='5791' && document.querySelector('#adviceFilter').value==='all' && document.querySelector('#portfolioAdvanced').open"):
                raise RuntimeError('Refresh did not preserve the tool link, unsaved allocation edit, or Research selection: '+str(browser.evaluate("({value:document.querySelector('#fitPreferences').elements.purchase_nok.value,filter:document.querySelector('#adviceFilter').value,advanced:document.querySelector('#portfolioAdvanced').open,saved:sessionStorage.getItem('northstar-workspace-ui-v1')})")))
            browser.wait("document.querySelector('#accountStatus').textContent==='Connected'",'connected account after direct route')
            if browser.evaluate("document.querySelector('#accountStatus').textContent!=='Connected'"):
                raise RuntimeError('Direct route lost the connected account: '+str(browser.evaluate("document.querySelector('#accountStatus').textContent+' '+document.querySelector('#accountPerformanceStatus').textContent")))
            if not browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').getAttribute('aria-current')==='page'"):
                raise RuntimeError('Deep-link section indicator does not match its title.')
            browser.evaluate("document.querySelector('#disconnect').click()")
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden && !sessionStorage.getItem('northstar-key') && !sessionStorage.getItem('northstar-workspace-ui-v1') && document.querySelector('#accountStatus').textContent==='Not connected' && !document.querySelector('#holdings').textContent.includes('SYNTH.OL')",'sign-out data clearing')
            browser.call('Page.navigate',{'url':fixture.origin+'/#daily'})
            browser.wait("document.querySelector('#overviewValue').textContent==='Unavailable' && document.querySelector('#overviewAccountStatus').textContent.includes('Sign in')",'disconnected Overview account state')
            if browser.errors:raise RuntimeError('Uncaught browser error during authenticated workflow.')
            completed='sign-in, holdings, account performance, research, '
            if width==1440:completed+='experiment, replay, '
            print('Authenticated browser checks passed at '+str(width)+'px: '+completed+'navigation, sign-out.')
        if not any(path=='/api/validation' and auth for method,path,auth in fixture.requests):raise RuntimeError('Authenticated experiment endpoint was not exercised.')
        if not any(path=='/api/state' and not auth for method,path,auth in fixture.requests):raise RuntimeError('Anonymous access was not exercised.')
    print('Synthetic browser account removed. No real portfolio or live experiment was changed.')

if __name__=='__main__':
    try:run()
    except Exception as error:
        import os
        if os.environ.get('NORTHSTAR_SMOKE_DEBUG'):raise
        raise SystemExit('Browser smoke failed ('+type(error).__name__+'): '+str(error))
