"""Authenticated browser flow against synthetic data using the real application code."""
from pathlib import Path
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from browser_fixture import Fixture
from browser_client import Browser


def run():
    with Fixture() as fixture,Browser() as browser:
        for width,height in ((1440,1000),(390,900)):
            browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':height,'deviceScaleFactor':1,'mobile':width<600})
            browser.call('Page.navigate',{'url':fixture.origin+'/?smoke_width='+str(width)})
            browser.wait("document.readyState==='complete' && location.search==='?smoke_width="+str(width)+"'",'fresh browser navigation')
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden",'sign-in panel')
            browser.fill_key(fixture.key)
            browser.wait("document.querySelector('#connectionPanel').hidden && document.querySelector('#holdings').textContent.includes('SYNTH.OL')",'authenticated holdings')
            browser.evaluate("document.querySelector('[data-tab=\"daily\"]').click()")
            browser.wait("!document.querySelector('#gettingStarted').hidden && document.querySelectorAll('#setupChecklist li').length===3",'consumer getting-started checklist')
            browser.evaluate("document.querySelector('#startLedger').click()")
            browser.wait("!document.querySelector('#portfolio').hidden && document.querySelector('#activityGroup').open",'guided activity shortcut')
            browser.evaluate("document.querySelector('[data-tab=\"portfolio\"]').click()")
            browser.wait("document.querySelector('#accountPerformanceStatus').textContent.includes('available')",'account performance')
            browser.evaluate("document.querySelector('[data-tab=\"recommendations\"]').click()")
            browser.wait("Boolean(document.querySelector('#chartPlot svg'))",'research explorer')
            if not browser.evaluate("document.querySelectorAll('nav [data-tab]').length===4 && !/NaN|Infinity/.test(document.querySelector('#chartPlot').innerHTML)"):
                raise RuntimeError('Research navigation/chart contract failed.')
            started=time.time()
            browser.evaluate("document.querySelector('[data-tab=\"validation\"]').click();document.querySelector('#validationRobustness').checked=true;document.querySelector('#runValidation').click()")
            browser.wait("!validationPolling && !document.querySelector('#robustnessPanel').hidden",'completed synthetic experiment',45)
            import app
            report=app.read_meta('validation_report',{})
            if report.get('generated',0)<started:raise RuntimeError('Browser did not complete a new experiment.')
            browser.wait("document.querySelector('#archiveRun').options.length>1",'archived research evidence')
            browser.evaluate("const select=document.querySelector('#archiveRun');select.selectedIndex=1;select.dispatchEvent(new Event('change'));document.querySelector('#replayArchive').click()")
            browser.wait("document.querySelector('#archiveReplayStatus').textContent.includes('0 ranking/action/score difference')",'recorded-input replay')
            if not browser.evaluate('document.documentElement.scrollWidth<=innerWidth+1'):raise RuntimeError('Workspace overflows the viewport.')
            browser.evaluate("document.querySelector('#disconnect').click()")
            browser.wait("document.querySelector('#connectionPanel') && !document.querySelector('#connectionPanel').hidden && !sessionStorage.getItem('northstar-key')",'sign-out')
            if browser.errors:raise RuntimeError('Uncaught browser error during authenticated workflow.')
            print('Authenticated browser checks passed at '+str(width)+'px: sign-in, holdings, account performance, research, experiment, replay, sign-out.')
        if not any(path=='/api/validation' and auth for method,path,auth in fixture.requests):raise RuntimeError('Authenticated experiment endpoint was not exercised.')
        if not any(path=='/api/state' and not auth for method,path,auth in fixture.requests):raise RuntimeError('Anonymous access was not exercised.')
    print('Synthetic browser account removed. No real portfolio or live experiment was changed.')

if __name__=='__main__':
    try:run()
    except Exception as error:
        import os
        if os.environ.get('NORTHSTAR_SMOKE_DEBUG'):raise
        raise SystemExit('Browser smoke failed ('+type(error).__name__+'): '+str(error))
