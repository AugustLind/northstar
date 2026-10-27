"""Three prioritized reviews and persistent, deduplicated in-dashboard alerts."""
import datetime as dt
import hashlib
import time
import portfolio_fit as pf
import trade_plan
import announcements
import fundamentals
import company_data


def build(snapshot,report,plan,feed,ledger=None,now=None):
    now=time.time() if now is None else now
    held={pf.canonical(p['symbol'],p['currency']) for p in snapshot['positions'] if p['shares']>0}
    reviews=[]
    def add(key,priority,title,detail,kind,symbol=None,url=None):
        reviews.append({'id':hashlib.sha256(key.encode()).hexdigest()[:24],'priority':priority,'title':title,
                        'detail':detail,'kind':kind,'symbol':symbol,'url':url,'observed':now})
    for symbol in snapshot['portfolio_context']['missing']:
        add('missing:'+symbol,100,'Refresh '+symbol+' before sizing trades','Current portfolio valuation is incomplete.','data',symbol)
    if ledger and not ledger.get('reconciled',True):
        add('ledger-mismatch',100,'Reconcile holdings and cash' if ledger.get('initialized') else 'Initialize transaction tracking','Verify holdings and cash before using the transaction ledger.','ledger')
    changes=(report or {}).get('recommendation_changes',[])
    changed={(r['symbol'],r['direction']):r for r in changes}
    for row in plan['holdings']:
        if row.get('sell_shares'):
            change=changed.get((row['symbol'],'sell'),{}).get('change','Review')
            add('sale:'+row['symbol']+':'+str(changed.get((row['symbol'],'sell'),{}).get('change_id','active')),90,row['symbol']+': review '+str(row['sell_shares'])+' shares for sale',
                change+'. '+' '.join(row['reasons'])+' Gross sale estimate; selling fees and tax are not included.','holding',row['symbol'])
    focused=held|set((report or {}).get('top20',[]))
    notices=announcements.view(feed,list(focused),now=now)
    for n in notices.get('items',[]):
        if n.get('corrected_by') or n['published']<now-86400:continue
        priority=(n.get('classification') or {}).get('priority',0)
        if priority>=3 or (n.get('classification') or {}).get('kind')=='earnings':
            add('notice:'+n['id'],95 if n['symbol'] in held else 75,n['symbol']+': '+n['title'],
                'New official issuer notice; read the linked source. Headline label is not a trade signal.','announcement',n['symbol'],n['url'])
    if notices.get('status') in ('unavailable','stale','degraded'):
        add('announcement-feed-status',85,'Check announcement coverage','Official notice feed: '+str(notices.get('status'))+'. An empty feed is not evidence that nothing happened.','data')
    for symbol in held:
        record=snapshot.get('fundamentals',{}).get(symbol)
        financial=fundamentals.analyse(record,trade_plan.quote_for(snapshot,symbol),now)
        assessment=company_data.assessment(financial,snapshot['portfolio_preferences']['sectors'].get(symbol))
        for check in assessment['checks']:
            if not check['passes'] and check['metric'] in ('free_cash_flow','net_income'):
                add('annual:'+symbol+':'+check['metric']+':'+check['period'],80,symbol+': review annual '+check['metric'].replace('_',' '),
                    'Non-positive reported value for fiscal period '+check['period']+'. Annual accounting evidence is not a sell signal.','company',symbol,financial.get('source_url'))
    for e in notices.get('events',[]):
        try:days=(dt.date.fromisoformat(e['date'])-dt.datetime.fromtimestamp(now,dt.timezone.utc).date()).days
        except ValueError:continue
        if 0<=days<=7:
            add('calendar:'+str(e.get('id',e.get('source_url')))+':'+e['date'],70,e['symbol']+': '+e['label']+' on '+e['date'],
                'Date stated by issuer; check the source for revisions.','calendar',e['symbol'],e.get('source_url'))
    for row in plan['buys']:
        change=changed.get((row['symbol'],'buy'),{}).get('change','Review')
        add('buy:'+row['symbol']+':'+str(changed.get((row['symbol'],'buy'),{}).get('change_id','active')),65,row['symbol']+': consider '+str(row['buy_shares'])+' shares',
            change+'. '+row['reason']+' Total including purchase fee: '+str(round(row['total_nok'],2))+' NOK.','purchase',row['symbol'])
    for c in changes:
        if c['change']=='Withdrawn':
            add('withdrawn:'+c['symbol']+':'+c['direction']+':'+str((report or {}).get('generated')),80,c['symbol']+': previous '+c['direction']+' suggestion withdrawn',
                'Do not use the earlier quantity; review the current plan.','change',c['symbol'])
    if not trade_plan.current_report(report,now):
        add('stale-report',100,'Refresh the market report','Buy quantities and technical sale reviews need current signal evidence.','data')
    ordered=sorted({r['id']:r for r in reviews}.values(),key=lambda r:(-r['priority'],r['id']))
    return {'generated':now,'top3':ordered[:3],'reviews':ordered,'changes':changes,
            'plan':plan,'announcement_status':notices.get('status'),'ledger':ledger,
            'coverage':(report or {}).get('coverage',{}),
            'method':'Priorities are review rules, not probabilities. No message is sent to any external service. Browser notifications require opt-in and an open dashboard.'}


def merge_alerts(old,reviews,now=None):
    now=time.time() if now is None else now
    by_id={a['id']:a for a in (old or []) if now-a.get('first_seen',now)<30*86400}
    for r in reviews:
        if r['id'] not in by_id:by_id[r['id']]={**r,'first_seen':now,'read':False}
        else:by_id[r['id']].update({**r,'read':by_id[r['id']].get('read',False)})
    return sorted(by_id.values(),key=lambda a:(-a['first_seen'],a['id']))[:200]
