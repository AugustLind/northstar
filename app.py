"""Local investment research notebook. Run: python3 app.py"""
import json
import math
import re
import sqlite3
import time
from datetime import datetime, timezone
import threading
import os
import hashlib
import hmac
import base64
import binascii
import secrets
import sys
import research
import research_worker
import decision_policy
import fundamentals
import announcements
import validation
import portfolio_fit
import holdings_import
import trade_plan
import transactions
import company_data
import advice_state
import daily_board
import email_alerts
import portfolio_risk
import financial_analysis
import stock_summary
import system_status
import research_archive
import account_performance
import ui_assets
import release_info
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit, parse_qs
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor
from zoneinfo import ZoneInfo

ROOT = Path(__file__).parent
STARTED_AT=time.time()
SOURCE_FINGERPRINT=release_info.fingerprint()
DB = ROOT / 'data' / 'portfolio.db'
REFRESH_LOCK = threading.Lock()
VALIDATION_LOCK = threading.Lock()
WORKER = None
FUNDAMENTALS_WORKER = None
ANNOUNCEMENTS_WORKER = None
COMPANY_WORKER = None
EMAIL_WORKER = None
MODEL_LOCK = threading.Lock()

def request_origin_allowed(origin, host):
    allowed = os.environ.get('NORTHSTAR_PUBLIC_ORIGIN') or 'http://' + host
    pages = os.environ.get('NORTHSTAR_PAGES_ORIGIN')
    return not origin or origin == allowed or bool(pages and origin == pages)

def bearer_digest(authorization):
    if authorization and authorization.startswith('Bearer '):
        return hashlib.sha256(authorization[7:].encode()).hexdigest()
    return ''


def api_authorized(authorization):
    expected = os.environ.get('NORTHSTAR_ACCESS_KEY_HASH')
    if not expected:
        return not os.environ.get('NORTHSTAR_PAGES_ORIGIN')
    digest = bearer_digest(authorization)
    if hmac.compare_digest(digest, expected):
        return True
    if not authorization or not authorization.startswith('Bearer ns-session-'):
        return False
    with connect() as db:
        return db.execute('SELECT 1 FROM remembered_sessions WHERE digest=? AND key_hash=?',
                          (digest, expected)).fetchone() is not None


def revoke_remembered_sessions():
    with connect() as db:
        db.execute('DELETE FROM remembered_sessions')


def connect():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    research_archive.schema(db)
    db.execute('CREATE TABLE IF NOT EXISTS account_baselines (id INTEGER PRIMARY KEY AUTOINCREMENT,created REAL NOT NULL,cutoff_date TEXT NOT NULL,payload TEXT NOT NULL)')
    for action in ('UPDATE','DELETE'):
        db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_account_baselines_{action.lower()} BEFORE {action} ON account_baselines BEGIN SELECT RAISE(ABORT,'Opening checkpoints are append-only'); END")
    db.execute('CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, currency TEXT, shares REAL, cost REAL, thesis TEXT, review TEXT, below REAL, above REAL)')
    if 'long_term' not in {r['name'] for r in db.execute('PRAGMA table_info(positions)')}:
        db.execute('ALTER TABLE positions ADD COLUMN long_term INTEGER NOT NULL DEFAULT 0')
    db.execute('CREATE TABLE IF NOT EXISTS quotes (symbol TEXT PRIMARY KEY, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS remembered_sessions (digest TEXT PRIMARY KEY, key_hash TEXT NOT NULL)')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, payload TEXT)')
    return db

def read_meta(key, default=None):
    with connect() as db:
        row = db.execute('SELECT payload FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row['payload']) if row else default

def write_meta(key, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))
        if key.startswith('fundamentals:') and value.get('series'):
            research_archive.capture(db,'financial',key.split(':',1)[1],value,source_asof=value.get('fetched'))
        elif key.startswith('company:') and value.get('fetched'):
            research_archive.capture(db,'company',key.split(':',1)[1],value,source_asof=value.get('fetched'))
        elif key=='settings' and value.get('universe'):
            research_archive.capture(db,'universe','oslo',{'universe':value['universe'],'min_turnover_nok':value.get('min_turnover_nok',250000)})

