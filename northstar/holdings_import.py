"""Strict Nordnet holdings export parser. No broker login, raw-file storage or trades."""
import csv
import io
import re
import unicodedata
from decimal import Decimal, InvalidOperation

MAX_BYTES=262144
MAX_ROWS=500


def name_key(value):
    text=unicodedata.normalize('NFKC',str(value)).casefold()
    return ' '.join(re.sub(r'[^\w]+',' ',text,flags=re.UNICODE).split())


def company_key(value):
    words=name_key(value).split()
    while words and words[-1] in ('asa','as','ab','plc','ltd','limited'):
        words.pop()
    return ' '.join(words)


def oslo_symbol(value):
    symbol=str(value).strip().upper()
    if '.' not in symbol:
        symbol+='.OL'
    if not re.fullmatch(r'[A-Z0-9][A-Z0-9\-]{0,16}\.OL',symbol):
        raise ValueError('Choose a valid Oslo ticker, for example BOUV.OL.')
    return symbol


def amount(value, field):
    compact=''.join(str(value).split()).replace('\u2212','-')
    if ',' in compact and '.' in compact:
        if not re.fullmatch(r'\+?\d{1,3}(?:\.\d{3})+,\d+',compact):
            raise ValueError(field+' has an ambiguous number format.')
        compact=compact.replace('.','')
    if not re.fullmatch(r'\+?\d+(?:[.,]\d+)?',compact):
        raise ValueError(field+' must be a nonnegative number.')
    try:
        number=Decimal(compact.replace(',','.'))
    except InvalidOperation:
        raise ValueError(field+' is not a number.')
    if not number.is_finite() or number>Decimal('1000000000000'):
        raise ValueError(field+' is outside the supported range.')
    return float(number)


def parse(raw):
    if not raw or len(raw)>MAX_BYTES:
        raise ValueError('Choose a nonempty holdings export up to 256 KiB.')
    if raw.startswith((b'\xff\xfe',b'\xfe\xff')):
        try:
            text=raw.decode('utf-16')
        except UnicodeError:
            raise ValueError('The UTF-16 export is damaged. Export it again from Nordnet.')
    else:
        try:
            text=raw.decode('utf-8-sig')
        except UnicodeError:
            text=raw.decode('cp1252')
    if '\x00' in text:
        raise ValueError('Unsupported binary file. Choose a CSV/TSV holdings export.')
    try:
        dialect=csv.Sniffer().sniff(text[:10000],delimiters='\t;,')
        rows=list(csv.reader(io.StringIO(text),dialect,strict=True))
    except csv.Error:
        raise ValueError('Cannot read the table. Export current holdings as CSV from Nordnet.')
    rows=[r for r in rows if any(c.strip() for c in r)]
    if len(rows)<2 or len(rows)>MAX_ROWS+1:
        raise ValueError('The export must contain between 1 and 500 holdings.')
    headers=[name_key(c) for c in rows[0]]
    required={'name':'navn','currency':'valuta','shares':'antall','cost':'gav'}
    if any(headers.count(v)!=1 for v in required.values()):
        raise ValueError('This must be a holdings export with Navn, Valuta, Antall and GAV columns, not a transaction history.')
    indices={k:headers.index(v) for k,v in required.items()}
    ticker=next((headers.index(k) for k in ('ticker','symbol','tickerkode') if k in headers),None)
    items=[]
    for line,row in enumerate(rows[1:],2):
        item={'id':line,'name':'','currency':'','shares':None,'cost':None,'symbol_hint':None,'error':None}
        try:
            if len(row)!=len(headers):
                raise ValueError('Column count differs from the header.')
            item['name']=row[indices['name']].strip()
            item['currency']=row[indices['currency']].strip().upper()
            if not item['name'] or len(item['name'])>200:
                raise ValueError('Company name is empty or too long.')
            if item['currency']!='NOK':
                raise ValueError('Only NOK Oslo holdings are supported by this importer. This row will not be imported.')
            item['shares']=amount(row[indices['shares']],'Antall')
            item['cost']=amount(row[indices['cost']],'GAV')
            if ticker is not None and row[ticker].strip():
                item['symbol_hint']=oslo_symbol(row[ticker])
        except ValueError as error:
            item['error']=str(error)
        items.append(item)
    return items


