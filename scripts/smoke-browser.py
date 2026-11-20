"""Authenticated browser flow against synthetic data using the real application code."""
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from browser_fixture import Fixture
from browser_client import Browser
import app
import json


def run():
    with Fixture() as fixture,Browser() as browser:
        for width,height in ((1440,1000),(390,900)):
            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
            browser.call('Page.navigate',{'url':fixture.origin+'/?smoke_width='+str(width)})
            browser.wait("document.readyState==='complete' && location.search==='?smoke_width="+str(width)+"'",'fresh browser navigation')
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden",'sign-in panel')
            browser.fill_key(fixture.key)
            browser.wait("document.querySelector('#connectionPanel').hidden && document.querySelector('#holdings').textContent.includes('SYNTH.OL') && document.querySelector('#accountStatus').textContent==='Connected'",'authenticated account context')
            browser.wait("!document.querySelector('#overviewAccountStatus').textContent.includes('Loading')",'current account summary response')
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
            if not browser.evaluate("document.querySelector('#workspaceTitle').textContent==='Overview' && document.querySelector('#overviewMetrics').parentElement.id==='daily' && document.querySelector('[data-tab][aria-current=page]').textContent.trim()==='Overview'"):
                raise RuntimeError('Overview account/section orientation failed.')
            if width<600 and not browser.evaluate("getComputedStyle(document.querySelector('.workspace-nav')).gridTemplateColumns.split(' ').length===2"):
                raise RuntimeError('Mobile workspace navigation did not use its compact layout.')
            browser.evaluate("document.querySelector('#openAccountPerformance').click()")
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio' && document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'Overview to detailed account performance')
            if not browser.evaluate("document.querySelector('#accountPerformanceMetrics').textContent.includes(money(60))"):
                raise RuntimeError('Detailed performance did not keep the synthetic 100 NOK deposit and 40 NOK withdrawal separate as net contributions.')
            browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
            browser.wait("!document.querySelector('#gettingStarted').hidden && document.querySelectorAll('#setupChecklist li').length===3",'consumer getting-started checklist')
            browser.evaluate("document.querySelector('#startLedger').click()")
            browser.wait("!document.querySelector('#portfolio').hidden && document.querySelector('#activityGroup').open",'guided activity shortcut')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').focus()")
            if not browser.evaluate("document.activeElement===document.querySelector('[data-tab=\"recommendations\"]')"):
                raise RuntimeError('Workspace navigation button did not receive keyboard focus.')
            browser.call('Input.dispatchKeyEvent',{'type':'rawKeyDown','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
            browser.call('Input.dispatchKeyEvent',{'type':'char','key':'Enter','code':'Enter','text':'\r','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
            browser.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'Enter','code':'Enter','windowsVirtualKeyCode':13,'nativeVirtualKeyCode':13})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research' && document.querySelector('[data-tab=\"recommendations\"]').getAttribute('aria-current')==='page'",'keyboard workspace navigation')
            if not browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').matches(':focus-visible') && getComputedStyle(document.querySelector('[data-tab=\"recommendations\"]')).outlineStyle==='solid'"):
                raise RuntimeError('Keyboard workspace focus is not visibly indicated.')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.call('Runtime.evaluate',{'expression':'history.back()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Research'",'browser back navigation')
            browser.call('Runtime.evaluate',{'expression':'history.forward()'})
            browser.wait("document.querySelector('#workspaceTitle').textContent==='Portfolio'",'browser forward navigation')
            browser.wait("document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'account performance')
            browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').click()")
            browser.wait("Boolean(document.querySelector('#chartPlot svg'))",'research explorer')
            if not browser.evaluate("document.querySelectorAll('nav [data-tab]').length===4 && !/NaN|Infinity/.test(document.querySelector('#chartPlot').innerHTML)"):
                raise RuntimeError('Research navigation/chart contract failed.')
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
            browser.wait("document.querySelector('#accountStatus').textContent==='Connected'",'connected account after direct route')
            if browser.evaluate("document.querySelector('#accountStatus').textContent!=='Connected'"):
                raise RuntimeError('Direct route lost the connected account: '+str(browser.evaluate("document.querySelector('#accountStatus').textContent+' '+document.querySelector('#accountPerformanceStatus').textContent")))
            if not browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').getAttribute('aria-current')==='page'"):
                raise RuntimeError('Deep-link section indicator does not match its title.')
            browser.evaluate("document.querySelector('#disconnect').click()")
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden && !sessionStorage.getItem('northstar-key') && document.querySelector('#accountStatus').textContent==='Not connected' && !document.querySelector('#holdings').textContent.includes('SYNTH.OL')",'sign-out data clearing')
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
