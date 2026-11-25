"""Authenticated browser flow against synthetic data using the real application code."""
from datetime import datetime
from pathlib import Path
import json
import sys
from tempfile import TemporaryDirectory
import time
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from browser_fixture import Fixture
from browser_client import Browser
import app


def press_enter(browser):
    browser.call('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    browser.call('Input.dispatchKeyEvent',{'type':'char','key':'Enter','code':'Enter','text':'\r','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
    browser.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})


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


def check_portfolio_today(fixture, browser):
    oslo = app.account_performance.OSLO

    def stamp(date_time):
        return datetime.fromisoformat(date_time).replace(tzinfo=oslo).timestamp()

    session = '2026-12-02'
    previous = '2026-12-01'
    current_time = stamp(session + 'T12:00')
    initial_report = app.account_performance.view

    def set_account(shares, cash, rows, price=110, quote_date=session, currency='NOK', fx=None):
        snapshot = app.state()
        app.save_position({'symbol': 'SYNTH.OL', 'currency': currency, 'shares': shares, 'cost': 100})
        app.write_meta('portfolio_preferences', {'cash_nok': cash})
        baseline = app.read_meta('ledger_state')
        baseline['cutoff_date'] = previous
        baseline['opening_cash_nok'] = 90000
        baseline['opening_positions'] = [{'symbol': 'SYNTH.OL', 'currency': currency, 'shares': 100, 'cost': 100}]
        baseline['fingerprint'] = app.transactions.fingerprint(app.state()['positions'], float(cash))
        app.write_meta('ledger_state', baseline)
        quote = {**snapshot['quotes']['SYNTH.OL'], 'currency': currency, 'price': price,
                 'asof': stamp(quote_date + 'T11:00'),
                 'history': [{'time': stamp(previous + 'T16:30'), 'account_close': 100 if currency == 'NOK' else 10},
                             {'time': stamp(session + 'T16:30'), 'account_close': price}]}
        with app.connect() as db:
            db.execute('DELETE FROM ledger_events')
            for kind, amount, quantity in rows:
                payload = {'date': session, 'type': kind, 'net_cash': amount, 'currency': 'NOK',
                           'symbol': 'SYNTH.OL' if kind == 'buy' else '', 'quantity': quantity, 'fee': None}
                db.execute('INSERT INTO ledger_events (uid,date,payload) VALUES (?,?,?)', (kind, session, json.dumps(payload)))
            db.execute('UPDATE quotes SET payload=? WHERE symbol=?', (json.dumps(quote), 'SYNTH.OL'))
            if fx:
                rate = {**quote, 'currency': 'NOK', 'price': fx,
                        'history': [{'time': stamp(previous + 'T16:30'), 'account_close': 10},
                                    {'time': stamp(session + 'T16:30'), 'account_close': fx}]}
                db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?)', ('NOK=X', json.dumps(rate)))

    def refresh():
        browser.evaluate('loadAccountPerformance()')

    def metrics(value, pnl, pct, external):
        browser.wait(
            "(() => {const cards=document.querySelector('#portfolioTodayMetrics').textContent;"
            f"return cards.includes(money({value})) && cards.includes('+'+money({pnl})+' ({pct}%)')"
            f" && cards.includes({json.dumps('+' if external > 0 else '')}+money({external}));}})()",
            f'visible current value {value}, investment performance {pnl} ({pct}%) and external flow {external}',
        )

    with patch.object(app.account_performance, 'view',
                      side_effect=lambda snapshot, baseline, events, **kwargs:
                      initial_report(snapshot, baseline, events, now=current_time, **kwargs)):
        set_account(100, 100000, [('deposit', 10000, 0)])
        browser.call('Page.navigate', {'url': fixture.origin})
        browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden", 'sign-in before Portfolio landing')
        browser.fill_key(fixture.key)
        browser.wait("document.querySelector('#accountStatus').textContent==='Connected' && document.querySelector('#workspaceTitle').textContent==='Portfolio' && !location.hash && document.querySelector('[data-tab=portfolio]').getAttribute('aria-current')==='page'", 'signed-in Portfolio landing')
        metrics(111000, 1000, '+1.0', 10000)
        browser.wait("document.querySelector('#portfolioTodayChart svg') && document.querySelector('#portfolioTodayStatus').textContent.includes('2026-12-02 · Europe/Oslo') && document.querySelector('#portfolioTodayMetrics').textContent.includes('day end')", 'dated Today chart and cash-flow assumption')
        browser.wait("document.querySelector('#portfolioTodayHoldings').textContent.includes('+'+money(1000)+' (+10.0%)')", 'holding session movement')

        set_account(110, 88720, [('withdrawal', -200, 0), ('dividend', 30, 0), ('fee', -10, 0), ('buy', -1100, 10)])
        refresh()
        metrics(100820, 1020, '+1.0', -200)

        set_account(110, 89000, [('buy', -1000, 10)], price=100)
        refresh()
        browser.wait("document.querySelector('#portfolioTodayHoldings').textContent.includes(money(0)+' (0.0%)')", 'additional shares at the same NOK price are not price movement')

        set_account(100, 90000, [], price=10, currency='USD', fx=11)
        refresh()
        metrics(101000, 1000, '+1.0', 0)
        browser.wait("document.querySelector('#portfolioTodayHoldings').textContent.includes('+'+money(1000)+' (+10.0%)')", 'holding movement includes USD/NOK')

        set_account(100, 100000, [('deposit', 10000, 0)], quote_date=previous)
        refresh()
        browser.wait("document.querySelector('#portfolioTodayStatus').textContent.includes('missing latest session quote coverage') && !document.querySelector('#portfolioTodayChart svg')", 'missing open-session quote flagged')

        set_account(100, 100000, [('deposit', 10000, 0)])
        current_time = stamp('2026-12-03T00:15')
        refresh()
        browser.wait("document.querySelector('#portfolioTodayStatus').textContent.includes('2026-12-02 · Europe/Oslo · Last completed session') && document.querySelector('#portfolioTodayChart svg')", 'Oslo date rollover and pre-open fallback')
        current_time = stamp('2026-12-26T12:00')
        refresh()
        browser.wait("document.querySelector('#portfolioTodayStatus').textContent.includes('2026-12-23 · Europe/Oslo · Last completed session')", 'scheduled Christmas closure')
    if browser.errors:
        raise RuntimeError('Uncaught browser error during Portfolio Today workflow.')
    print('Portfolio landing and Today passed with dated chart, cash flows, holding movements, Oslo boundaries and coverage states.')


