"""Запросы к базе для портала: поиск сделок с фильтрами, сортировкой, пагинацией и состояние данных.

Портал работает только с локальной базой (trades.db) — к сайтам бирж не обращается.
"""
import sqlite3

DB_PATH = "trades.db"

# Допустимые поля сортировки (белый список: в SQL подставляется только значение отсюда)
SORT_COLUMNS = {
    "date": "t.trade_date",
    "exchange": "e.code",
    "product": "p.name",
    "buyer": "b.name",
    "seller": "s.name",
    "buyer_broker": "bb.name",
    "seller_broker": "sb.name",
    "deals": "t.deals_count",
    "price_avg": "t.price_avg",
    "amount": "t.amount",
    "terms": "t.delivery_terms",
}

FROM_SQL = """
    FROM trades t
    JOIN exchanges e          ON e.id  = t.exchange_id
    LEFT JOIN products p      ON p.id  = t.product_id
    LEFT JOIN participants b  ON b.id  = t.buyer_id
    LEFT JOIN participants s  ON s.id  = t.seller_id
    LEFT JOIN brokers bb      ON bb.id = t.buyer_broker_id
    LEFT JOIN brokers sb      ON sb.id = t.seller_broker_id
"""


def open_db(path=DB_PATH):
    """Соединение только для чтения. Поиск без учёта регистра (в т.ч. для кириллицы)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    # в SQLite LIKE не понимает регистр кириллицы, поэтому своя функция
    conn.create_function("has", 2, lambda text, needle:
                         1 if text and needle.casefold() in str(text).casefold() else 0)
    return conn


def _where(f):
    """Собирает WHERE и параметры из фильтров. Все значения — только через параметры (?)."""
    sql, args = [], []

    def add(cond, *params):
        sql.append(cond)
        args.extend(params)

    if f.get("exchange") in ("ETS", "CCX"):
        add("e.code = ?", f["exchange"])
    if f.get("date_from"):
        add("t.trade_date >= ?", f["date_from"])
    if f.get("date_to"):
        add("t.trade_date <= ?", f["date_to"])
    if f.get("product"):
        add("(has(p.name, ?) OR has(p.tnved, ?) OR has(t.product_code, ?))",
            f["product"], f["product"], f["product"])
    if f.get("participant"):            # продавец или покупатель: по названию или БИН
        q = f["participant"]
        add("(has(b.name, ?) OR has(b.bin, ?) OR has(s.name, ?) OR has(s.bin, ?))", q, q, q, q)
    if f.get("broker"):
        add("(has(bb.name, ?) OR has(sb.name, ?))", f["broker"], f["broker"])
    if f.get("amount_min") is not None:
        add("t.amount >= ?", f["amount_min"])
    if f.get("amount_max") is not None:
        add("t.amount <= ?", f["amount_max"])
    if f.get("delivery"):               # место/базис поставки: код (EXW) или текст в названии товара (ETS)
        add("(has(t.delivery_terms, ?) OR has(p.name, ?))", f["delivery"], f["delivery"])
    return (" WHERE " + " AND ".join(sql)) if sql else "", args


def _select(conn, f, sort, order, limit, offset):
    col = SORT_COLUMNS.get(sort, SORT_COLUMNS["date"])
    direction = "ASC" if str(order).lower() == "asc" else "DESC"
    where, args = _where(f)
    # вторичная сортировка делает порядок стабильным между страницами
    rows = conn.execute(
        f"""SELECT t.id, t.trade_date AS date, e.code AS exchange, p.name AS product, p.tnved,
                   t.product_code, b.name AS buyer, b.bin AS buyer_bin, s.name AS seller, s.bin AS seller_bin,
                   bb.name AS buyer_broker, sb.name AS seller_broker, t.deals_count AS deals,
                   t.price_open, t.price_close, t.price_max, t.price_min, t.price_avg,
                   t.amount, t.delivery_terms AS terms
            {FROM_SQL} {where}
            ORDER BY {col} {direction}, t.trade_date DESC, t.id DESC
            LIMIT ? OFFSET ?""", args + [limit, offset]).fetchall()
    return [dict(r) for r in rows]


def search_trades(conn, f, sort="date", order="desc", page=1, page_size=50):
    page = max(1, int(page))
    page_size = min(max(1, int(page_size)), 200)
    where, args = _where(f)
    total, amount_sum = conn.execute(
        f"SELECT COUNT(*), COALESCE(SUM(t.amount), 0) {FROM_SQL} {where}", args).fetchone()
    return {
        "total": total, "amount_sum": amount_sum, "page": page, "page_size": page_size,
        "pages": max(1, -(-total // page_size)),
        "rows": _select(conn, f, sort, order, page_size, (page - 1) * page_size),
    }


def export_rows(conn, f, sort="date", order="desc", limit=50000):
    """Все строки текущей выборки (для выгрузки в Excel), но не больше limit."""
    return _select(conn, f, sort, order, limit, 0)


def status(conn):
    """Данные для страницы состояния: последняя дата, число записей, последний запуск по каждой бирже."""
    exchanges = []
    for r in conn.execute("""SELECT e.id, e.code, e.name, COUNT(t.id) AS records,
                                    MIN(t.trade_date) AS first_date, MAX(t.trade_date) AS last_date,
                                    COALESCE(SUM(t.amount), 0) AS amount
                             FROM exchanges e LEFT JOIN trades t ON t.exchange_id = e.id
                             GROUP BY e.id ORDER BY e.code"""):
        last_run = conn.execute(
            "SELECT started_at, finished_at, period, added, skipped, status, message "
            "FROM scrape_runs WHERE source = ? ORDER BY id DESC LIMIT 1", (r["code"],)).fetchone()
        exchanges.append({**dict(r), "last_run": dict(last_run) if last_run else None})
    runs = [dict(r) for r in conn.execute(
        "SELECT id, started_at, finished_at, source, period, added, skipped, status, message "
        "FROM scrape_runs ORDER BY id DESC LIMIT 20")]
    total = conn.execute("SELECT COUNT(*) FROM trades").fetchone()[0]
    return {"total_records": total, "exchanges": exchanges, "runs": runs}
