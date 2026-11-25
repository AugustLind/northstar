"""Explainable share-count scenarios, with a shared cash budget and no order execution."""
import copy
import math
import time
import portfolio_fit as pf
import company_data
import decision_policy as policy
from broker_costs import BUY_FEE_NOK

VERSION='share-count-scenarios-v1'
SELL_SIGNALS=policy.SELL_SIGNALS


def quote_for(snapshot,symbol):
    existing=next((snapshot['quotes'].get(p['symbol']) for p in snapshot['positions']
                   if pf.canonical(p['symbol'],p['currency'])==symbol and snapshot['quotes'].get(p['symbol'])),None)
    return existing or snapshot['quotes'].get(symbol)


def signal_current(card,now):
    return bool(card and pf.fresh({'price':card.get('price'),'asof':card.get('asof')},now))


buy_signal = policy.buy_signal


def sell_scenario(snapshot,cards,ctx,profile,report_ok,now):
    import advice_state
    rows=[]
    issuer_over_limit={r['issuer'] for r in ctx['issuer_exposure']
                       if r['weight_pct'] is not None and r['weight_pct']>profile['max_stock_pct']+1e-8}
    sector_over_limit={r['sector'] for r in ctx['sectors']
                       if ctx['sectors_complete'] and r['weight_pct'] is not None
                       and r['weight_pct']>profile['max_sector_pct']+1e-8}
    for h in ctx['holdings']:
        card=cards.get(h['symbol']);q=quote_for(snapshot,h['symbol'])
        aliases=[p for p in snapshot['positions'] if pf.canonical(p['symbol'],p['currency'])==h['symbol']]
        supported=(len(aliases)==1 and h['symbol'].endswith('.OL') and pf.fresh(q,now) and q.get('currency')=='NOK'
                   and abs(h['shares']-round(h['shares']))<1e-8)
        position=aliases[0] if len(aliases)==1 else None
        basis=position.get('cost') if position else None
        basis_valid=(isinstance(basis,(int,float)) and not isinstance(basis,bool)
                     and math.isfinite(basis) and basis>0)
        break_even=(basis+(profile['buy_fee_nok']+profile['sell_fee_nok'])/h['shares']
                    if supported and basis_valid and profile['sell_fee_nok'] is not None and h['shares']>0 else None)
        target=position.get('above') if position else None
        action=card.get('action') if report_ok and signal_current(card,now) else None
        sell_action=action in SELL_SIGNALS
        level_key=policy.REVIEW_LEVELS.get(action)
        review_price=position.get(level_key) if position and level_key else None
        live_trigger=(policy.saved_price_trigger(position,q['price'])
                      if position and pf.fresh(q,now) and q.get('currency')==position['currency'] else None)
        waiting=None
        if sell_action:
            if level_key and not (
                live_trigger==action and card.get('review_price')==review_price
            ):
                waiting='Refresh the market report to confirm the current saved review price.'
            else:
                waiting=advice_state.gate(
                    h['symbol'],'sell',snapshot,profile,now,
                    review_trigger=(action,review_price) if level_key else None)
        elif action=='Hold / monitor' and live_trigger:
            waiting='Refresh the market report to confirm the current saved review price.'
        technical_reason=None
        if sell_action and not waiting:
            technical_reason=(card.get('reasons') or [action])[0]
            if level_key:
                level='Lower' if level_key=='below' else 'Upper'
                technical_reason=f'{level} review price reached.'
        sizing_blocker=None
        if snapshot.get('ledger_reconciled') is False:
            sizing_blocker='Reconcile holdings and cash against the ledger before sizing sales.'
        elif not ctx['complete'] or not supported:
            sizing_blocker='Quantity unavailable: complete portfolio valuation, fresh NOK quotes and one whole-share Oslo entry per ticker are required.'
        portfolio_reasons=[]
        if sizing_blocker:
            weight=h['weight_pct']
            if weight is not None and weight>profile['max_stock_pct']+1e-8:
                portfolio_reasons.append(f"Above your {profile['max_stock_pct']}% position limit.")
            elif h['issuer'] in issuer_over_limit:
                portfolio_reasons.append(f"Combined share classes exceed your {profile['max_stock_pct']}% company limit.")
            if h['sector'] in sector_over_limit:
                portfolio_reasons.append(f"{h['sector']} exceeds your {profile['max_sector_pct']}% sector limit.")
        row={'symbol':h['symbol'],'name':(card or {}).get('name',h['symbol']),'owned':h['shares'],
             'sell_shares':0 if not sizing_blocker else None,'remaining_shares':h['shares'],
             'gross_proceeds_nok':0. if not sizing_blocker else None,
             'price':q['price'] if supported else None,'quote_asof':q.get('asof') if q else None,
             'quote_source':q.get('source') if q else None,
             'quote_age_seconds':max(0,now-q['asof']) if q and isinstance(q.get('asof'),(int,float)) else None,
             'break_even_price':break_even,'break_even_status':('Available' if break_even is not None else
                 'Fresh quote, positive cost basis and entered buy and sell fee assumptions required.'),
             'limit_reference_price':q['price'] if supported else None,
             'limit_reference_note':'Current quote reference only; a limit order may not fill, especially if the limit is away from the market. You choose whether and how to place any order.',
             'target_price':target if supported and isinstance(target,(int,float)) and target>0 else None,
             'target_reason':'Your saved upper review level.' if supported and isinstance(target,(int,float)) and target>0 else None,
             'sector':h['sector'],'reasons':[],'technical_action':action or 'Current technical signal unavailable',
             'technical_review_reason':technical_reason,'technical_review_blocker':waiting,
             'review_price':review_price if technical_reason else None,
             'portfolio_review_reasons':portfolio_reasons,'sizing_blocker':sizing_blocker}
        if not basis_valid:
            row['break_even_status']='Break-even unavailable: enter a positive cost basis for this holding.'
        elif profile['sell_fee_nok'] is None:
            row['break_even_status']='Break-even unavailable: enter a sell-fee assumption; current sale fees are unknown.'
        if sizing_blocker:
            row['reasons'].append(sizing_blocker)
        rows.append(row)
    if not ctx['complete'] or not ctx['total_nok']:
        return rows
    total=ctx['total_nok']
    def add(row,quantity,reason,*,portfolio_limit=True):
        quantity=min(int(row['owned'])-row['sell_shares'],max(0,int(quantity)))
        if quantity:
            row['sell_shares']+=quantity
            row['remaining_shares']=row['owned']-row['sell_shares']
            row['gross_proceeds_nok']=row['sell_shares']*row['price']
            row['reasons'].append(reason)
            if portfolio_limit:
                row['portfolio_review_reasons'].append(reason)
    def ceil_shares(value,price):
        return max(0,math.ceil(value/price-1e-10))
    for row in rows:
        if row['sell_shares'] is None:
            continue
        if row['technical_review_reason']:
            if profile['review_sell_pct']>0:
                add(row,math.ceil(row['owned']*profile['review_sell_pct']/100-1e-10),
                    row['technical_action']+': your '+str(profile['review_sell_pct'])+'% sale-review setting, rounded up to whole shares.',
                    portfolio_limit=False)
            else:
                row['sizing_blocker']='Your sale-review size is 0%; no signal-based sale quantity assigned.'
                row['reasons'].append(row['sizing_blocker'])
        if row['technical_review_blocker']:
            row['reasons'].append(row['technical_review_blocker'])
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
    sell_fee=profile['sell_fee_nok']
    selected_orders=sum(bool(r['sell_shares']) for r in rows)
    reserve_shortfall=total*profile['reserve_pct']/100-ctx['cash_nok']
    if reserve_shortfall>1e-8 and all(r['sell_shares'] is None for r in rows):
        for row in rows:
            row['portfolio_review_reasons'].append(
                f"Tracked cash is below your {profile['reserve_pct']}% cash reserve.")
    need=reserve_shortfall-sum(r['gross_proceeds_nok'] or 0 for r in rows)
    if sell_fee is not None:
        need+=selected_orders*sell_fee
    for row in sorted((r for r in rows if r['sell_shares'] is not None),key=lambda r:(-r['remaining_shares']*r['price'],r['symbol'])):
        if need<=1e-8:
            break
        before=row['sell_shares']
        target=need+(sell_fee if not row['sell_shares'] and sell_fee is not None else 0.)
        add(row,ceil_shares(target,row['price']), 'Restore your '+str(profile['reserve_pct'])+'% cash reserve after the entered sale-fee assumption.' if sell_fee is not None else 'Restore your '+str(profile['reserve_pct'])+'% cash reserve before unknown selling fees.')
        added=row['sell_shares']-before
        need-=added*row['price']
        if sell_fee is not None and added and before==0:
            need+=sell_fee
    for row in rows:
        if row['sell_shares']==0:
            row['reasons'].append('No whole-share reduction is required by the active sizing rules.')
        if row['price']:
            row['after_stock_pct']=row['remaining_shares']*row['price']/total*100
    return rows


