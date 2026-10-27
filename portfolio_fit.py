"""User-selected portfolio constraints and hypothetical purchases. No broker execution."""
import math
import re
import time

SECTORS = ['Energy', 'Materials', 'Industrials', 'Consumer discretionary', 'Consumer staples',
           'Health care', 'Financials', 'Information technology', 'Communication services',
           'Utilities', 'Real estate']
DEFAULTS = {'cash_nok': 0., 'purchase_nok': 0., 'max_stock_pct': 20., 'max_sector_pct': 35.,
            'reserve_pct': 10., 'cost_bps': 20., 'sectors': {}}


def number(value, name, maximum):
    if isinstance(value, bool):
        raise ValueError(name + ' must be a number.')
    try:
        value = float(value)
    except (ValueError, TypeError):
        raise ValueError(name + ' must be a number.')
    if not math.isfinite(value) or not 0 <= value <= maximum:
        raise ValueError(name + ' must be between 0 and ' + str(maximum) + '.')
    return value


def canonical(symbol, currency='NOK'):
    symbol = str(symbol).strip().upper()
    if currency == 'NOK' and '.' not in symbol:
        symbol += '.OL'
    return symbol


def preferences(data):
    out = {k:number(data.get(k,DEFAULTS[k]),k,1e9 if k in ('cash_nok','purchase_nok') else 200 if k=='cost_bps' else 100)
           for k in DEFAULTS if k != 'sectors'}
    if out['max_stock_pct'] == 0 or out['max_sector_pct'] == 0:
        raise ValueError('Position and sector limits must be greater than zero.')
    sectors = data.get('sectors',{})
    if not isinstance(sectors,dict) or len(sectors)>1000:
        raise ValueError('Sector classifications must be an object with at most 1000 symbols.')
    out['sectors']={}
    for s,sector in sectors.items():
        s=str(s).strip().upper()
        if not re.fullmatch(r'[A-Z0-9][A-Z0-9.\-]{0,19}',s) or sector not in SECTORS:
            raise ValueError('Choose a listed sector for a valid stock symbol.')
        out['sectors'][s]=sector
    return out


def fresh(q, now):
    return (q and isinstance(q.get('price'),(int,float)) and math.isfinite(q['price']) and q['price']>0
            and isinstance(q.get('asof'),(int,float)) and math.isfinite(q['asof'])
            and -300 <= now-q['asof'] < 4*86400)


def context(snapshot, profile, now=None):
    now=time.time() if now is None else now
    holdings={}; fx=snapshot['quotes'].get('NOK=X'); missing=[]
    for p in snapshot['positions']:
        if p['shares']<=0:
            continue
        s=canonical(p['symbol'],p['currency'])
        row=holdings.setdefault(s,{'symbol':s,'shares':0.,'value_nok':0.,'sector':profile['sectors'].get(s),'priced':True})
        row['shares']+=p['shares']
        q=snapshot['quotes'].get(p['symbol']) or snapshot['quotes'].get(s)
        valid=fresh(q,now) and q.get('currency')==p['currency']
        rate=1.
        if p['currency']=='USD':
            valid=valid and fresh(fx,now) and fx.get('currency')=='NOK'
            rate=fx['price'] if valid else 1.
        elif p['currency']!='NOK':
            valid=False
        if valid:
            row['value_nok']+=p['shares']*q['price']*rate
        else:
            row['priced']=False
            missing.append(s)
    complete=not missing
    total=profile['cash_nok']+sum(r['value_nok'] for r in holdings.values()) if complete else None
    sectors={}
    for r in holdings.values():
        if not r['priced']:
            r['value_nok']=None
        r['weight_pct']=r['value_nok']/total*100 if complete and total and r['priced'] else None
        if r['priced']:
            sector=r['sector'] or 'Unclassified'
            sectors[sector]=sectors.get(sector,0)+r['value_nok']
    exposure=[{'sector':s,'value_nok':v,'weight_pct':v/total*100 if complete and total else None}
              for s,v in sorted(sectors.items(),key=lambda item:-item[1])]
    warnings=[]
    if missing:
        warnings.append('Portfolio valuation is incomplete. Refresh missing prices before sizing purchases: '+', '.join(sorted(set(missing))))
    if any(not r['sector'] for r in holdings.values()):
        warnings.append('Some holdings have no sector classification. Sector capacity cannot be confirmed until all held stocks are classified.')
    if total:
        warnings.extend(r['symbol']+' exceeds your position limit.' for r in holdings.values() if r['weight_pct']>profile['max_stock_pct']+1e-8)
        warnings.extend(r['sector']+' exceeds your sector limit.' for r in exposure if r['sector']!='Unclassified' and r['weight_pct']>profile['max_sector_pct']+1e-8)
        if profile['cash_nok']/total*100 < profile['reserve_pct']-1e-8:
            warnings.append('Tracked cash is below your chosen reserve.')
    return {'holdings':list(holdings.values()),'sectors':exposure,'complete':complete,'total_nok':total,
            'priced_holdings_nok':sum(r['value_nok'] or 0 for r in holdings.values()),'cash_nok':profile['cash_nok'],
            'cash_pct':profile['cash_nok']/total*100 if total else None,
            'sectors_complete':all(r['sector'] for r in holdings.values()),'missing':sorted(set(missing)),
            'warnings':warnings,'scope':'Tracked holdings plus manually entered cash only; excludes other assets and accounts.'}


