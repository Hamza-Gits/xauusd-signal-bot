"""Unit tests for signal_parser. Run from project root:

    python -m unittest tests/test_parser.py
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from signal_parser import parse_signal


FORMAT_1 = """GOLD BUY 4673
🔷TP1 - 4675.4
🔷TP2 - 4679
🔷TP3 - 4683
🔶SL - 4664"""

FORMAT_2 = """XAUUSD | Potential upward movement
XAUUSD | BUY 4672
❌ Stop Loss 4665 (70 pips)
✅TP1 4675
✅TP2 4680
✅TP3 4685"""

FORMAT_1_SELL = """GOLD SELL 4673
🔷TP1 - 4670
🔷TP2 - 4665
🔷TP3 - 4660
🔶SL - 4680"""


class TestSignalParser(unittest.TestCase):
    def test_format1_buy(self):
        s = parse_signal(FORMAT_1)
        self.assertIsNotNone(s)
        self.assertEqual(s.direction, "BUY")
        self.assertEqual(s.entry, 4673.0)
        self.assertEqual(s.stop_loss, 4664.0)
        self.assertEqual(s.tp1, 4675.4)
        self.assertEqual(s.tp2, 4679.0)
        self.assertEqual(s.tp3, 4683.0)

    def test_format2_buy(self):
        s = parse_signal(FORMAT_2)
        self.assertIsNotNone(s)
        self.assertEqual(s.direction, "BUY")
        self.assertEqual(s.entry, 4672.0)
        self.assertEqual(s.stop_loss, 4665.0)
        self.assertEqual(s.tp1, 4675.0)
        self.assertEqual(s.tp2, 4680.0)
        self.assertEqual(s.tp3, 4685.0)

    def test_format1_sell(self):
        s = parse_signal(FORMAT_1_SELL)
        self.assertIsNotNone(s)
        self.assertEqual(s.direction, "SELL")
        self.assertEqual(s.entry, 4673.0)
        self.assertEqual(s.stop_loss, 4680.0)
        self.assertEqual(s.tp1, 4670.0)

    def test_garbage_returns_none(self):
        self.assertIsNone(parse_signal("hello world"))
        self.assertIsNone(parse_signal(""))
        self.assertIsNone(parse_signal("just some random chat about gold prices"))

    def test_missing_sl_returns_none(self):
        text = """GOLD BUY 4673
🔷TP1 - 4675.4"""
        self.assertIsNone(parse_signal(text))

    def test_buy_with_invalid_sl_above_entry(self):
        text = """GOLD BUY 4673
🔷TP1 - 4675
🔶SL - 4680"""
        # SL above entry on a BUY is nonsense — parser must reject
        self.assertIsNone(parse_signal(text))


if __name__ == "__main__":
    unittest.main()
