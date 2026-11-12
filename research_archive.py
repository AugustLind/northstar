"""Append-only, content-addressed research inputs. Capture time is never backdated."""
import hashlib
import json
import math
import time
import zlib

KINDS={'quote','financial','company','universe','report','run'}

def schema(db):
    db.executescript('''CREATE TABLE IF NOT EXISTS research_blobs (
      digest TEXT PRIMARY KEY, payload BLOB NOT NULL, original_bytes INTEGER NOT NULL);
    CREATE TABLE IF NOT EXISTS research_snapshots (
      id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, subject TEXT NOT NULL,
      captured REAL NOT NULL, source_asof REAL, digest TEXT NOT NULL REFERENCES research_blobs(digest));
    CREATE INDEX IF NOT EXISTS research_snapshot_lookup ON research_snapshots(kind,subject,captured,id);
    CREATE TABLE IF NOT EXISTS research_price_versions (
      id INTEGER PRIMARY KEY AUTOINCREMENT, subject TEXT NOT NULL, stamp REAL NOT NULL,
      captured REAL NOT NULL, digest TEXT NOT NULL REFERENCES research_blobs(digest));
    CREATE TABLE IF NOT EXISTS research_latest_refs (kind TEXT NOT NULL,subject TEXT NOT NULL,signature TEXT NOT NULL,snapshot_id INTEGER NOT NULL,PRIMARY KEY(kind,subject));
    CREATE INDEX IF NOT EXISTS research_price_lookup ON research_price_versions(subject,stamp,id);
    ''')
    for table in ('research_blobs','research_snapshots','research_price_versions'):
        for action in ('UPDATE','DELETE'):
            db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT,'Research archive is append-only'); END")


def blob(db,value):
    raw=json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()
    digest=hashlib.sha256(raw).hexdigest()
    db.execute('INSERT OR IGNORE INTO research_blobs VALUES (?,?,?)',(digest,zlib.compress(raw),len(raw)))
    return digest


def unpack(db,digest):
    row=db.execute('SELECT payload FROM research_blobs WHERE digest=?',(digest,)).fetchone()
    if not row:raise ValueError('Archived input blob is missing.')
    raw=zlib.decompress(row['payload'])
    if hashlib.sha256(raw).hexdigest()!=digest:raise ValueError('Archived input checksum failed.')
    return json.loads(raw)


