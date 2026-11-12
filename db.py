"""База данных итогов торгов (SQLite, стандартный модуль sqlite3).

Таблицы:
  exchanges      — биржи (ETS, CCX)
  products       — товары (код ТН ВЭД + название)
  participants   — покупатели и продавцы (название + БИН)
  brokers        — брокеры
  trades         — сделки (строки итогов торгов), уникальный dedup_hash
  daily_totals   — оборот за день по бирже
  scrape_runs    — журнал запусков парсеров
"""
import hashlib
import sqlite3
from datetime import datetime

DB_PATH = "trades.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS exchanges (
    id   INTEGER PRIMARY KEY,
    code TEXT NOT NULL UNIQUE,          -- ETS / CCX
    name TEXT
);
CREATE TABLE IF NOT EXISTS products (
    id    INTEGER PRIMARY KEY,
    tnved TEXT,
    name  TEXT NOT NULL,
    UNIQUE (tnved, name)
);
CREATE TABLE IF NOT EXISTS participants (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    bin  TEXT,
    UNIQUE (name, bin)
);
CREATE TABLE IF NOT EXISTS brokers (
    id   INTEGER PRIMARY KEY,
    name TEXT NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS trades (
    id               INTEGER PRIMARY KEY,
    exchange_id      INTEGER NOT NULL REFERENCES exchanges(id),
    trade_date       TEXT    NOT NULL,         -- ГГГГ-ММ-ДД
    product_id       INTEGER REFERENCES products(id),
    buyer_id         INTEGER REFERENCES participants(id),
    seller_id        INTEGER REFERENCES participants(id),
    buyer_broker_id  INTEGER REFERENCES brokers(id),
    seller_broker_id INTEGER REFERENCES brokers(id),
    deals_count      INTEGER,
    price_open       REAL,
    price_close      REAL,
    price_max        REAL,
    price_min        REAL,
    price_avg        REAL,
    amount           REAL,                     -- сумма сделки, тг
    delivery_terms   TEXT,                     -- базис поставки (EXW, FCA...)
    product_code     TEXT,                     -- код товара на бирже (ETS)
    dedup_hash       TEXT    NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS daily_totals (
    exchange_id   INTEGER NOT NULL REFERENCES exchanges(id),
    trade_date    TEXT    NOT NULL,
    day_turnover  REAL,
    deals_count   INTEGER,
    PRIMARY KEY (exchange_id, trade_date)
);
CREATE TABLE IF NOT EXISTS scrape_runs (
    id          INTEGER PRIMARY KEY,
    started_at  TEXT NOT NULL,
    finished_at TEXT,
    source      TEXT NOT NULL,
    period      TEXT,
    added       INTEGER DEFAULT 0,
    skipped     INTEGER DEFAULT 0,
    status      TEXT,                          -- ok / error
    message     TEXT
);
-- индексы под фильтры портала
CREATE INDEX IF NOT EXISTS ix_trades_date     ON trades(trade_date);
CREATE INDEX IF NOT EXISTS ix_trades_exchange ON trades(exchange_id, trade_date);
CREATE INDEX IF NOT EXISTS ix_trades_product  ON trades(product_id);
CREATE INDEX IF NOT EXISTS ix_trades_buyer    ON trades(buyer_id);
CREATE INDEX IF NOT EXISTS ix_trades_seller   ON trades(seller_id);
CREATE INDEX IF NOT EXISTS ix_trades_bbroker  ON trades(buyer_broker_id);
CREATE INDEX IF NOT EXISTS ix_trades_sbroker  ON trades(seller_broker_id);
CREATE INDEX IF NOT EXISTS ix_trades_amount   ON trades(amount);
CREATE INDEX IF NOT EXISTS ix_trades_terms    ON trades(delivery_terms);
CREATE INDEX IF NOT EXISTS ix_participants_bin  ON participants(bin);
CREATE INDEX IF NOT EXISTS ix_products_name     ON products(name);
"""

EXCHANGES = {"ETS": "Товарная биржа ETS", "CCX": "Биржа Каспий (CCX)"}


def connect(path=DB_PATH):
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    for code, name in EXCHANGES.items():
        conn.execute("INSERT OR IGNORE INTO exchanges(code, name) VALUES (?, ?)", (code, name))
    conn.commit()
    return conn


def dedup_hash(rec):
    """Хеш строки: повторная загрузка той же строки не создаёт дубль."""
    parts = [rec.get(k) for k in (
        "exchange", "trade_date", "tnved", "product", "product_code",
        "buyer", "buyer_bin", "buyer_broker", "seller", "seller_bin",
        "seller_broker", "amount", "price_avg", "deals_count", "delivery_terms")]
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()


class _Refs:
    """Справочники: найти или создать запись, вернуть id (с кэшем)."""
    def __init__(self, conn):
        self.conn, self.cache = conn, {}

    def _get(self, table, cols, values):
        if all(v is None for v in values):
            return None
        key = (table, values)
        if key not in self.cache:
            where = " AND ".join(f"{c} IS ?" for c in cols)
            row = self.conn.execute(f"SELECT id FROM {table} WHERE {where}", values).fetchone()
            if row is None:
                cur = self.conn.execute(
                    f"INSERT INTO {table}({','.join(cols)}) VALUES ({','.join('?' * len(cols))})", values)
                row = (cur.lastrowid,)
            self.cache[key] = row[0]
        return self.cache[key]

    def product(self, tnved, name):
        return self._get("products", ("tnved", "name"), (tnved, name)) if name else None

    def participant(self, name, bin_):
        return self._get("participants", ("name", "bin"), (name, bin_)) if name else None

    def broker(self, name):
        return self._get("brokers", ("name",), (name,)) if name else None


def save(conn, trades, totals=()):
    """Сохраняет сделки и итоги дня. Возвращает (добавлено, пропущено_как_дубли)."""
    refs = _Refs(conn)
    ex = {code: id_ for id_, code in conn.execute("SELECT id, code FROM exchanges")}   # код биржи -> id
    added = skipped = 0
    seen = {}                                   # сколько раз уже встретилась такая строка в этой загрузке
    for t in trades:
        base = dedup_hash(t)
        n = seen[base] = seen.get(base, 0) + 1
        # одинаковые строки одного дня — это разные сделки: 2-й и далее получают номер.
        # 1-я сохраняет прежний хеш, поэтому ранее загруженные данные не дублируются.
        h = base if n == 1 else hashlib.sha1(f"{base}#{n}".encode("utf-8")).hexdigest()
        cur = conn.execute(
            """INSERT OR IGNORE INTO trades(
                   exchange_id, trade_date, product_id, buyer_id, seller_id,
                   buyer_broker_id, seller_broker_id, deals_count,
                   price_open, price_close, price_max, price_min, price_avg,
                   amount, delivery_terms, product_code, dedup_hash)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (ex[t["exchange"]], t["trade_date"],
             refs.product(t.get("tnved"), t.get("product")),
             refs.participant(t.get("buyer"), t.get("buyer_bin")),
             refs.participant(t.get("seller"), t.get("seller_bin")),
             refs.broker(t.get("buyer_broker")), refs.broker(t.get("seller_broker")),
             t.get("deals_count"), t.get("price_open"), t.get("price_close"),
             t.get("price_max"), t.get("price_min"), t.get("price_avg"),
             t.get("amount"), t.get("delivery_terms"), t.get("product_code"), h))
        if cur.rowcount:
            added += 1
        else:
            skipped += 1
    for d in totals:
        conn.execute(
            "INSERT OR REPLACE INTO daily_totals(exchange_id, trade_date, day_turnover, deals_count) VALUES (?,?,?,?)",
            (ex[d["exchange"]], d["trade_date"], d["day_turnover"], d["deals_count"]))
    conn.commit()
    return added, skipped


def log_run(conn, source, period, fn):
    """Выполняет fn() -> (добавлено, пропущено), пишет результат в журнал запусков."""
    started = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute("INSERT INTO scrape_runs(started_at, source, period, status) VALUES (?,?,?, 'running')",
                       (started, source, period))
    run_id = cur.lastrowid
    conn.commit()
    try:
        result = fn()
        added, skipped = result[0], result[1]
        msg = result[2] if len(result) > 2 else None
        status = "warning" if msg else "ok"     # warning: часть данных не обработана, остальное сохранено
    except Exception as e:                      # ошибка не должна терять уже собранное
        conn.rollback()
        added = skipped = 0
        status, msg = "error", f"{type(e).__name__}: {e}"
    conn.execute("UPDATE scrape_runs SET finished_at=?, added=?, skipped=?, status=?, message=? WHERE id=?",
                 (datetime.now().isoformat(timespec="seconds"), added, skipped, status, msg, run_id))
    conn.commit()
    return status, added, skipped, msg
