"""Выгрузка базы в SQL-скрипт и восстановление из него.

    python dump_db.py                 # trades.db -> trades_dump.sql
    python dump_db.py --restore       # trades_dump.sql -> новая trades.db (существующая не перезаписывается)
"""
import argparse
import sqlite3
import sys
from pathlib import Path

DB, DUMP = Path("trades.db"), Path("trades_dump.sql")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--restore", action="store_true")
    ap.add_argument("--db", default=str(DB))
    ap.add_argument("--sql", default=str(DUMP))
    a = ap.parse_args()
    if a.restore:
        if Path(a.db).exists():
            sys.exit(f"{a.db} уже существует — удалите или переименуйте его перед восстановлением")
        conn = sqlite3.connect(a.db)
        conn.executescript(Path(a.sql).read_text(encoding="utf-8"))
        conn.close()
        print(f"База восстановлена: {a.db}")
    else:
        conn = sqlite3.connect(f"file:{a.db}?mode=ro", uri=True)
        with open(a.sql, "w", encoding="utf-8") as f:
            for line in conn.iterdump():
                f.write(line + "\n")
        n = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
        print(f"Выгружено в {a.sql}; сделок в базе: {n}")


if __name__ == "__main__":
    main()
