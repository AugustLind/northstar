"""Reviewable broker transaction ledger. Net cash amounts already include broker fees."""
import csv
import datetime as dt
import hashlib
import io
import json
import math
import re
import holdings_import as hi

FIELDS=['date','type','name','symbol','quantity','net_cash','currency','trade_id','fee']
HEADERS={'date':['bokforingsdag','bokføringsdag','handelsdag','dato','date'],'type':['transaksjonstype','type','transaction type'],
         'name':['verdipapir','navn','name'],'symbol':['ticker','symbol'],'quantity':['antall','quantity'],
         'net_cash':['belop','beløp','netto','net cash','amount'],'currency':['valuta','currency'],
         'trade_id':['id','transaksjons id','transaction id','bilagsnummer'],'fee':['kurtasje','gebyr','fee']}
TYPES={'kjop':'buy','kjøp':'buy','buy':'buy','salg':'sell','sell':'sell','utbytte':'dividend','dividend':'dividend',
       'innskudd':'deposit','deposit':'deposit','uttak':'withdrawal','withdrawal':'withdrawal','rente':'interest',
       'interest':'interest','kurtasje':'fee','gebyr':'fee','fee':'fee','avgift':'fee'}


def schema(db):
    db.execute('CREATE TABLE IF NOT EXISTS ledger_events (uid TEXT PRIMARY KEY, date TEXT NOT NULL, payload TEXT NOT NULL)')


def table(raw):
    if not raw or len(raw)>hi.MAX_BYTES:raise ValueError('Choose a transaction export up to 256 KiB.')
    try:
        text=raw.decode('utf-16') if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else raw.decode('utf-8-sig')
    except UnicodeError:text=raw.decode('cp1252')
    if '\x00' in text:raise ValueError('Unsupported binary export.')
    try:
        dialect=csv.Sniffer().sniff(text[:10000],delimiters='\t;,')
        rows=[r for r in csv.reader(io.StringIO(text),dialect,strict=True) if any(v.strip() for v in r)]
    except csv.Error:raise ValueError('Cannot read transaction table.')
    if not 2<=len(rows)<=501:raise ValueError('Import 1–500 transaction rows at a time.')
    if len(set(rows[0]))!=len(rows[0]):raise ValueError('Transaction column names must be unique.')
    columns=rows[0]
    mapping={}
    for field,aliases in HEADERS.items():
        found=[c for c in columns if hi.name_key(c) in {hi.name_key(a) for a in aliases}]
        mapping[field]=found[0] if len(found)==1 else ''
    return {'columns':columns,'rows':rows[1:],'mapping':mapping}


def signed(value,label):
    text=''.join(str(value).split()).replace('\u2212','-')
    minus=text.startswith('-')
    return (-1 if minus else 1)*hi.amount(text[1:] if minus else text,label)


def date(value):
    value=str(value).strip()
    for fmt in ('%Y-%m-%d','%d.%m.%Y','%d/%m/%Y'):
        try:return dt.datetime.strptime(value,fmt).date().isoformat()
        except ValueError:pass
    raise ValueError('Date must be YYYY-MM-DD or DD.MM.YYYY.')


def events(parsed,mapping,scope,aliases=None,companies=None):
    if not isinstance(mapping,dict):raise ValueError('Choose the transaction columns.')
    for key in ('date','type','net_cash','currency'):
        if mapping.get(key) not in parsed['columns']:raise ValueError('Map the '+key+' column.')
    if not isinstance(scope,str) or not 1<=len(scope.strip())<=80:raise ValueError('Enter an account label (1–80 characters).')
    occurrences={};out=[]
    for index,row in enumerate(parsed['rows'],2):
        e={'id':index,'error':None,'symbol':'','name':'','quantity':0.,'fee':None}
        try:
            if len(row)!=len(parsed['columns']):raise ValueError('Column count differs from header.')
            def cell(key):
                col=mapping.get(key)
                return row[parsed['columns'].index(col)].strip() if col in parsed['columns'] else ''
            kind=TYPES.get(hi.name_key(cell('type')))
            if not kind:raise ValueError('Unsupported transaction type: map or exclude it; transfers/splits are not inferred.')
            e.update(date=date(cell('date')),type=kind,currency=cell('currency').upper(),net_cash=signed(cell('net_cash'),'Net cash'))
            if e['date']>dt.datetime.now(dt.timezone.utc).date().isoformat():raise ValueError('Future transactions cannot be imported.')
            if e['currency']!='NOK':raise ValueError('This ledger supports NOK transactions only.')
            if kind in ('buy','withdrawal','fee') and e['net_cash']>0:raise ValueError('This event needs a negative signed net cash amount.')
            if kind in ('sell','dividend','deposit') and e['net_cash']<0:raise ValueError('This event needs a positive signed net cash amount.')
            e['name']=cell('name')[:200]
            if kind in ('buy','sell'):
                e['quantity']=hi.amount(cell('quantity'),'Quantity')
                if e['quantity']<=0:raise ValueError('Trade quantity must be positive.')
                hint=hi.oslo_symbol(cell('symbol')) if cell('symbol') else None
                matched=hi.suggest([{'id':index,'name':e['name'],'currency':'NOK','shares':e['quantity'],'cost':0,'symbol_hint':hint,'error':None}],companies or [],aliases or {})[0]
                e['symbol']=matched['symbol']
            if cell('fee'):e['fee']=abs(signed(cell('fee'),'Reported fee'))
            identity={k:e[k] for k in ('date','type','quantity','net_cash','currency','name')}
            if cell('symbol'):identity['source_symbol']=cell('symbol').upper()
            broker_id=cell('trade_id')
            key=json.dumps(identity,sort_keys=True)
            occurrences[key]=occurrences.get(key,0)+1
            basis=broker_id if broker_id else key+'#'+str(occurrences[key])
            e['uid']=hashlib.sha256((scope.strip()+'|'+basis).encode()).hexdigest()
            e['broker_id_present']=bool(broker_id)
        except (ValueError,TypeError) as error:e['error']=str(error)
        out.append(e)
    return out