def buy_inputs(card,snapshot,ctx,profile,report_ok,blocked_sales,budget,minimum_order,now):
    import advice_state

    symbol=pf.canonical(card['symbol'])
    if not report_ok or not signal_current(card,now):
        return None,'Current technical report and quote required.',True
    if snapshot.get('ledger_reconciled') is False:
        return None,'Reconcile holdings and cash against the ledger before sizing purchases.',True
    if symbol in blocked_sales:
        return None,'This stock has a sale-review quantity; no conflicting purchase is planned.',False
    if not buy_signal(card):
        return None,'The complete technical buy screen is not met.',False
    if not ctx['complete'] or not ctx['total_nok']:
        return None,'Complete tracked portfolio valuation required.',True
    if budget<minimum_order-1e-8:
        return None,'Remaining shared budget is below '+str(round(minimum_order,2))+' NOK needed for your purchase-fee limit.',False
    waiting=advice_state.gate(symbol,'buy',snapshot,profile,now)
    if waiting:
        return None,waiting,False
    q=quote_for(snapshot,symbol)
    if not pf.fresh(q,now) or q.get('currency')!='NOK':
        return None,'Fresh NOK price required.',True
    entries=[p for p in snapshot['positions'] if pf.canonical(p['symbol'],p['currency'])==symbol]
    if len(entries)>1 or any(abs(p['shares']-round(p['shares']))>1e-8 for p in entries):
        return None,'Resolve fractional or duplicate holding entries before planning a whole-share purchase.',True
    if not ctx['sectors_complete'] or not profile['sectors'].get(symbol):
        return None,'Classify this stock and every holding to confirm sector capacity.',True
    return q,None,False


