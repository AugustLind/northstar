"""Explainable share-count scenarios, with a shared cash budget and no order execution."""
import copy
import math
import time
import portfolio_fit as pf
import company_data
from broker_costs import BUY_FEE_NOK

VERSION='share-count-scenarios-v1'
SELL_SIGNALS={'Consider reducing / selling','Review sell threshold','Consider taking profits'}


def quote_for(snapshot,symbol):
    existing=next((snapshot['quotes'].get(p['symbol']) for p in snapshot['positions']
                   if pf.canonical(p['symbol'],p['currency'])==symbol and snapshot['quotes'].get(p['symbol'])),None)
    return existing or snapshot['quotes'].get(symbol)


def current_report(report,now):
    t=(report or {}).get('generated')
    return isinstance(t,(int,float)) and math.isfinite(t) and -300<=now-t<=86400


def signal_current(card,now):
    return bool(card and pf.fresh({'price':card.get('price'),'asof':card.get('asof')},now))


def buy_signal(card):
    if not card.get('rank_eligible'):
        return False
    if card.get('action')=='Consider buying':
        return True
    # Holdings have a Hold / monitor label even when they meet the new-stock buy screen.
    m=card.get('metrics',{})
    return (card.get('action')=='Hold / monitor' and card.get('score')==100
            and isinstance(m.get('volatility'),(float,int)) and math.isfinite(m['volatility']) and m['volatility']<50
            and isinstance(m.get('extension50'),(float,int)) and math.isfinite(m['extension50']) and m['extension50']<15)


def sell_scenario(snapshot,cards,ctx,profile,report_ok,now):
    import advice_state
    rows=[]
    for h in ctx['holdings']:
        card=cards.get(h['symbol']);q=quote_for(snapshot,h['symbol'])
        aliases=[p for p in snapshot['positions'] if pf.canonical(p['symbol'],p['currency'])==h['symbol']]
        supported=(len(aliases)==1 and h['symbol'].endswith('.OL') and pf.fresh(q,now) and q.get('currency')=='NOK'
                   and abs(h['shares']-round(h['shares']))<1e-8)
        row={'symbol':h['symbol'],'name':(card or {}).get('name',h['symbol']),'owned':h['shares'],
             'sell_shares':0 if ctx['complete'] and supported else None,'remaining_shares':h['shares'],
             'gross_proceeds_nok':0. if ctx['complete'] and supported else None,
             'price':q['price'] if supported else None,'quote_asof':q.get('asof') if q else None,
             'sector':h['sector'],'reasons':[],'technical_action':(card or {}).get('action') if report_ok and signal_current(card,now) else 'Current technical signal unavailable'}
        if row['sell_shares'] is None:
            row['reasons'].append('Quantity unavailable: complete portfolio valuation, fresh NOK quotes and one whole-share Oslo entry per ticker are required.')
        rows.append(row)
    if snapshot.get('ledger_reconciled') is False:
        for r in rows:
            r.update(sell_shares=None,gross_proceeds_nok=None,reasons=['Reconcile holdings and cash against the ledger before sizing sales.'])
        return rows
    if not ctx['complete'] or not ctx['total_nok']:
        return rows
    total=ctx['total_nok']
    def add(row,quantity,reason):
        quantity=min(int(row['owned'])-row['sell_shares'],max(0,int(quantity)))
        if quantity:
            row['sell_shares']+=quantity
            row['remaining_shares']=row['owned']-row['sell_shares']
            row['gross_proceeds_nok']=row['sell_shares']*row['price']
            row['reasons'].append(reason)
    def ceil_shares(value,price):
        return max(0,math.ceil(value/price-1e-10))
    for row in rows:
        if row['sell_shares'] is None:
            continue
        card=cards.get(row['symbol'])
        if report_ok and signal_current(card,now) and card.get('action') in SELL_SIGNALS and profile['review_sell_pct']>0 and not advice_state.gate(row['symbol'],'sell',snapshot,profile,now):
            add(row,math.ceil(row['owned']*profile['review_sell_pct']/100-1e-10),
                card['action']+': your '+str(profile['review_sell_pct'])+'% sale-review setting, rounded up to whole shares.')
        if report_ok and signal_current(card,now) and card.get('action') in SELL_SIGNALS and profile['review_sell_pct']==0:
            row['reasons'].append('Technical sale review is active, but your sale-review size is 0%; no signal-based sale quantity assigned.')
        waiting=advice_state.gate(row['symbol'],'sell',snapshot,profile,now) if report_ok and signal_current(card,now) and card.get('action') in SELL_SIGNALS else None
        if waiting:row['reasons'].append(waiting)
        excess=row['remaining_shares']*row['price']-total*profile['max_stock_pct']/100
        add(row,ceil_shares(excess,row['price']), 'Reduce to your '+str(profile['max_stock_pct'])+'% position limit before selling costs.')
    for issuer in sorted({h['issuer'] for h in ctx['holdings']}):
        group=[r for r in rows if company_data.issuer(r['symbol'])==issuer]
        if len(group)<2:continue
        original=sum(h['value_nok'] for h in ctx['holdings'] if h['issuer']==issuer)
        excess=original-sum(r['gross_proceeds_nok'] or 0 for r in group)-total*profile['max_stock_pct']/100
        for row in sorted((r for r in group if r['sell_shares'] is not None),key=lambda r:(-r['remaining_shares']*r['price'],r['symbol'])):
            if excess<=1e-8:break
            before=row['sell_shares'];add(row,ceil_shares(excess,row['price']),'Combined company limit for alternate share classes: '+issuer)
            excess-=(row['sell_shares']-before)*row['price']
    if ctx['sectors_complete']:
        for sector in sorted({h['sector'] for h in ctx['holdings']}):
            group=[r for r in rows if r['sector']==sector]
            # Unsupported holdings still count towards exposure, but cannot receive orders.
            original=sum(h['value_nok'] for h in ctx['holdings'] if h['sector']==sector)
            proceeds=sum(r['gross_proceeds_nok'] or 0 for r in group)
            excess=original-proceeds-total*profile['max_sector_pct']/100
            for row in sorted((r for r in group if r['sell_shares'] is not None),key=lambda r:(-r['remaining_shares']*r['price'],r['symbol'])):
                if excess<=1e-8:
                    break
                before=row['sell_shares']
                add(row,ceil_shares(excess,row['price']), 'Reduce '+sector+' to your '+str(profile['max_sector_pct'])+'% sector limit; largest remaining holding trimmed first.')
                excess-=(row['sell_shares']-before)*row['price']
    # Sales to meet the cash reserve are a separate scenario; proceeds never fund the buy plan.
    need=total*profile['reserve_pct']/100-ctx['cash_nok']-sum(r['gross_proceeds_nok'] or 0 for r in rows)
    for row in sorted((r for r in rows if r['sell_shares'] is not None),key=lambda r:(-r['remaining_shares']*r['price'],r['symbol'])):
        if need<=1e-8:
            break
        before=row['sell_shares']
        add(row,ceil_shares(need,row['price']), 'Restore your '+str(profile['reserve_pct'])+'% cash reserve before selling costs.')
        need-=(row['sell_shares']-before)*row['price']
    for row in rows:
        if row['sell_shares']==0:
            row['reasons'].append('No whole-share reduction is required by the active sizing rules.')
        if row['price']:
            row['after_stock_pct']=row['remaining_shares']*row['price']/total*100
    return rows