def fingerprint(positions,cash):
    values=sorted([{k:p[k] for k in ('symbol','currency','shares','cost')} for p in positions],key=lambda p:p['symbol'])
    return hashlib.sha256(json.dumps({'positions':values,'cash':cash},sort_keys=True,allow_nan=False).encode()).hexdigest()


def apply(db,items,selections,ledger,profile,positions):
    schema(db)
    if not ledger:raise ValueError('Initialize the ledger from a verified holdings and cash snapshot first.')
    if ledger['fingerprint']!=fingerprint(positions,profile['cash_nok']):raise ValueError('Cash or holdings changed outside the ledger. Reconcile or initialize a new verified snapshot first.')
    if not isinstance(selections,list) or not selections:raise ValueError('Select transaction rows to import.')
    selected=[];seen=set();seen_uids={};by_id={r['id']:r for r in items}
    for pick in selections:
        row=by_id.get(pick.get('id')) if isinstance(pick,dict) else None
        if not row or row['error'] or row['id'] in seen:raise ValueError('Invalid or duplicate selected transaction.')
        seen.add(row['id']);row=dict(row)
        if row['type'] in ('buy','sell'):row['symbol']=hi.oslo_symbol(pick.get('symbol') or row['symbol'])
        existing=db.execute('SELECT payload FROM ledger_events WHERE uid=?',(row['uid'],)).fetchone()
        if existing:
            old=json.loads(existing['payload'])
            if any(old.get(k)!=row.get(k) for k in ('date','type','quantity','net_cash','currency','symbol')):
                raise ValueError('A broker transaction ID conflicts with an imported event. Resolve the correction explicitly.')
            continue
        if row['uid'] in seen_uids:
            old=seen_uids[row['uid']]
            if any(old.get(k)!=row.get(k) for k in ('date','type','quantity','net_cash','currency','symbol')):raise ValueError('Conflicting broker IDs inside this export.')
            continue
        seen_uids[row['uid']]=row
        selected.append(row)
    working={p['symbol']:dict(p) for p in positions};cash=profile['cash_nok'];last_trades={}
    # Daily weighted-average book keeping; actual broker GAV remains authoritative on reconciliation.
    for row in sorted(selected,key=lambda e:(e['date'],e['type']!='buy',e['id'])):
        if row['type'] in ('buy','sell'):
            last_trades[row['symbol']]=max(last_trades.get(row['symbol'],0),dt.datetime.fromisoformat(row['date']).replace(tzinfo=dt.timezone.utc).timestamp())
        if row['date']<=ledger['cutoff_date']:continue
        cash+=row['net_cash']
        if row['type'] not in ('buy','sell'):continue
        matches=[p for p in working.values() if p['currency']=='NOK' and hi.oslo_symbol(p['symbol'])==row['symbol']]
        if len(matches)>1:raise ValueError('Resolve duplicate bare/.OL holdings before applying transactions.')
        p=matches[0] if matches else {'symbol':row['symbol'],'currency':'NOK','shares':0.,'cost':0.,'thesis':'','review':'','below':None,'above':None}
        if row['type']=='buy':
            cost=p['shares']*p['cost']+abs(row['net_cash']);p['shares']+=row['quantity'];p['cost']=cost/p['shares']
        else:
            if p['shares']+1e-8<row['quantity']:raise ValueError('Sale exceeds tracked shares. Verify the opening snapshot and full transaction history.')
            p['shares']=max(0,p['shares']-row['quantity'])
        working[p['symbol']]=p
        last_trades[row['symbol']]=dt.datetime.fromisoformat(row['date']).replace(tzinfo=dt.timezone.utc).timestamp()
    if cash < -1e-8:raise ValueError('These transactions produce negative tracked cash. Verify the opening cash and missing deposits.')
    for row in selected:
        db.execute('INSERT INTO ledger_events VALUES (?,?,?)',(row['uid'],row['date'],json.dumps(row,allow_nan=False)))
    for p in working.values():
        db.execute('INSERT OR REPLACE INTO positions VALUES (?,?,?,?,?,?,?,?)',tuple(p[k] for k in ('symbol','currency','shares','cost','thesis','review','below','above')))
    profile={**profile,'cash_nok':max(0,cash)}
    ledger={**ledger,'fingerprint':fingerprint(list(working.values()),profile['cash_nok']),'updated':time_now()}
    return {'imported':len(selected),'duplicates':len(selections)-len(selected),'profile':profile,'ledger':ledger,'last_trades':last_trades}


def time_now():
    import time
    return time.time()
