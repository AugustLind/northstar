"""Dated technical-signal experiments, separate from real holdings."""
import bisect
import math
import time
import research
from broker_costs import BUY_FEE_NOK, FEE_MODEL

VERSION = 'technical-monthly-fixed-buy-v2'
LIMITS = ('Exploratory, not an unbiased market backtest: today’s configured universe excludes '
          'unknown delisted stocks. Adjusted prices may be revised. Financials and news are excluded. '
          'Benchmark is the same complete-history basket bought and held, not an Oslo index. '
          'Stocks without a complete reference calendar and warm-up, including younger IPOs and incomplete histories, are excluded. '
          'Uses fractional stock allocations, fixed 79 NOK per buy order and optional extra slippage. '
          'Fee reserves can leave residual cash. No selling commission, tax, market impact or cash interest is modelled.')


def history(q):
    points = {}
    if q.get('currency') != 'NOK':
        return []
    for p in q.get('history', []):
        if all(isinstance(p.get(k), (float, int)) and math.isfinite(p[k]) and p[k] > 0 for k in ('time','close')):
            points[int(p['time']//86400)] = p
    return [points[d] for d in sorted(points)]


def evaluate(quotes, universe, cost_bps=0, floor=250000, initial_capital=100000, progress=None):
    """Monthly decision at close; execute next common close; no future inputs to screen."""
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
    buy_orders=0;fixed_fees=0.
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
            reserve=potential*BUY_FEE_NOK/initial_capital+(2*equity*cost_bps/10000 if nominal_turnover>1e-10 else 0)
            pool=max(0,equity-reserve)
            target={s:pool/len(pending) for s in pending} if pool and pending else {}
            moves={s:target.get(s,0)-equity*holdings.get(s,0) for s in set(target)|set(holdings)}
            buys=sum(v>1e-10 for v in moves.values())
            fixed=buys*BUY_FEE_NOK/initial_capital
            charge=fixed+sum(abs(v) for v in moves.values())*cost_bps/10000
            equity-=charge
            fees+=charge;fixed_fees+=fixed;buy_orders+=buys
            trades+=sum(abs(v)>1e-10 for v in moves.values())
            holdings={s:v/equity for s,v in target.items()} if equity else {}
            pending=None
        curve.append({'time': day*86400, 'close':equity, 'benchmark':benchmark})
        this_month = time.strftime('%Y-%m', time.gmtime(day*86400))
        if this_month != month and day != common[-1]:
            ranked = []
            for s,h in series.items():
                past = h[:bisect.bisect_right([int(p['time']//86400) for p in h],day)]
                # Turnover from available daily bars only; never use latest cached turnover.
                bars = past[-20:]
                tv = [p['close']*p['volume'] for p in bars if isinstance(p.get('volume'),(float,int)) and math.isfinite(p['volume']) and p['volume']>=0]
                q = {'price':past[-1]['close'],'asof':past[-1]['time'],'currency':'NOK','history':past,
                     'turnover20':sum(tv)/len(tv) if tv else None,'turnover_days':len(tv)}
                c = research.screen(s,q,min_turnover_nok=floor,as_of=day*86400+86399)
                if c.get('rank_eligible'):
                    ranked.append(c)
            pending = [c['symbol'] for c in sorted(ranked,key=lambda c:(-c['composite'],c['symbol']))[:20]]
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
    return {'generated':time.time(),'version':VERSION,'cost_bps':cost_bps,'limits':LIMITS,'fee_model':FEE_MODEL,
            'folds':folds,'oslo_index':index,'test_protocol':'Technical-ranking experiment, not the personalized quantity/stability policy. Fixed rules, 200-session warm-up, monthly forward decisions and next-common-close execution; chronological calendar-year holdout slices, no parameter fitting. Point-in-time delisted coverage unavailable.',
            'initial_capital':initial_capital,'buy_fee_nok':BUY_FEE_NOK,'buy_orders':buy_orders,
            'fixed_fees_nok':fixed_fees*initial_capital,'total_costs_nok':fees*initial_capital,
            'stocks':len(series),'requested':len(set(universe)),'sessions':len(common),'decisions':decisions,
            'trades':trades,'cost_pct_initial':fees*100,'return_pct':(equity-1)*100,
            'benchmark_pct':(curve[-1]['benchmark']-1)*100,'max_drawdown_pct':drawdown*100,'curve':curve}


def capture(db, report, now=None):
    """Append once per report. Capture wall clock prevents backdating a saved report."""
    now = time.time() if now is None else now
    db.execute('CREATE TABLE IF NOT EXISTS paper_snapshots (generated REAL PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)')
    import json
    cards = {c['symbol']:c for c in report.get('cards',[])}
    payload = {'version':VERSION,'symbols':[{'symbol':s,'rank':cards[s].get('rank'),'action':cards[s].get('action'),
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
                    'fee_model':payload.get('fee_model','legacy-percentage'),
                    'cost_note':('79 NOK per purchase; selling fees unmodelled; budget '+str(payload['order_budget_nok'])+' NOK per stock, including fees; whole shares and residual cash.' if payload.get('fee_model')==FEE_MODEL else 'Legacy cohort: original 20 bps each way; preserved without retroactive changes.'),
                    'measured':len(measured),'return_pct':sum(measured)/len(measured) if measured and len(measured)==len(results) else None})
    return {'snapshots':out,'method':'Independent equal-weight recommendation cohorts, not a rebalanced trading account. Entry at first later daily close. New cohorts save the 79 NOK purchase fee and order budget at capture time; selling fees are not modelled. Legacy assumptions remain labelled on each cohort. Pending or missing stocks prevent a cohort total. No real trades.'}