def build(snapshot,report,profile,now=None):
    import advice_state
    now=time.time() if now is None else now
    profile=pf.preferences(profile)
    ctx=pf.context(snapshot,profile,now)
    report_ok=current_report(report,now)
    cards={pf.canonical(c['symbol']):c for c in (report or {}).get('cards',[])}
    sells=sell_scenario(snapshot,cards,ctx,profile,report_ok,now)
    blocked_sales={r['symbol'] for r in sells if r['sell_shares']}
    ranked=sorted((c for c in cards.values() if c.get('rank_eligible')),
                  key=lambda c:(-c.get('composite',0),c['symbol']))[:20]
    buys=[];blocked=[];working=copy.deepcopy(snapshot);working_profile=dict(profile)
    left=profile['purchase_nok'];spent=0.;fees=0.;warnings=list(ctx['warnings'])
    minimum_order=BUY_FEE_NOK*(1+100/profile['max_buy_fee_pct'])
    max_orders=min(len(ranked),int(min(left,ctx['cash_nok'])/minimum_order))
    if not report_ok:
        warnings.append('Refresh the market report before generating buy quantities or signal-based sale quantities.')
    if snapshot.get('ledger_reconciled') is False:warnings.append('Ledger reconciliation is required; buy and sale quantities are withheld.')
    if profile['purchase_nok']==0:
        warnings.append('Set your total buy-plan budget in Portfolio fit to generate purchase quantities.')
    for card in ranked:
        symbol=pf.canonical(card['symbol']);reason=None
        if not report_ok or not signal_current(card,now):
            reason='Current technical report and quote required.'
        elif snapshot.get('ledger_reconciled') is False:
            reason='Reconcile holdings and cash against the ledger before sizing purchases.'
        elif symbol in blocked_sales:
            reason='This stock has a sale-review quantity; no conflicting purchase is planned.'
        elif not buy_signal(card):
            reason='The complete technical buy screen is not met.'
        elif not ctx['complete'] or not ctx['total_nok']:
            reason='Complete tracked portfolio valuation required.'
        elif left<minimum_order-1e-8:
            reason='Remaining shared budget is below '+str(round(minimum_order,2))+' NOK needed for your purchase-fee limit.'
        if reason is None:
            reason=advice_state.gate(symbol,'buy',snapshot,profile,now)
        q=quote_for(working,symbol)
        if reason is None and (not pf.fresh(q,now) or q.get('currency')!='NOK'):
            reason='Fresh NOK price required.'
        existing_entries=[p for p in working['positions'] if pf.canonical(p['symbol'],p['currency'])==symbol]
        if reason is None and (len(existing_entries)>1 or any(abs(p['shares']-round(p['shares']))>1e-8 for p in existing_entries)):
            reason='Resolve fractional or duplicate holding entries before planning a whole-share purchase.'
        current=pf.context(working,working_profile,now)
        if reason is None and (not current['sectors_complete'] or not profile['sectors'].get(symbol)):
            reason='Classify this stock and every holding to confirm sector capacity.'
        if reason is None:
            # Reserve all possible later buy fees so the entire plan respects final weights.
            reserve_fees=max(0,max_orders-len(buys)-1)*BUY_FEE_NOK
            final_total=current['total_nok']-BUY_FEE_NOK-reserve_fees
            held=sum(h['value_nok'] for h in current['holdings'] if h['issuer']==company_data.issuer(symbol))
            sector_value=sum(h['value_nok'] for h in current['holdings'] if h['sector']==profile['sectors'][symbol])
            capacity=min(left-BUY_FEE_NOK,profile['max_stock_pct']/100*final_total-held,
                         profile['max_sector_pct']/100*final_total-sector_value,
                         working_profile['cash_nok']-BUY_FEE_NOK-reserve_fees-profile['reserve_pct']/100*final_total)
            n=max(0,math.floor(capacity/q['price']))
            value=n*q['price'];fee_pct=BUY_FEE_NOK/value*100 if value else None
            if not n or fee_pct>profile['max_buy_fee_pct']+1e-8:
                reason='No whole-share purchase fits your remaining budget, allocation limits, reserve and purchase-fee limit.'
            else:
                total=value+BUY_FEE_NOK
                buys.append({'symbol':symbol,'name':card.get('name',symbol),'buy_shares':n,'sell_shares':0,
                             'price':q['price'],'quote_asof':q['asof'],'value_nok':value,'fee_nok':BUY_FEE_NOK,
                             'total_nok':total,'fee_pct':fee_pct,'rank':card.get('rank'),
                             'reason':'Meets the technical buy screen; sized in rank order within one shared budget and your limits.'})
                left-=total;spent+=total;fees+=BUY_FEE_NOK;working_profile['cash_nok']-=total
                old=next((p for p in working['positions'] if p['currency']=='NOK' and pf.canonical(p['symbol'])==symbol),None)
                if old:
                    old['shares']+=n
                else:
                    working['positions'].append({'symbol':symbol,'currency':'NOK','shares':n})
                working['quotes'][symbol]=q
                if old:
                    working['quotes'][old['symbol']]=q
        if reason:
            blocked.append({'symbol':symbol,'buy_shares':0,'reason':reason})
    result_ctx=pf.context(working,working_profile,now)
    sale_proceeds=sum(r['gross_proceeds_nok'] or 0 for r in sells)
    return {'version':VERSION,'generated':now,'report_generated':(report or {}).get('generated'),
            'buy_budget_nok':profile['purchase_nok'],'spent_nok':spent,'unallocated_budget_nok':left,
            'buy_fees_nok':fees,'cash_after_buys_nok':working_profile['cash_nok'],
            'cash_after_sell_scenario_nok':profile['cash_nok']+sale_proceeds,
            'after_buys':result_ctx,'buys':buys,'holdings':sells,'blocked_buys':blocked,'warnings':warnings,
            'max_buy_fee_pct':profile['max_buy_fee_pct'],'review_sell_pct':profile['review_sell_pct'],
            'post_buy_warnings':result_ctx['warnings'],
            'method':'Rule-based share-count scenarios, not optimal trade amounts or forecasts. Buys share one budget and use current cash only; '
                     'each order includes 79 NOK and follows technical rank, whole-share, position, sector, reserve and fee limits. '
                     'Remaining budget can stay unused. Sales first apply your signal-review percentage, then position, sector and reserve rules '
                     'without counting the same shares twice. Sector/reserve trims use largest holdings first. '
                     'Sale counts and proceeds are before selling fees and tax, which are unknown. The sale scenario is separate from the buy plan; '
                     'sale proceeds do not fund purchases. Recalculate after any real trade. Missing data means no quantity, not zero risk. '
                     'Signal-review percentage and fee limits are illustrative user-adjustable settings; no order is placed.'}