def buy_quantity(symbol,quote,ctx,profile,budget,reserve_fees=0):
    buy_fee=profile['buy_fee_nok']
    final_total=ctx['total_nok']-buy_fee-reserve_fees
    held=sum(h['value_nok'] for h in ctx['holdings'] if h['issuer']==company_data.issuer(symbol))
    sector_value=sum(h['value_nok'] for h in ctx['holdings'] if h['sector']==profile['sectors'][symbol])
    capacity=min(budget-buy_fee,profile['max_stock_pct']/100*final_total-held,
                 profile['max_sector_pct']/100*final_total-sector_value,
                 ctx['cash_nok']-buy_fee-reserve_fees-profile['reserve_pct']/100*final_total)
    shares=max(0,math.floor(capacity/quote['price']))
    value=shares*quote['price']
    return shares,value,buy_fee/value*100 if value else None


def add_purchase(snapshot,symbol,quote,shares):
    old=next((p for p in snapshot['positions'] if p['currency']=='NOK' and pf.canonical(p['symbol'])==symbol),None)
    if old:
        old['shares']+=shares
    else:
        snapshot['positions'].append({'symbol':symbol,'currency':'NOK','shares':shares})
    snapshot['quotes'][symbol]=quote
    if old:
        snapshot['quotes'][old['symbol']]=quote


