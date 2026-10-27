"""Local investment research notebook. Run: python3 app.py"""
import json
import math
import re
import sqlite3
import time
import threading
import os
import hashlib
import hmac
import base64
import binascii
import secrets
import research
import fundamentals
import announcements
import validation
import portfolio_fit
import holdings_import
import trade_plan
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import Request, urlopen
from urllib.parse import quote, urlsplit, parse_qs
from urllib.error import HTTPError, URLError
from concurrent.futures import ThreadPoolExecutor

ROOT = Path(__file__).parent
DB = ROOT / 'data' / 'portfolio.db'
REFRESH_LOCK = threading.Lock()
WORKER = None
FUNDAMENTALS_WORKER = None
ANNOUNCEMENTS_WORKER = None
MODEL_LOCK = threading.Lock()

def request_origin_allowed(origin, host):
    allowed = os.environ.get('NORTHSTAR_PUBLIC_ORIGIN') or 'http://' + host
    pages = os.environ.get('NORTHSTAR_PAGES_ORIGIN')
    return not origin or origin == allowed or bool(pages and origin == pages)

def api_authorized(authorization):
    expected = os.environ.get('NORTHSTAR_ACCESS_KEY_HASH')
    if not expected:
        return not os.environ.get('NORTHSTAR_PAGES_ORIGIN')
    if not authorization or not authorization.startswith('Bearer '):
        return False
    digest = hashlib.sha256(authorization[7:].encode()).hexdigest()
    return hmac.compare_digest(digest, expected)

def connect():
    DB.parent.mkdir(exist_ok=True)
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    db.execute('CREATE TABLE IF NOT EXISTS positions (symbol TEXT PRIMARY KEY, currency TEXT, shares REAL, cost REAL, thesis TEXT, review TEXT, below REAL, above REAL)')
    db.execute('CREATE TABLE IF NOT EXISTS quotes (symbol TEXT PRIMARY KEY, payload TEXT)')
    db.execute('CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, payload TEXT)')
    return db

def read_meta(key, default=None):
    with connect() as db:
        row = db.execute('SELECT payload FROM metadata WHERE key=?', (key,)).fetchone()
    return json.loads(row['payload']) if row else default

def write_meta(key, value):
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO metadata VALUES (?,?)', (key, json.dumps(value, allow_nan=False)))

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
    values = (symbol, currency, positive(data.get('shares')), positive(data.get('cost')),
              str(data.get('thesis', ''))[:5000], str(data.get('review', ''))[:5000],
              positive(data.get('below'), True), positive(data.get('above'), True))
    with connect() as db:
        db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?)', values)

