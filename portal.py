"""Веб-портал итогов торгов ETS и Каспий — на стандартной библиотеке Python.
Ничего устанавливать не нужно (кроме openpyxl для выгрузки в Excel, он уже есть в проекте).

Запуск:   python portal.py
Открыть:  http://127.0.0.1:8000
Остановить: Ctrl+C

Портал читает только локальную базу trades.db; к сайтам бирж не обращается.
"""
import io
import json
import os
import re
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import queries

BASE = Path(__file__).resolve().parent
DB = os.environ.get("TRADES_DB", str(BASE / "trades.db"))
HOST, PORT = "127.0.0.1", int(os.environ.get("PORT", 8000))
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

EXPORT_COLUMNS = [("date", "Дата"), ("exchange", "Биржа"), ("product", "Товар"), ("tnved", "ТН ВЭД"),
                  ("buyer", "Покупатель"), ("buyer_bin", "БИН покупателя"), ("buyer_broker", "Брокер покупателя"),
                  ("seller", "Продавец"), ("seller_bin", "БИН продавца"), ("seller_broker", "Брокер продавца"),
                  ("deals", "Сделок"), ("price_open", "Цена открытия"), ("price_close", "Цена закрытия"),
                  ("price_max", "Макс. цена"), ("price_min", "Мин. цена"), ("price_avg", "Средневзв. цена"),
                  ("amount", "Сумма, тг"), ("terms", "Условия поставки")]


class BadRequest(Exception):
    pass


def parse_filters(q):
    f = {"exchange": q.get("exchange") or None}
    for key in ("date_from", "date_to"):
        v = q.get(key) or None
        if v and not DATE_RE.match(v):
            raise BadRequest(f"Неверная дата в поле {key}: ожидается ГГГГ-ММ-ДД")
        f[key] = v
    for key in ("product", "participant", "broker", "delivery"):
        f[key] = (q.get(key) or "").strip()
    for key in ("amount_min", "amount_max"):
        try:
            f[key] = float(q[key]) if q.get(key) else None
        except ValueError:
            raise BadRequest(f"Неверное число в поле {key}")
    return f


def to_int(q, key, default, lo, hi):
    try:
        return min(max(int(q.get(key, default)), lo), hi)
    except ValueError:
        raise BadRequest(f"Неверное число в поле {key}")


def make_xlsx(rows):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Итоги торгов"
    ws.append([title for _, title in EXPORT_COLUMNS])
    for r in rows:
        ws.append([r.get(key) for key, _ in EXPORT_COLUMNS])
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "TradesPortal/1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def reply(self, body, ctype, status=200, extra=None):
        if isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def reply_json(self, data, status=200):
        self.reply(json.dumps(data, ensure_ascii=False), "application/json; charset=utf-8", status)

    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
        try:
            if url.path in ("/", "/index.html"):
                return self.reply((BASE / "static" / "index.html").read_bytes(), "text/html; charset=utf-8")
            if url.path in ("/api/trades", "/api/export.xlsx", "/api/status"):
                if not Path(DB).exists():
                    return self.reply_json({"error": "База trades.db не найдена. Сначала загрузите данные (load.py)."}, 500)
                conn = queries.open_db(DB)
                try:
                    if url.path == "/api/status":
                        return self.reply_json(queries.status(conn))
                    f = parse_filters(q)
                    sort, order = q.get("sort", "date"), q.get("order", "desc")
                    if url.path == "/api/trades":
                        return self.reply_json(queries.search_trades(
                            conn, f, sort, order, to_int(q, "page", 1, 1, 10**9), to_int(q, "page_size", 50, 1, 200)))
                    rows = queries.export_rows(conn, f, sort, order)
                    return self.reply(make_xlsx(rows),
                                      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                                      extra={"Content-Disposition": 'attachment; filename="trades.xlsx"'})
                finally:
                    conn.close()
            self.reply_json({"error": "Не найдено"}, 404)
        except BadRequest as e:
            self.reply_json({"error": str(e)}, 400)
        except Exception as e:                       # сервер не должен падать от одного плохого запроса
            sys.stderr.write(f"Ошибка: {type(e).__name__}: {e}\n")
            self.reply_json({"error": "Внутренняя ошибка сервера"}, 500)


if __name__ == "__main__":
    print(f"Портал: http://{HOST}:{PORT}   (база: {DB})\nОстановить: Ctrl+C")
    try:
        ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\nОстановлено")
