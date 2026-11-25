"""Authenticated browser flow against synthetic data using the real application code."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from browser_fixture import Fixture
from browser_client import Browser
import app
import advice_state
import research


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


def run():
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
                same_session = {**original_quote, 'asof': time.time(), 'price': 142.45}
                db.execute('UPDATE quotes SET payload=? WHERE symbol=?',(json.dumps(same_session),'SYNTH.OL'))
            try:
                browser.evaluate('loadOverviewAccount()')
                browser.wait("document.querySelector('#overviewMove').textContent === money(30) + ' · 2.04%' && document.querySelector('#overviewMoveMeta').textContent.includes('cash flows excluded')", 'Today’s movement from the prior close and recorded cash')
            finally:
                with app.connect() as db:
                    db.execute('UPDATE quotes SET payload=? WHERE symbol=?',(json.dumps(original_quote),'SYNTH.OL'))
            browser.evaluate('loadOverviewAccount()')
            browser.wait("document.querySelector('#overviewValue').textContent === "+expected_value+" && document.querySelector('#overviewMove').textContent==='Unavailable'", 'account valuation recovery and prior-session movement withheld')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.wait("!document.querySelector('#portfolio').hidden && !document.querySelector('#portfolioAdvanced').open && document.querySelector('#workspaceTitle').textContent==='Portfolio'", 'Portfolio landing page')
            prove_holding_advice(browser)
            if width==1440:
                browser.evaluate("document.querySelector('#holdings button').click();const field=document.querySelector('#positionForm').elements.review;field.value='Unsaved reload draft';field.dispatchEvent(new Event('input',{bubbles:true}))")
                browser.call('Page.reload',{'ignoreCache':True})
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
