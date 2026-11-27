import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
import app

class PortfolioTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.patch = patch.object(app, 'DB', Path(self.tmp.name) / 'portfolio.db')
        self.patch.start()
    def tearDown(self):
        self.patch.stop()
        self.tmp.cleanup()
    def position(self, **changes):
        return dict(symbol='EQNR.OL', currency='NOK', shares=10, cost=250, **changes)
    def test_round_trip_and_update(self):
        app.save_position(self.position(thesis='Energy thesis'))
        app.save_position(self.position(thesis='Updated thesis'))
        rows = app.state()['positions']
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['thesis'], 'Updated thesis')
        self.assertIsNone(rows[0]['below'])
    def test_nonfinite_and_negative_rejected(self):
        for value in ['nan', 'inf', -1]:
            with self.assertRaises(ValueError):
                app.positive(value)
    def test_oslo_suffix_for_existing_holding(self):
        app.save_position(dict(symbol='KOG', currency='NOK', shares=5, cost=306))
        def provider(symbol):
            self.assertIn(symbol, ['KOG.OL', 'NOK=X'])
            return {'price': 310, 'currency': 'NOK', 'asof': 123}
        with patch.object(app, 'fetch_quote', side_effect=provider) as fetch:
            self.assertEqual(app.refresh(), [])
            self.assertEqual(fetch.call_count, 2)
        self.assertEqual(app.state()['quotes']['KOG']['price'], 310)
        self.assertEqual(app.state()['positions'][0]['symbol'], 'KOG')

    def test_portfolio_state_reads_holdings_and_cash_from_one_commit(self):
        app.save_position(self.position())
        app.write_meta('portfolio_preferences',{'cash_nok':100})
        with app.connect() as db:
            db.execute('PRAGMA journal_mode=WAL')
        original_connect=app.connect
        first_connection=True
        writer_finished=threading.Event()
        writer_errors=[]

        def write_new_state():
            try:
                with original_connect() as db:
                    db.execute('UPDATE positions SET shares=20 WHERE symbol=?',('EQNR.OL',))
                    db.execute('UPDATE metadata SET payload=? WHERE key=?',
                               ('{"cash_nok":200}','portfolio_preferences'))
            except Exception as error:
                writer_errors.append(error)
            finally:
                writer_finished.set()

        def connect_during_read(*,timeout=5.0):
            nonlocal first_connection
            db=original_connect(timeout=timeout)
            if first_connection:
                first_connection=False
                def trace(statement):
                    if statement.startswith('SELECT * FROM quotes'):
                        db.set_trace_callback(None)
                        threading.Thread(target=write_new_state).start()
                        self.assertTrue(writer_finished.wait(3),'Concurrent ledger write timed out')
                db.set_trace_callback(trace)
            return db

        with patch.object(app,'connect',side_effect=connect_during_read):
            snapshot=app.state()

        self.assertEqual(writer_errors,[])
        self.assertIn((snapshot['positions'][0]['shares'],
                       snapshot['manual_portfolio_preferences']['cash_nok']),
                      {(10,100),(20,200)})

    def test_promotion_requires_a_latest_historical_candidate_and_can_restore_baseline(self):
        app.write_meta('validation_report',{'generated':123,'robustness':{'variants':[
            {'label':'10 positions / 1 month(s)','max_positions':10,'rebalance_months':1}]}})
        promoted=app.set_promoted_experiment_model({'max_positions':10})['promoted_model']
        self.assertEqual(promoted['max_positions'],10)
        self.assertEqual(promoted['label'],'10-position recommendation cap')
        self.assertEqual(promoted['validation_generated'],123)
        with self.assertRaises(ValueError):
            app.set_promoted_experiment_model({'max_positions':15})
        with self.assertRaises(ValueError):
            app.set_promoted_experiment_model({})
        self.assertEqual(app.read_meta('promoted_experiment_model')['label'],'10-position recommendation cap')
        self.assertIsNone(app.set_promoted_experiment_model({'max_positions':None})['promoted_model'])
    def test_refresh_failure_preserves_quote(self):
        app.save_position(self.position())
        with app.connect() as db:
            db.execute('INSERT INTO quotes VALUES (?,?)', ('EQNR.OL', '{"price":250,"asof":123}'))
        with patch.object(app, 'fetch_quote', side_effect=OSError('offline')):
            errors = app.refresh()
        self.assertEqual(len(errors), 2)
        self.assertEqual(app.state()['quotes']['EQNR.OL']['asof'], 123)

if __name__ == '__main__':
    unittest.main()

class LongTermMigrationTests(unittest.TestCase):
    def test_existing_positions_migrate_and_designation_round_trips(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(app, 'DB', Path(tmp) / 'old.db'):
            import sqlite3
            with sqlite3.connect(app.DB) as db:
                db.execute('CREATE TABLE positions (symbol TEXT PRIMARY KEY, currency TEXT, shares REAL, cost REAL, thesis TEXT, review TEXT, below REAL, above REAL)')
                db.execute("INSERT INTO positions VALUES ('OLD.OL','NOK',1,10,'thesis','review',NULL,NULL)")
            snapshot=app.state()
            self.assertEqual(snapshot['positions'][0]['long_term'],0)
            app.save_position({'symbol':'OLD.OL','currency':'NOK','shares':2,'cost':11,'thesis':'updated','review':'review','long_term':True})
            saved=app.state()['positions'][0]
            self.assertEqual(saved['shares'],2)
            self.assertEqual(saved['long_term'],1)
