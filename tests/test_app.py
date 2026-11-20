import tempfile
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
