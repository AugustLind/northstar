"""Dated technical-signal experiments, separate from real holdings."""
import bisect
import math
import time
import research
import decision_policy as policy
from broker_costs import BUY_FEE_NOK, FEE_MODEL

VERSION = 'technical-policy-robustness-v4'
LIMITS = ('Exploratory, not an unbiased market backtest: today’s configured universe excludes '
          'unknown delisted stocks. Adjusted prices may be revised. Financials and news are excluded. '
          'Benchmark is the same complete-history basket bought and held, not an Oslo index. '
          'Stocks without a complete reference calendar and warm-up, including younger IPOs and incomplete histories, are excluded. '
          'Uses fractional stock allocations, fixed 79 NOK per buy order and optional extra slippage. '
          'Fee reserves can leave residual cash. Selling commission is user-configurable; tax, market impact and cash interest are not modelled.')


def history(q):
    points = {}
    if q.get('currency') != 'NOK':
        return []
    for p in q.get('history', []):
        if all(isinstance(p.get(k), (float, int)) and math.isfinite(p[k]) and p[k] > 0 for k in ('time','close')):
            points[int(p['time']//86400)] = p
    return [points[d] for d in sorted(points)]


def evaluate(quotes, universe, cost_bps=0, floor=250000, initial_capital=100000, progress=None,
             selling_fee_nok=0, max_positions=20, rebalance_months=1, signal_cache=None):
    """Monthly decision at close; execute next common close; no future inputs to screen."""
    selling_fee_nok=float(selling_fee_nok)
    if not math.isfinite(selling_fee_nok) or not 0<=selling_fee_nok<=10000:
        raise ValueError('Selling fee must be between 0 and 10,000 NOK per sell order.')
    if isinstance(max_positions,bool) or not isinstance(max_positions,int) or not 1<=max_positions<=20:
        raise ValueError('Maximum experiment positions must be an integer from 1 to 20.')
    if rebalance_months not in (1,3):raise ValueError('Experiment rebalancing must be every 1 or 3 months.')
    cost_bps = float(cost_bps)
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 200:
        raise ValueError('Additional slippage must be 0–200 basis points.')
    initial_capital=float(initial_capital)
    if not math.isfinite(initial_capital) or not 1000 <= initial_capital <= 1e9:
        raise ValueError('Starting capital must be 1,000–1,000,000,000 NOK.')
    series = {s: history(quotes.get(s, {})) for s in set(universe)}
    series = {s: h for s, h in series.items() if len(h) >= 260}
    if not series:
        raise ValueError('Download at least 260 daily observations for a stock first.')
    # Complete-case sample is explicit; never silently mark suspended assets flat.
    latest = max(int(h[-1]['time']//86400) for h in series.values())
    series = {s:h for s,h in series.items() if int(h[-1]['time']//86400) == latest}
    # A young IPO must not shorten the entire experiment to its own history length.
    # Use the longest Oslo history's dated calendar and explicitly report complete-case exclusions.
    anchor=max(series.values(),key=len)
    common=sorted({int(p['time']//86400) for p in anchor[199:]})[-756:]
    series={s:h for s,h in series.items() if set(common).issubset({int(p['time']//86400) for p in h})
            and sum(int(p['time']//86400)<=common[0] for p in h)>=200}
    if len(common)<40 or not series:
        raise ValueError('Fewer than 40 complete test sessions; insufficient comparable history.')
    lookups = {s:{int(p['time']//86400):p['close'] for p in h} for s,h in series.items()}
    equity, benchmark, holdings, pending = 1., 1., {}, None
    curve, trades, decisions, fees = [], 0, 0, 0.
    start = common[1]
    benchmark_entry_fee=BUY_FEE_NOK*len(series)/initial_capital
    if benchmark_entry_fee+cost_bps/10000>=1:
        raise ValueError('Starting capital cannot cover benchmark purchase fees. Increase it or use a smaller universe.')
    buy_orders=0;fixed_fees=0.;sell_orders=0;sell_fees=0.;turnover=0.;trade_log=[]
    signal_cache={} if signal_cache is None else signal_cache
    calendar={s:[int(p["time"]//86400) for p in h] for s,h in series.items()}
    first_month=time.gmtime(common[0]*86400).tm_year*12+time.gmtime(common[0]*86400).tm_mon
    previous = None
    month = None
    for day in common:
        if previous is not None:
            equity *= 1 + sum(w*(lookups[s][day]/lookups[s][previous]-1) for s,w in holdings.items())
            # Update weights for price drift before rebalancing.
            grown = {s:w*lookups[s][day]/lookups[s][previous] for s,w in holdings.items()}
            total = 1-sum(holdings.values())+sum(grown.values())
            holdings = {s:w/total for s,w in grown.items()}
        benchmark = (sum(lookups[s][day]/lookups[s][start] for s in series)/len(series)
                     *(1-benchmark_entry_fee-cost_bps/10000)) if day>=start else 1.
        if pending is not None:
            # Reserve fees for potential positive-value orders before sizing targets.
            equal=equity/len(pending) if pending else 0.
            potential=sum(equal-equity*holdings.get(s,0)>1e-10 for s in pending)
            nominal={s:equal for s in pending}
            nominal_turnover=sum(abs(nominal.get(s,0)-equity*holdings.get(s,0)) for s in set(nominal)|set(holdings))
            # Reserve all possible sale fees before sizing, leaving any excess as cash.
            sale_reserve=len(holdings)*selling_fee_nok/initial_capital if nominal_turnover>1e-10 else 0
            reserve=potential*BUY_FEE_NOK/initial_capital+sale_reserve+(2*equity*cost_bps/10000 if nominal_turnover>1e-10 else 0)
            pool=max(0,equity-reserve)
            target={s:pool/len(pending) for s in pending} if pool and pending else {}
            moves={s:target.get(s,0)-equity*holdings.get(s,0) for s in set(target)|set(holdings)}
            buys=sum(v>1e-10 for v in moves.values())
            fixed=buys*BUY_FEE_NOK/initial_capital
            sells=sum(v < -1e-10 for v in moves.values())
            sale_fee=sells*selling_fee_nok/initial_capital
            traded=sum(abs(v) for v in moves.values())
            turnover+=traded/equity/2 if equity else 0
            charge=fixed+sale_fee+traded*cost_bps/10000
            if charge>=equity:raise ValueError('Estimated transaction costs exhaust the experiment capital.')
            sell_orders+=sells;sell_fees+=sale_fee
            trade_log.append({'time':day*86400,'buys':buys,'sells':sells,'traded_nok':traded*initial_capital,'fees_nok':charge*initial_capital})
            equity-=charge
            fees+=charge;fixed_fees+=fixed;buy_orders+=buys
            trades+=sum(abs(v)>1e-10 for v in moves.values())
            holdings={s:v/equity for s,v in target.items()} if equity else {}
            pending=None
        curve.append({'time': day*86400, 'close':equity, 'benchmark':benchmark,'invested_pct':sum(holdings.values())*100})
        this_month = time.strftime('%Y-%m', time.gmtime(day*86400))
        ordinal=time.gmtime(day*86400).tm_year*12+time.gmtime(day*86400).tm_mon
        if this_month != month and (ordinal-first_month)%rebalance_months==0 and day != common[-1]:
            measured = []
            for s,h in series.items():
                key=(s,day,s in holdings,floor)
                if key in signal_cache:
                    measured.append(signal_cache[key]);continue
                past = h[:bisect.bisect_right(calendar[s],day)]
                # Turnover from available daily bars only; never use latest cached turnover.
                bars = past[-20:]
                tv = [p['close']*p['volume'] for p in bars if isinstance(p.get('volume'),(float,int)) and math.isfinite(p['volume']) and p['volume']>=0]
                q = {'price':past[-1]['close'],'asof':past[-1]['time'],'currency':'NOK','history':past,
                     'turnover20':sum(tv)/len(tv) if tv else None,'turnover_days':len(tv)}
                position = {'shares': 1, 'currency': 'NOK'} if s in holdings else None
                key=(s,day,bool(position),floor)
                if key not in signal_cache:
                    card=research.screen(s,q,position=position,min_turnover_nok=floor,as_of=day*86400+86399)
                    signal_cache[key]={k:card.get(k) for k in ('symbol','action','rank_eligible','composite')}
                measured.append(signal_cache[key])
            # Falling out of the entry screen is not an exit signal. Keep existing
            # positions until the shared exit policy fires; fill vacant slots only.
            retained = sorted(c['symbol'] for c in measured if c['symbol'] in holdings
                              and c.get('action') not in policy.SELL_SIGNALS)[:max_positions]
            available = (c for c in measured if c['symbol'] not in holdings)
            additions = policy.entries(available, limit=max_positions-len(retained))
            pending = retained + [c['symbol'] for c in additions]
            decisions += 1
            if progress:progress({'decisions':decisions,'session':day*86400})
            month = this_month
        previous = day
    peak, drawdown = 1., 0.
    for p in curve:
        peak = max(peak,p['close'])
        drawdown = min(drawdown,p['close']/peak-1)
    # Fixed-rule chronological holdout slices. No weights are fitted on the test returns.
    folds=[]
    for year in sorted({time.strftime('%Y',time.gmtime(p['time'])) for p in curve}):
        indices=[i for i,p in enumerate(curve) if time.strftime('%Y',time.gmtime(p['time']))==year]
        first,last=indices[0],indices[-1];base=curve[first-1] if first else {'close':1.,'benchmark':1.}
        folds.append({'year':year,'sessions':len(indices),'from':curve[first]['time'],'to':curve[last]['time'],
                      'strategy_pct':(curve[last]['close']/base['close']-1)*100,
                      'basket_pct':(curve[last]['benchmark']/base['benchmark']-1)*100})
    index_history=history(quotes.get('OSEBX.OL',{}));index_days={int(p['time']//86400):p['close'] for p in index_history}
    comparable=all(d in index_days for d in common[1:])
    index_curve=[{'time':d*86400,'close':1. if d<start else index_days[d]/index_days[start]} for d in common] if comparable else []
    index={'symbol':'OSEBX.OL','name':'Oslo Børs Benchmark GR (gross return)',
           'source_url':'https://live.euronext.com/en/product/indices/NO0007035327-XOSL',
           'status':'available' if comparable else 'unavailable / incomplete date coverage',
           'return_pct':(index_curve[-1]['close']-1)*100 if index_curve else None,'curve':index_curve,
           'method':'Provider series for the OSEBX gross-return benchmark. Index is not investable; no fund fees or transaction costs applied. Never forward-filled.'}
    return {'generated':time.time(),'version':VERSION,'policy_version':policy.VERSION,'cost_bps':cost_bps,'limits':LIMITS,'fee_model':FEE_MODEL,
            'folds':folds,'oslo_index':index,'test_protocol':str(max_positions)+'-position cap; '+str(rebalance_months)+'-month rebalance interval. '+'Shared technical entry/exit signals, 200-session warm-up, scheduled decisions and next-common-close execution. Retain holdings until a technical exit; fill vacant slots with qualifying entries in score order, up to 20 positions. Scheduled equal-weight sizing is an experiment overlay and can trim retained positions. Personal review prices, confirmation periods, cooldowns, sector/position limits and personalized quantities are not simulated. Chronological calendar-year slices for this fixed configuration; optional robustness selection is reported separately. Point-in-time delisted coverage unavailable.',
            'initial_capital':initial_capital,'buy_fee_nok':BUY_FEE_NOK,'buy_orders':buy_orders,
            'fixed_fees_nok':fixed_fees*initial_capital,'total_costs_nok':fees*initial_capital,
            'sell_orders':sell_orders,'selling_fee_nok':selling_fee_nok,'selling_fees_nok':sell_fees*initial_capital,
            'max_positions':max_positions,'rebalance_months':rebalance_months,'one_way_turnover_pct':turnover*100,
            'trade_log':trade_log,'performance':performance(curve),
            'stocks':len(series),'requested':len(set(universe)),'sessions':len(common),'decisions':decisions,
            'trades':trades,'cost_pct_initial':fees*100,'return_pct':(equity-1)*100,
            'benchmark_pct':(curve[-1]['benchmark']-1)*100,'max_drawdown_pct':drawdown*100,'curve':curve}


def capture(db, report, now=None):
    """Append once per report. Capture wall clock prevents backdating a saved report."""
    now = time.time() if now is None else now
    db.execute('CREATE TABLE IF NOT EXISTS paper_snapshots (generated REAL PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)')
    import json
    cards = {c['symbol']:c for c in report.get('cards',[])}
    payload = {'version':VERSION,'policy_version':report.get('policy_version'),'symbols':[{'symbol':s,'rank':cards[s].get('rank'),'action':cards[s].get('action'),
               'composite':cards[s].get('composite'),'quote_asof':cards[s].get('asof')} for s in report.get('top20',[]) if s in cards]}
    budget=(report.get('portfolio_limits') or {}).get('purchase_nok',0)
    payload['share_plan_audit']={'buys':(report.get('trade_plan') or {}).get('buys',[]),'sales':(report.get('trade_plan') or {}).get('holdings',[])}
    payload.update(fee_model=FEE_MODEL,buy_fee_nok=BUY_FEE_NOK,
                   order_budget_nok=budget if budget>0 else 100000/max(1,len(payload['symbols'])))
    db.execute('INSERT OR IGNORE INTO paper_snapshots VALUES (?,?,?)', (report['generated'],now,json.dumps(payload,allow_nan=False)))


def paper_view(db, quotes, now=None):
    import json
    now = time.time() if now is None else now
    rows = db.execute('SELECT * FROM paper_snapshots ORDER BY captured DESC LIMIT 60').fetchall()
    out=[]
    for row in rows:
        payload=json.loads(row['payload']); results=[]
        for item in payload['symbols']:
            h=[p for p in history(quotes.get(item['symbol'],{})) if row['captured'] < p['time'] <= now]
            # First later close is a hypothetical entry, never the signal close.
            fixed_model=payload.get('fee_model')==FEE_MODEL
            budget=payload.get('order_budget_nok') if fixed_model else None
            shares=max(0,math.floor((budget-payload['buy_fee_nok'])/h[0]['close'])) if fixed_model and h else None
            gain=None
            if len(h)>1:
                if fixed_model and shares:
                    remaining=budget-shares*h[0]['close']-payload['buy_fee_nok']
                    gain=((shares*h[-1]['close']+remaining)/budget-1)*100
                elif not fixed_model:
                    gain=(h[-1]['close']/h[0]['close']*(1-.002)/(1+.002)-1)*100
            results.append({**item,'entry_time':h[0]['time'] if h else None,'entry':h[0]['close'] if h else None,
                            'asof':h[-1]['time'] if h else None,'shares':shares,'budget_nok':budget,
                            'return_pct':gain})
        measured=[r['return_pct'] for r in results if r['return_pct'] is not None]
        out.append({'captured':row['captured'],'generated':row['generated'],'symbols':results,
                    'policy_version':payload.get('policy_version'),
                    'fee_model':payload.get('fee_model','legacy-percentage'),
                    'cost_note':('79 NOK per purchase; selling fees unmodelled; budget '+str(payload['order_budget_nok'])+' NOK per stock, including fees; whole shares and residual cash.' if payload.get('fee_model')==FEE_MODEL else 'Legacy cohort: original 20 bps each way; preserved without retroactive changes.'),
                    'measured':len(measured),'return_pct':sum(measured)/len(measured) if measured and len(measured)==len(results) else None})
    return {'snapshots':out,'method':'Independent equal-weight recommendation cohorts, not a rebalanced trading account. Entry at first later daily close. New cohorts save the 79 NOK purchase fee and order budget at capture time; selling fees are not modelled. Legacy assumptions remain labelled on each cohort. Pending or missing stocks prevent a cohort total. No real trades.'}


def performance(curve,start=0,end=None):
    """Chronological segment normalised at its preceding close, zero risk-free rate."""
    points=curve[start:end]
    if not points:return {}
    base=curve[start-1] if start else {'close':1.,'benchmark':1.,'time':points[0]['time']}
    returns=[];previous=base['close'];peak=previous;drawdown=0.;duration=0;longest=0
    for p in points:
        returns.append(p['close']/previous-1);previous=p['close'];peak=max(peak,previous)
        dd=previous/peak-1;drawdown=min(drawdown,dd)
        duration=duration+1 if dd < -1e-12 else 0;longest=max(longest,duration)
    if not start:returns=returns[1:]
    n=len(returns);mean=sum(returns)/n if n else 0
    vol=math.sqrt(sum((v-mean)**2 for v in returns)/(n-1)*252) if n>=2 else None
    downside=math.sqrt(sum(min(v,0)**2 for v in returns)/n*252) if n else 0
    years=(points[-1]['time']-base['time'])/(365.25*86400)
    gain=points[-1]['close']/base['close']-1
    return {'sessions':len(points),'from':points[0]['time'],'to':points[-1]['time'],'return_pct':gain*100,
        'benchmark_pct':(points[-1].get('benchmark',1)/base.get('benchmark',1)-1)*100,
        'cagr_pct':((1+gain)**(1/years)-1)*100 if years>=365/365.25 and gain > -1 else None,
        'annual_volatility_pct':vol*100 if vol is not None else None,
        'sharpe_zero_rate':mean*252/vol if n>=20 and vol and vol>1e-10 else None,
        'sortino_zero_rate':mean*252/downside if n>=20 and downside>1e-10 else None,
        'max_drawdown_pct':drawdown*100,'longest_underwater_sessions':longest,
        'positive_sessions_pct':sum(v>0 for v in returns)/n*100 if n else None,
        'average_invested_pct':sum(p.get('invested_pct',0) for p in points)/len(points)}


def choose_variant(training):
    """Select using only already-truncated training metrics. Never inspect holdout."""
    return max(training,key=lambda r:((r['training'].get('sharpe_zero_rate') if r['training'].get('sharpe_zero_rate') is not None else -1e9),
                                      r['training']['return_pct'],-r['max_positions'],-r['rebalance_months']))


def evaluate_suite(quotes,universe,cost_bps=0,floor=250000,initial_capital=100000,progress=None,selling_fee_nok=0):
    cache={};variants=[];base=None
    configurations=[(20,1),(10,1),(20,3),(10,3)]
    for i,(positions,months) in enumerate(configurations):
        label=str(positions)+' positions / '+str(months)+' month(s)'
        def update(value):
            if progress:progress({**value,'phase':'Parameter diagnostics','variant':label,'variants_done':i,'variants_total':6})
        v=evaluate(quotes,universe,cost_bps,floor,initial_capital,update,selling_fee_nok,positions,months,cache)
        if base is None:base=v
        split=max(20,min(len(v['curve'])-20,int(len(v['curve'])*.7)))
        variants.append({'label':label,'max_positions':positions,'rebalance_months':months,
                         'training':performance(v['curve'],end=split),'holdout':performance(v['curve'],start=split),'result':v,'split':split})
    chosen=choose_variant(variants)
    costs=[]
    for i,extra in enumerate((25,50)):
        bps=min(200,float(cost_bps)+extra)
        if progress:progress({'phase':'Cost sensitivity','variant':str(bps)+' bps','variants_done':4+i,'variants_total':6})
        v=evaluate(quotes,universe,bps,floor,initial_capital,None,selling_fee_nok,chosen['max_positions'],chosen['rebalance_months'],cache)
        costs.append({'cost_bps':bps,'holdout':performance(v['curve'],start=chosen['split']),'total_costs_nok':v['total_costs_nok']})
    selected=chosen['result'];split=chosen['split']
    base['robustness']={'training_fraction':.7,'split_date':selected['curve'][split]['time'],
        'selected':chosen['label'],'training':chosen['training'],'holdout':chosen['holdout'],
        'holdout_curve':[{'time':selected['curve'][split-1]['time'],'close':1.}]+[{'time':p['time'],'close':p['close']/selected['curve'][split-1]['close']} for p in selected['curve'][split:]],
        'variants':[{k:v for k,v in r.items() if k not in ('result','split')} for r in variants],'cost_sensitivity':costs,
        'method':'Retrospective chronological 70/30 split. Four fixed position-count/rebalancing variants; select highest training Sharpe (zero risk-free rate), then training return as tie-break. '
                 'No holdout return is passed to the selector. Holdings carry across the boundary; holdout wealth is normalised at the preceding close. '
                 'All rules were authored before this run, not independently certified before historical dates. Today’s survivor universe and revised prices remain biases. '
                 'Variant holdout comparisons and extra-cost runs are diagnostics, not additional independent confirmations. Repeatedly viewing/tuning against this holdout invalidates an unseen-test claim.'}
    return base
