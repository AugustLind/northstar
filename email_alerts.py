"""Private SMTP delivery of confirmed share-plan changes, with a persistent outbox."""
import hashlib
import json
import os
import re
import smtplib
import ssl
import threading
import time
from email.message import EmailMessage
from email.utils import formatdate

import decision_policy as policy
import trade_plan

TIMEOUT = 20
LEASE_SECONDS = 600


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


def event_id(target, symbol, direction, change_id, kind):
    value = json.dumps([policy.VERSION, target, symbol, direction, change_id, kind])
    return hashlib.sha256(value.encode()).hexdigest()


def sync(db, report, plan, config, now):
    """Recheck the live plan before queuing or retrying an old suggestion."""
    schema(db)
    active = []
    rows = {}
    if trade_plan.current_report(report, now):
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
    # Withdrawn, superseded, stale or newly blocked suggestions must not be retried.
    for row in db.execute("SELECT * FROM email_outbox WHERE status='pending' AND kind!='test'").fetchall():
        # A withdrawal may disappear from the next scan's change list. Retain its
        # retry while the original suggestion remains absent from the live plan.
        if (row['kind'] == 'withdrawn' and row['target'] == config['target']
                and trade_plan.current_report(report, now)
                and (row['symbol'], row['direction']) not in rows):
            active.append(row['id'])
        if row['id'] not in active or row['target'] != config['target']:
            db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE id=?", (now, row['id']))
    db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE status='pending' AND (target!=? OR (kind='test' AND created<?))",
               (now, config['target'], now-3600))


def message(config, events, dashboard_url=None):
    msg = EmailMessage()
    msg['From'], msg['To'] = config['EMAIL_FROM'], config['EMAIL_TO']
    msg['Date'] = formatdate(localtime=False)
    digest = hashlib.sha256('|'.join(sorted(r['id'] for r in events)).encode()).hexdigest()
    msg['Message-ID'] = '<northstar-'+digest+'@'+config['EMAIL_FROM'].split('@')[1]+'>'
    test = all(r['kind'] == 'test' for r in events)
    msg['Subject'] = 'Northstar: email test' if test else 'Northstar: '+str(len(events))+' portfolio review update(s)'
    lines = ['Northstar email delivery is working.' if test else 'Your confirmed share-count plan has changed.', '']
    for event in events:
        payload = json.loads(event['payload'])
        if event['kind'] == 'test':
            continue
        if event['kind'] == 'withdrawn':
            lines.append(payload['symbol']+': previous '+payload['direction']+' suggestion withdrawn. Do not use the earlier quantity.')
        else:
            lines.append(payload['symbol']+': review '+payload['direction']+' of '+str(payload['shares'])+' shares at a quoted '+str(payload['price'])+' NOK.')
            lines.append('Quote: '+time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(payload['quote_asof']))+'.')
            lines.append(payload['reason'])
        lines.append('Analysis: '+time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime(payload['report_generated']))+'.')
        lines.append('')
    if dashboard_url:
        lines.extend(['Review the current plan: '+dashboard_url, ''])
    lines.append('Review prompts, not orders or forecasts. Recheck prices and the current plan before trading. '
                 'Purchase sizing includes 79 NOK per order; sale estimates exclude selling costs and tax. '
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
                'method': 'Server-side email for confirmed share-plan changes. Repeated scans are deduplicated; stale or blocked suggestions are cancelled. No open browser is needed.'}

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
            with self.connect() as db:
                schema(db)
                db.execute('BEGIN IMMEDIATE')
                db.execute("UPDATE email_outbox SET status='pending' WHERE status='sending' AND updated<?", (now-LEASE_SECONDS,))
                if test_pending:
                    db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE status='pending' AND kind='test' AND (target!=? OR created<?)",
                               (now, config['target'], now-3600))
                else:
                    sync(db, report, plan, config, now)
                selection = " AND kind='test'" if test_pending else ''
                events = db.execute("SELECT * FROM email_outbox WHERE target=? AND status='pending' AND next_attempt<=?"+selection+" ORDER BY created,id LIMIT 50",
                                    (config['target'], now)).fetchall()
                if events:
                    is_test = events[0]['kind'] == 'test'
                    events = [r for r in events if (r['kind'] == 'test') == is_test]
                for event in events:
                    db.execute("UPDATE email_outbox SET status='sending',updated=?,attempts=attempts+1 WHERE id=?", (now, event['id']))
            if not events:
                return
            # A pause can race with queueing; check again immediately before SMTP.
            if not self.read('email_enabled', True):
                with self.connect() as db:
                    for event in events:
                        db.execute("UPDATE email_outbox SET status='cancelled',updated=? WHERE id=?", (now, event['id']))
                return
            try:
                origin = (os.environ if self.env is None else self.env).get('NORTHSTAR_PAGES_ORIGIN', '')
                dashboard = origin+'/northstar/#recommendations' if origin.startswith('https://') else None
                deliver(config, message(config, events, dashboard))
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
