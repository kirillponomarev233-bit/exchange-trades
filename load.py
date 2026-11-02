"""Ручной запуск загрузки данных в базу.

Примеры:
  python load.py ets samples/ets_2026-09-02.xlsx samples/ets_2026-09-03.xlsx
  python load.py ets samples                      (все .xlsx из папки)
  python load.py ccx 2026-09-01 2026-09-30        (период, обе даты включительно)
  python load.py ccx-html saved_page.html         (разбор сохранённой страницы, для проверки)
  python load.py stats                            (сколько записей в базе)
  python load.py check                            (сверка сумм сделок с оборотом дня)
"""
import sys
from datetime import date
from pathlib import Path

import db
import ets_parser


def load_ets(conn, paths):
    files = []
    for p in map(Path, paths):
        files += sorted(p.glob("*.xlsx")) if p.is_dir() else [p]
    files = [f for f in files if not f.name.startswith("~$")]

    def work():
        added = skipped = 0
        for f in files:
            trades, totals = ets_parser.parse_workbook(f)
            a, s = db.save(conn, trades, totals)
            print(f"{f.name}: сделок {len(trades)}, добавлено {a}, дублей {s}")
            added, skipped = added + a, skipped + s
        return added, skipped

    return db.log_run(conn, "ETS", f"{len(files)} файл(ов)", work)


def load_ccx(conn, d_from, d_to):
    import ccx_parser

    def work():
        trades, totals = ccx_parser.fetch_range(d_from, d_to)
        return db.save(conn, trades, totals)

    return db.log_run(conn, "CCX", f"{d_from}..{d_to}", work)


def load_ccx_html(conn, path):
    import ccx_parser
    html = Path(path).read_text(encoding="utf-8")
    return db.log_run(conn, "CCX", f"file:{path}", lambda: db.save(conn, *ccx_parser.parse_html(html)))


def stats(conn):
    for row in conn.execute("""SELECT e.code, COUNT(t.id), MIN(t.trade_date), MAX(t.trade_date), ROUND(SUM(t.amount),2)
                               FROM exchanges e LEFT JOIN trades t ON t.exchange_id = e.id GROUP BY e.code"""):
        print(row)
    for row in conn.execute("SELECT id, started_at, source, period, added, skipped, status, message "
                            "FROM scrape_runs ORDER BY id DESC LIMIT 5"):
        print(row)


def check(conn):
    """По каждому дню: сумма сделок в базе против оборота дня с сайта и число сделок."""
    rows = conn.execute("""SELECT e.code, d.trade_date, d.day_turnover, d.deals_count,
                                  ROUND(SUM(t.amount), 2), SUM(t.deals_count), COUNT(t.id)
                           FROM daily_totals d JOIN exchanges e ON e.id = d.exchange_id
                           LEFT JOIN trades t ON t.exchange_id = d.exchange_id AND t.trade_date = d.trade_date
                           GROUP BY d.exchange_id, d.trade_date ORDER BY e.code, d.trade_date""").fetchall()
    bad = 0
    print("биржа  дата        оборот_сайта    сумма_в_базе   сделок(сайт/база)  строк  результат")
    for code, dt, turn, deals_site, total, deals_db, n in rows:
        ok = turn is not None and total is not None and abs(turn - total) < 0.5 and deals_site == deals_db
        bad += not ok
        print(f"{code:5} {dt}  {turn or 0:14.2f}  {total or 0:14.2f}   {deals_site}/{deals_db}  {n}  {'OK' if ok else '<-- РАСХОЖДЕНИЕ'}")
    print(f"Дней: {len(rows)}, с расхождениями: {bad}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    conn = db.connect()
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "ets":
        print(load_ets(conn, args))
    elif cmd == "ccx":
        print(load_ccx(conn, date.fromisoformat(args[0]), date.fromisoformat(args[1])))
    elif cmd == "ccx-html":
        print(load_ccx_html(conn, args[0]))
    elif cmd == "check":
        check(conn)
    elif cmd == "stats":
        stats(conn)
    else:
        print(__doc__)
