"""Веб-портал итогов торгов ETS и Каспий.

Запуск:   uvicorn server:app --reload
Открыть:  http://127.0.0.1:8000
Портал читает только локальную базу trades.db; к сайтам бирж не обращается.
"""
import io
import os
from pathlib import Path

import openpyxl
from fastapi import FastAPI, Query
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import queries

BASE = Path(__file__).parent
DB = os.environ.get("TRADES_DB", str(BASE / "trades.db"))
DATE = r"^\d{4}-\d{2}-\d{2}$"

app = FastAPI(title="Итоги торгов ETS и Каспий")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")


def _filters(exchange, date_from, date_to, product, participant, broker, amount_min, amount_max, delivery):
    return {"exchange": exchange, "date_from": date_from, "date_to": date_to,
            "product": (product or "").strip(), "participant": (participant or "").strip(),
            "broker": (broker or "").strip(), "amount_min": amount_min, "amount_max": amount_max,
            "delivery": (delivery or "").strip()}


@app.get("/")
def index():
    return FileResponse(BASE / "static" / "index.html")


@app.get("/api/trades")
def trades(exchange: str | None = None,
           date_from: str | None = Query(None, pattern=DATE),
           date_to: str | None = Query(None, pattern=DATE),
           product: str | None = None, participant: str | None = None, broker: str | None = None,
           amount_min: float | None = None, amount_max: float | None = None,
           delivery: str | None = None,
           sort: str = "date", order: str = "desc",
           page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=200)):
    f = _filters(exchange, date_from, date_to, product, participant, broker, amount_min, amount_max, delivery)
    conn = queries.open_db(DB)
    try:
        return queries.search_trades(conn, f, sort, order, page, page_size)
    finally:
        conn.close()


@app.get("/api/status")
def status():
    conn = queries.open_db(DB)
    try:
        return queries.status(conn)
    finally:
        conn.close()


EXPORT_COLUMNS = [("date", "Дата"), ("exchange", "Биржа"), ("product", "Товар"), ("tnved", "ТН ВЭД"),
                  ("buyer", "Покупатель"), ("buyer_bin", "БИН покупателя"), ("buyer_broker", "Брокер покупателя"),
                  ("seller", "Продавец"), ("seller_bin", "БИН продавца"), ("seller_broker", "Брокер продавца"),
                  ("deals", "Сделок"), ("price_open", "Цена открытия"), ("price_close", "Цена закрытия"),
                  ("price_max", "Макс. цена"), ("price_min", "Мин. цена"), ("price_avg", "Средневзв. цена"),
                  ("amount", "Сумма, тг"), ("terms", "Условия поставки")]


@app.get("/api/export.xlsx")
def export(exchange: str | None = None,
           date_from: str | None = Query(None, pattern=DATE),
           date_to: str | None = Query(None, pattern=DATE),
           product: str | None = None, participant: str | None = None, broker: str | None = None,
           amount_min: float | None = None, amount_max: float | None = None,
           delivery: str | None = None, sort: str = "date", order: str = "desc"):
    """Выгрузка текущей выборки с фильтрами в Excel (до 50 000 строк)."""
    f = _filters(exchange, date_from, date_to, product, participant, broker, amount_min, amount_max, delivery)
    conn = queries.open_db(DB)
    try:
        rows = queries.export_rows(conn, f, sort, order)
    finally:
        conn.close()
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Итоги торгов"
    ws.append([title for _, title in EXPORT_COLUMNS])
    for r in rows:
        ws.append([r.get(key) for key, _ in EXPORT_COLUMNS])
    ws.freeze_panes = "A2"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="trades.xlsx"'})
