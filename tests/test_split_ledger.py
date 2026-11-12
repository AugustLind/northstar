import unittest
import transactions as tx
import test_transactions as ledger_tests

class SplitLedgerTests(unittest.TestCase):
    setUp=ledger_tests.LedgerTests.setUp
    tearDown=ledger_tests.LedgerTests.tearDown
    apply=ledger_tests.LedgerTests.apply
    def test_explicit_ratio_changes_units_and_basis_but_not_cash_or_cooldown(self):
        parsed=tx.table(('Date;Type;Ticker;Cash;Currency;Ratio\n2025-01-02;split;EXA;0;NOK;2:1\n').encode())
        rows=tx.events(parsed,{'date':'Date','type':'Type','symbol':'Ticker','net_cash':'Cash','currency':'Currency','split_ratio':'Ratio'},'test')
        self.assertIsNone(rows[0]['error']);self.assertEqual(rows[0]['split_ratio'],2)
        import app
        snapshot=app.state()
        with app.connect() as db:result=tx.apply(db,rows,[{'id':2,'symbol':'EXA.OL'}],app.read_meta('ledger_state'),snapshot['manual_portfolio_preferences'],snapshot['positions'])
        self.assertEqual(result['profile']['cash_nok'],10000)
        self.assertEqual(result['last_trades'],{})
        position=app.state()['positions'][0];self.assertEqual(position['shares'],2);self.assertEqual(position['cost'],50)
    def test_ratio_is_never_inferred_from_broker_quantity(self):
        parsed=tx.table(('Date;Type;Ticker;Quantity;Cash;Currency\n2025-01-02;split;EXA;10;0;NOK\n').encode())
        rows=tx.events(parsed,{'date':'Date','type':'Type','symbol':'Ticker','net_cash':'Cash','currency':'Currency','quantity':'Quantity'},'test')
        self.assertTrue(rows[0]['error'])