def funded_switch(snapshot,report,plan):
    """Compare one reviewed sale and one ranked purchase against keeping the portfolio."""
    profile=snapshot['portfolio_preferences']
    now=plan['generated']
    sales=[row for row in plan['holdings'] if row['sell_shares']]
    report_ok=policy.current_report(report,now)
    missing=None
    if not report_ok or (report or {}).get('coverage',{}).get('unavailable'):
        missing='Current research coverage is incomplete.'
    if not profile['purchase_nok']:
        return {'status':'unavailable','reason':missing} if missing else {'status':'none'}

    # Use the trade-plan clock for both sides of the comparison.
    ctx=pf.context(snapshot,profile,now)
    if not ctx['complete'] or snapshot.get('ledger_reconciled') is False:
        return {'status':'unavailable','reason':'Complete portfolio valuation and ledger reconciliation are required.'}
    blocked_sales={row['symbol'] for row in sales}
    for row in plan['holdings']:
        if row['sell_shares'] is None and (row['technical_review_reason'] or row['portfolio_review_reasons']):
            missing=row['sizing_blocker']
    if not sales:
        return {'status':'unavailable','reason':missing} if missing else {'status':'none'}

    budget=profile['purchase_nok']
    buy_fee=profile['buy_fee_nok']
    minimum_order=buy_fee*(1+100/profile['max_buy_fee_pct'])
    cards={pf.canonical(card['symbol']):card for card in (report or {}).get('cards',[])}
    ranked=policy.recommendations(cards.values(),(report or {}).get('promoted_model'))
    for card in ranked:
        symbol=pf.canonical(card['symbol'])
        quote,reason,evidence_missing=buy_inputs(card,snapshot,ctx,profile,report_ok,
                                                blocked_sales,budget,minimum_order,now)
        if evidence_missing:
            missing=reason
        if reason:
            continue
        for sale in sales:
            # A zero fee gives an upper bound on available proceeds when the assumption is missing.
            sale_fee=sale['fee_nok'] or 0.
            proceeds=sale['gross_proceeds_nok']-sale_fee
            if proceeds<=0:
                continue
            sold=sale['symbol']
            working={**snapshot,'positions':[dict(p) for p in snapshot['positions']],
                     'quotes':dict(snapshot['quotes'])}
            position=next(p for p in working['positions'] if pf.canonical(p['symbol'],p['currency'])==sold)
            position['shares']=sale['remaining_shares']
            funded={**profile,'cash_nok':ctx['cash_nok']+proceeds}
            after_sale=pf.context(working,funded,now)
            shares,value,fee_pct=buy_quantity(symbol,quote,after_sale,funded,budget)
            if not shares or fee_pct>profile['max_buy_fee_pct']+1e-8:
                continue
            keep_reserve=(ctx['total_nok']-buy_fee)*profile['reserve_pct']/100
            if ctx['cash_nok']-value-buy_fee>=keep_reserve-1e-8:
                continue
            add_purchase(working,symbol,quote,shares)
            funded['cash_nok']-=value+buy_fee
            after=pf.context(working,funded,now)
            if (after['cash_pct']<profile['reserve_pct']-1e-8
                or any(row['weight_pct']>profile['max_stock_pct']+1e-8 for row in after['issuer_exposure'])
                or any(row['weight_pct']>profile['max_sector_pct']+1e-8 for row in after['sectors'])):
                continue
            if sale['fee_nok'] is None:
                missing='Enter a sell-fee assumption to confirm net sale proceeds.'
                continue
            companies=dict.fromkeys((company_data.issuer(sold),company_data.issuer(symbol)))
            sectors=dict.fromkeys((profile['sectors'][sold],profile['sectors'][symbol]))
            def weights(key,category,names):
                before={row[category]:row['weight_pct'] for row in ctx[key]}
                final={row[category]:row['weight_pct'] for row in after[key]}
                return [{'name':name,'keep_pct':before.get(name,0.),'switch_pct':final.get(name,0.)}
                        for name in names]
            return {'status':'feasible','sell_symbol':sold,'sell_shares':sale['sell_shares'],
                    'buy_symbol':symbol,'buy_shares':shares,'sell_fee_nok':sale_fee,'buy_fee_nok':buy_fee,
                    'keep_cash_nok':ctx['cash_nok'],'switch_cash_nok':after['cash_nok'],
                    'keep_cash_pct':ctx['cash_pct'],'switch_cash_pct':after['cash_pct'],
                    'reserve_pct':profile['reserve_pct'],
                    'companies':weights('issuer_exposure','issuer',companies),
                    'sectors':weights('sectors','sector',sectors)}
    return {'status':'unavailable','reason':missing} if missing else {'status':'none'}


