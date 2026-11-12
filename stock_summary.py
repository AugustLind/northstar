"""Measured stock decision context using existing policy and current portfolio gates."""
import time
import decision_policy as policy
import portfolio_fit as pf
import trade_plan
import fundamentals


def build(symbol,snapshot,report,profile,now=None):
    now=time.time() if now is None else now
    symbol=fundamentals.canonical(symbol)
    card=next((c for c in (report or {}).get('cards',[]) if c['symbol']==symbol),{})
    m=card.get('metrics',{});current=trade_plan.current_report(report,now)
    quote=snapshot['quotes'].get(symbol) or snapshot['quotes'].get(symbol[:-3])
    current=bool(current and pf.fresh(quote,now) and quote.get('currency')=='NOK' and card.get('currency')=='NOK' and pf.fresh({'price':card.get('price'),'asof':card.get('asof')},now))
    preview=pf.preview(symbol,profile['purchase_nok'],snapshot,profile,now=now)
    plan=trade_plan.build(snapshot,report,profile,now)
    buy=next((r for r in plan.get('buys',[]) if r['symbol']==symbol),None)
    holding=next((r for r in plan.get('holdings',[]) if r['symbol']==symbol),None)
    blocked=next((r for r in plan.get('blocked_buys',[]) if r['symbol']==symbol),None)
    checks=[]
    def check(label,keys,test):
        ready=all(isinstance(m.get(k),(float,int)) for k in keys)
        checks.append({'label':label,'passes':bool(test()) if ready and current else None})
    check('Close above MA200',['close','ma200'],lambda:m['close']>m['ma200'])
    check('Close above MA50',['close','ma50'],lambda:m['close']>m['ma50'])
    check('MA50 above MA200',['ma50','ma200'],lambda:m['ma50']>m['ma200'])
    check('Positive 3-month momentum',['momentum3m'],lambda:m['momentum3m']>0)
    check('Annual volatility below 50%',['volatility'],lambda:m['volatility']<50)
    check('Close less than 15% above MA50',['extension50'],lambda:m['extension50']<15)
    check('Turnover floor with 15 observations',['turnover20','turnover_days'],lambda:m['turnover_days']>=15 and m['turnover20']>=(report or {}).get('min_turnover_nok',250000))
    reasons=list(card.get('reasons',[])) if current else ['A current report and fresh matching quote are required before interpreting this signal.']
    risks=[]
    if m.get('volatility63',0)>=40:risks.append('Recent annualised volatility is at least 40%; large price moves have occurred.')
    if m.get('max_drawdown1y',0)<=-20:risks.append('The historical one-year sample includes a drawdown of at least 20%.')
    record=snapshot.get('fundamentals',{}).get(symbol)
    financial=fundamentals.analyse(record,quote,now)
    if financial['status'] in ('stale','unavailable'):risks.append('Annual financial coverage is '+financial['status']+'. Review current company reports.')
    if financial['status'] not in ('stale','unavailable'):
        fm=financial.get('metrics',{});sector=profile['sectors'].get(symbol)
        for key,label in [('revenue_growth','Annual revenue growth'),('net_income','Annual net income'),('equity','Reported equity')]+([] if sector=='Financials' else [('operating_cash_flow','Annual operating cash flow'),('free_cash_flow','Annual free cash flow')]):
            metric=fm.get(key)
            if metric and metric['value']<0:risks.append(label+' was negative for '+metric['period']+'. Review the source and sector context.')
    risks+=preview['warnings']
    if not risks:risks=['No additional diagnostic flag fired. Business, valuation and execution risks still require review.']
    invalidation=['Entry qualification can lapse if any trend, liquidity, volatility or extension check fails.',
                  'A failed entry check alone is not an automatic sell signal. The held-stock exit rule requires close below MA200 and negative 3-month momentum.',
                  'Stale quotes/reports, cash mismatches, confirmation and cooldown gates can withhold quantities.']
    positions=[p for p in snapshot['positions'] if pf.canonical(p['symbol'],p['currency'])==symbol]
    for p in positions:
        if p.get('below') is not None:invalidation.append('Your lower review level: '+str(p['below'])+' '+p['currency']+'.')
        if p.get('above') is not None:invalidation.append('Your upper review level: '+str(p['above'])+' '+p['currency']+'.')
        if p.get('review'):invalidation.append('Your reconsideration note: '+p['review'])
    return {'symbol':symbol,'generated':now,'report_generated':(report or {}).get('generated'),'current':current,
        'qualifies':bool(current and policy.buy_signal(card)),'action':card.get('action','Insufficient data') if current else 'Refresh required',
        'why':reasons,'checks':checks,'invalidation':invalidation,'risks':list(dict.fromkeys(risks)),
        'portfolio':{'buy_shares':buy['buy_shares'] if buy else 0,'sell_shares':holding.get('sell_shares') if holding else None,
            'reason':buy.get('reason') if buy else blocked.get('reason') if blocked else 'No confirmed purchase in the current shared-budget plan.',
            'allocation_ready':preview['ready'],'after_stock_pct':preview.get('after_stock_pct'),'fee_pct':preview.get('fee_pct'),
            'sale_reasons':holding.get('reasons',[]) if holding else []},
        'method':'Deterministic explanation of the existing technical policy and live shared-budget plan. No new trade rules, targets, probabilities or execution instructions.'}