def correlation(a,b):
    # Align both the start AND end date of a daily return, never bridge different missing sessions.
    def returns(q):
        days={}
        for p in (q or {}).get('history',[]):
            if all(isinstance(p.get(k),(int,float)) and math.isfinite(p[k]) and p[k]>0 for k in ('time','close')):
                days[int(p['time']//86400)]=p['close']
        keys=sorted(days)[-127:]
        return {(x,y):days[y]/days[x]-1 for x,y in zip(keys,keys[1:])}
    ra,rb=returns(a),returns(b); shared=sorted(set(ra)&set(rb))[-126:]
    if len(shared)<60:
        return None
    x=[ra[k] for k in shared];y=[rb[k] for k in shared]
    ax=sum(x)/len(x);ay=sum(y)/len(y)
    vx=sum((v-ax)**2 for v in x);vy=sum((v-ay)**2 for v in y)
    if vx<1e-20 or vy<1e-20:
        return None
    return {'value':max(-1.,min(1.,sum((a-ax)*(b-ay) for a,b in zip(x,y))/math.sqrt(vx*vy))),
            'observations':len(shared),'from':shared[0][0]*86400,'to':shared[-1][1]*86400}


def preview(symbol, amount, snapshot, profile, portfolio=None, now=None):
    now=time.time() if now is None else now
    symbol=canonical(symbol)
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL',symbol):
        raise ValueError('Choose an Oslo stock symbol.')
    amount=number(amount,'Purchase budget',1e9)
    ctx=portfolio or context(snapshot,profile,now)
    q=snapshot['quotes'].get(symbol)
    if not q:
        q=next((snapshot['quotes'].get(p['symbol']) for p in snapshot['positions']
                if canonical(p['symbol'],p['currency'])==symbol and snapshot['quotes'].get(p['symbol'])),None)
    sector=profile['sectors'].get(symbol)
    result={'symbol':symbol,'sector':sector,'budget_nok':amount,'ready':False,'warnings':[],
            'max_purchase_nok':None,'shares':None,'purchase_nok':None,'fees_nok':None,
            'after_stock_pct':None,'after_sector_pct':None,'after_cash_nok':None,'after_cash_pct':None,
            'current_stock_pct':None,'current_sector_pct':None,'quote_asof':q.get('asof') if q else None}
    if not fresh(q,now) or q.get('currency')!='NOK':
        result['warnings'].append('Fresh NOK price required for purchase preview.')
        return result
    if not ctx['complete'] or not ctx['total_nok']:
        result['warnings'].append('Complete holdings prices and a positive tracked portfolio value are required.')
        return result
    total=ctx['total_nok'];rate=profile['cost_bps']/10000
    existing=next((h['value_nok'] for h in ctx['holdings'] if h['symbol']==symbol),0.)
    sector_value=sum(h['value_nok'] for h in ctx['holdings'] if sector and h['sector']==sector)
    result['current_stock_pct']=existing/total*100
    sector_known=bool(sector and ctx['sectors_complete'])
    result['current_sector_pct']=sector_value/total*100 if sector_known else None
    stock_limit=profile['max_stock_pct']/100;sector_limit=profile['max_sector_pct']/100;reserve=profile['reserve_pct']/100
    capacities={'position':max(0,(stock_limit*total-existing)/(1+stock_limit*rate)),
                'cash reserve':max(0,(profile['cash_nok']-reserve*total)/(1+rate*(1-reserve)))}
    if sector_known:
        capacities['sector']=max(0,(sector_limit*total-sector_value)/(1+sector_limit*rate))
        result['max_purchase_nok']=min(capacities.values())
    else:
        result['warnings'].append('Classify this stock and every holding before sector capacity can be confirmed.')
    # Whole shares. Budget includes estimated costs, never silently overspend the entered amount.
    shares=math.floor(amount/(q['price']*(1+rate)))
    purchase=shares*q['price'];fee=purchase*rate;after_total=total-fee
    if after_total<=0:
        result['warnings'].append('Estimated costs exhaust the tracked portfolio.')
        return result
    after_cash=profile['cash_nok']-purchase-fee
    result.update(shares=shares,purchase_nok=purchase,fees_nok=fee,price=q['price'],
                  after_stock_pct=(existing+purchase)/after_total*100,
                  after_sector_pct=(sector_value+purchase)/after_total*100 if sector_known else None,
                  after_cash_nok=after_cash,after_cash_pct=after_cash/after_total*100,
                  capacity_before_costs_nok=capacities)
    if shares==0:
        result['warnings'].append('Budget does not cover one whole share including estimated costs.')
    if purchase>capacities['position']+1e-8:
        result['warnings'].append('Purchase would exceed your position limit.')
    if purchase>capacities['cash reserve']+1e-8:
        result['warnings'].append('Purchase would breach your cash reserve or available cash.')
    if sector_known and purchase>capacities['sector']+1e-8:
        result['warnings'].append('Purchase would exceed your sector limit.')
    result['ready']=not result['warnings']
    return result


def view(snapshot, report, profile, now=None):
    now=time.time() if now is None else now
    profile=preferences(profile)
    ctx=context(snapshot,profile,now)
    cards=(report or {}).get('cards',[])
    old=not report or not isinstance(report.get('generated'),(int,float)) or now-report['generated']>86400 or report['generated']>now+300
    candidates=[]
    for card in sorted((c for c in cards if c.get('rank_eligible')),key=lambda c:(-c.get('composite',0),c['symbol']))[:20]:
        symbol=canonical(card['symbol'])
        simulation=preview(symbol,profile['purchase_nok'],snapshot,profile,ctx,now)
        actionable=not old and card.get('action')=='Consider buying' and fresh({'price':card.get('price'),'asof':card.get('asof')},now)
        simulation['technical_action']=card.get('action') if not old else 'Stale report'
        simulation['rank']=card.get('rank');simulation['name']=card.get('name',symbol)
        simulation['held']=any(h['symbol']==symbol for h in ctx['holdings'])
        simulation['status']=('Within chosen limits' if simulation['ready'] and actionable else
                              'Monitor technical signal' if simulation['ready'] else 'Review portfolio limits / data')
        simulation['buy_candidate']=simulation['ready'] and actionable
        correlations=[]
        for h in ctx['holdings']:
            if h['symbol']==symbol:
                continue
            other=snapshot['quotes'].get(h['symbol']) or next((snapshot['quotes'].get(p['symbol']) for p in snapshot['positions'] if canonical(p['symbol'],p['currency'])==h['symbol']),None)
            if not fresh(other,now) or other.get('currency')!='NOK':
                continue
            corr=correlation(snapshot['quotes'].get(symbol),other)
            if corr:
                correlations.append({'symbol':h['symbol'],**corr})
        simulation['highest_correlation']=max(correlations,key=lambda c:c['value']) if correlations else None
        candidates.append(simulation)
    return {'generated':now,'profile':profile,'sector_choices':SECTORS,'portfolio':ctx,'candidates':candidates,
            'report_generated':(report or {}).get('generated'),'report_stale':old,
            'method':'Your limits are screening constraints, not a measure of investment suitability. Defaults are illustrative. '
                     'Preview uses whole shares at the cached quote with proportional costs. No minimum brokerage, tax, '
                     'spread, price movement or real execution is modelled. Classifications are entered by you; '
                     'unclassified holdings block sector clearance. Correlations use 60–126 matching historical daily returns '
                     'in NOK, omit USD holdings, and do not predict future relationships. Purchases do not change saved holdings or cash.'}
