"""Private SMTP delivery of confirmed share-plan changes, with a persistent outbox."""
import hashlib
import json
import math
import os
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, time as wall_time, timedelta, timezone
from email.message import EmailMessage
from email.utils import formatdate
from zoneinfo import ZoneInfo

from northstar import decision_policy as policy
from northstar import trade_plan

TIMEOUT = 20
LEASE_SECONDS = 600
OSLO = ZoneInfo('Europe/Oslo')


def configuration(env=None):
    env = os.environ if env is None else env
    config = {k: env.get('NORTHSTAR_'+k, '').strip() for k in
              ('SMTP_HOST', 'SMTP_PORT', 'SMTP_SECURITY', 'SMTP_USERNAME', 'EMAIL_FROM', 'EMAIL_TO')}
    config['SMTP_PASSWORD'] = env.get('NORTHSTAR_SMTP_PASSWORD', '')
    config['SMTP_SECURITY'] = config['SMTP_SECURITY'] or 'starttls'
    config['SMTP_PORT'] = config['SMTP_PORT'] or ('465' if config['SMTP_SECURITY'] == 'ssl' else '587')
    enabled = env.get('NORTHSTAR_EMAIL_ENABLED', '').lower() in ('1', 'true', 'yes')
    errors = []
    for key in ('SMTP_HOST', 'SMTP_USERNAME', 'SMTP_PASSWORD', 'EMAIL_FROM', 'EMAIL_TO'):
        if not config[key]:
            errors.append('Set NORTHSTAR_'+key+'.')
    if any(any(c in value for c in '\r\n\x00') for value in config.values()):
        errors.append('Email settings cannot contain line breaks or null characters.')
    if config['SMTP_HOST'] and not re.fullmatch(r'[A-Za-z0-9.-]+', config['SMTP_HOST']):
        errors.append('SMTP host must be a hostname without a URL scheme or path.')
    for key in ('EMAIL_FROM', 'EMAIL_TO'):
        if config[key] and not re.fullmatch(r'[A-Za-z0-9.!#$%&\x27*+/=?^_`{|}~-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,63}', config[key]):
            errors.append('Use one plain email address for NORTHSTAR_'+key+'.')
    if config['SMTP_SECURITY'] not in ('starttls', 'ssl'):
        errors.append('SMTP security must be starttls or ssl; plaintext delivery is not supported.')
    try:
        config['SMTP_PORT'] = int(config['SMTP_PORT'])
        if not 1 <= config['SMTP_PORT'] <= 65535:
            raise ValueError()
    except ValueError:
        errors.append('SMTP port must be between 1 and 65535.')
    config.update(enabled=enabled, configured=not errors, errors=errors)
    # Changing destination/provider starts a separate delivery history; secrets never enter the DB.
    identity = '|'.join(str(config[k]) for k in ('SMTP_HOST', 'SMTP_USERNAME', 'EMAIL_FROM', 'EMAIL_TO'))
    config['target'] = hashlib.sha256(identity.encode()).hexdigest()
    return config


def schema(db):
    db.execute('''CREATE TABLE IF NOT EXISTS email_outbox (
        id TEXT PRIMARY KEY, target TEXT NOT NULL, symbol TEXT, direction TEXT,
        change_id TEXT, kind TEXT NOT NULL, payload TEXT NOT NULL,
        status TEXT NOT NULL, created REAL NOT NULL, updated REAL NOT NULL,
        attempts INTEGER NOT NULL DEFAULT 0, next_attempt REAL NOT NULL DEFAULT 0,
        last_error TEXT, sent REAL)''')
    db.execute('''CREATE TABLE IF NOT EXISTS email_risk_state (
        target TEXT NOT NULL, alert_id TEXT NOT NULL, event_key TEXT NOT NULL,
        loss_pct REAL NOT NULL, warning_pct REAL NOT NULL, active INTEGER NOT NULL,
        PRIMARY KEY (target,alert_id))''')