def capture(db,kind,subject,value,now=None,source_asof=None):
    """Caller owns transaction; schema must be initialised before BEGIN."""
    if kind not in KINDS:raise ValueError('Unknown archive kind.')
    now=time.time() if now is None else now
    if not isinstance(now,(int,float)) or not math.isfinite(now):raise ValueError('Invalid capture time.')
    signature=hashlib.sha256(json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    previous=db.execute('SELECT r.signature,r.snapshot_id,s.captured FROM research_latest_refs r JOIN research_snapshots s ON r.snapshot_id=s.id WHERE r.kind=? AND r.subject=?',(kind,str(subject))).fetchone()
    if previous and previous['signature']==signature and previous['captured']<=now:return previous['snapshot_id']
    payload=value
    if kind=='quote' and isinstance(value,dict) and 'history' in value:
        latest={r['stamp']:(r['id'],r['digest']) for r in db.execute('''SELECT v.* FROM research_price_versions v
          JOIN (SELECT stamp,MAX(id) AS latest FROM research_price_versions WHERE subject=? GROUP BY stamp) x
          ON v.id=x.latest''',(subject,))}
        stamps=[];through=0
        for point in value['history']:
            stamp=point['time'];digest=hashlib.sha256(json.dumps(point,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()).hexdigest()
            old=latest.get(stamp)
            if not old or old[1]!=digest:
                digest=blob(db,point)
                cursor=db.execute('INSERT INTO research_price_versions(subject,stamp,captured,digest) VALUES (?,?,?,?)',(subject,stamp,now,digest))
                old=(cursor.lastrowid,digest);latest[stamp]=old
            stamps.append(stamp);through=max(through,old[0])
        payload={k:v for k,v in value.items() if k!='history'}
        payload['_archived_history']={'stamps':stamps,'through_version':through}
    digest=blob(db,payload)
    if not isinstance(source_asof,(int,float)) or not math.isfinite(source_asof):source_asof=None
    cursor=db.execute('INSERT INTO research_snapshots(kind,subject,captured,source_asof,digest) VALUES (?,?,?,?,?)',
                      (kind,str(subject),now,source_asof,digest))
    identifier=cursor.lastrowid
    db.execute('INSERT OR REPLACE INTO research_latest_refs VALUES (?,?,?,?)',(kind,str(subject),signature,identifier))
    return identifier


def read(db,identifier,before=None):
    row=db.execute('SELECT * FROM research_snapshots WHERE id=?',(identifier,)).fetchone()
    if not row or before is not None and row['captured']>before:raise ValueError('No archived record was known by that capture time.')
    value=unpack(db,row['digest'])
    if row['kind']=='quote' and '_archived_history' in value:
        ref=value.pop('_archived_history');needed=set(ref['stamps'])
        bars={r['stamp']:unpack(db,r['digest']) for r in db.execute('''SELECT v.stamp,v.digest FROM research_price_versions v
          JOIN (SELECT stamp,MAX(id) AS latest FROM research_price_versions
                WHERE subject=? AND id<=? GROUP BY stamp) x ON v.id=x.latest''',(row['subject'],ref['through_version'])) if r['stamp'] in needed}
        if len(bars)!=len(needed):raise ValueError('Archived price coverage is incomplete.')
        value['history']=[bars[stamp] for stamp in ref['stamps']]
    return {**dict(row),'value':value}


def latest(db,kind,subject,before):
    row=db.execute('SELECT id FROM research_snapshots WHERE kind=? AND subject=? AND captured<=? ORDER BY captured DESC,id DESC LIMIT 1',
                   (kind,subject,before)).fetchone()
    return read(db,row['id'],before) if row else None


def analysis_fingerprint(root):
    digest=hashlib.sha256()
    for name in ('research.py','indicators.py','decision_policy.py','trade_plan.py','portfolio_fit.py','advice_state.py','fundamentals.py','company_data.py','announcements.py'):
        digest.update(name.encode());digest.update((root/name).read_bytes())
    return digest.hexdigest()


def capture_run(db,report,snapshot,settings,fingerprint,now=None):
    now=time.time() if now is None else now
    quotes={s:capture(db,'quote',s,q,now,q.get('asof')) for s,q in snapshot['quotes'].items()}
    financials={s:capture(db,'financial',s,f,now,f.get('fetched')) for s,f in snapshot.get('fundamentals',{}).items()}
    universe=capture(db,'universe','oslo',{'universe':settings['universe'],'min_turnover_nok':settings.get('min_turnover_nok',250000)},now)
    recorded=capture(db,'report',str(report['generated']),report,now,report['generated'])
    context={k:snapshot.get(k) for k in ('positions','portfolio_preferences','manual_portfolio_preferences','signal_state','last_trades','ledger_reconciled','companies','announcements') if k in snapshot}
    return capture(db,'run','research',{'quote_ids':quotes,'financial_ids':financials,'universe_id':universe,'report_id':recorded,
        'context':context,'analysis_fingerprint':fingerprint,'report_generated':report['generated']},now,report['generated'])


def stats(db,before=None):
    clause=' WHERE captured<=?' if before is not None else '';args=(before,) if before is not None else ()
    groups=[dict(r) for r in db.execute('SELECT kind,COUNT(*) AS observations,MIN(captured) AS first_capture,MAX(captured) AS last_capture FROM research_snapshots'+clause+' GROUP BY kind',args)]
    size=db.execute('SELECT COALESCE(SUM(LENGTH(payload)),0) AS compressed,COALESCE(SUM(original_bytes),0) AS original FROM research_blobs').fetchone()
    runs=[dict(r) for r in db.execute("SELECT id,captured,source_asof,digest FROM research_snapshots WHERE kind='run'"+(' AND captured<=?' if before is not None else '')+' ORDER BY captured DESC,id DESC LIMIT 30',args)]
    return {'kinds':groups,'runs':runs,'compressed_bytes':size['compressed'],'original_bytes':size['original'],
        'price_versions':db.execute('SELECT COUNT(*) FROM research_price_versions').fetchone()[0],
        'method':'Capture times are wall-clock observations, never provider dates. Earlier price/fiscal dates do not imply earlier availability. Revisions are preserved; changed bars are stored once per version. Existing cache is first archived when observed after this feature was installed.'}


def replay(db,identifier,root):
    run=read(db,identifier)
    if run['kind']!='run':raise ValueError('Choose an archived research run.')
    manifest=run['value'];before=run['captured']
    quote_rows={s:read(db,i,before) for s,i in manifest['quote_ids'].items()}
    financial_rows={s:read(db,i,before) for s,i in manifest['financial_ids'].items()}
    universe=read(db,manifest['universe_id'],before)['value'];saved=read(db,manifest['report_id'],before)['value']
    snapshot={**manifest['context'],'quotes':{s:r['value'] for s,r in quote_rows.items()},'fundamentals':{s:r['value'] for s,r in financial_rows.items()}}
    import research
    rebuilt=research.build_report(snapshot,universe['universe'],universe['min_turnover_nok'],as_of=manifest['report_generated'])
    old={c['symbol']:c for c in saved['cards']};new={c['symbol']:c for c in rebuilt['cards']}
    rows=[{'symbol':s,'saved_rank':old.get(s,{}).get('rank'),'replayed_rank':new.get(s,{}).get('rank'),
           'saved_action':old.get(s,{}).get('action'),'replayed_action':new.get(s,{}).get('action'),
           'saved_score':old.get(s,{}).get('composite'),'replayed_score':new.get(s,{}).get('composite')} for s in sorted(set(old)|set(new))]
    differences=sum(r['saved_rank']!=r['replayed_rank'] or r['saved_action']!=r['replayed_action'] or r['saved_score']!=r['replayed_score'] for r in rows)
    return {'run_id':run['id'],'captured':before,'report_generated':manifest['report_generated'],
            'same_analysis_code':manifest['analysis_fingerprint']==analysis_fingerprint(root),'differences':differences,'rows':rows,
            'inputs':{'quotes':len(quote_rows),'financials':len(financial_rows),'universe':len(universe['universe'])},
            'method':'Read-only replay of recorded inputs at the original report time under current analysis code. No live prices, holdings or alerts are modified. A different code fingerprint can produce different results. Personal quantity alerts and historical investment performance are not re-created or certified.'}
