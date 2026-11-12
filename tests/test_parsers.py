"""Тесты: python -m unittest discover -s tests -v   (из корня проекта)"""
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
FIX = Path(__file__).resolve().parent / "fixtures"

import ccx_parser  # noqa: E402
import db  # noqa: E402
import ets_parser  # noqa: E402
import queries  # noqa: E402
import ets_fetch  # noqa: E402


class CcxParser(unittest.TestCase):
    def setUp(self):
        self.trades, self.totals = ccx_parser.parse_html((FIX / "ccx_page.html").read_text(encoding="utf-8"))

    def test_rows_parsed(self):
        self.assertGreater(len(self.trades), 0)
        t = self.trades[0]
        self.assertEqual(t["exchange"], "CCX")
        self.assertRegex(t["trade_date"], r"^\d{4}-\d{2}-\d{2}$")

    def test_bin_split(self):
        self.assertEqual(ccx_parser._split_bin("ТОО KARA TASS 221140037278"), ("ТОО KARA TASS", "221140037278"))
        self.assertEqual(ccx_parser._split_bin("-"), (None, None))

    def test_totals_not_below_deals(self):
        # на сохранённой странице может быть лишь часть сделок дня (пагинация), поэтому сумма сделок
        # не должна превышать оборот дня; полная сверка по базе — `python load.py check`
        self.assertGreater(len(self.totals), 0)
        for d in self.totals:
            s = sum(t["amount"] or 0 for t in self.trades if t["trade_date"] == d["trade_date"])
            self.assertLessEqual(s, d["day_turnover"] + 1.0)


class EtsParser(unittest.TestCase):
    def test_workbook(self):
        trades, totals = ets_parser.parse_workbook(FIX / "ets_2026-09-02.xlsx")
        self.assertGreater(len(trades), 0)
        self.assertEqual(trades[0]["exchange"], "ETS")
        self.assertEqual(trades[0]["trade_date"], "2026-09-02")

    def test_file_date(self):
        from datetime import date
        self.assertEqual(ets_fetch.file_date("http://x/a.xlsx", "Итоги торгов 02.09.2026"), date(2026, 9, 2))
        self.assertIsNone(ets_fetch.file_date("http://x/a.xlsx", "без даты"))


class Database(unittest.TestCase):
    def setUp(self):
        self.conn = db.connect(":memory:")
        self.trades, self.totals = ccx_parser.parse_html((FIX / "ccx_page.html").read_text(encoding="utf-8"))

    def test_dedup_on_reload(self):
        a1, _ = db.save(self.conn, self.trades, self.totals)
        a2, s2 = db.save(self.conn, self.trades, self.totals)
        self.assertEqual(a1, len(self.trades))
        self.assertEqual((a2, s2), (0, len(self.trades)))

    def test_identical_rows_kept(self):
        t = dict(self.trades[0])
        db.save(self.conn, [t, dict(t)])
        n = self.conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        self.assertEqual(n, 2)

    def test_run_journal_warning(self):
        st, a, s, m = db.log_run(self.conn, "X", "p", lambda: (1, 0, "часть файлов не обработана"))
        self.assertEqual(st, "warning")
        st, *_ = db.log_run(self.conn, "X", "p", lambda: 1 / 0)
        self.assertEqual(st, "error")


if __name__ == "__main__":
    unittest.main()