def event_id(target, symbol, direction, change_id, kind):
    value = json.dumps([policy.VERSION, target, symbol, direction, change_id, kind])
    return hashlib.sha256(value.encode()).hexdigest()


def weekly_slot(now):
    """Return the latest Sunday 10:00 Europe/Oslo slot that has arrived."""
    local = datetime.fromtimestamp(now, timezone.utc).astimezone(OSLO)
    sunday = local.date() - timedelta(days=(local.weekday()+1) % 7)
    slot = datetime.combine(sunday, wall_time(10), OSLO)
    if slot.timestamp() > now:
        slot = datetime.combine(sunday-timedelta(days=7), wall_time(10), OSLO)
    return slot.date().isoformat(), slot.timestamp()


def dashboard_url(env=None, workspace='recommendations'):
    env=os.environ if env is None else env
    pages=env.get('NORTHSTAR_PAGES_ORIGIN','').rstrip('/')
    if pages.startswith('https://'):
        return pages+'/northstar/#'+workspace
    public=env.get('NORTHSTAR_PUBLIC_ORIGIN','').rstrip('/')
    if public.startswith('https://'):
        return public+'/recommendations#'+workspace
    return None


def risk_event_key(db, alert, target, symbol, now):
    """Persist warning episodes; five percentage points from the last alert is material."""
    loss,level=alert.get('loss_pct'),alert.get('warning_pct')
    if not all(isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)
               for v in (loss,level)):
        return event_id(target,symbol,'review',alert['id'],'review')
    previous=db.execute('SELECT * FROM email_risk_state WHERE target=? AND alert_id=?',
                        (target,alert['id'])).fetchone()
    if (previous and previous['active'] and previous['warning_pct']==level
            and abs(previous['loss_pct']-loss)<5):
        return previous['event_key']
    key=event_id(target,symbol,'review',alert['id']+':'+str(now),'review')
    if previous is None:
        legacy=event_id(target,symbol,'review',alert['id'],'review')
        if db.execute('SELECT 1 FROM email_outbox WHERE id=?',(legacy,)).fetchone():
            key=legacy
    db.execute('''INSERT INTO email_risk_state VALUES (?,?,?,?,?,1)
        ON CONFLICT(target,alert_id) DO UPDATE SET event_key=excluded.event_key,
        loss_pct=excluded.loss_pct,warning_pct=excluded.warning_pct,active=1''',
        (target,alert['id'],key,loss,level))
    return key


