"""Ledger-derived account returns, distinct from hypothetical current-weight proxies.

NOK cash ledger; USD opening holdings are translated with dated USD/NOK observations.
Returns use dated net broker cash, without subtracting informational fees again.
"""
import datetime as dt
import math
import time
import portfolio_fit as pf

VERSION='ledger-performance-v1'
METHOD=('Account valuations use historical-share-unit closes, recorded quantities and dated NOK cash. '
        'Net broker cash already includes fees and withholding; reported fee fields are informational. '
        'Dividend income is recognised on its recorded cash date, not inferred from adjusted prices. '
        'Daily-linked returns assume external deposits/withdrawals occur at day end; transaction exports contain no intraday timing. '
        'Modified Dietz is a date-weighted approximation, not certified true time-weighted or broker-reported performance. '
        'USD holdings use same-date USD/NOK; issuer business-currency exposure is not inferred. '
        'No missing trades, unsupported transfers, accruals, corporate actions or historical cost bases are invented.')


def finite(v):return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
def day(stamp):return dt.datetime.fromtimestamp(stamp,dt.timezone.utc).date().isoformat()
def event_order(e):return (e['date'],0 if e['type']=='split' else 1 if e['type']=='buy' else 2,e.get('id',0),e.get('uid',''))


def positions_map(rows):
    result={}
    for p in rows:
        if p['shares']<0:raise ValueError('Negative holdings cannot be reconstructed.')
        symbol=pf.canonical(p['symbol'],p['currency'])
        if symbol in result:raise ValueError('Resolve duplicate bare/.OL holdings before measuring account returns.')
        result[symbol]={'symbol':symbol,'currency':p['currency'],'shares':p['shares'],'cost':p.get('cost')}
    return result


def apply_event(holdings,e,reverse=False):
    if e['type'] not in ('buy','sell','split'):return
    symbol=pf.canonical(e['symbol']);p=holdings.setdefault(symbol,{'symbol':symbol,'currency':'NOK','shares':0.,'cost':None})
    if p['currency']!='NOK':raise ValueError('This ledger supports NOK-settled Oslo trades; USD trades require a separate supported ledger.')
    if e['type']=='split':
        ratio=e.get('split_ratio')
        if not finite(ratio) or ratio<=0:raise ValueError('A verified positive split ratio is required.')
        p['shares']*=1/ratio if reverse else ratio
        if not reverse and p.get('cost') is not None:p['cost']/=ratio
    else:
        delta=e['quantity']*(1 if e['type']=='buy' else -1)*(-1 if reverse else 1)
        if not finite(delta) or p['shares']+delta < -1e-8:raise ValueError('Recorded trades cannot reconstruct nonnegative opening quantities.')
        if not reverse and e['type']=='buy':
            book=0. if p['shares']<=1e-10 else p['shares']*p['cost'] if p.get('cost') is not None else None
            p['cost']=(book+abs(e['net_cash']))/(p['shares']+delta) if book is not None and p['shares']+delta else None
        p['shares']=max(0,p['shares']+delta)


