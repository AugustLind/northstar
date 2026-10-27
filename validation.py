"""Dated technical-signal experiments, separate from real holdings."""
import bisect
import math
import time
import research

VERSION = 'technical-monthly-v1'
LIMITS = ('Exploratory, not an unbiased market backtest: today’s configured universe excludes '
          'unknown delisted stocks. Adjusted prices may be revised. Financials and news are excluded. '
          'Benchmark is the same complete-history basket bought and held, not an Oslo index. '
          'Missing common sessions are excluded; stocks without complete test history are excluded. '
          'No tax, market impact, minimum commission or cash interest. Costs are illustrative, not your Nordnet plan.')


def history(q):
    points = {}
    if q.get('currency') != 'NOK':
        return []
    for p in q.get('history', []):
        if all(isinstance(p.get(k), (float, int)) and math.isfinite(p[k]) and p[k] > 0 for k in ('time','close')):
            points[int(p['time']//86400)] = p
    return [points[d] for d in sorted(points)]


def evaluate(quotes, universe, cost_bps=20, floor=250000):
    """Monthly decision at close; execute next common close; no future inputs to screen."""
    cost_bps = float(cost_bps)
    if not math.isfinite(cost_bps) or not 0 <= cost_bps <= 200:
        raise ValueError('One-way cost must be 0–200 basis points.')
    series = {s: history(quotes.get(s, {})) for s in set(universe)}
    series = {s: h for s, h in series.items() if len(h) >= 260}
    if not series:
        raise ValueError('Download at least 260 daily observations for a stock first.')
    # Complete-case sample is explicit; never silently mark suspended assets flat.
    latest = max(int(h[-1]['time']//86400) for h in series.values())
    series = {s:h for s,h in series.items() if int(h[-1]['time']//86400) == latest}
    common = sorted(set.intersection(*[{int(p['time']//86400) for p in h[199:]} for h in series.values()]))
    if len(common) < 40:
        raise ValueError('Fewer than 40 common test sessions; insufficient comparable history.')
    common = common[-252:]
    lookups = {s:{int(p['time']//86400):p['close'] for p in h} for s,h in series.items()}
    equity, benchmark, holdings, pending = 1., 1., {}, None
    curve, trades, decisions, fees = [], 0, 0, 0.
    start = common[0]
    previous = None
    month = None
    for day in common:
        if previous is not None:
            equity *= 1 + sum(w*(lookups[s][day]/lookups[s][previous]-1) for s,w in holdings.items())
            # Update weights for price drift before rebalancing.
            grown = {s:w*lookups[s][day]/lookups[s][previous] for s,w in holdings.items()}
            total = 1-sum(holdings.values())+sum(grown.values())
            holdings = {s:w/total for s,w in grown.items()}
        benchmark = sum(lookups[s][day]/lookups[s][start] for s in series)/len(series)
        if pending is not None:
            target = {s:1/len(pending) for s in pending} if pending else {}
            turnover = sum(abs(target.get(s,0)-holdings.get(s,0)) for s in set(target)|set(holdings))
            charge = equity*turnover*cost_bps/10000
            equity -= charge
            fees += charge
            trades += sum(abs(target.get(s,0)-holdings.get(s,0))>1e-9 for s in set(target)|set(holdings))
            holdings, pending = target, None
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
            month = this_month
        previous = day
    peak, drawdown = 1., 0.
    for p in curve:
        peak = max(peak,p['close'])
        drawdown = min(drawdown,p['close']/peak-1)
    # Benchmark pays same entry-cost assumption, no terminal liquidation on either curve.
    for p in curve:
        p['benchmark'] *= 1-cost_bps/10000
    return {'generated':time.time(),'version':VERSION,'cost_bps':cost_bps,'limits':LIMITS,
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
            results.append({**item,'entry_time':h[0]['time'] if h else None,'entry':h[0]['close'] if h else None,
                            'asof':h[-1]['time'] if h else None,
                            'return_pct':(h[-1]['close']/h[0]['close']*(1-.002)/(1+.002)-1)*100 if len(h)>1 else None})
        measured=[r['return_pct'] for r in results if r['return_pct'] is not None]
        out.append({'captured':row['captured'],'generated':row['generated'],'symbols':results,
                    'measured':len(measured),'return_pct':sum(measured)/len(measured) if measured and len(measured)==len(results) else None})
    return {'snapshots':out,'method':'Independent equal-weight recommendation cohorts, not a rebalanced trading account. Entry at first later daily close; 20 bps each way including hypothetical liquidation. Pending or missing stocks prevent a cohort total. No real trades.'}
