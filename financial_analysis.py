"""Dated annual trends and comparable-sector distributions, with no ranking changes."""
import datetime as dt
import statistics
import time
import fundamentals as f
import company_data as cd


def timeline(record):
    series=(record or {}).get('series',{})
    periods=sorted({r['period'] for rows in series.values() for r in rows})
    output={key:[] for key in (*f.FIELDS.values(),'operating_margin','net_margin','fcf_margin','net_cash','debt_to_equity','revenue_growth','share_count_change')}
    for period in periods:
        rows={k:next((r for r in v if r['period']==period and f.number(r.get('value'))),None) for k,v in series.items()}
        def same(*items):return all(r and r.get('currency') for r in items) and len({r['currency'] for r in items})==1
        for key in f.FIELDS.values():
            r=rows.get(key)
            if r:output[key].append({**r,'unit':'shares' if key in ('ordinary_shares','diluted_shares') else 'amount','derived':False})
        ocf,capex=rows.get('operating_cash_flow'),rows.get('capital_expenditure')
        cashflow=rows.get('free_cash_flow')
        if not cashflow and same(ocf,capex):
            cashflow={'period':period,'value':ocf['value']-abs(capex['value']),'currency':ocf['currency'],'unit':'amount','derived':True}
            output['free_cash_flow'].append(cashflow)
        def put(key,value,unit='percent',currency=None):
            if f.number(value):output[key].append({'period':period,'value':value,'unit':unit,'currency':currency,'derived':True})
        revenue=rows.get('revenue')
        if revenue and revenue['value']>0:
            for key,numerator in [('operating_margin',rows.get('operating_income')),('net_margin',rows.get('net_income')),('fcf_margin',cashflow)]:
                if same(revenue,numerator):put(key,numerator['value']/revenue['value']*100)
        cash,debt,equity=rows.get('cash'),rows.get('debt'),rows.get('equity')
        if same(cash,debt):put('net_cash',cash['value']-debt['value'],'amount',cash['currency'])
        if same(debt,equity) and equity['value']>0:put('debt_to_equity',debt['value']/equity['value'],'ratio')
        for source,target in [('revenue','revenue_growth'),('ordinary_shares','share_count_change')]:
            latest=rows.get(source)
            previous=sorted((r for r in series.get(source,[]) if r['period']<period),key=lambda r:r['period'])
            if latest and previous:
                previous=previous[-1];gap=(dt.date.fromisoformat(period)-dt.date.fromisoformat(previous['period'])).days
                currency_ok=same(latest,previous) if source=='revenue' else True
                if 300<=gap<=430 and previous['value']>0 and currency_ok:put(target,(latest['value']/previous['value']-1)*100)
    return {k:sorted(rows,key=lambda r:r['period']) for k,rows in output.items() if rows}


def trends(history):
    result=[]
    for key,label in [('revenue','Revenue'),('operating_margin','Operating margin'),('free_cash_flow','Free cash flow'),('net_cash','Cash minus debt'),('ordinary_shares','Year-end share count')]:
        rows=history.get(key,[])
        if len(rows)<2:continue
        first,last=rows[0],rows[-1]
        if first.get('unit')=='amount' and (not first.get('currency') or any(r.get('currency')!=first['currency'] for r in rows)):continue
        gap=(dt.date.fromisoformat(last['period'])-dt.date.fromisoformat(first['period'])).days/365.25
        cagr=((last['value']/first['value'])**(1/gap)-1)*100 if key=='revenue' and gap>=300/365.25 and first['value']>0 and last['value']>0 else None
        result.append({'metric':key,'label':label,'from':first['period'],'to':last['period'],'observations':len(rows),
                       'change':last['value']-first['value'],'unit':last['unit'],'currency':last.get('currency'),'cagr_pct':cagr})
    return result


def peers(symbol,financial,records,quotes,sectors,now=None):
    now=time.time() if now is None else now
    sector=sectors.get(symbol);out=[]
    if not sector or financial.get('status') in ('stale','unavailable'):
        return {'sector':sector,'metrics':[],'method':'Fresh financial coverage and a known sector are required.'}
    keys=['revenue_growth','operating_margin','net_margin','fcf_margin','debt_to_equity','annual_pe_proxy']
    if sector=='Financials':keys=['revenue_growth','net_margin','annual_pe_proxy']
    for key in keys:
        subject=financial.get('metrics',{}).get(key)
        if key=='fcf_margin':
            rows=timeline(records.get(symbol)).get(key,[])
            subject=next((r for r in rows if r['period']==financial.get('period')),None)
        if not subject:continue
        values=[];seen={cd.issuer(symbol)}
        for other,record in sorted(records.items()):
            if sectors.get(other)!=sector or cd.issuer(other) in seen:continue
            analysed=f.analyse(record,quotes.get(other) or quotes.get(other[:-3]),now)
            if analysed['status'] in ('stale','unavailable'):continue
            metric=analysed['metrics'].get(key)
            if key=='fcf_margin':metric=next((r for r in timeline(record).get(key,[]) if r['period']==subject['period']),None)
            if not metric or metric['period']!=subject['period'] or not f.number(metric.get('value')):continue
            values.append({'symbol':other,'value':metric['value']});seen.add(cd.issuer(other))
        numbers=sorted(v['value'] for v in values)
        enough=len(numbers)>=3
        percentile=(sum(v<subject['value'] for v in numbers)+.5*sum(v==subject['value'] for v in numbers))/len(numbers)*100 if enough else None
        out.append({'metric':key,'subject':subject['value'],'unit':subject.get('unit','percent'),'period':subject['period'],
                    'peer_count':len(numbers),'median':statistics.median(numbers) if enough else None,
                    'percentile':percentile,'peers':values})
    return {'sector':sector,'metrics':out,'method':'At least three other issuers from the same sector and exact fiscal period. Fresh annual statements; current matching-currency quote/EPS for annual P/E. One share class per issuer. '
            'Percentile describes magnitude, not investment quality. Financial-sector comparisons omit industrial cash-flow, margin and leverage tests. No point-in-time history or forecasts.'}