def settings():
    saved = read_meta('settings', {})
    # Migrate the earlier US/large-cap screen once without changing holdings.
    if saved.get('market_scope') != research.SCOPE:
        extra = [s for s in saved.get('universe',[]) if re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL',s)]
        saved = {k: v for k, v in saved.items() if k in ('model', 'llm_enabled', 'interval_minutes', 'min_turnover_nok')}
        saved['universe'] = list(dict.fromkeys(research.DEFAULT_UNIVERSE + extra))[:500]
    return {**research.DEFAULT_SETTINGS, **saved}

def save_settings(data):
    universe = data.get('universe', [])
    if not isinstance(universe, list) or not 1 <= len(universe) <= 500:
        raise ValueError('Choose between 1 and 500 Oslo stock symbols.')
    symbols = list(dict.fromkeys(str(s).strip().upper() for s in universe))
    symbols = [s if s.endswith('.OL') else s + '.OL' for s in symbols]
    symbols = list(dict.fromkeys(symbols))
    if any(not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL', s) for s in symbols):
        raise ValueError('Only Oslo candidates are supported. Use symbols such as NORBT.OL or BOUV.OL.')
    interval = int(data.get('interval_minutes', 360))
    if not 60 <= interval <= 1440:
        raise ValueError('Refresh interval must be 60–1440 minutes.')
    model = str(data.get('model', 'qwen2.5:3b'))
    if not re.fullmatch(r'[a-zA-Z0-9_.:/-]{1,100}', model):
        raise ValueError('Invalid Ollama model name.')
    if not isinstance(data.get('llm_enabled', False), bool):
        raise ValueError('LLM enabled must be true or false.')
    turnover = positive(data.get('min_turnover_nok', 250000))
    write_meta('settings', {'universe': symbols, 'interval_minutes': interval,
                           'model': model, 'llm_enabled': data.get('llm_enabled', False),
                           'min_turnover_nok': turnover, 'market_scope': research.SCOPE})

def positive(value, optional=False):
    if optional and value in ('', None):
        return None
    value = float(value)
    if not math.isfinite(value) or value < 0:
        raise ValueError('Numbers must be finite and nonnegative.')
    return value

def save_position(data):
    symbol = str(data.get('symbol', '')).strip().upper()
    if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.\-^]{0,19}', symbol):
        raise ValueError('Enter a valid ticker, such as MSFT or EQNR.OL.')
    currency = data.get('currency')
    if currency not in ('USD', 'NOK'):
        raise ValueError('Choose USD or NOK.')
    long_term=data.get('long_term',False)
    if not isinstance(long_term,bool):
        raise ValueError('Long-term designation must be true or false.')
    values = (symbol, currency, positive(data.get('shares')), positive(data.get('cost')),
              str(data.get('thesis', ''))[:5000], str(data.get('review', ''))[:5000],
              positive(data.get('below'), True), positive(data.get('above'), True), int(long_term))
    with connect() as db:
        db.execute('''INSERT INTO positions(symbol,currency,shares,cost,thesis,review,below,above,long_term)
                      VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                      currency=excluded.currency,shares=excluded.shares,cost=excluded.cost,
                      thesis=excluded.thesis,review=excluded.review,below=excluded.below,
                      above=excluded.above,long_term=excluded.long_term''', values)

def fetch_quote(symbol):
    # Unofficial public endpoint: errors are surfaced, never replaced with sample prices.
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='') + '?range=5y&interval=1d&events=div%2Csplits'
    req = Request(url, headers={'User-Agent': 'Mozilla/5.0'})
    with urlopen(req, timeout=12) as response:
        result = json.load(response)['chart']['result'][0]
    meta = result['meta']
    close = [v for v in result['indicators']['quote'][0]['close'] if v is not None and math.isfinite(v)]
    series = result['indicators'].get('adjclose', [{}])[0].get('adjclose')
    adjusted = series is not None
    if series is None:
        series = result['indicators']['quote'][0]['close']
    raw = result['indicators']['quote'][0]
    history = []
    for i,(t,v) in enumerate(zip(result.get('timestamp',[]),series)):
        if (not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0
                or not isinstance(t,(int,float)) or not math.isfinite(t) or t<=0 or t>time.time()+300):
            continue
        point = {'time':t,'close':v}
        fields = {k: raw.get(k,[])[i] if i<len(raw.get(k,[])) else None for k in ('open','high','low','close','volume')}
        if (all(isinstance(fields[k],(int,float)) and math.isfinite(fields[k]) and fields[k]>0 for k in ('open','high','low','close'))
                and fields['high']>=max(fields['open'],fields['close'])
                and fields['low']<=min(fields['open'],fields['close'])):
            factor = v/fields['close']
            point.update({k:fields[k]*factor for k in ('open','high','low')})
        if isinstance(fields['volume'],(int,float)) and math.isfinite(fields['volume']) and fields['volume']>=0:
            point['volume']=fields['volume']
        history.append(point)
    history=sorted({point['time']:point for point in history}.values(),key=lambda p:p['time'])
    turnover = [p * v for p, v in zip(raw['close'][-20:], raw.get('volume', [])[-20:])
                if isinstance(p, (int, float)) and isinstance(v, (int, float)) and
                math.isfinite(p) and math.isfinite(v) and p > 0 and v >= 0]
    price = float(meta['regularMarketPrice'])
    if price <= 0 or not math.isfinite(price):
        raise ValueError('Provider returned an invalid price.')
    events=[]
    event_source='https://finance.yahoo.com/quote/'+quote(symbol,safe='')+'/history/'
    for kind,key in [('dividend','dividends'),('split','splits')]:
        for item in (result.get('events',{}).get(key,{}) or {}).values():
            stamp=item.get('date')
            if not isinstance(stamp,(int,float)) or not math.isfinite(stamp) or not 0<stamp<=time.time()+86400:continue
            if kind=='dividend':
                amount=item.get('amount')
                if not isinstance(amount,(int,float)) or not math.isfinite(amount) or amount<0:continue
                label='Provider dividend / ex-date: '+str(amount)+' '+meta.get('currency','')
            else:
                numerator=item.get('numerator');denominator=item.get('denominator')
                if not all(isinstance(v,(int,float)) and math.isfinite(v) and v>0 for v in (numerator,denominator)):continue
                amount=None;label='Provider split: '+str(numerator)+':'+str(denominator)
            events.append({'time':stamp,'kind':kind,'label':label,'amount':amount,'currency':meta.get('currency'),
                           'source':'Yahoo Finance chart events (unofficial)','source_url':event_source,**({'ratio':numerator/denominator} if kind=='split' else {})})
    raw_by_time={t:v for t,v in zip(result.get('timestamp',[]),raw.get('close',[])) if isinstance(t,(int,float)) and isinstance(v,(int,float)) and math.isfinite(v) and v>0}
    for point in history:
        raw_close=raw_by_time.get(point['time'])
        if raw_close is not None:
            factor=math.prod(e['ratio'] for e in events if e['kind']=='split' and int(e['time']//86400)>int(point['time']//86400) and int(e['time']//86400)<=int(meta['regularMarketTime']//86400))
            point['raw_close']=raw_close
            point['account_close']=raw_close*factor
    return {'price': price, 'currency': meta['currency'], 'asof': meta['regularMarketTime'],
            'fetched': time.time(), 'source': 'Yahoo Finance (unofficial)',
            'history': history, 'history_basis': 'Dividend/split adjusted close' if adjusted else 'Provider daily close',
            'history_version':3,'events_version':1,'account_history_version':1,
            'account_price_basis':'Provider split-only close restored to historical share units using sourced split events; dividends not added.','events':sorted(events,key=lambda e:e['time']),
            'name': meta.get('longName') or meta.get('shortName') or symbol,
            'turnover20': sum(turnover)/len(turnover) if turnover else None, 'turnover_days': len(turnover),
            'ma200': sum(close[-200:])/200 if len(close) >= 200 else None,
            'previous': close[-2] if len(close) >= 2 else None}

def refresh(extra_symbols=None):
    with REFRESH_LOCK:
        return _refresh(extra_symbols)

def _refresh(extra_symbols=None):
    with connect() as db:
        positions = list(db.execute('SELECT symbol, currency FROM positions'))
    lookups = {r['symbol']: (r['symbol'] + '.OL' if r['currency'] == 'NOK' and '.' not in r['symbol'] else r['symbol']) for r in positions}
    for symbol in extra_symbols or []:
        lookups.setdefault(symbol, symbol)
    lookups['NOK=X'] = 'NOK=X'
    if extra_symbols is not None:
        lookups['OSEBX.OL']='OSEBX.OL'
        lookups['OBXD.OL']='OBXD.OL'
    symbols = list(dict.fromkeys(lookups.values()))
    progress_lock = threading.Lock()
    progress = {'done':0,'total':len(symbols),'started':time.time(),'failed':0}
    write_meta('refresh_progress',progress)
    with connect() as db:
        cached = {row['symbol']:json.loads(row['payload']) for row in db.execute('SELECT * FROM quotes')}
    def one(symbol):
        failed=False
        try:
            old = cached.get(symbol)
            if extra_symbols is not None and old and old.get('history_version')==3 and old.get('events_version')==1 and old.get('account_history_version')==1 and time.time()-old.get('fetched',0)<1200:
                payload=old
            else:
                for attempt in range(2):
                    try:
                        payload = fetch_quote(symbol)
                        break
                    except HTTPError as error:
                        if error.code not in (429,503) or attempt==1:
                            raise
                        time.sleep(5)
            with connect() as db:
                research_archive.capture(db,'quote',symbol,payload,source_asof=payload.get('asof'))
                for key, lookup in lookups.items():
                    if lookup == symbol:
                        db.execute('INSERT OR REPLACE INTO quotes VALUES (?,?)', (key, json.dumps(payload)))
            return None
        except Exception as error:
            failed=True
            if isinstance(error, HTTPError):
                reason = ('ticker not found' if error.code == 404 else
                          'provider rate limit; try again later' if error.code == 429 else
                          'provider returned HTTP ' + str(error.code))
            elif isinstance(error, (URLError, TimeoutError)):
                reason = 'provider could not be reached; check connection and try again'
            else:
                reason = 'provider returned unusable data; check ticker and retry'
            return f'{symbol}: {reason}. Any previous quote retains its original timestamp.'
        finally:
            with progress_lock:
                progress['done']+=1
                progress['failed']+=int(failed)
                if progress['done']%5==0 or progress['done']==progress['total']:
                    write_meta('refresh_progress',progress)
    with ThreadPoolExecutor(max_workers=3) as pool:
        return [error for error in pool.map(one, symbols) if error]

def financial_symbols():
    with connect() as db:
        held = [fundamentals.canonical(r['symbol']) for r in db.execute("SELECT symbol FROM positions WHERE currency='NOK' ORDER BY shares DESC")]
    return list(dict.fromkeys(held + settings()['universe']))

def financial_view(symbol):
    symbol=fundamentals.canonical(symbol);snapshot=state(True)
    record=snapshot.get('fundamentals',{}).get(symbol)
    q=snapshot['quotes'].get(symbol) or snapshot['quotes'].get(symbol[:-3])
    financial=fundamentals.analyse(record,q)
    annual=financial_analysis.timeline(record)
    return {**financial,'annual_series':annual,'trends':financial_analysis.trends(annual),
            'peer_comparison':financial_analysis.peers(symbol,financial,snapshot.get('fundamentals',{}),snapshot['quotes'],snapshot['portfolio_preferences']['sectors']),
            'symbol':symbol,'scan':read_meta('fundamentals_progress'),'attempted':(record or {}).get('attempted'),
            'assessment':company_data.assessment(financial,snapshot['portfolio_preferences']['sectors'].get(symbol)),
            'valuation':company_data.peer_valuation(symbol,financial,snapshot.get('fundamentals',{}),snapshot['quotes'],snapshot['portfolio_preferences']['sectors'])}


def announcement_focus(scope='focus'):
    with connect() as db:
        held=[fundamentals.canonical(r['symbol']) for r in db.execute("SELECT symbol FROM positions WHERE currency='NOK' AND shares>0")]
    if scope=='held':
        return list(dict.fromkeys(held))
    if scope=='universe':
        return list(dict.fromkeys(held+settings()['universe']))
    report=read_meta('report',{})
    return list(dict.fromkeys(held+report.get('top20',[])))

def announcement_view(symbol=None, scope='focus'):
    if scope not in ('focus','held','universe'):
        raise ValueError('Unknown announcement scope.')
    wanted=[fundamentals.canonical(symbol)] if symbol else announcement_focus(scope)
    result=announcements.view(read_meta('announcements_feed'),wanted)
    result.update(focus_symbols=wanted,reviewed_at=read_meta('announcements_reviewed_at',0),
                  progress=read_meta('announcements_progress'))
    return result

def ledger_reconciliation(positions, profile, baseline, cash_check):
    if cash_check.get('mismatch_active'):
        return False
    if baseline:
        return baseline['fingerprint'] == transactions.fingerprint(positions, profile['cash_nok'])
    return None


def state(include_fundamentals=False):
    with connect() as db:
        result = {'positions': [dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')],
                'quotes': {r['symbol']: json.loads(r['payload']) for r in db.execute('SELECT * FROM quotes')}}
        if include_fundamentals:
            result['fundamentals'] = {r['key'].split(':', 1)[1]: json.loads(r['payload']) for r in db.execute("SELECT key,payload FROM metadata WHERE key LIKE 'fundamentals:%'")}
            result['announcements']=read_meta('announcements_feed',{})
        result['companies']={r['key'].split(':',1)[1]:json.loads(r['payload']) for r in db.execute("SELECT key,payload FROM metadata WHERE key LIKE 'company:%'")}
        result['manual_portfolio_preferences']=portfolio_fit.preferences(read_meta('portfolio_preferences',{}))
        result['portfolio_preferences']=company_data.effective(result['manual_portfolio_preferences'],result['companies'])
        result['signal_state']=read_meta('signal_state',{})
        result['last_trades']=read_meta('last_trades',{})
        baseline=read_meta('ledger_state')
        result['ledger_reconciled']=ledger_reconciliation(result['positions'], result['manual_portfolio_preferences'],
                                                        baseline, read_meta('broker_cash_check',{}))
        result['portfolio_context']=portfolio_fit.context(result,result['portfolio_preferences'])
        return result

def positions_fingerprint(positions):
    return hashlib.sha256(json.dumps(sorted(positions,key=lambda p:p['symbol']),sort_keys=True,allow_nan=False).encode()).hexdigest()


def import_preview(data):
    encoded=data.get('file_b64')
    if not isinstance(encoded,str) or len(encoded)>350000:
        raise ValueError('Choose a holdings export up to 256 KiB.')
    try:
        raw=base64.b64decode(encoded,validate=True)
    except (binascii.Error,ValueError):
        raise ValueError('The upload could not be decoded. Choose the CSV file again.')
    items=holdings_import.parse(raw)
    snapshot=state()
    companies=holdings_import.catalogue(snapshot['quotes'],read_meta('report'))
    aliases=read_meta('holdings_import_aliases',{})
    token=secrets.token_urlsafe(24)
    expires=time.time()+900
    write_meta('pending_holdings_import',{'token':token,'expires':expires,'items':items,
                                        'fingerprint':positions_fingerprint(snapshot['positions'])})
    rows=holdings_import.suggest(items,companies,aliases)
    for row in rows:
        row['existing']=next(({k:p[k] for k in ('symbol','shares','cost')} for p in snapshot['positions'] if p['currency']=='NOK' and
                              portfolio_fit.canonical(p['symbol'])==row['symbol']),None)
    return {'token':token,'expires':expires,'rows':rows,'companies':companies,
            'valid':sum(not r['error'] for r in rows),
            'existing_holdings':[{k:p[k] for k in ('symbol','currency','shares','cost')} for p in snapshot['positions']],
            'method':'Preview only. Confirm ticker matches before applying. Quantities and GAV replace the selected existing holdings, not add to them. '
                     'Notes and price-review levels are preserved; omitted stocks and tracked cash are unchanged. '
                     'Use a consolidated export if the same stock is held across multiple accounts. GAV is imported unchanged, without adding another purchase fee.'}


def apply_import(data):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT payload FROM metadata WHERE key='pending_holdings_import'").fetchone()
        pending=json.loads(row['payload']) if row else None
        if not pending or not isinstance(data.get('token'),str) or not hmac.compare_digest(data['token'],pending['token']):
            raise ValueError('This import preview is no longer available. Upload the export again.')
        if pending['expires']<time.time():
            raise ValueError('This import preview has expired. Upload the export again.')
        positions=[dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')]
        if positions_fingerprint(positions)!=pending['fingerprint']:
            raise ValueError('Your holdings changed after this preview. Upload again to review the current differences.')
        row=db.execute("SELECT payload FROM metadata WHERE key='holdings_import_aliases'").fetchone()
        aliases=json.loads(row['payload']) if row else {}
        result=holdings_import.save(db,pending['items'],data.get('selections'),aliases)
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('holdings_import_aliases',json.dumps(result['aliases'],allow_nan=False)))
        db.execute("DELETE FROM metadata WHERE key='pending_holdings_import'")
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('holdings_import_status',json.dumps({'imported':time.time(),'updated':result['updated']})))
    if WORKER:
        WORKER.trigger()
    return {'updated':result['updated']}


def start_validation(data):
    slippage=portfolio_fit.number(data.get('cost_bps',0),'Additional slippage',200)
    capital=portfolio_fit.number(data.get('initial_capital',100000),'Starting capital',1e9)
    if capital<1000:raise ValueError('Starting capital must be at least 1,000 NOK.')
    selling_fee=portfolio_fit.number(data.get('selling_fee_nok',0),'Selling fee',10000)
    robustness=data.get('robustness',True)
    if not isinstance(robustness,bool):raise ValueError('Robustness must be true or false.')
    if not VALIDATION_LOCK.acquire(blocking=False):return {'queued':False,'message':'A historical experiment is already running.'}
    try:
        snapshot=state();config=settings();started=time.time()
        write_meta('validation_progress',{'running':True,'started':started,'decisions':0})
        def run():
            try:
                def progress(value):write_meta('validation_progress',{'running':True,'started':started,**value})
                runner=validation.evaluate_suite if robustness else validation.evaluate
                result=runner(snapshot['quotes'],config['universe'],slippage,config['min_turnover_nok'],capital,progress,selling_fee_nok=selling_fee)
                write_meta('validation_report',result)
                write_meta('validation_progress',{'running':False,'started':started,'finished':time.time()})
            except Exception as error:
                message=str(error) if isinstance(error,ValueError) else 'Historical experiment failed; previous result retained.'
                write_meta('validation_progress',{'running':False,'started':started,'finished':time.time(),'error':message})
            finally:VALIDATION_LOCK.release()
        threading.Thread(target=run,name='northstar-validation',daemon=True).start()
        return {'queued':True}
    except Exception:
        VALIDATION_LOCK.release()
        raise


def set_promoted_experiment_model(data):
    """Save only a model present in the most recent robustness experiment."""
    if not isinstance(data,dict) or 'max_positions' not in data:
        raise ValueError('Choose an available experimental model.')
    count=data.get('max_positions')
    if count is None:
        write_meta('promoted_experiment_model',None)
    else:
        report=read_meta('validation_report',{}) or {}
        variants=((report.get('robustness') or {}).get('variants') or [])
        if (isinstance(count,bool) or not isinstance(count,int) or count not in (10,20)
                or not any(v.get('max_positions')==count for v in variants)):
            raise ValueError('That model is not available in the latest completed experiment. Run it again and review the results.')
        write_meta('promoted_experiment_model',{
            'label':str(count)+'-position recommendation cap','max_positions':count,
            'validation_generated':report.get('generated'),
            'promoted_at':time.time()})
    if WORKER:
        WORKER.trigger()
    return {'promoted_model':read_meta('promoted_experiment_model')}


def ledger_view():
    snapshot=state();profile=snapshot['manual_portfolio_preferences'];baseline=read_meta('ledger_state')
    with connect() as db:
        transactions.schema(db)
        rows=[json.loads(r['payload']) for r in db.execute('SELECT payload FROM ledger_events ORDER BY date DESC,uid DESC LIMIT 200')]
        count=db.execute('SELECT COUNT(*) FROM ledger_events').fetchone()[0]
    reconciled=bool(baseline and snapshot['ledger_reconciled'])
    return {'initialized':bool(baseline),'reconciled':reconciled,'baseline':baseline,'cash_nok':profile['cash_nok'],
            'events':rows,'count':count,'broker_cash_check':read_meta('broker_cash_check'), 'holdings_import':read_meta('holdings_import_status'), 'method':'Net broker cash includes actual fees; the 79 NOK estimate is not charged again. '
            'Transactions on or before the opening snapshot date are history only. Later new events update shares, weighted-average cost and cash. '
            'Same-day buys are booked before sales for weighted-average bookkeeping; this is not FIFO tax accounting. '
            'After a holdings CSV import or manual financial edit, reconcile by verifying holdings/cash and initializing a new snapshot.'}


def ledger_initialize(data):
    cutoff=transactions.date(data.get('date',''))
    import datetime as dt
    if cutoff>dt.datetime.now(dt.timezone.utc).date().isoformat():raise ValueError('Opening snapshot cannot be future dated.')
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        positions=[dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')]
        transactions.schema(db)
        latest=db.execute('SELECT MAX(date) FROM ledger_events').fetchone()[0]
        if latest and cutoff<latest:raise ValueError('A new opening snapshot must include all already-imported event dates.')
        row=db.execute("SELECT payload FROM metadata WHERE key='portfolio_preferences'").fetchone()
        profile=portfolio_fit.preferences(json.loads(row['payload']) if row else {})
        baseline={'cutoff_date':cutoff,'created':time.time(),'opening_cash_nok':profile['cash_nok'],
                  'fingerprint':transactions.fingerprint(positions,profile['cash_nok']),
                  'opening_positions':[{k:p[k] for k in ('symbol','currency','shares','cost')} for p in positions]}
        cursor=db.execute('INSERT INTO account_baselines(created,cutoff_date,payload) VALUES (?,?,?)',(baseline['created'],cutoff,json.dumps(baseline,allow_nan=False)))
        baseline['baseline_id']=cursor.lastrowid
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('ledger_state',json.dumps(baseline)))
        db.execute("DELETE FROM metadata WHERE key='pending_ledger_import'")
        db.execute("DELETE FROM metadata WHERE key='broker_cash_check'")
    return {'initialized':True}


def ledger_inspect(data):
    try:raw=base64.b64decode(data.get('file_b64',''),validate=True)
    except (ValueError,binascii.Error,TypeError):raise ValueError('Choose a valid transaction CSV.')
    parsed=transactions.table(raw);token=secrets.token_urlsafe(24)
    saved=read_meta('ledger_column_mapping',{})
    mapping={k:(saved[k] if saved.get(k) in parsed['columns'] else v) for k,v in parsed['mapping'].items()}
    write_meta('pending_ledger_table',{'token':token,'expires':time.time()+900,'parsed':parsed})
    return {'token':token,'columns':parsed['columns'],'mapping':mapping,'fields':transactions.FIELDS,'rows':len(parsed['rows'])}


def ledger_preview(data):
    pending=read_meta('pending_ledger_table',{})
    if pending.get('token')!=data.get('token') or pending.get('expires',0)<time.time():raise ValueError('Upload the transaction export again; this preview expired.')
    snapshot=state();mapping=data.get('mapping');scope=data.get('scope','default')
    items=transactions.events(pending['parsed'],mapping,scope,read_meta('holdings_import_aliases',{}),holdings_import.catalogue(snapshot['quotes'],read_meta('report')))
    with connect() as db:
        transactions.schema(db)
        known={r['uid'] for r in db.execute('SELECT uid FROM ledger_events')}
    for r in items:r['duplicate']=r.get('uid') in known
    token=secrets.token_urlsafe(24)
    write_meta('pending_ledger_import',{'token':token,'expires':time.time()+900,'items':items,'mapping':mapping,
               'fingerprint':transactions.fingerprint(snapshot['positions'],snapshot['manual_portfolio_preferences']['cash_nok'])})
    return {'token':token,'rows':items,'baseline':read_meta('ledger_state'),
            'method':'Review signed NET cash amounts: buys negative, sales/dividends positive. Do not subtract fees again. '
                     'Confirm ticker matches. Existing transaction IDs are skipped. Without broker IDs, identical events are identified by economic fields and occurrence within the file; ambiguous overlapping exports require review.'}


def ledger_apply(data):
    with connect() as db:
        db.execute('BEGIN IMMEDIATE')
        def meta(key,default=None):
            row=db.execute('SELECT payload FROM metadata WHERE key=?',(key,)).fetchone()
            return json.loads(row['payload']) if row else default
        pending=meta('pending_ledger_import',{})
        if pending.get('token')!=data.get('token') or pending.get('expires',0)<time.time():raise ValueError('Transaction preview expired or was replaced. Upload again.')
        profile=portfolio_fit.preferences(meta('portfolio_preferences',{}))
        positions=[dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')]
        if pending['fingerprint']!=transactions.fingerprint(positions,profile['cash_nok']):raise ValueError('Holdings or cash changed after preview. Preview again.')
        result=transactions.apply(db,pending['items'],data.get('selections'),meta('ledger_state'),profile,positions)
        last=meta('last_trades',{})
        for s,t in result['last_trades'].items():last[s]=max(t,last.get(s,0))
        for key,value in [('portfolio_preferences',result['profile']),('ledger_state',result['ledger']),('last_trades',last),('ledger_column_mapping',pending['mapping'])]:
            db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',(key,json.dumps(value,allow_nan=False)))
        db.execute("DELETE FROM metadata WHERE key='pending_ledger_import'")
        db.execute("DELETE FROM metadata WHERE key='pending_ledger_table'")
    if WORKER:WORKER.trigger()
    return {'imported':result['imported'],'duplicates':result['duplicates']}


def broker_cash_check(data):
    reported=portfolio_fit.number(data.get('cash_nok'),'Broker cash',1e9)
    tracked=state()['manual_portfolio_preferences']['cash_nok']
    result={'checked':time.time(),'reported_cash':reported,'tracked_cash':tracked,'difference':reported-tracked,
            'mismatch_active':abs(reported-tracked)>.01}
    write_meta('broker_cash_check',result)
    return result


def daily_view():
    snapshot=state(True);report=read_meta('report');plan=trade_plan.build(snapshot,report,snapshot['portfolio_preferences'])
    result=daily_board.build(snapshot,report,plan,read_meta('announcements_feed'),ledger_view())
    result['buy_candidates']=plan['buys'][:5]
    result['buy_candidates_stale']=not decision_policy.current_report(report,time.time())
    result['buy_candidate_warnings']=[
        row['symbol']+': '+row['reason'] for row in plan['blocked_buys'] if row['evidence_missing']
    ]
    result['buy_candidate_research_incomplete']=bool((report or {}).get('coverage', {}).get('unavailable'))
    alerts=daily_board.merge_alerts(read_meta('dashboard_alerts',[]),result['reviews'])
    write_meta('dashboard_alerts',alerts);result['alerts']=alerts
    result['email']=email_worker().status()
    return result


def email_plan():
    now=time.time()
    snapshot=state(True)
    report=read_meta('report')
    plan=trade_plan.build(snapshot,report,snapshot['portfolio_preferences'])
    alerts=daily_board.build(snapshot,report,plan,read_meta('announcements_feed'),ledger_view(),now)['reviews']
    risk=portfolio_risk.view(snapshot,snapshot['portfolio_preferences'],now)
    quote_times=[q.get('asof') for p in snapshot['positions'] if p['shares']>0
                 for q in [trade_plan.quote_for(snapshot,portfolio_fit.canonical(p['symbol'],p['currency']))]
                 if q and isinstance(q.get('asof'),(int,float))]
    if any(p['shares']>0 and p['currency']=='USD' for p in snapshot['positions']):
        fx=snapshot['quotes'].get('NOK=X')
        if fx and isinstance(fx.get('asof'),(int,float)):
            quote_times.append(fx['asof'])
    risk_source=min(quote_times) if quote_times else None
    for warning in risk.get('risk_warnings',[]):
        label=warning['label']
        if label not in ('Historical 95% daily VaR','Historical 95% tail loss','Historical proxy drawdown') and ' long-term holding · ' not in label:
            continue
        identity=hashlib.sha256(('risk:'+label).encode()).hexdigest()[:24]
        long_term=' long-term holding · ' in label
        alerts.append({'id':identity,'priority':95 if long_term else 85,'title':'Review portfolio risk: '+label,
                       'detail':('Long-term designation does not remove this significant risk from review. ' if long_term else '')+
                                'Observed or hypothetical loss of '+str(round(warning['loss_pct'],1))+
                                '% meets your '+str(risk['risk_warning_pct'])+'% warning level. Historical measures describe past data; scenario losses are hypothetical. This is not a guaranteed loss limit or a trade instruction.',
                       'kind':'risk','symbol':None,
                       'loss_pct':warning['loss_pct'],'warning_pct':risk['risk_warning_pct'],
                       'url':email_alerts.dashboard_url(workspace='portfolio'),
                       'source_asof':risk_source,'observed':now})
    long_term_symbols=[portfolio_fit.canonical(p['symbol'],p['currency']) for p in snapshot['positions']
                       if p['shares']>0 and p.get('long_term',False)]
    oslo=ZoneInfo('Europe/Oslo')
    def oslo_date(timestamp):
        if (isinstance(timestamp,(int,float)) and not isinstance(timestamp,bool)
                and math.isfinite(timestamp) and 0<=timestamp<=now+300):
            return datetime.fromtimestamp(timestamp,timezone.utc).astimezone(oslo).date().isoformat()
        return None
    today=oslo_date(now)
    close_dates=[oslo_date(point.get('time')) for symbol,q in snapshot['quotes'].items()
                 if symbol!='NOK=X' for point in q.get('history',[])
                 if isinstance(point.get('close'),(int,float)) and not isinstance(point['close'],bool)
                 and math.isfinite(point['close']) and point['close']>0]
    # Today's daily provider bar can still be trading. Use an earlier dated bar.
    last_close_date=max((date for date in close_dates if date and date<today),default=None)
    stale=[]
    for position in snapshot['positions']:
        if position['shares']<=0:continue
        symbol=portfolio_fit.canonical(position['symbol'],position['currency'])
        quote=trade_plan.quote_for(snapshot,symbol)
        if not quote:stale.append(symbol+': quote missing')
        elif not portfolio_fit.fresh(quote,now):stale.append(symbol+': quote stale')
        if position['currency']=='USD':
            fx=snapshot['quotes'].get('NOK=X')
            if not fx:stale.append('NOK/USD conversion quote missing')
            elif not portfolio_fit.fresh(fx,now):stale.append('NOK/USD conversion quote stale')
    report_ok=decision_policy.current_report(report,now)
    if not report_ok:
        stale.append('Research report: stale or missing')
    coverage=(report or {}).get('coverage',{})
    if coverage.get('unavailable'):
        stale.append(str(coverage['unavailable'])+' research entries have missing or inadequate data')
    holdings_attention=[]
    for holding in plan.get('holdings',[]):
        if holding.get('sell_shares') or holding.get('technical_action') in trade_plan.SELL_SIGNALS:
            reasons=' '.join(holding.get('reasons',[]))
            detail=(holding['symbol']+' — review '+str(holding.get('technical_action') or 'holding risk')+
                    (('; '+str(holding['sell_shares'])+' shares in the current review scenario') if holding.get('sell_shares') else '')+
                    ('. '+reasons if reasons else '.'))
            holdings_attention.append((90,detail[:700]))
    held_symbols={portfolio_fit.canonical(p['symbol'],p['currency']) for p in snapshot['positions'] if p['shares']>0}
    for alert in alerts:
        if alert.get('kind') not in ('announcement','company') or alert.get('symbol') not in held_symbols:
            continue
        source_asof=alert.get('source_asof')
        source_date=oslo_date(source_asof)
        detail=str(alert.get('title','Holding review'))+'. '+str(alert.get('detail',''))
        if source_date:
            detail+=' Source date: '+source_date+'.'
        else:
            detail+=' Source date unavailable.'
            stale.append(str(alert['symbol'])+': review source date missing')
        if isinstance(source_asof,(int,float)) and now-source_asof>7*86400:
            stale.append(str(alert['symbol'])+': review source is stale')
        source_url=alert.get('url')
        if (isinstance(source_url,str) and len(source_url)<=2000 and source_url.startswith('https://')
                and not any(c in source_url for c in '\r\n\x00')):
            detail+=' Source: '+source_url
        priority=alert.get('priority',80)
        if not isinstance(priority,(int,float)) or isinstance(priority,bool) or not math.isfinite(priority):
            priority=80
        holdings_attention.append((priority,detail[:700]))
    holdings_attention=[detail for _,detail in sorted(holdings_attention,key=lambda item:-item[0])[:5]]
    candidates=[]
    if report_ok:
        for card in decision_policy.recommendations((report or {}).get('cards',[]),(report or {}).get('promoted_model')):
            if card.get('held'):continue
            if not trade_plan.signal_current(card,now):
                stale.append(str(card['symbol'])+': candidate quote stale or missing; candidate withheld')
                continue
            quote_date=oslo_date(card.get('asof'))
            reasons=' '.join(card.get('reasons',[])[:2]) or 'Passes the shared technical entry screen.'
            candidates.append(str(card['symbol'])+' — '+quote_date+' quote reference. '+reasons[:500])
    candidates=candidates[:5]
    warnings=risk.get('risk_warnings',[])
    measures=[]
    for label,key in (('annualized historical volatility','volatility_pct'),('daily 95% VaR','var95_pct')):
        value=risk.get(key)
        if isinstance(value,(int,float)) and not isinstance(value,bool) and math.isfinite(value):
            measures.append(label+' '+str(round(value,1))+'%')
    if warnings:
        warning_text='; '.join(str(w['label'])+' '+str(round(w['loss_pct'],1))+'% loss' for w in warnings[:3])
        risk_text=(('Historical risk: '+', '.join(measures)+'. ' if measures else 'Historical risk available. ')
                   if risk.get('status')=='available' else 'Historical risk unavailable; valuation scenarios show: ')+warning_text
    elif risk.get('status')=='available':
        risk_text=(('Historical risk: '+', '.join(measures)+'. ' if measures else 'Historical risk is available. ')+
                   'No calculated warnings at the '+str(risk.get('risk_warning_pct',20))+'% warning level.')
    elif risk.get('status')=='cash_only':
        risk_text='Cash only; no invested portfolio risk is currently calculated.'
    else:
        risk_text='Historical risk unavailable'+(': '+', '.join(risk.get('missing',[])[:3]) if risk.get('missing') else '.')
    summary={'last_close_date':last_close_date,'holdings_attention':holdings_attention[:5],
             'candidates':candidates,'risk':risk_text,
             'data_status':('Stale or missing: '+ '; '.join(stale[:6])+'.' if stale else
                            'No stale or missing tracked quote data.')}
    return {**(report or {}),'review_alerts':alerts,'long_term_symbols':long_term_symbols,
            'risk_review_complete':risk.get('status') in ('available','cash_only'),
            'weekly_summary':summary},plan


def email_worker():
    return EMAIL_WORKER or email_alerts.Worker(connect,read_meta,write_meta,email_plan)


def operational_view():
    snapshot=state(True)
    worker=WORKER.view().get('worker',{}) if WORKER else {}
    email=email_worker()
    return system_status.build(snapshot,read_meta('report'),worker,read_meta('refresh_progress',{}),
        read_meta('fundamentals_progress',{}),read_meta('announcements_feed',{}),read_meta('announcements_progress',{}),
        {t.name for t in threading.enumerate() if t.is_alive()},email.status(),email.history(),STARTED_AT)


def archive_run(report,snapshot,config):
    with connect() as db:
        identifier=research_archive.capture_run(db,report,snapshot,config,research_archive.analysis_fingerprint(ROOT))
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)',('archive_status',json.dumps({'last_success':time.time(),'run_id':identifier})))
    return identifier


def account_view(allow_prior_close=False):
    with connect() as db:
        transactions.schema(db)
        db.execute('BEGIN')
        positions = [dict(row) for row in db.execute('SELECT * FROM positions ORDER BY symbol')]
        quotes = {row['symbol']: json.loads(row['payload']) for row in db.execute('SELECT * FROM quotes')}
        metadata = {row['key']: json.loads(row['payload']) for row in db.execute(
            "SELECT * FROM metadata WHERE key IN ('portfolio_preferences', 'ledger_state', 'broker_cash_check')")}
        events = [json.loads(row['payload']) for row in db.execute('SELECT payload FROM ledger_events ORDER BY date,uid')]
    profile = portfolio_fit.preferences(metadata.get('portfolio_preferences', {}))
    baseline = metadata.get('ledger_state')
    reconciled = ledger_reconciliation(positions, profile, baseline, metadata.get('broker_cash_check', {}))
    snapshot = {'positions': positions, 'quotes': quotes, 'manual_portfolio_preferences': profile,
                'ledger_reconciled': reconciled}
    return account_performance.view(snapshot, baseline, events, allow_prior_close=allow_prior_close)


class Handler(BaseHTTPRequestHandler):
    def cors_headers(self):
        origin = self.headers.get('Origin')
        if origin and request_origin_allowed(origin, self.headers.get('Host', '')):
            self.send_header('Access-Control-Allow-Origin', origin)
            self.send_header('Vary', 'Origin')

    def send_json(self, value, status=200):
        payload = json.dumps(value, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Cache-Control', 'no-store')
        self.cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def do_GET(self):
        if self.path == '/api/health':
            return self.send_json({'ok': True})
        if self.path.startswith('/api/') and not api_authorized(self.headers.get('Authorization')):
            return self.send_json({'error': 'Sign in with your Northstar access key.'}, 401)
        if self.path == '/api/release':return self.send_json({'source_fingerprint':SOURCE_FINGERPRINT,'started':STARTED_AT,'public_origin':os.environ.get('NORTHSTAR_PUBLIC_ORIGIN')})
        if urlsplit(self.path).path == '/api/account-performance':
            return self.send_json(account_view(parse_qs(urlsplit(self.path).query).get('allow_prior_close',['0'])[0]=='1'))
        if urlsplit(self.path).path == '/api/archive':
            try:
                raw=parse_qs(urlsplit(self.path).query).get('before',[None])[0]
                before=float(raw) if raw is not None else None
                if before is not None and not math.isfinite(before):raise ValueError('Finite capture cutoff required.')
                with connect() as db:result=research_archive.stats(db,before)
                return self.send_json({**result,'last_scan':read_meta('archive_status'), 'error':(read_meta('report',{}) or {}).get('archive_error')})
            except ValueError as error:return self.send_json({'error':str(error)},400)
        if urlsplit(self.path).path == '/api/archive/replay':
            try:
                identifier=int(parse_qs(urlsplit(self.path).query).get('id',['0'])[0])
                with connect() as db:result=research_archive.replay(db,identifier,ROOT)
                return self.send_json(result)
            except (ValueError,KeyError) as error:return self.send_json({'error':str(error)},400)
        if self.path == '/api/system-status':return self.send_json(operational_view())
        if self.path == '/api/email/history':return self.send_json({'items':email_worker().history()})
        if urlsplit(self.path).path in ('/api/portfolio-risk','/api/stock-summary'):
            try:
                query=parse_qs(urlsplit(self.path).query);snapshot=state(True);profile=snapshot['portfolio_preferences']
                if urlsplit(self.path).path=='/api/stock-summary':
                    return self.send_json(stock_summary.build(query.get('symbol',[''])[0],snapshot,read_meta('report'),profile))
                stock=float(query.get('stock_shock',[-20])[0]);fx=float(query.get('fx_shock',[-10])[0])
                return self.send_json(portfolio_risk.view(snapshot,profile,stock_shock=stock,fx_shock=fx))
            except (ValueError,TypeError):return self.send_json({'error':'Choose a valid Oslo symbol or finite shocks between -100% and +100%.'},400)
        if urlsplit(self.path).path == '/api/announcements':
            try:
                query=parse_qs(urlsplit(self.path).query)
                return self.send_json(announcement_view(query.get('symbol',[None])[0],query.get('scope',['focus'])[0]))
            except ValueError as error:
                return self.send_json({'error':str(error)},400)
        if urlsplit(self.path).path == '/api/fundamentals':
            try:
                symbol = parse_qs(urlsplit(self.path).query).get('symbol',[''])[0]
                return self.send_json(financial_view(symbol))
            except ValueError as error:
                return self.send_json({'error': str(error)}, 400)
        if urlsplit(self.path).path == '/api/history':
            symbol = parse_qs(urlsplit(self.path).query).get('symbol',[''])[0]
            if not re.fullmatch(r'[A-Z0-9^][A-Z0-9.\-^]{0,19}',symbol):
                return self.send_json({'error':'Invalid symbol.'},400)
            with connect() as db:
                row=db.execute('SELECT payload FROM quotes WHERE symbol=?',(symbol,)).fetchone()
            if not row:
                return self.send_json({'error':'History is not downloaded yet. Wait for the scan to finish.'},404)
            return self.send_json(json.loads(row['payload']))
        if self.path == '/api/daily':return self.send_json(daily_view())
        if self.path == '/api/email':return self.send_json(email_worker().status())
        if self.path == '/api/ledger':return self.send_json(ledger_view())
        if self.path == '/api/trade-plan':
            snapshot=state()
            return self.send_json(trade_plan.build(snapshot,read_meta('report'),snapshot['portfolio_preferences']))
        if self.path == '/api/portfolio-fit':
            snapshot=state()
            report=read_meta('report')
            profile=snapshot['portfolio_preferences']
            now=time.time()
            result=portfolio_fit.view(snapshot,report,profile,now)
            result['trade_plan']=trade_plan.build(snapshot,report,profile,now)
            return self.send_json(result)
        if self.path == '/api/validation':
            with connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS paper_snapshots (generated REAL PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)')
                paper = validation.paper_view(db, state()['quotes'])
            progress=read_meta('validation_progress',{})
            if progress.get('running') and not VALIDATION_LOCK.locked():progress={**progress,'running':False,'error':'Experiment interrupted by a server restart. Run it again.'}
            return self.send_json({'historical':read_meta('validation_report'), 'paper':paper,'progress':progress,
                                   'promoted_model':read_meta('promoted_experiment_model')})
        if self.path == '/api/research':
            return self.send_json(WORKER.view() if WORKER else {'report': read_meta('report'), 'settings': settings(), 'worker': {}})
        if self.path == '/api/state':
            snapshot=state()
            wanted={p['symbol'] for p in snapshot['positions']}|{'NOK=X'}
            snapshot['quotes']={s:{k:v for k,v in q.items() if k!='history'} for s,q in snapshot['quotes'].items() if s in wanted}
            return self.send_json(snapshot)
        mime={'.js':'text/javascript','.css':'text/css','.svg':'image/svg+xml','.json':'application/json','.html':'text/html'}
        files={'/'+name:(name,mime[Path(name).suffix]) for name in ui_assets.public_files()}
        files.update({'/':('index.html','text/html'),'/recommendations':('index.html','text/html'),'/favicon.ico':('favicon.svg','image/svg+xml')})
        asset_path=urlsplit(self.path).path
        if asset_path not in files:
            return self.send_error(404)
        name, mime = files[asset_path]
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
        self.send_header('Cache-Control','no-cache')
        self.end_headers()
        self.wfile.write((ROOT / 'static' / name).read_bytes())

    def do_OPTIONS(self):
        origin = self.headers.get('Origin')
        if not origin or not request_origin_allowed(origin, self.headers.get('Host', '')):
            return self.send_json({'error': 'Origin rejected.'}, 403)
        self.send_response(204)
        self.cors_headers()
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.send_header('Access-Control-Max-Age', '600')
        self.end_headers()

    def do_POST(self):
        # Reject browser cross-origin writes to this local service.
        origin = self.headers.get('Origin')
        if not request_origin_allowed(origin, self.headers.get('Host', '')):
            return self.send_json({'error': 'Cross-origin request rejected.'}, 403)
        authorization = self.headers.get('Authorization')
        if self.path == '/api/session/remember':
            expected = os.environ.get('NORTHSTAR_ACCESS_KEY_HASH')
            if not expected or not hmac.compare_digest(bearer_digest(authorization), expected):
                return self.send_json({'error': 'Enter your Northstar access key to remember this browser.'}, 401)
        elif not api_authorized(authorization):
            return self.send_json({'error': 'Sign in with your Northstar access key.'}, 401)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json({'error': 'JSON required.'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= (400000 if self.path in ('/api/import/preview','/api/import/apply','/api/ledger/inspect','/api/ledger/preview','/api/ledger/apply') else 50000):
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('JSON object required.')
            if self.path == '/api/session/remember':
                token = 'ns-session-' + secrets.token_urlsafe(32)
                with connect() as db:
                    db.execute('INSERT INTO remembered_sessions VALUES (?,?)',
                               (bearer_digest('Bearer ' + token), expected))
                return self.send_json({'token': token})
            if self.path == '/api/session/sign-out':
                with connect() as db:
                    db.execute('DELETE FROM remembered_sessions WHERE digest=?', (bearer_digest(authorization),))
                return self.send_json({'ok': True})
            if self.path == '/api/email/settings':
                return self.send_json(email_worker().set_enabled(data.get('enabled')))
            elif self.path == '/api/email/test':
                if not EMAIL_WORKER:
                    return self.send_json({'error':'Email worker is not started.'},503)
                return self.send_json(EMAIL_WORKER.queue_test())
            elif self.path == '/api/ledger/reconcile':return self.send_json(broker_cash_check(data))
            elif self.path == '/api/ledger/initialize':return self.send_json(ledger_initialize(data))
            elif self.path == '/api/ledger/inspect':return self.send_json(ledger_inspect(data))
            elif self.path == '/api/ledger/preview':return self.send_json(ledger_preview(data))
            elif self.path == '/api/ledger/apply':return self.send_json(ledger_apply(data))
            elif self.path == '/api/alerts/read':
                ids=data.get('ids',[])
                if not isinstance(ids,list):raise ValueError('Alert IDs must be a list.')
                rows=read_meta('dashboard_alerts',[])
                for r in rows:
                    if r['id'] in ids:r['read']=True
                write_meta('dashboard_alerts',rows)
                return self.send_json({'saved':True})
            elif self.path == '/api/import/preview':
                return self.send_json(import_preview(data))
            elif self.path == '/api/import/apply':
                return self.send_json(apply_import(data))
            elif self.path == '/api/position':
                save_position(data)
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/delete':
                with connect() as db:
                    db.execute('DELETE FROM positions WHERE symbol=?', (data['symbol'],))
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/refresh':
                return self.send_json({'errors': refresh()})
            elif self.path == '/api/portfolio-fit':
                profile=portfolio_fit.preferences(data)
                write_meta('portfolio_preferences',profile)
                if WORKER:
                    WORKER.trigger()
                return self.send_json({'saved':True})
            elif self.path == '/api/portfolio-fit/preview':
                snapshot=state()
                return self.send_json(portfolio_fit.preview(data.get('symbol',''),data.get('amount',0),snapshot,snapshot['portfolio_preferences']))
            elif self.path == '/api/validation':
                return self.send_json(start_validation(data))
            elif self.path == '/api/validation/promotion':
                return self.send_json(set_promoted_experiment_model(data))
            elif self.path == '/api/analyze':
                if not WORKER:
                    return self.send_json({'error': 'Background worker is not started.'}, 503)
                WORKER.trigger()
                return self.send_json({'queued': True})
            elif self.path == '/api/fundamentals':
                symbol = fundamentals.canonical(data.get('symbol', ''))
                if not FUNDAMENTALS_WORKER:
                    return self.send_json({'error': 'Financial scan worker is not started.'}, 503)
                cached = read_meta('fundamentals:' + symbol, {})
                if time.time() - cached.get('attempted', 0) < 60:
                    return self.send_json({'queued': False, 'message': 'Financial figures were checked within the last minute.'})
                FUNDAMENTALS_WORKER.request(symbol)
                return self.send_json({'queued': True})
            elif self.path == '/api/announcements/refresh':
                if not ANNOUNCEMENTS_WORKER:
                    return self.send_json({'error':'Announcement worker is not started.'},503)
                record=read_meta('announcements_feed',{})
                if time.time()-record.get('attempted',0)<300:
                    return self.send_json({'queued':False,'message':'The announcement feed was checked within the last five minutes.'})
                ANNOUNCEMENTS_WORKER.trigger()
                return self.send_json({'queued':True})
            elif self.path == '/api/announcements/reviewed':
                write_meta('announcements_reviewed_at',time.time())
            elif self.path == '/api/settings':
                save_settings(data)
                if WORKER:
                    WORKER.trigger()
            elif self.path == '/api/ask':
                config = settings()
                if not config['llm_enabled']:
                    return self.send_json({'error': 'Enable local AI in Research settings first.'}, 400)
                question = str(data.get('question', '')).strip()
                if not 1 <= len(question) <= 2000:
                    raise ValueError('Enter a question of 1–2000 characters.')
                if not MODEL_LOCK.acquire(blocking=False):
                    return self.send_json({'error': 'A question is already being answered. Please wait.'}, 429)
                try:
                    report = research.build_report(state(True), config['universe'], config['min_turnover_nok'])
                    answer = research.local_answer(config['model'], report, question)
                    return self.send_json({'answer': answer, 'model': config['model'], 'generated': time.time()})
                except research.ModelBusy as error:
                    return self.send_json({'error': research.llm_error(error, config['model'])}, 429)
                except Exception as error:
                    return self.send_json({'error': research.llm_error(error, config['model'])}, 503)
                finally:
                    MODEL_LOCK.release()
            else:
                return self.send_error(404)
            self.send_json({'ok': True})
        except (ValueError, TypeError, KeyError) as error:
            self.send_json({'error': str(error)}, 400)

def report_ready():
    report = read_meta('report')
    if report:
        with connect() as db:
            validation.capture(db,report)
    if ANNOUNCEMENTS_WORKER:
        ANNOUNCEMENTS_WORKER.trigger()
    if EMAIL_WORKER:
        EMAIL_WORKER.wake.set()

if __name__ == '__main__':
    if sys.argv[1:] == ['revoke-remembered-sessions']:
        revoke_remembered_sessions()
        print('Revoked all remembered browser sessions.')
        sys.exit(0)
    connect().close()
    ANNOUNCEMENTS_WORKER = announcements.Worker(read_meta,write_meta,announcement_focus)
    COMPANY_WORKER=company_data.Worker(read_meta,write_meta,financial_symbols)
    WORKER = research_worker.ResearchWorker(refresh, lambda: state(True), read_meta, write_meta, settings, report_ready, archive_run)
    EMAIL_WORKER = email_alerts.Worker(connect,read_meta,write_meta,email_plan)
    FUNDAMENTALS_WORKER = fundamentals.Worker(read_meta, write_meta, financial_symbols)
    # Bind first so a second process cannot start a competing background worker.
    server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
    EMAIL_WORKER.start()
    COMPANY_WORKER.start()
    WORKER.start()
    FUNDAMENTALS_WORKER.start()
    ANNOUNCEMENTS_WORKER.start()
    print('Open http://127.0.0.1:8000 — press Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        EMAIL_WORKER.stop.set()
        EMAIL_WORKER.wake.set()
        COMPANY_WORKER.stop.set()
        COMPANY_WORKER.wake.set()
        WORKER.stop.set()
        WORKER.wake.set()
        FUNDAMENTALS_WORKER.stop.set()
        FUNDAMENTALS_WORKER.wake.set()
        ANNOUNCEMENTS_WORKER.stop.set()
        ANNOUNCEMENTS_WORKER.wake.set()
    finally:
        server.server_close()