def run():
    with Fixture() as fixture:
        check_remembered_browser(fixture)
    with Fixture() as fixture, Browser() as browser:
        check_portfolio_today(fixture, browser)
    with Fixture() as fixture,Browser() as browser:
        for width,height in ((1440,1000),(390,900)):
            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
            browser.call('Page.navigate',{'url':fixture.origin+'/?smoke_width='+str(width)+'#daily'})
            browser.wait("document.readyState==='complete' && location.search==='?smoke_width="+str(width)+"'",'fresh browser navigation')
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden",'sign-in panel')
            browser.fill_key(fixture.key)
            browser.wait("document.querySelector('#connectionPanel').hidden && document.querySelector('#holdings').textContent.includes('SYNTH.OL') && document.querySelector('#accountStatus').textContent==='Connected'",'authenticated account context')
            browser.evaluate('loadDaily()')
            browser.wait("document.querySelector('#dailyStatus').textContent.startsWith('Updated') && document.querySelector('#holdingAssessments').textContent.includes('Policy result:') && !document.querySelector('#buyCandidatesStatus').textContent.includes('Loading eligible candidates')",'authenticated holding assessment and buying-candidate response')
            browser.wait("!document.querySelector('#overviewAccountStatus').textContent.includes('Loading')",'current account summary response')
            browser.wait("document.querySelector('#researchStatus').textContent.includes('Last report:') && document.querySelector('#workspaceTitle').textContent==='Overview'",'completed sign-in workspace startup')
            if browser.evaluate("document.querySelector('#overviewValue').textContent==='Unavailable' || document.querySelector('#overviewValue').textContent==='—'"):
                raise RuntimeError('Current account value unavailable: '+str(browser.evaluate("document.querySelector('#overviewValueMeta').textContent+' '+document.querySelector('#overviewAccountStatus').textContent")))
            if browser.evaluate("document.querySelector('#overviewPnl').textContent==='Unavailable'"):
                raise RuntimeError('Verified historical investment P&L unavailable: '+str(browser.evaluate("document.querySelector('#overviewPnlMeta').textContent+' '+document.querySelector('#overviewAccountStatus').textContent")))
            expected_value="new Intl.NumberFormat('nb-NO',{style:'currency',currency:'NOK',maximumFractionDigits:2}).format("+str(fixture.expected_current_value_nok)+")"
            if not browser.evaluate("document.querySelector('#overviewValue').textContent==="+expected_value):
                raise RuntimeError('Current value does not match synthetic holdings plus recorded cash.')
            if not browser.evaluate("document.querySelector('#overviewValueMeta').textContent.includes('NOK cash') && document.querySelector('#overviewValueMeta').textContent.includes('reporting date') && document.querySelector('#overviewPnlMeta').textContent.includes(' to ')"):
                raise RuntimeError('Overview account dates, cash scope or price basis are missing.')
            if browser.evaluate("document.querySelector('#overviewMove').textContent!=='Unavailable'"):
                raise RuntimeError('A prior completed session was presented as today movement.')
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
            browser.wait("document.querySelector('#overviewValue').textContent!=='Unavailable'",'account valuation recovery after quote refresh')
            if width==1440:
                browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
                browser.wait("!document.querySelector('#portfolio').hidden",'Portfolio workspace for holding edit')
                browser.evaluate("document.querySelector('#holdings button').click();const field=document.querySelector('#positionForm').elements.review;field.value='Unsaved reload draft';field.dispatchEvent(new Event('input',{bubbles:true}))")
                browser.call('Page.reload',{'ignoreCache':True})
                browser.wait("document.querySelector('#editor').open && document.querySelector('#positionForm').elements.review.value==='Unsaved reload draft'",'holding edit draft restoration')
                if not browser.evaluate("document.querySelector('#positionForm').elements.symbol.readOnly"):
                    raise RuntimeError('Reloaded holding edit draft lost its protected ticker field.')
                browser.evaluate("document.querySelector('#close').click()")
                browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
                browser.wait("document.querySelector('#workspaceTitle').textContent==='Overview'",'return to Overview after edit recovery')
            if not browser.evaluate("document.querySelector('#workspaceTitle').textContent==='Overview' && document.querySelector('#overviewMetrics').parentElement.id==='daily' && document.querySelector('[data-tab][aria-current=page]').textContent.trim()==='Overview'"):
                raise RuntimeError('Overview account/section orientation failed.')
            if not browser.evaluate("['overviewAdvanced','researchAdvanced','portfolioAdvanced','strategyAdvanced'].every(id=>{const details=document.getElementById(id);return details&&!details.open&&details.querySelector(':scope > summary').textContent.trim()==='Advanced tools'})"):
                raise RuntimeError('Each workspace must start with one collapsed Advanced tools disclosure.')
            browser.evaluate("document.querySelector('#overviewAdvanced > summary').focus()")
            press_enter(browser)
            if not browser.evaluate("document.querySelector('#overviewAdvanced').open && document.activeElement.matches('#overviewAdvanced > summary') && getComputedStyle(document.activeElement).outlineStyle==='solid'"):
                raise RuntimeError('Advanced tools disclosure did not open with visible keyboard focus.')
            press_enter(browser)
            if width<600 and not browser.evaluate("getComputedStyle(document.querySelector('.workspace-nav')).gridTemplateColumns.split(' ').length===2"):
                raise RuntimeError('Mobile workspace navigation did not use its compact layout.')
            browser.evaluate("openWorkspace('accountPerformance')")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#portfolioAdvanced').open && document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'Overview to detailed account performance')
            if not browser.evaluate("document.querySelector('#accountPerformanceMetrics').textContent.includes(money(60))"):
                raise RuntimeError('Detailed performance did not keep the synthetic 100 NOK deposit and 40 NOK withdrawal separate as net contributions.')
            browser.wait("document.querySelector('#fitStatus').textContent.includes('Current portfolio check:') && document.querySelector('#portfolioRiskStatus').textContent.includes('Risk model:')",'portfolio allocation and risk workflows')
            browser.evaluate("document.querySelector('#stockShock').value='-15';document.querySelector('#fxShock').value='-5';document.querySelector('#riskScenarioForm').dispatchEvent(new Event('submit',{bubbles:true,cancelable:true}))")
            browser.wait("document.querySelector('#riskScenarios').textContent.includes('Hypothetical assumption')",'portfolio risk scenario calculation')
            browser.evaluate("const budget=document.querySelector('#fitPreferences').elements.purchase_nok;budget.value='4567';budget.dispatchEvent(new Event('input',{bubbles:true}));document.querySelector('#refreshFit').click()")
            browser.wait("document.querySelector('#fitStatus').textContent.includes('Current portfolio check:') && document.querySelector('#fitPreferences').elements.purchase_nok.value==='4567'",'unsaved allocation edit during refresh')
            browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
            browser.wait("!document.querySelector('#gettingStarted').hidden && document.querySelectorAll('#setupChecklist li').length===3",'consumer getting-started checklist')
            browser.evaluate("document.querySelector('#startLedger').click()")
            browser.wait("!document.querySelector('#portfolio').hidden && document.querySelector('#activityGroup').open",'guided activity shortcut')
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
            browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').focus()")
            if not browser.evaluate("document.activeElement===document.querySelector('[data-tab=\"recommendations\"]')"):
                raise RuntimeError('Workspace navigation button did not receive keyboard focus.')
            press_enter(browser)
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research' && document.querySelector('[data-tab=\"recommendations\"]').getAttribute('aria-current')==='page'",'keyboard workspace navigation')
            if not browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').matches(':focus-visible') && getComputedStyle(document.querySelector('[data-tab=\"recommendations\"]')).outlineStyle==='solid'"):
                raise RuntimeError('Keyboard workspace focus is not visibly indicated.')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.call('Runtime.evaluate',{'expression':'history.back()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research'",'browser back navigation')
            browser.call('Runtime.evaluate',{'expression':'history.forward()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio'",'browser forward navigation')
            browser.wait("document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'account performance')
            if not browser.evaluate("document.querySelector('#fitPreferences').elements.purchase_nok.value==='4567'"):
                raise RuntimeError('Unsaved allocation edit was lost during browser history navigation.')
            browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').click()")
            browser.wait("Boolean(document.querySelector('#chartPlot svg'))",'research explorer')
            browser.evaluate("document.querySelector('#adviceFilter').value='all';document.querySelector('#adviceFilter').dispatchEvent(new Event('change',{bubbles:true}))")
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click();document.querySelector('[data-tab=\"recommendations\"]').click()")
            if not browser.evaluate("document.querySelector('#adviceFilter').value==='all'"):
                raise RuntimeError('Research selection was lost when changing workspaces.')
            if not browser.evaluate("document.querySelectorAll('nav [data-tab]').length===4 && !/NaN|Infinity/.test(document.querySelector('#chartPlot').innerHTML)"):
                raise RuntimeError('Research navigation/chart contract failed.')
            candidate_checks=browser.evaluate("(() => { const item=i=>({symbol:'BOUV.OL',name:'Bouvet',rank:i+1,buy_shares:1,total_nok:204,portfolio_reason:'Fits your sector and cash limits.'}); let counts=[]; for(let n=0;n<=3;n++){renderBuyCandidates({buy_candidates:Array.from({length:n},(_,i)=>item(i)),buy_candidates_stale:false,buy_candidate_warnings:[]});counts.push(document.querySelectorAll('#buyCandidates [data-candidate-stock]').length);} renderBuyCandidates({buy_candidates:Array.from({length:5},(_,i)=>item(i)),buy_candidates_stale:false,buy_candidate_warnings:[]}); const capped=document.querySelectorAll('#buyCandidates [data-candidate-stock]').length; renderBuyCandidates({buy_candidates:[],buy_candidates_stale:true,buy_candidate_warnings:[]}); const stale=document.querySelector('#buyCandidatesStatus').textContent.includes('Research is stale'); renderBuyCandidates({buy_candidates:[],buy_candidates_stale:false,buy_candidate_warnings:['Portfolio incomplete']}); const blocked=document.querySelector('#buyCandidatesStatus').textContent.includes('current portfolio inputs'); return {counts,capped,stale,blocked}; })()")
            if candidate_checks != {'counts':[0,1,2,3],'capped':3,'stale':True,'blocked':True}:
                raise RuntimeError('Buying-candidate count, stale or blocked-state check failed: '+str(candidate_checks))
            browser.evaluate("document.querySelector('#daily').hidden=false;document.querySelector('#recommendations').hidden=true;document.querySelector('#workspaceTitle').textContent='Overview';document.querySelector('[data-tab=\"daily\"]').setAttribute('aria-current','page')")
            browser.evaluate("renderBuyCandidates({buy_candidates:[{symbol:'BOUV.OL',name:'Bouvet',rank:1,buy_shares:1,total_nok:204,portfolio_reason:'Fits your sector and cash limits.'}],buy_candidates_stale:false,buy_candidate_warnings:[]});document.querySelector('#buyCandidates [data-candidate-stock]').focus()")
            if not browser.evaluate("document.activeElement.matches('#buyCandidates [data-candidate-stock]')"):
                raise RuntimeError('Buying-candidate action is not keyboard focusable.')
            press_enter(browser)
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research' && explorerSymbol==='BOUV.OL'",'keyboard buying-candidate Research action')
            browser.evaluate("document.querySelector('[data-tab=\"validation\"]').click()")
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
            browser.call('Page.reload',{'ignoreCache':True})
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