def sync(db, report, plan, config, now):
    """Recheck the live plan before queuing or retrying an old suggestion."""
    schema(db)
    active = []
    active_risks=[]
    rows = {}
    if policy.current_report(report, now):
        long_term=set((report or {}).get('long_term_symbols',[]))
        rows = {(r['symbol'], 'buy'): r for r in plan.get('buys', [])}
        rows.update({(r['symbol'], 'sell'): r for r in plan.get('holdings', []) if r.get('sell_shares')})
        for change in report.get('recommendation_changes', []):
            symbol, direction = change['symbol'], change['direction']
            change_id = change.get('change_id')
            if not change_id or direction not in ('buy', 'sell'):
                continue
            kind = 'withdrawn' if change.get('change') == 'Withdrawn' else 'suggestion'
            row = rows.get((symbol, direction))
            if kind == 'suggestion':
                quantity = 'buy_shares' if direction == 'buy' else 'sell_shares'
                if not row or row.get(quantity) != change.get('shares'):
                    continue
                payload = {'symbol': symbol, 'direction': direction, 'shares': row[quantity],
                           'price': row['price'], 'quote_asof': row['quote_asof'],
                           'report_generated': report['generated'],
                           'long_term': symbol in long_term,
                           'fee_nok':row.get('fee_nok'),'net_proceeds_nok':row.get('net_proceeds_nok'),
                           'reason': row.get('reason') or ' '.join(row.get('reasons', [])),
                           'change': change['change']}
            else:
                original = event_id(config['target'], symbol, direction, change_id, 'suggestion')
                sent = db.execute("SELECT 1 FROM email_outbox WHERE id=? AND status='sent'", (original,)).fetchone()
                if row or not sent:
                    continue
                payload = {'symbol': symbol, 'direction': direction,
                           'report_generated': report['generated']}
            key = event_id(config['target'], symbol, direction, change_id, kind)
            active.append(key)
            db.execute('''INSERT INTO email_outbox
                (id,target,symbol,direction,change_id,kind,payload,status,created,updated)
                VALUES (?,?,?,?,?,?,?,'pending',?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated=excluded.updated,
                status='pending',next_attempt=CASE WHEN email_outbox.status='cancelled' THEN 0 ELSE email_outbox.next_attempt END
                WHERE email_outbox.status IN ('pending','cancelled') ''',
                       (key, config['target'], symbol, direction, change_id, kind,
                        json.dumps(payload, allow_nan=False), now, now))
    for alert in (report or {}).get('review_alerts',[]):
        if alert.get('kind') not in ('announcement','company','risk') or not alert.get('id'):
            continue
        source_asof=alert.get('source_asof')
        if (isinstance(source_asof,bool) or not isinstance(source_asof,(int,float))
                or not 0<=now-source_asof<=7*86400):
            continue
        symbol=alert.get('symbol') or ''
        if alert['kind']=='risk':
            active_risks.append(alert['id'])
            key=risk_event_key(db,alert,config['target'],symbol,now)
        else:
            key=event_id(config['target'],symbol,'review',alert['id'],'review')
        source_url=alert.get('url')
        if (not isinstance(source_url,str) or len(source_url)>2000
                or not source_url.startswith('https://') or any(c in source_url for c in '\r\n\x00')):
            source_url=None
        analysis_asof=(report or {}).get('generated')
        if isinstance(analysis_asof,bool) or not isinstance(analysis_asof,(int,float)):
            analysis_asof=source_asof
        payload={'title':str(alert.get('title','Review alert'))[:500],
                 'detail':str(alert.get('detail',''))[:2000],
                 'priority':(max(0,min(100,alert.get('priority',50)))
                             if isinstance(alert.get('priority',50),(int,float)) and not isinstance(alert.get('priority',50),bool) else 50),
                 'url':source_url,'source_asof':source_asof,'report_generated':analysis_asof}
        active.append(key)
        db.execute('''INSERT INTO email_outbox
            (id,target,symbol,direction,change_id,kind,payload,status,created,updated)
            VALUES (?,?,?,'review',?,'review',?,'pending',?,?)
            ON CONFLICT(id) DO UPDATE SET payload=excluded.payload, updated=excluded.updated,
            status='pending',next_attempt=CASE WHEN email_outbox.status='cancelled' THEN 0 ELSE email_outbox.next_attempt END
            WHERE email_outbox.status IN ('pending','cancelled')''',
                   (key,config['target'],symbol or None,alert['id'],json.dumps(payload,allow_nan=False),now,now))
    if (report or {}).get('risk_review_complete'):
        for row in db.execute('SELECT alert_id FROM email_risk_state WHERE target=? AND active=1',
                              (config['target'],)).fetchall():
            if row['alert_id'] not in active_risks:
                db.execute('UPDATE email_risk_state SET active=0 WHERE target=? AND alert_id=?',
                           (config['target'],row['alert_id']))
    # Withdrawn, superseded, stale or newly blocked suggestions must not be retried.
    for row in db.execute("SELECT * FROM email_outbox WHERE status='pending' AND kind!='test'").fetchall():
        # A withdrawal may disappear from the next scan's change list. Retain its
        # retry while the original suggestion remains absent from the live plan.
        if (row['kind'] == 'withdrawn' and row['target'] == config['target']
                and policy.current_report(report, now)
                and (row['symbol'], row['direction']) not in rows):
            active.append(row['id'])
        if row['kind'] == 'weekly' and row['target'] == config['target']:
            active.append(row['id'])
        if row['id'] not in active or row['target'] != config['target']:
            db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE id=?", (now, row['id']))
    db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE status='pending' AND (target!=? OR (kind='test' AND created<?))",
               (now, config['target'], now-3600))


