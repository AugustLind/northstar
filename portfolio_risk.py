"""Current-weight historical risk and explicit hypothetical shocks; no forecasts."""
import math
import time
import portfolio_fit as pf


def daily_prices(quote):
    return {int(p['time']//86400):p['close'] for p in (quote or {}).get('history', [])
            if all(isinstance(p.get(k),(int,float)) and not isinstance(p[k],bool)
                   and math.isfinite(p[k]) and p[k]>0 for k in ('time','close'))}


def intervals(prices):
    days=sorted(prices)
    return {(a,b):prices[b]/prices[a]-1 for a,b in zip(days,days[1:])}


def covariance(a,b):
    ma=sum(a)/len(a);mb=sum(b)/len(b)
    return sum((x-ma)*(y-mb) for x,y in zip(a,b))/(len(a)-1)


def tail_losses(values):
    values=sorted(values);n=len(values);at=(n-1)*.05;i=int(at)
    percentile=values[i]+(values[min(i+1,n-1)]-values[i])*(at-i)
    mass=n*.05;k=int(mass)
    mean=(sum(values[:k])+(mass-k)*values[k])/mass
    return max(0,-percentile*100),max(0,-mean*100)


def view(snapshot,profile,now=None,stock_shock=-20,fx_shock=-10):
    now=time.time() if now is None else now
    for name,value in [('Equity shock',stock_shock),('USD/NOK shock',fx_shock)]:
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not -100<=value<=100:
            raise ValueError(name+' must be between -100% and +100%.')
    ctx=pf.context(snapshot,profile,now);holdings=ctx['holdings'];total=ctx['total_nok']
    result={'generated':now,'status':'unavailable','portfolio':ctx,'volatility_pct':None,'var95_pct':None,
            'tail95_pct':None,'risk_contributions':[],'correlations':[],'observations':0,'from':None,'to':None,
            'curve':[],'scenarios':[],'benchmark':None,'missing':[],
            'method':'Historical proxy using today’s NOK weights, rebalanced daily with zero-return NOK cash. Not actual account performance or a forecast. '
                     'All held assets must have fresh prices and at least 60 exactly matching return intervals; at most 252 intervals are used. '
                     'USD prices require FX on both endpoints. Missing sessions are never filled. Contribution = weight × covariance with portfolio / portfolio variance; hedges can be negative. '
                     'Shocks are user assumptions, not predicted events. Excludes fees, tax and untracked accounts.'}
    if not ctx['complete'] or not total:
        result['missing']=ctx['missing'] or ['Positive tracked value required.'];return result
    currencies={}
    for p in snapshot['positions']:
        if p['shares']>0:currencies[pf.canonical(p['symbol'],p['currency'])]=p['currency']
    # Valuation-based shocks remain available even when historical risk is unavailable.
    def scenario(label,equity,fx,sector=None):
        rows=[]
        for h in holdings:
            e=equity/100 if sector is None or h['sector']==sector else 0
            f=fx/100 if currencies.get(h['symbol'])=='USD' else 0
            change=h['value_nok']*((1+e)*(1+f)-1)
            rows.append({'symbol':h['symbol'],'change_nok':change})
        change=sum(r['change_nok'] for r in rows)
        return {'label':label,'change_nok':change,'change_pct':change/total*100,'after_nok':total+change,'holdings':rows}
    result['scenarios']=[scenario('All equities −20%; FX unchanged',-20,0),scenario('USD/NOK −10%; local stock prices unchanged',0,-10),
                         scenario('Custom: equities '+str(stock_shock)+'%, USD/NOK '+str(fx_shock)+'%',stock_shock,fx_shock)]
    sectors=[s for s in ctx['sectors'] if s['sector']!='Unclassified']
    if sectors:result['scenarios'].append(scenario('Largest classified sector −30%: '+sectors[0]['sector'],-30,0,sectors[0]['sector']))
    weights=[h['value_nok']/total for h in holdings]
    issuer_weights=[r['value_nok']/total for r in ctx['issuer_exposure']]
    invested=sum(weights)
    result['concentration']={'largest_company_pct':max(issuer_weights,default=0)*100,
        'effective_equity_companies':invested**2/sum(w*w for w in issuer_weights) if invested else None,
        'usd_asset_pct':sum(h['value_nok'] for h in holdings if currencies.get(h['symbol'])=='USD')/total*100}
    if not holdings:
        result.update(status='cash_only',volatility_pct=0,var95_pct=0,tail95_pct=0);return result
    fx=daily_prices(snapshot['quotes'].get('NOK=X'));returns=[]
    for h in holdings:
        q=snapshot['quotes'].get(h['symbol']) or next((snapshot['quotes'].get(p['symbol']) for p in snapshot['positions']
            if pf.canonical(p['symbol'],p['currency'])==h['symbol']),None)
        prices=daily_prices(q)
        r=intervals(prices)
        if currencies[h['symbol']]=='USD':r={(a,b):(1+v)*fx[b]/fx[a]-1 for (a,b),v in r.items() if a in fx and b in fx}
        returns.append(r)
        if len(r)<60:result['missing'].append(h['symbol']+': fewer than 60 usable NOK return intervals')
    common=sorted(set.intersection(*(set(r) for r in returns)))[-252:]
    result['observations']=len(common)
    if common:result.update({'from':common[0][0]*86400,'to':common[-1][1]*86400})
    if len(common)<60:
        result['missing'].append('At least 60 matching intervals across every holding required; no partial portfolio is substituted.');return result
    values=[[r[d] for d in common] for r in returns]
    portfolio=[sum(w*values[i][t] for i,w in enumerate(weights)) for t in range(len(common))]
    variance=max(0,covariance(portfolio,portfolio));vol=math.sqrt(variance*252)*100
    var,tail=tail_losses(portfolio)
    result.update(status='available',volatility_pct=vol,var95_pct=var,tail95_pct=tail)
    for i,h in enumerate(holdings):
        individual=max(0,covariance(values[i],values[i]));contribution=weights[i]*covariance(values[i],portfolio)
        result['risk_contributions'].append({'symbol':h['symbol'],'weight_pct':weights[i]*100,
             'annual_volatility_pct':math.sqrt(individual*252)*100,
             'risk_share_pct':contribution/variance*100 if variance>1e-20 else None,
             'volatility_contribution_pct':contribution/math.sqrt(variance)*math.sqrt(252)*100 if variance>1e-20 else 0})
    # Bound display size only; the covariance model above always includes ALL holdings.
    matrix_indices=sorted(range(len(holdings)),key=lambda i:-weights[i])[:24]
    for i in matrix_indices:
        row=[]
        for j in matrix_indices:
            vi=covariance(values[i],values[i]);vj=covariance(values[j],values[j])
            row.append(max(-1,min(1,covariance(values[i],values[j])/math.sqrt(vi*vj))) if vi>1e-20 and vj>1e-20 else None)
        result['correlations'].append({'symbol':holdings[i]['symbol'],'values':row})
    result['matrix_note']='Largest '+str(len(matrix_indices))+' holdings displayed; risk totals include all '+str(len(holdings))+'. Same aligned sample for every cell.'
    equity=1.;peak=1.;worst=0
    result['curve']=[{'time':common[0][0]*86400,'close':1.}]
    for day,value in zip(common,portfolio):
        equity*=1+value;peak=max(peak,equity);worst=min(worst,equity/peak-1)
        result['curve'].append({'time':day[1]*86400,'close':equity})
    result['proxy_drawdown_pct']=worst*100
    benchmark=intervals(daily_prices(snapshot['quotes'].get('OSEBX.OL')))
    shared=[(i,d) for i,d in enumerate(common) if d in benchmark]
    if len(shared)>=60:
        a=[portfolio[i] for i,d in shared];b=[benchmark[d] for i,d in shared]
        va=covariance(a,a);vb=covariance(b,b);co=covariance(a,b)
        result['benchmark']={'symbol':'OSEBX.OL','observations':len(shared),'beta':co/vb if vb>1e-20 else None,
                             'correlation':max(-1,min(1,co/math.sqrt(va*vb))) if va>1e-20 and vb>1e-20 else None}
    return result
