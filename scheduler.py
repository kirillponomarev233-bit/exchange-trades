"""Планировщик: ежедневный автозапуск сбора данных и ручной запуск.

Запуск по расписанию (оставить окно терминала открытым):
    python scheduler.py

Ручной запуск (один раз и выход):
    python scheduler.py --once                                   # за последние N дней из config.ini
    python scheduler.py --once --from 2026-09-01 --to 2026-09-30 # первоначальная загрузка истории
    python scheduler.py --once --only ccx                        # только одна биржа (ccx или ets)

Расписание и параметры — в файле config.ini. Результат каждого запуска пишется в таблицу
scrape_runs (видна на странице «Состояние данных» портала).
Вместо постоянно запущенного окна можно настроить «Планировщик заданий Windows» на команду
`python scheduler.py --once` (см. README).
"""
import argparse
import configparser
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import ccx_parser
import db
import ets_fetch

BASE_DIR = Path(__file__).resolve().parent
CONFIG = BASE_DIR / "config.ini"


def load_config(path=CONFIG):
    cp = configparser.ConfigParser(inline_comment_prefixes=("#", ";"))
    if not cp.read(path, encoding="utf-8"):
        raise SystemExit(f"Не найден файл настроек: {path}")
    return cp


def db_path(cfg):
    return str((BASE_DIR / cfg.get("database", "path", fallback="trades.db")))


def run_all(conn, cfg, d_from=None, d_to=None, only=None, log=print):
    """Запускает сбор данных. Возвращает список (источник, статус, добавлено, пропущено, сообщение)."""
    today = date.today()
    pause = cfg.getfloat("http", "pause_seconds", fallback=1.5)
    ccx_parser.PAUSE_SECONDS = pause
    results = []

    def run(source, lookback, job):
        a = d_from or today - timedelta(days=lookback)
        b = d_to or today
        log(f"=== {source}: {a} .. {b}")
        status, added, skipped, msg = db.log_run(conn, source, f"{a}..{b}", lambda: job(a, b))
        results.append((source, status, added, skipped, msg))

    if only in (None, "ccx") and cfg.getboolean("ccx", "enabled", fallback=True):
        run("CCX", cfg.getint("ccx", "lookback_days", fallback=7),
            lambda a, b: db.save(conn, *ccx_parser.fetch_range(a, b, log=log)))
    if only in (None, "ets") and cfg.getboolean("ets", "enabled", fallback=True):
        run("ETS", cfg.getint("ets", "lookback_days", fallback=7),
            lambda a, b: ets_fetch.sync(conn, a, b, BASE_DIR / cfg.get("ets", "folder", fallback="data/ets"),
                                        pause, cfg.get("ets", "base_url", fallback=ets_fetch.BASE), log))
    for source, status, added, skipped, msg in results:
        log(f"{source}: {status}, добавлено {added}, дублей {skipped}" + (f" — {msg}" if msg else ""))
    return results


def ran_today(conn):
    """Был ли сегодня успешный запуск, захвативший сегодняшнюю дату."""
    row = conn.execute("SELECT 1 FROM scrape_runs WHERE status IN ('ok', 'warning') AND period LIKE ? LIMIT 1",
                       (f"%..{date.today().isoformat()}",)).fetchone()
    return row is not None


def serve(cfg):
    run_at = datetime.strptime(cfg.get("schedule", "run_at", fallback="07:30"), "%H:%M").time()
    retry = timedelta(minutes=cfg.getint("schedule", "retry_minutes", fallback=30))
    print(f"Планировщик запущен. Ежедневный запуск в {run_at:%H:%M}. Остановить: Ctrl+C")
    last_attempt = None
    while True:
        now = datetime.now()
        if now.time() >= run_at and (last_attempt is None or now - last_attempt >= retry):
            conn = db.connect(db_path(cfg))
            try:
                if not ran_today(conn):
                    last_attempt = now
                    run_all(conn, cfg)
            finally:
                conn.close()
        time.sleep(30)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Сбор итогов торгов ETS и Каспий")
    ap.add_argument("--once", action="store_true", help="выполнить один запуск и выйти")
    ap.add_argument("--from", dest="d_from", type=date.fromisoformat, help="дата начала ГГГГ-ММ-ДД")
    ap.add_argument("--to", dest="d_to", type=date.fromisoformat, help="дата конца ГГГГ-ММ-ДД")
    ap.add_argument("--only", choices=["ccx", "ets"], help="только одна биржа")
    args = ap.parse_args(argv)
    cfg = load_config()
    if args.once or args.d_from or args.d_to:
        conn = db.connect(db_path(cfg))
        results = run_all(conn, cfg, args.d_from, args.d_to, args.only)
        conn.close()
        sys.exit(1 if any(r[1] != "ok" for r in results) else 0)
    try:
        serve(cfg)
    except KeyboardInterrupt:
        print("\nПланировщик остановлен")


if __name__ == "__main__":
    main()