def message(config, events, dashboard_url=None, portfolio_url=None):
    msg = EmailMessage()
    msg['From'], msg['To'] = config['EMAIL_FROM'], config['EMAIL_TO']
    msg['Date'] = formatdate(localtime=False)
    digest = hashlib.sha256('|'.join(sorted(r['id'] for r in events)).encode()).hexdigest()
    msg['Message-ID'] = '<northstar-'+digest+'@'+config['EMAIL_FROM'].split('@')[1]+'>'
    test = all(r['kind'] == 'test' for r in events)
    has_reviews=any(r['kind']=='review' for r in events)
    has_plan_changes=any(r['kind']!='review' and r['kind']!='test' for r in events)
    weekly = len(events) == 1 and events[0]['kind'] == 'weekly'
    weekly_payload = json.loads(events[0]['payload']) if weekly else {}
    msg['Subject'] = ('Northstar: email test' if test else
                      'Northstar: '+('late weekly catch-up' if weekly_payload.get('late') else 'weekly investor summary') if weekly else
                      'Northstar: '+str(len(events))+' portfolio review update(s)')
    if weekly:
        summary = weekly_payload.get('summary', {})
        lines = [('Late weekly catch-up for Sunday '+weekly_payload['slot']+' (Europe/Oslo).' if weekly_payload.get('late')
                  else 'Weekly investor summary for Sunday '+weekly_payload['slot']+' (Europe/Oslo).'), '']
        close_date = summary.get('last_close_date') or 'unavailable'
        lines.extend(['Last available close at summary refresh: '+str(close_date)+'.',
                      'A fresh quote is needed before placing an order.',
                      'Portfolio risk: '+str(summary.get('risk') or 'Risk data unavailable.')])
        attention = summary.get('holdings_attention') or []
        lines.extend(['', 'Holdings needing attention:'])
        lines.extend(['- '+str(item) for item in attention[:5]] if attention else ['No holdings currently need attention.'])
        candidates = summary.get('candidates') or []
        lines.extend(['', 'Noteworthy candidates:'])
        lines.extend(['- '+str(item) for item in candidates[:5]] if candidates else ['No current candidates are ready for review.'])
        if not attention and not candidates:
            lines.extend(['', 'No new holding or candidate changes were detected.'])
        lines.extend(['', 'Data freshness: '+str(summary.get('data_status') or 'Freshness could not be confirmed.')])
        if dashboard_url:
            lines.extend(['', 'Recommendations: '+dashboard_url])
        if portfolio_url:
            lines.append('Portfolio: '+portfolio_url)
        lines.extend(['', 'This summary is for review only. Prices are closing references and may be stale; verify a fresh quote and the current plan before any order.'])
        msg.set_content('\n'.join(lines))
        return msg
    opening=('Northstar email delivery is working.' if test else
             'Your share-count plan has changed and new review alerts are available.' if has_reviews and has_plan_changes else
             'New portfolio risk and issuer review alerts are available.' if has_reviews else
             'Your confirmed share-count plan has changed.')
    lines = [opening, '']
    for event in events:
        payload = json.loads(event['payload'])
        if event['kind'] == 'test':
            continue
        if event['kind'] == 'withdrawn':
            lines.append(payload['symbol']+': previous '+payload['direction']+' suggestion withdrawn. Do not use the earlier quantity.')
            lines.append('Change: Withdrawn. Priority: Elevated review.')
        elif event['kind'] == 'review':
            lines.append(payload['title'])
            urgency='High-priority review' if payload.get('priority',50)>=90 else 'Priority review' if payload.get('priority',50)>=75 else 'Review'
            lines.append('Urgency: '+urgency+'.')
            lines.append(payload['detail'])
            lines.append('Source data: '+time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(payload['source_asof']))+'.')
            if payload.get('url'):
                lines.append('Supporting source: '+payload['url'])
        else:
            lines.append(payload['symbol']+': review '+payload['direction']+' of '+str(payload['shares'])+' shares at a quoted '+str(payload['price'])+' NOK.')
            lines.append('Change: '+payload['change']+'. Urgency: '+('High-priority holding review.' if payload['direction']=='sell' else 'Candidate review.'))
            lines.append('Quote: '+time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(payload['quote_asof']))+'.')
            if payload.get('long_term'):
                lines.append('Long-term designation noted; this is a review prompt and does not direct a sale.')
            lines.append(payload['reason'])
            fee=payload.get('fee_nok')
            lines.append('Estimated '+payload['direction']+' fee: '+str(fee)+' NOK per order.'
                         if fee is not None else 'Trading fee unavailable; check the current plan assumptions.')
            if payload['direction']=='sell' and payload.get('net_proceeds_nok') is not None:
                lines.append('Estimated net proceeds before tax: '+str(payload['net_proceeds_nok'])+' NOK.')
        lines.append('Analysis: '+time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(payload['report_generated']))+'.')
        lines.append('')
    if dashboard_url:
        lines.extend(['Review the current plan: '+dashboard_url, ''])
    lines.append('Review prompts, not orders or forecasts. Recheck prices and the current plan before trading. '
                 'Fees use the current plan assumptions where entered; tax and execution differences are excluded. '
                 'Pause email alerts in the Daily overview.')
    msg.set_content('\n'.join(lines))
    return msg


