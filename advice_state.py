"""Dated signal persistence and recommendation change tracking; polling is not evidence."""
import datetime as dt
import time
import trade_plan


def observe(report,previous,now=None):
    now=time.time() if now is None else now
    result=dict(previous or {})
    for card in report.get('cards',[]):
        symbol=trade_plan.pf.canonical(card['symbol']);old=result.get(symbol,{})
        if card.get('action') in trade_plan.SELL_SIGNALS:
            intent='sell'
        elif trade_plan.buy_signal(card):intent='buy'
        else:intent='watch'
        if not trade_plan.signal_current(card,now):intent='unavailable'
        session=dt.datetime.fromtimestamp(card.get('asof') or now,dt.timezone.utc).date().isoformat()
        same=old.get('intent')==intent
        sessions=list(old.get('sessions',[])) if same else []
        if session not in sessions:sessions.append(session)
        result[symbol]={'intent':intent,'since':old.get('since',now) if same else now,'sessions':sessions[-30:],
                        'last_seen':now,'action':card.get('action')}
    return result


def gate(symbol,direction,snapshot,profile,now):
    if 'signal_state' not in snapshot:return None
    record=snapshot.get('signal_state',{}).get(symbol,{})
    if record.get('intent')!=direction:return 'Waiting for a matching dated signal observation.'
    count=len(record.get('sessions',[]));required=int(profile['confirm_sessions'])
    if count<required:return 'Waiting for signal confirmation: '+str(count)+' / '+str(required)+' market sessions.'
    if now-record.get('since',now)<profile['signal_wait_hours']*3600:
        return 'Waiting for your '+str(profile['signal_wait_hours'])+'-hour signal persistence period.'
    last=snapshot.get('last_trades',{}).get(symbol)
    if last and 0<=now-last<profile['trade_cooldown_days']*86400:
        return 'Within your '+str(profile['trade_cooldown_days'])+'-day cooldown after a recorded trade.'
    return None


def differences(plan,previous,threshold=20,now=None):
    now=time.time() if now is None else now
    current={r['symbol']:{'direction':'buy','shares':r['buy_shares']} for r in plan.get('buys',[])}
    current.update({r['symbol']:{'direction':'sell','shares':r['sell_shares']} for r in plan.get('holdings',[]) if r.get('sell_shares')})
    rows=[]
    for symbol,value in current.items():
        old=(previous or {}).get(symbol)
        reference=(old or {}).get('reference_shares',(old or {}).get('shares',0))
        delta=abs(value['shares']-reference)
        small=old and old.get('direction')==value['direction'] and delta<max(1,reference*threshold/100)
        label='New' if not old else 'Unchanged' if small or (old.get('direction')==value['direction'] and old.get('shares')==value['shares']) else 'Updated'
        value['reference_shares']=reference if label=='Unchanged' else value['shares']
        value['change_id']=old.get('change_id',str(now)) if label=='Unchanged' else str(now)
        rows.append({'symbol':symbol,**value,'change':label})
    rows.extend({'symbol':s,**v,'change':'Withdrawn'} for s,v in (previous or {}).items() if s not in current)
    return current,rows