def build(snapshot,report,profile,now=None):
    now=time.time() if now is None else now
    profile=pf.preferences(profile)
    ctx=pf.context(snapshot,profile,now)
    report_ok=policy.current_report(report,now)
    cards={pf.canonical(c['symbol']):c for c in (report or {}).get('cards',[])}
    sells=sell_scenario(snapshot,cards,ctx,profile,report_ok,now)
    blocked_sales={r['symbol'] for r in sells if r['sell_shares']}
    ranked=policy.recommendations(cards.values(),(report or {}).get('promoted_model'))
    buys=[];blocked=[];working=copy.deepcopy(snapshot);working_profile=dict(profile)
    left=profile['purchase_nok'];spent=0.;fees=0.;warnings=list(ctx['warnings'])
    buy_fee=profile['buy_fee_nok']
    minimum_order=buy_fee*(1+100/profile['max_buy_fee_pct'])
    max_orders=len(ranked) if minimum_order==0 else min(len(ranked),int(min(left,ctx['cash_nok'])/minimum_order))
    if not report_ok:
        warnings.append('Refresh the market report before generating buy quantities or signal-based sale quantities.')
    if snapshot.get('ledger_reconciled') is False:warnings.append('Ledger reconciliation is required; buy and sale quantities are withheld.')
    if profile['purchase_nok']==0:
        warnings.append('Set your total buy-plan budget in Portfolio fit to generate purchase quantities.')
    for card in ranked:
        symbol=pf.canonical(card['symbol'])
        current=pf.context(working,working_profile,now)
        q,reason,evidence_missing=buy_inputs(card,working,current,working_profile,report_ok,
                                             blocked_sales,left,minimum_order,now)
        if reason is None:
            # Reserve all possible later buy fees so the entire plan respects final weights.
            reserve_fees=max(0,max_orders-len(buys)-1)*buy_fee
            n, value, fee_pct=buy_quantity(symbol,q,current,working_profile,left,reserve_fees)
            if not n or fee_pct>profile['max_buy_fee_pct']+1e-8:
                reason='No whole-share purchase fits your remaining budget, allocation limits, reserve and purchase-fee limit.'
            else:
                total=value+buy_fee
                buys.append({'symbol':symbol,'name':card.get('name',symbol),'buy_shares':n,'sell_shares':0,
                             'price':q['price'],'quote_asof':q['asof'],'value_nok':value,'fee_nok':buy_fee,
                             'total_nok':total,'fee_pct':fee_pct,'rank':card.get('rank'),
                             'reason':'Meets the technical buy screen; sized in rank order within one shared budget and your limits.',
                             'portfolio_reason':'Fits your '+profile['sectors'][symbol]+' sector and company limits; '+str(n)+' whole shares fit your remaining shared budget, cash reserve and purchase-fee limit.'})
                left-=total;spent+=total;fees+=buy_fee;working_profile['cash_nok']-=total
                add_purchase(working,symbol,q,n)
        if reason:
            blocked.append({'symbol':symbol,'buy_shares':0,'reason':reason,'evidence_missing':evidence_missing})
    result_ctx=pf.context(working,working_profile,now)
    sale_proceeds=sum(r['gross_proceeds_nok'] or 0 for r in sells)
    for row in sells:
        row['fee_nok']=profile['sell_fee_nok'] if row['sell_shares'] and profile['sell_fee_nok'] is not None else (0. if not row['sell_shares'] else None)
        row['net_proceeds_nok']=row['gross_proceeds_nok']-row['fee_nok'] if row['gross_proceeds_nok'] is not None and row['fee_nok'] is not None else None
    sales_complete=all(r['sell_shares'] is not None and r['gross_proceeds_nok'] is not None for r in sells)
    sell_fees=sum(r['fee_nok'] or 0 for r in sells)
    return {'version':VERSION,'policy_version':policy.VERSION,'generated':now,'report_generated':(report or {}).get('generated'),
            'buy_budget_nok':profile['purchase_nok'],'spent_nok':spent,'unallocated_budget_nok':left,
            'buy_fees_nok':fees,'cash_after_buys_nok':working_profile['cash_nok'],
            'cash_after_sell_scenario_nok':profile['cash_nok']+sale_proceeds-sell_fees if profile['sell_fee_nok'] is not None and sales_complete else None,
            'sell_fees_nok':sell_fees if profile['sell_fee_nok'] is not None and sales_complete else None,
            'after_buys':result_ctx,'buys':buys,'holdings':sells,'blocked_buys':blocked,'warnings':warnings,
            'max_buy_fee_pct':profile['max_buy_fee_pct'],'review_sell_pct':profile['review_sell_pct'],
            'post_buy_warnings':result_ctx['warnings'],
            'method':'Rule-based share-count scenarios, not optimal trade amounts or forecasts. Buys share one budget and use current cash only; '
                     'each order includes your entered buy-fee assumption and follows technical rank, whole-share, position, sector, reserve and fee limits. '
                     'Remaining budget can stay unused. Sales first apply your signal-review percentage, then position, sector and reserve rules '
                     'without counting the same shares twice. Sector/reserve trims use largest holdings first. '
                     + ('Sale fees use your entered assumption; ' if profile['sell_fee_nok'] is not None else 'Sale fees are unknown until you enter an assumption; ')
                     + 'sale proceeds are shown gross and net where the fee assumption is available, before tax. The sale scenario is separate from the buy plan; '
                     'sale proceeds do not fund purchases. Recalculate after any real trade. Missing data means no quantity, not zero risk. '
                     'Signal-review percentage and fee limits are illustrative user-adjustable settings; no order is placed.'}