def deliver(config, msg):
    context = ssl.create_default_context()
    client = (smtplib.SMTP_SSL(config['SMTP_HOST'], config['SMTP_PORT'], timeout=TIMEOUT, context=context)
              if config['SMTP_SECURITY'] == 'ssl' else
              smtplib.SMTP(config['SMTP_HOST'], config['SMTP_PORT'], timeout=TIMEOUT))
    try:
        client.ehlo()
        if config['SMTP_SECURITY'] == 'starttls':
            client.starttls(context=context)
            client.ehlo()
        client.login(config['SMTP_USERNAME'], config['SMTP_PASSWORD'])
        refused = client.send_message(msg, from_addr=config['EMAIL_FROM'], to_addrs=[config['EMAIL_TO']])
        if refused:
            raise smtplib.SMTPRecipientsRefused(refused)
    finally:
        # A failed QUIT after accepted DATA does not turn an accepted email into a retry.
        try:
            client.quit()
        except OSError:
            client.close()


def error_message(error):
    # Provider responses may echo credentials or addresses. Never persist raw exceptions.
    if isinstance(error, smtplib.SMTPAuthenticationError):
        return 'SMTP authentication failed. Check the server-side username and app password.'
    if isinstance(error, ssl.SSLError):
        return 'SMTP TLS verification failed. Check the hostname and TLS settings.'
    if isinstance(error, smtplib.SMTPNotSupportedError):
        return 'The SMTP server does not support the required TLS or authentication mode.'
    if isinstance(error, smtplib.SMTPRecipientsRefused):
        return 'The SMTP server rejected the recipient.'
    return 'Email delivery failed. Check SMTP settings and outbound server connectivity; delivery will retry.'