def catalogue(quotes,report=None):
    result={}
    for symbol,q in quotes.items():
        if q.get('currency')!='NOK':
            continue
        try:
            symbol=oslo_symbol(symbol)
        except ValueError:
            continue
        result[symbol]={'symbol':symbol,'name':q.get('name') or symbol}
    for card in (report or {}).get('cards',[]):
        if card.get('currency')!='NOK':
            continue
        try:
            symbol=oslo_symbol(card['symbol'])
        except ValueError:
            continue
        result.setdefault(symbol,{'symbol':symbol,'name':card.get('name') or symbol})
    return sorted(result.values(),key=lambda c:(name_key(c['name']),c['symbol']))


def suggest(items,companies,aliases):
    by_name={}
    for c in companies:
        by_name.setdefault(name_key(c['name']),set()).add(c['symbol'])
    legal_names={}
    for c in companies:
        legal_names.setdefault(company_key(c['name']),set()).add(c['symbol'])
    out=[]
    for item in items:
        row={**item,'symbol':'','match':'Choose ticker','selected':False}
        if not item['error']:
            key=name_key(item['name'])
            saved=aliases.get(key)
            if item['symbol_hint']:
                row.update(symbol=item['symbol_hint'],match='Ticker supplied by export')
            elif saved:
                try:
                    row.update(symbol=oslo_symbol(saved),match='Your saved name match')
                except ValueError:
                    pass
            if not row['symbol'] and len(by_name.get(key,set()))==1:
                row.update(symbol=next(iter(by_name[key])),match='Exact cached company-name match; please confirm')
            if not row['symbol'] and len(legal_names.get(company_key(item['name']),set()))==1:
                row.update(symbol=next(iter(legal_names[company_key(item['name'])])),match='Name match ignoring legal suffix; please confirm')
            row['selected']=bool(row['symbol'])
        out.append(row)
    return out


def save(db, items, selections, aliases):
    """Validate the complete selection before writing; caller owns the transaction."""
    if not isinstance(selections,list) or not 1<=len(selections)<=MAX_ROWS:
        raise ValueError('Select between 1 and 500 holdings.')
    by_id={r['id']:r for r in items}
    positions=[dict(r) for r in db.execute('SELECT * FROM positions')]
    seen_ids=set();seen_symbols=set();changes=[];new_aliases=dict(aliases)
    for selection in selections:
        if not isinstance(selection,dict) or not isinstance(selection.get('id'),int) or isinstance(selection.get('id'),bool):
            raise ValueError('Invalid import selection.')
        item=by_id.get(selection['id'])
        if item is None or item['error'] or item['id'] in seen_ids:
            raise ValueError('An invalid or duplicate export row was selected.')
        symbol=oslo_symbol(selection.get('symbol',''))
        if symbol in seen_symbols:
            raise ValueError('Two rows resolve to '+symbol+'. Import one consolidated holding per ticker.')
        seen_ids.add(item['id']);seen_symbols.add(symbol)
        matches=[]
        for p in positions:
            if p['currency']=='NOK':
                try:
                    if oslo_symbol(p['symbol'])==symbol:
                        matches.append(p)
                except ValueError:
                    pass
            elif p['symbol']==symbol:
                raise ValueError('The existing '+symbol+' holding uses a different currency. Resolve it before importing.')
        if len(matches)>1:
            raise ValueError('Both bare and .OL holdings exist for '+symbol+'. Resolve the duplicate before importing.')
        old=matches[0] if matches else None
        changes.append((old['symbol'] if old else symbol,item))
        key=name_key(item['name'])
        if key in new_aliases and new_aliases[key]!=symbol and any(name_key(r['name'])==key and r['id'] in seen_ids and r['id']!=item['id'] for r in items):
            raise ValueError('The same company name maps to different tickers. Import and confirm each share class separately.')
        new_aliases[key]=symbol
    for symbol,item in changes:
        # GAV is the broker-provided average cost. Do not add another 79 NOK to it.
        db.execute('''INSERT INTO positions(symbol,currency,shares,cost,thesis,review,below,above)
                      VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(symbol) DO UPDATE SET
                      currency=excluded.currency,shares=excluded.shares,cost=excluded.cost''',
                   (symbol,item['currency'],item['shares'],item['cost'],'','',None,None))
    return {'updated':len(changes),'aliases':new_aliases}
