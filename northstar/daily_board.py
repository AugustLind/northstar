"""Three prioritized reviews and persistent, deduplicated in-dashboard alerts."""
import datetime as dt
import hashlib
import time
from northstar import portfolio_fit as pf
from northstar import decision_policy
from northstar import trade_plan
from northstar import announcements
from northstar import fundamentals
from northstar import company_data


def technical_sale(row):
    action=row.get('technical_action')
    return bool(action in trade_plan.SELL_SIGNALS and
                any(reason.startswith(action) for reason in row.get('reasons',[])))


def holding_advice(sale):
    if not sale:
        return {'label':'Insufficient data','reason':'No current technical assessment.'}
    technical=sale['technical_review_reason']
    reasons=([technical] if technical else [])+sale['portfolio_review_reasons']
    if reasons:
        shares=sale['sell_shares']
        return {'label':'Sell review','reason':' '.join(reasons),
                'review_price':sale['review_price'],
                'shares':shares or None,'percent':shares/sale['owned']*100 if shares else None,
                'sizing_blocker':None if shares else (sale['sizing_blocker'] or 'No whole-share reduction is available.')}
    if sale['technical_action']=='Hold / monitor' and not sale['technical_review_blocker']:
        return {'label':'Hold','reason':'No confirmed sell trigger for this holding.'}
    return {'label':'Insufficient data',
            'reason':sale['technical_review_blocker'] or 'No current technical assessment.'}


def build(snapshot,report,plan,feed,ledger=None,now=None):
    now=time.time() if now is None else now
    held={pf.canonical(p['symbol'],p['currency']) for p in snapshot['positions'] if p['shares']>0}
    reviews=[]
    def add(key,priority,title,detail,kind,symbol=None,url=None,source_asof=None,review_type=None):
        reviews.append({'id':hashlib.sha256(key.encode()).hexdigest()[:24],'priority':priority,'title':title,
                        'detail':detail,'kind':kind,'review_type':review_type,'symbol':symbol,'url':url,'source_asof':source_asof,'observed':now})
    for symbol in snapshot['portfolio_context']['missing']:
        add('missing:'+symbol,100,'Refresh '+symbol+' before sizing trades','Current portfolio valuation is incomplete.','data',symbol)
    if ledger and not ledger.get('reconciled',True):
        add('ledger-mismatch',100,'Reconcile holdings and cash' if ledger.get('initialized') else 'Initialize transaction tracking','Verify holdings and cash before using the transaction ledger.','ledger')
    changes=(report or {}).get('recommendation_changes',[])
    changed={(r['symbol'],r['direction']):r for r in changes}
    for row in plan['holdings']:
        if row.get('sell_shares'):
            change=changed.get((row['symbol'],'sell'),{}).get('change','Review')
            technical=technical_sale(row)
            add('sale:'+row['symbol']+':'+str(changed.get((row['symbol'],'sell'),{}).get('change_id','active')),90,row['symbol']+': review '+str(row['sell_shares'])+' shares for sale',
                change+'. '+' '.join(row['reasons'])+
                (' Entered sale fee: '+str(row['fee_nok'])+' NOK; estimated net proceeds before tax: '+str(row['net_proceeds_nok'])+' NOK.'
                 if row.get('fee_nok') is not None and row.get('net_proceeds_nok') is not None else
                 ' Gross sale estimate; sale fee unknown until entered. Tax is excluded.'),'holding',row['symbol'],
                review_type='technical sell review' if technical else 'portfolio-limit sale scenario')
    focused=held|set((report or {}).get('top20',[]))
    notices=announcements.view(feed,list(focused),now=now)
    for n in notices.get('items',[]):
        if n.get('corrected_by') or n['published']<now-86400:continue
        priority=(n.get('classification') or {}).get('priority',0)
        if priority>=3 or (n.get('classification') or {}).get('kind')=='earnings':
            add('notice:'+n['id'],95 if n['symbol'] in held else 75,n['symbol']+': '+n['title'],
                'New official issuer notice; read the linked source. Headline label is not a trade signal.','announcement',n['symbol'],n['url'],n['published'])
    if notices.get('status') in ('unavailable','stale','degraded'):
        add('announcement-feed-status',85,'Check announcement coverage','Official notice feed: '+str(notices.get('status'))+'. An empty feed is not evidence that nothing happened.','data')
    for symbol in held:
        record=snapshot.get('fundamentals',{}).get(symbol)
        financial=fundamentals.analyse(record,trade_plan.quote_for(snapshot,symbol),now)
        assessment=company_data.assessment(financial,snapshot['portfolio_preferences']['sectors'].get(symbol))
        for check in assessment['checks']:
            if not check['passes'] and check['metric'] in ('free_cash_flow','net_income'):
                add('annual:'+symbol+':'+check['metric']+':'+check['period'],80,symbol+': review annual '+check['metric'].replace('_',' '),
                    'Non-positive reported value for fiscal period '+check['period']+'. Annual accounting evidence is not a sell signal.','company',symbol,financial.get('source_url'),(record or {}).get('fetched'))
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
    if not decision_policy.current_report(report,now):
        add('stale-report',100,'Refresh the market report','Buy quantities and technical sale reviews need current signal evidence.','data')
    ordered=sorted({r['id']:r for r in reviews}.values(),key=lambda r:(-r['priority'],r['id']))
    cards={pf.canonical(c['symbol']):c for c in (report or {}).get('cards',[])}
    planned={r['symbol']:r for r in plan.get('holdings',[])}
    current=decision_policy.current_report(report,now)
    assessments=[]
    for position in snapshot['positions']:
        if position['shares']<=0:continue
        symbol=pf.canonical(position['symbol'],position['currency'])
        card=cards.get(symbol)
        sale=planned.get(symbol)
        assessments.append({'symbol':symbol,'position_symbol':position['symbol'],'shares':position['shares'],
            'advice':holding_advice(sale),
            'status':'current' if current and card else 'stale' if card else 'unavailable',
            'action':card.get('action') if card else None,
            'reasons':(card.get('reasons') or [])[:8] if card else [],
            'source_asof':card.get('asof') if card else None,
            'sale_review':({'shares':sale.get('sell_shares'),'reasons':sale.get('reasons',[]),
                'gross_proceeds_nok':sale.get('gross_proceeds_nok'),'fee_nok':sale.get('fee_nok'),
                'net_proceeds_nok':sale.get('net_proceeds_nok'),
                'technical':technical_sale(sale)} if sale and sale.get('sell_shares') else None)})
    return {'generated':now,'top3':ordered[:3],'reviews':ordered,'changes':changes,
            'plan':plan,'announcement_status':notices.get('status'),'ledger':ledger,
            'holding_assessments':assessments,
            'coverage':(report or {}).get('coverage',{}),
            'method':'Priorities are review rules, not probabilities. Browser notifications require opt-in and an open dashboard. Optional server-side email sends confirmed share-plan changes, recent issuer and annual financial reviews, and significant historical or long-term holding risks when SMTP is configured and enabled.'}


def merge_alerts(old,reviews,now=None):
    now=time.time() if now is None else now
    by_id={a['id']:dict(a) for a in (old or []) if now-a.get('first_seen',now)<30*86400}
    for r in reviews:
        if r['id'] not in by_id:by_id[r['id']]={**r,'first_seen':now,'read':False}
        else:by_id[r['id']].update({**r,'read':by_id[r['id']].get('read',False)})
    return sorted(by_id.values(),key=lambda a:(-a['first_seen'],a['id']))[:200]