class Worker:
    def __init__(self, connect, read, write, current_plan, env=None):
        self.connect, self.read, self.write, self.current_plan = connect, read, write, current_plan
        self.env = env
        self.stop, self.wake, self.lock = threading.Event(), threading.Event(), threading.Lock()

    def config(self):
        return configuration(self.env)

    def status(self):
        config = self.config()
        enabled = config['enabled'] and self.read('email_enabled', True)
        with self.connect() as db:
            schema(db)
            counts = dict(db.execute('SELECT status,COUNT(*) FROM email_outbox WHERE target=? GROUP BY status', (config['target'],)).fetchall())
        return {'configured': config['configured'], 'server_enabled':config['enabled'], 'enabled': bool(enabled),
                'active': bool(config['configured'] and enabled), 'configuration_errors': config['errors'],
                'pending': counts.get('pending', 0)+counts.get('sending', 0), 'sent': counts.get('sent', 0),
                **self.read('email_status', {}),
                'method': 'Server-side email sends a weekly investor summary on Sunday around 10:00 Europe/Oslo, including no-change updates, plus confirmed share-plan changes and review alerts. Repeated sends are deduplicated; stale or blocked suggestions are cancelled.'}

    def history(self,limit=30):
        config=self.config()
        with self.connect() as db:
            schema(db)
            rows=db.execute("SELECT kind,symbol,status,created,updated,attempts,next_attempt,last_error,sent FROM email_outbox WHERE target=? ORDER BY created DESC,id DESC LIMIT ?",(config['target'],max(1,min(100,int(limit))))).fetchall()
        return [{**dict(row),'last_error':'Delivery attempt failed; see current delivery status for diagnosis.' if row['last_error'] else None} for row in rows]

    def set_enabled(self, enabled):
        if not isinstance(enabled, bool):
            raise ValueError('Email enabled must be true or false.')
        config = self.config()
        if enabled and (not config['configured'] or not config['enabled']):
            raise ValueError('Configure SMTP and allow email delivery on the server first.')
        self.write('email_enabled', enabled)
        if not enabled:
            with self.connect() as db:
                schema(db)
                db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE status='pending'", (time.time(),))
        self.wake.set()
        return self.status()

    def queue_test(self, now=None):
        now = time.time() if now is None else now
        config = self.config()
        if not config['configured'] or not config['enabled'] or not self.read('email_enabled', True):
            raise ValueError('Configure SMTP on Oracle and enable email alerts before sending a test.')
        with self.connect() as db:
            schema(db)
            db.execute('BEGIN IMMEDIATE')
            recent = db.execute("SELECT 1 FROM email_outbox WHERE kind='test' AND created>?", (now-60,)).fetchone()
            if recent:
                raise ValueError('Wait one minute before sending another test email.')
            key = event_id(config['target'], '', '', str(now), 'test')
            db.execute("INSERT INTO email_outbox (id,target,kind,payload,status,created,updated) VALUES (?,?,'test','{}','pending',?,?)",
                       (key, config['target'], now, now))
        self.wake.set()
        return {'queued': True, 'message': 'Test queued. Check delivery status and your inbox.'}

    def tick(self, now=None):
        now = time.time() if now is None else now
        if not self.lock.acquire(blocking=False):
            return
        try:
            config = self.config()
            if not config['configured'] or not config['enabled'] or not self.read('email_enabled', True):
                return
            # Test delivery must work even if research/plan generation is broken.
            with self.connect() as db:
                schema(db)
                test_pending = db.execute("""SELECT 1 FROM email_outbox WHERE target=? AND kind='test'
                    AND created>=? AND next_attempt<=? AND
                    (status='pending' OR (status='sending' AND updated<?)) LIMIT 1""",
                    (config['target'], now-3600, now, now-LEASE_SECONDS)).fetchone()
            if not test_pending:
                report, plan = self.current_plan()
            initialize_weekly = False
            with self.connect() as db:
                schema(db)
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE email_outbox SET status='pending' WHERE status='sending' AND updated<?", (now-LEASE_SECONDS,))
                if test_pending:
                    db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE status='pending' AND kind='test' AND (target!=? OR created<?)",
                               (now, config['target'], now-3600))
                else:
                    sync(db, report, plan, config, now)
                    slot, scheduled = weekly_slot(now)
                    local = datetime.fromtimestamp(now, timezone.utc).astimezone(OSLO)
                    this_sunday = local.date()-timedelta(days=(local.weekday()+1) % 7)
                    due_now = (local.weekday() == 6 and
                               now >= datetime.combine(this_sunday, wall_time(10), OSLO).timestamp())
                    start_slot = self.read('weekly_summary_start_slot')
                    if not start_slot:
                        start_date=this_sunday if due_now else this_sunday+timedelta(days=7)
                        start_slot=start_date.isoformat()
                        initialize_weekly=True
                    if slot >= start_slot:
                        weekly_id = event_id(config['target'], '', 'weekly', slot, 'weekly')
                        summary = (report or {}).get('weekly_summary', {})
                        db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE target=? AND kind='weekly' AND status IN ('pending','sending') AND change_id<?",
                                   (now, config['target'], slot))
                        db.execute('''INSERT INTO email_outbox
                            (id,target,direction,change_id,kind,payload,status,created,updated)
                            VALUES (?,?,'weekly',?,'weekly',?,'pending',?,?)
                            ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,updated=excluded.updated
                            WHERE email_outbox.status='pending' ''',
                            (weekly_id, config['target'], slot,
                             json.dumps({'slot':slot,'late':now-scheduled>300,'summary':summary},allow_nan=False), now, now))
                selection = " AND kind='test'" if test_pending else ''
                events = db.execute("SELECT * FROM email_outbox WHERE target=? AND status='pending' AND next_attempt<=?"+selection+" ORDER BY created,id LIMIT 50",
                                    (config['target'], now)).fetchall()
                if events:
                    is_test = events[0]['kind'] == 'test'
                    is_weekly = events[0]['kind'] == 'weekly'
                    events = [r for r in events if (r['kind'] == 'test') == is_test
                              and (r['kind'] == 'weekly') == is_weekly]
                for event in events:
                    db.execute("UPDATE email_outbox SET status='sending',updated=?,attempts=attempts+1 WHERE id=?", (now, event['id']))
            if initialize_weekly:
                self.write('weekly_summary_start_slot', start_slot)
            if not events:
                return
            # A pause can race with queueing; check again immediately before SMTP.
            if not self.read('email_enabled', True):
                with self.connect() as db:
                    for event in events:
                        db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE id=?", (now, event['id']))
                return
            try:
                dashboard = dashboard_url(os.environ if self.env is None else self.env)
                portfolio = dashboard_url(os.environ if self.env is None else self.env, 'portfolio')
                deliver(config, message(config, events, dashboard, portfolio))
            except Exception as error:
                failure = error_message(error)
                with self.connect() as db:
                    for event in events:
                        delay = min(3600, 60 * 2**min(event['attempts'], 6))
                        db.execute("UPDATE email_outbox SET status='pending',updated=?,next_attempt=?,last_error=? WHERE id=?",
                                   (now, now+delay, failure, event['id']))
                self.write('email_status', {**self.read('email_status', {}), 'last_attempt': now, 'error': failure})
                return
            with self.connect() as db:
                for event in events:
                    db.execute("UPDATE email_outbox SET status='sent',updated=?,sent=?,last_error=NULL WHERE id=?", (now, now, event['id']))
            self.write('email_status', {'last_attempt': now, 'last_sent': now, 'error': None})
        finally:
            self.lock.release()

    def loop(self):
        while not self.stop.is_set():
            self.wake.clear()
            try:
                self.tick()
            except Exception:
                self.write('email_status', {**self.read('email_status', {}), 'error': 'Email worker failed; retrying in one minute.'})
            self.wake.wait(60)

    def start(self):
        threading.Thread(target=self.loop, name='northstar-email', daemon=True).start()