def view(snapshot,baseline,events,now=None,allow_prior_close=False):
    now=time.time() if now is None else now
    out={'version':VERSION,'generated':now,'status':'unavailable','method':METHOD,'curve':[],'coverage':[],
         'opening_value_nok':None,'ending_value_nok':None,'net_contributions_nok':None,'investment_pnl_nok':None,
         'daily_linked_return_pct':None,'modified_dietz_pct':None,'realized_trade_pnl_nok':None,
         'income_nok':None,'reported_fees_nok':None,'carried_valuations':0,'excluded_later_events':0,'opening_basis':None}
    def block(reason):
        if reason not in out['coverage']:out['coverage'].append(reason)
    if not baseline:
        block('Initialize a verified opening holdings/cash snapshot in Activity & cash first.');return out
    if snapshot.get('ledger_reconciled') is not True:
        block('Reconcile tracked holdings and cash with the ledger and broker before measuring account returns.');return out
    cutoff=baseline['cutoff_date'];today=day(now);yesterday=(dt.date.fromisoformat(today)-dt.timedelta(days=1)).isoformat()
    if cutoff>=yesterday:
        block('At least one completed UTC day after the verified opening cutoff is required.');return out
    selected=sorted((e for e in events if e['date']>cutoff),key=event_order)
    if any(e.get('currency')!='NOK' or e['type'] not in ('buy','sell','split','deposit','withdrawal','dividend','interest','fee')
           or not finite(e.get('net_cash')) for e in selected):
        block('Unsupported transaction currency/type or nonfinite cash amount prevents a complete account calculation.');return out
    try:
        if 'opening_positions' in baseline:
            opening=positions_map(baseline['opening_positions']);out['opening_basis']='Verified stored opening positions and cost bases.'
        else:
            opening=positions_map(snapshot['positions'])
            for e in reversed(selected):apply_event(opening,e,reverse=True)
            for p in opening.values():p['cost']=None
            out['opening_basis']='Opening quantities reconstructed backwards from reconciled holdings and imported events. Historical average costs cannot be recovered reliably; realised trade P&L is unavailable.'
        check={s:dict(p) for s,p in opening.items()};cash=baseline['opening_cash_nok']
        for e in selected:apply_event(check,e);cash+=e['net_cash']
        current=positions_map(snapshot['positions'])
        if any(abs(check.get(s,{}).get('shares',0)-current.get(s,{}).get('shares',0))>1e-7 for s in set(check)|set(current)) or abs(cash-snapshot['manual_portfolio_preferences']['cash_nok'])>.01:
            block('The opening snapshot plus imported events does not reproduce current holdings/cash.');return out
    except (ValueError,KeyError,TypeError) as error:
        block(str(error));return out
    historical={s:dict(p) for s,p in opening.items()}
    for e in selected:
        if e['date']<=yesterday:apply_event(historical,e)
    active=[s for s,p in historical.items() if p['shares']>1e-10]
    symbols={s for s,p in opening.items() if p['shares']>1e-10}|{pf.canonical(e['symbol']) for e in selected if e['type'] in ('buy','sell','split') and e['date']<=yesterday}
    if any(p['currency']=='USD' and p['shares']>1e-10 for p in opening.values()):symbols.add('NOK=X')
    prices={};splits={};quotes=snapshot['quotes']
    for s in symbols:
        q=quotes.get(s) or next((quotes.get(p['symbol']) for p in snapshot['positions'] if pf.canonical(p['symbol'],p['currency'])==s),None)
        if not q:prices[s]={};block(s+': no historical prices.');continue
        expected_currency='NOK' if s=='NOK=X' else opening.get(s,{}).get('currency','NOK')
        if q.get('currency')!=expected_currency:
            prices[s]={};block(s+': quote currency does not match the recorded asset or FX basis.');continue
        if q.get('account_history_version')!=1:
            prices[s]={};block(s+': refresh market data to store the separate account-valuation price basis.');continue
        prices[s]={day(p['time']):p['account_close'] for p in q.get('history',[]) if finite(p.get('account_close')) and p['account_close']>0 and day(p['time'])<=yesterday}
        splits[s]={day(e['time']):e['ratio'] for e in q.get('events',[]) if e.get('kind')=='split' and finite(e.get('ratio')) and e['ratio']>0}
    end=yesterday
    for s in active+(['NOK=X'] if any(historical[s]['currency']=='USD' for s in active) else []):
        if not prices.get(s):block(s+': account price history is unavailable.');continue
        end=min(end,max(prices[s]))
    if out['coverage']:return out
    if end<=cutoff:block('Opening cutoff is outside available account price history.');return out
    out.update({'from':cutoff,'to':end})
    selected=[e for e in selected if e['date']<=end]
    out['excluded_later_events']=sum(e['date']>end for e in events if e['date']>cutoff)
    calendar={cutoff,end}|{e['date'] for e in selected}
    # Union means an absent held-asset price is visible; it cannot disappear in an intersection.
    for s,rows in prices.items():calendar.update(d for d in rows if cutoff<=d<=end)
    cash=baseline['opening_cash_nok'];holdings={s:dict(p) for s,p in opening.items()};flows=[];curve=[];linked=1.;linked_valid=True;realized=0.;realized_valid=True
    out['income_nok']=sum(e['net_cash'] for e in selected if e['type'] in ('dividend','interest'))
    out['reported_fees_nok']=sum(abs(e['net_cash']) if e['type']=='fee' else e['fee'] if finite(e.get('fee')) else 0 for e in selected) # informational; never deducted again
    groups={}
    for e in selected:groups.setdefault(e['date'],[]).append(e)
    def price(s,date):
        if date in prices.get(s,{}):return prices[s][date],False
        earlier=[d for d in prices.get(s,{}) if d<date]
        if allow_prior_close and earlier:
            previous=max(earlier)
            if (dt.date.fromisoformat(date)-dt.date.fromisoformat(previous)).days<=4:return prices[s][previous],True
        block(s+': missing exact-date account close on '+date+'.');return None,False
    for date in sorted(calendar):
        rows=groups.get(date,[]);external=sum(e['net_cash'] for e in rows if e['type'] in ('deposit','withdrawal'))
        for s,p in holdings.items():
            provider_ratio=splits.get(s,{}).get(date)
            ledger_ratios=[e['split_ratio'] for e in rows if e['type']=='split' and pf.canonical(e['symbol'])==s]
            ledger_ratio=math.prod(ledger_ratios) if ledger_ratios else None
            if p['shares']>1e-10 and (provider_ratio is not None or ledger_ratio is not None) and (provider_ratio is None or ledger_ratio is None or abs(provider_ratio-ledger_ratio)>1e-8):
                block(s+': provider/ledger split on '+date+' needs an explicitly matching recorded ratio.')
        for e in rows:
            if e['type']=='sell':
                p=holdings.get(pf.canonical(e['symbol']))
                if p and p.get('cost') is not None:realized+=e['net_cash']-e['quantity']*p['cost']
                else:realized_valid=False
            apply_event(holdings,e);cash+=e['net_cash']
            if e['type'] in ('deposit','withdrawal'):flows.append((date,e['net_cash']))
        valuation_day=date in (cutoff,end) or bool(rows) or any(p['shares']>1e-10 and (date in prices.get(s,{}) or p['currency']=='USD' and date in prices.get('NOK=X',{})) for s,p in holdings.items())
        if not valuation_day:continue
        value=cash;carried=False;valid=True
        for s,p in holdings.items():
            if p['shares']<=1e-10:continue
            close,was_carried=price(s,date);carried|=was_carried
            fx=1.
            if p['currency']=='USD':fx,fx_carried=price('NOK=X',date);carried|=fx_carried
            elif p['currency']!='NOK':block(s+': unsupported valuation currency.');valid=False
            if close is None or fx is None:valid=False
            else:value+=p['shares']*close*fx
        if not valid:continue
        if curve:
            previous=curve[-1]['value_nok']
            if previous<=0 or value-external<0:linked_valid=False
            else:linked*=(value-external)/previous
        if carried:out['carried_valuations']+=1
        curve.append({'date':date,'time':dt.datetime.fromisoformat(date).replace(tzinfo=dt.timezone.utc).timestamp(),
                      'value_nok':value,'cash_nok':cash,'external_cash_nok':external,'close':linked if linked_valid else None,'prior_close_used':carried})
    if out['coverage'] or not curve or curve[0]['date']!=cutoff or curve[-1]['date']!=end:
        out['coverage']=out['coverage'][:25];return out
    start_value=curve[0]['value_nok'];end_value=curve[-1]['value_nok'];net=sum(v for d,v in flows)
    pnl=end_value-start_value-net;duration=(dt.date.fromisoformat(end)-dt.date.fromisoformat(cutoff)).days
    weighted=start_value+sum((dt.date.fromisoformat(end)-dt.date.fromisoformat(d)).days/duration*v for d,v in flows)
    out.update(status='estimated' if out['carried_valuations'] else 'available',curve=curve,opening_value_nok=start_value,
        ending_value_nok=end_value,net_contributions_nok=net,investment_pnl_nok=pnl,
        daily_linked_return_pct=(linked-1)*100 if linked_valid else None,modified_dietz_pct=pnl/weighted*100 if weighted>0 and pnl/weighted>=-1 else None,
        realized_trade_pnl_nok=realized if realized_valid and 'opening_positions' in baseline else None)
    if not linked_valid:out['coverage'].append('Daily linking is undefined for zero prior capital or incompatible end-of-day cash-flow timing; NOK P&L remains measurable.')
    if out['carried_valuations']:out['coverage'].append('Prior closes were explicitly allowed (at most four calendar days). Returns are estimates across those valuations.')
    return out