def fetch_quote(symbol):
    # Unofficial public endpoint: errors are surfaced, never replaced with sample prices.
    url = 'https://query1.finance.yahoo.com/v8/finance/chart/' + quote(symbol, safe='') + '?range=2y&interval=1d'
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
    return {'price': price, 'currency': meta['currency'], 'asof': meta['regularMarketTime'],
            'fetched': time.time(), 'source': 'Yahoo Finance (unofficial)',
            'history': history, 'history_basis': 'Dividend/split adjusted close' if adjusted else 'Provider daily close',
            'history_version':2,
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
            if extra_symbols is not None and old and old.get('history_version')==2 and time.time()-old.get('fetched',0)<1200:
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
    canonical = fundamentals.canonical(symbol)
    record = read_meta('fundamentals:' + canonical)
    with connect() as db:
        row = db.execute('SELECT payload FROM quotes WHERE symbol IN (?,?) ORDER BY symbol DESC LIMIT 1', (canonical, symbol)).fetchone()
    return {**fundamentals.analyse(record, json.loads(row['payload']) if row else None), 'symbol': canonical,
            'scan': read_meta('fundamentals_progress'), 'attempted': (record or {}).get('attempted')}

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

def state(include_fundamentals=False):
    with connect() as db:
        result = {'positions': [dict(r) for r in db.execute('SELECT * FROM positions ORDER BY symbol')],
                'quotes': {r['symbol']: json.loads(r['payload']) for r in db.execute('SELECT * FROM quotes')}}
        if include_fundamentals:
            result['fundamentals'] = {r['key'].split(':', 1)[1]: json.loads(r['payload']) for r in db.execute("SELECT key,payload FROM metadata WHERE key LIKE 'fundamentals:%'")}
            result['announcements']=read_meta('announcements_feed',{})
        result['portfolio_preferences']=portfolio_fit.preferences(read_meta('portfolio_preferences',{}))
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
        if self.path == '/api/trade-plan':
            snapshot=state()
            return self.send_json(trade_plan.build(snapshot,read_meta('report'),snapshot['portfolio_preferences']))
        if self.path == '/api/portfolio-fit':
            snapshot=state()
            return self.send_json(portfolio_fit.view(snapshot,read_meta('report'),snapshot['portfolio_preferences']))
        if self.path == '/api/validation':
            with connect() as db:
                db.execute('CREATE TABLE IF NOT EXISTS paper_snapshots (generated REAL PRIMARY KEY, captured REAL NOT NULL, payload TEXT NOT NULL)')
                paper = validation.paper_view(db, state()['quotes'])
            return self.send_json({'historical':read_meta('validation_report'), 'paper':paper})
        if self.path == '/api/research':
            return self.send_json(WORKER.view() if WORKER else {'report': read_meta('report'), 'settings': settings(), 'worker': {}})
        if self.path == '/api/state':
            snapshot=state()
            wanted={p['symbol'] for p in snapshot['positions']}|{'NOK=X'}
            snapshot['quotes']={s:{k:v for k,v in q.items() if k!='history'} for s,q in snapshot['quotes'].items() if s in wanted}
            return self.send_json(snapshot)
        files = {'/': ('index.html', 'text/html'), '/recommendations': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/style.css': ('style.css', 'text/css'), '/advice.js': ('advice.js', 'text/javascript'), '/charts.js': ('charts.js', 'text/javascript'), '/news.js': ('news.js', 'text/javascript'), '/validation.js': ('validation.js', 'text/javascript'), '/portfolio-fit.js': ('portfolio-fit.js', 'text/javascript'), '/holdings-import.js': ('holdings-import.js', 'text/javascript'), '/trade-plan.js': ('trade-plan.js', 'text/javascript'), '/config.js': ('config.js', 'text/javascript'), '/favicon.ico': ('favicon.svg', 'image/svg+xml')}
        if self.path not in files:
            return self.send_error(404)
        name, mime = files[self.path]
        self.send_response(200)
        self.send_header('Content-Type', mime + '; charset=utf-8')
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
        if not api_authorized(self.headers.get('Authorization')):
            return self.send_json({'error': 'Sign in with your Northstar access key.'}, 401)
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send_json({'error': 'JSON required.'}, 415)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= (400000 if self.path in ('/api/import/preview','/api/import/apply') else 50000):
                raise ValueError('Invalid request size.')
            data = json.loads(self.rfile.read(length))
            if not isinstance(data, dict):
                raise ValueError('JSON object required.')
            if self.path == '/api/import/preview':
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
                result = validation.evaluate(state()['quotes'], settings()['universe'], data.get('cost_bps',0), settings()['min_turnover_nok'], data.get('initial_capital',100000))
                write_meta('validation_report',result)
                return self.send_json(result)
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

if __name__ == '__main__':
    connect().close()
    ANNOUNCEMENTS_WORKER = announcements.Worker(read_meta,write_meta,announcement_focus)
    WORKER = research.ResearchWorker(refresh, lambda: state(True), read_meta, write_meta, settings, report_ready)
    FUNDAMENTALS_WORKER = fundamentals.Worker(read_meta, write_meta, financial_symbols)
    # Bind first so a second process cannot start a competing background worker.
    server = ThreadingHTTPServer(('127.0.0.1', 8000), Handler)
    WORKER.start()
    FUNDAMENTALS_WORKER.start()
    ANNOUNCEMENTS_WORKER.start()
    print('Open http://127.0.0.1:8000 — press Ctrl+C to stop', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        WORKER.stop.set()
        WORKER.wake.set()
        FUNDAMENTALS_WORKER.stop.set()
        FUNDAMENTALS_WORKER.wake.set()
        ANNOUNCEMENTS_WORKER.stop.set()
        ANNOUNCEMENTS_WORKER.wake.set()
    finally:
        server.server_close()
