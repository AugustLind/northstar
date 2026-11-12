"""Authenticated operational summaries. No configuration values or raw payloads."""
import time
import portfolio_fit as pf


def build(snapshot,report,worker,progress,financial_progress,announcements,announcement_progress,
          threads,email,email_history,started,now=None):
    now=time.time() if now is None else now
    quotes=snapshot.get('quotes',{});positions=snapshot.get('positions',[])
    symbols={pf.canonical(p['symbol'],p['currency']) for p in positions if p['shares']>0}
    cards=(report or {}).get('cards',[]);symbols.update(c['symbol'] for c in cards)
    fresh=stale=missing=invalid=0
    currencies={pf.canonical(p["symbol"],p["currency"]):p["currency"] for p in positions if p["shares"]>0}
    for symbol in symbols:
        q=quotes.get(symbol) or quotes.get(symbol[:-3] if symbol.endswith('.OL') else symbol)
        if not q:missing+=1
        elif q.get('currency')!=currencies.get(symbol,'NOK'):invalid+=1
        elif pf.fresh(q,now):fresh+=1
        else:stale+=1
    records=snapshot.get('fundamentals',{})
    import fundamentals
    financial_counts={'available':0,'partial':0,'stale':0,'unavailable':0}
    for symbol in symbols:
        status=fundamentals.analyse(records.get(symbol),quotes.get(symbol),now)['status']
        financial_counts[status]+=1
    generated=(report or {}).get('generated');report_fresh=bool(generated and -300<=now-generated<=86400)
    components=[]
    def component(key,label,state,detail,action,last=None):
        components.append({'id':key,'label':label,'state':state,'detail':detail,'action':action,'last_success':last})
    running=bool(worker.get('running'))
    overdue=bool(not running and worker.get('next_run') and now-worker['next_run']>300)
    component('research','Research','running' if running else 'error' if worker.get('error') or overdue else 'ready' if report_fresh else 'stale' if generated else 'missing',
              ('Scheduled analysis is overdue. ' if overdue else 'Last research cycle failed; previous report retained. ' if worker.get('error') else '')+str((report or {}).get('coverage',{}).get('analysed',0))+' analysed; '+str(len((report or {}).get('errors',[])))+' provider failures in the last report.',
              'Run analysis from Research if the report is missing or stale.',generated)
    component('quotes','Market data','ready' if symbols and not(stale or missing or invalid) else 'partial' if fresh else 'missing',
              str(fresh)+' fresh, '+str(stale)+' stale, '+str(missing)+' missing, '+str(invalid)+' currency mismatches across '+str(len(symbols))+' held/researched symbols.',
              'Refresh market data; old quotes retain their original timestamps.')
    component('financials','Annual financials','error' if financial_progress.get('error') else 'running' if financial_progress.get('running') and financial_progress.get('started',0)>=started else 'partial' if financial_counts['stale'] or financial_counts['unavailable'] or financial_counts['partial'] else 'ready' if symbols else 'missing',
              str(financial_counts['available'])+' available, '+str(financial_counts['partial'])+' partial, '+str(financial_counts['stale'])+' stale, '+str(financial_counts['unavailable'])+' unavailable.',
              'Refresh the selected company’s financials and check fiscal dates.',financial_progress.get('finished'))
    fetched=announcements.get('fetched');news_current=bool(fetched and -300<=now-fetched<=86400)
    component('announcements','Issuer notices','error' if announcements.get('error') else 'ready' if news_current else 'stale' if fetched else 'missing',
              'Latest source refresh '+('available.' if fetched else 'has not completed.')+(' Provider error recorded; cached notices retained.' if announcements.get('error') else ''),
              'Refresh announcements; an empty or failed feed is not evidence of no events.',fetched)
    expected={'research':'northstar-research','financials':'northstar-fundamentals','announcements':'northstar-announcements','company_metadata':'northstar-company-data','email':'northstar-email'}
    worker_rows=[{'name':label,'state':'running' if thread in threads else 'not_started'} for label,thread in expected.items()]
    component('workers','Background workers','ready' if all(row['state']=='running' for row in worker_rows) else 'partial',
              str(sum(row['state']=='running' for row in worker_rows))+' / '+str(len(worker_rows))+' worker threads present.',
              'A missing worker requires checking or restarting the Python service.')
    component('email','Email delivery','missing' if not email['configured'] else 'paused' if not email['active'] else 'error' if email.get('error') else 'ready',
              'SMTP configuration incomplete.' if not email['configured'] else 'Alerts paused.' if not email['active'] else email.get('error') or str(email['pending'])+' pending; '+str(email['sent'])+' accepted by SMTP.',
              'Review email setup and delivery history. SMTP acceptance does not guarantee inbox delivery.',email.get('last_sent'))
    return {'generated':now,'started':started,'uptime_seconds':max(0,now-started),'state':'ready' if all(c['state'] in ('ready','running','paused') for c in components) else 'attention',
        'components':components,'workers':worker_rows,'email':email,'email_history':email_history,
        'quote_coverage':{'fresh':fresh,'stale':stale,'missing':missing,'invalid_currency':invalid,'total':len(symbols)},'financial_coverage':financial_counts,
        'research_progress':{k:progress.get(k) for k in ('done','total','failed','started')},
        'method':'Private operational diagnostics. Readiness describes process/data state, not investment quality. Public health remains a boolean; no credentials, addresses or message contents are returned.'}
