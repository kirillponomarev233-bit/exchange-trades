"""Парсер итогов торгов биржи ETS (ets.kz) из Excel-файлов.

Один файл .xlsx = один торговый день. Структура листа:
  строка 3: заголовок «... ИТОГИ ТОРГОВ ДД.ММ.ГГГГ»
  строка 4: шапка
  далее: строки товаров (колонки B..Q), в конце строка «Итого»
Колонки читаем по позиции.
"""
import re
from datetime import datetime

import openpyxl

EXCHANGE = "ETS"
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
BASIS_RE = re.compile(r"\b(EXW|FCA|CPT|CIP|DAP|DPU|DDP|FOB|CFR|CIF|FAS|DAT)\b", re.I)

# позиция колонки (A=1) -> поле
COLS = {2: "buyer", 3: "buyer_bin", 4: "buyer_broker",
        5: "seller", 6: "seller_bin", 7: "seller_broker",
        8: "product", 9: "tnved", 10: "product_code", 11: "deals_count",
        12: "price_open", 13: "price_close", 14: "price_max",
        15: "price_min", 16: "price_avg", 17: "amount"}


def _str(v):
    if v is None:
        return None
    s = str(v).replace("\xa0", " ").strip()
    return s or None


def _num(v):
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).replace("\xa0", "").replace(" ", "").replace(",", "."))
    except ValueError:
        return None


def parse_workbook(path):
    """Возвращает (сделки, итоги_по_дням) из файла ETS."""
    wb = openpyxl.load_workbook(path, data_only=True)
    trades, totals = [], []
    for ws in wb.worksheets:
        # дата торгов — из заголовка (строки 1-4), запасной вариант — имя листа/файла
        trade_date = None
        for row in ws.iter_rows(min_row=1, max_row=4, values_only=True):
            for v in row:
                m = DATE_RE.search(str(v)) if v else None
                if m:
                    trade_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
        if trade_date is None:
            m = DATE_RE.search(str(path))
            if not m:
                continue
            trade_date = f"{m.group(3)}-{m.group(2)}-{m.group(1)}"

        day_sum = 0.0
        day_deals = 0
        for row in ws.iter_rows(min_row=5, values_only=True):
            cells = {name: row[pos - 1] if pos - 1 < len(row) else None for pos, name in COLS.items()}
            if _str(cells["product"]) and _str(cells["product"]).lower().startswith("итого"):
                total_row = _num(cells["amount"])
                if total_row is not None:
                    day_sum = total_row           # контрольная сумма из файла
                continue
            if not _str(cells["buyer"]) and not _str(cells["seller"]):
                continue                          # пустая строка
            rec = {
                "exchange": EXCHANGE, "trade_date": trade_date,
                "buyer": _str(cells["buyer"]), "buyer_bin": _str(cells["buyer_bin"]),
                "buyer_broker": _str(cells["buyer_broker"]),
                "seller": _str(cells["seller"]), "seller_bin": _str(cells["seller_bin"]),
                "seller_broker": _str(cells["seller_broker"]),
                "product": _str(cells["product"]), "tnved": _str(cells["tnved"]),
                "product_code": _str(cells["product_code"]),
                "deals_count": int(_num(cells["deals_count"]) or 0),
                "price_open": _num(cells["price_open"]), "price_close": _num(cells["price_close"]),
                "price_max": _num(cells["price_max"]), "price_min": _num(cells["price_min"]),
                "price_avg": _num(cells["price_avg"]), "amount": _num(cells["amount"]),
            }
            m = BASIS_RE.search(rec["product"] or "")
            rec["delivery_terms"] = m.group(1).upper() if m else None
            trades.append(rec)
            day_deals += rec["deals_count"]
        totals.append({"exchange": EXCHANGE, "trade_date": trade_date,
                       "day_turnover": day_sum or None, "deals_count": day_deals})
    return trades, totals


if __name__ == "__main__":
    import sys
    tr, tt = parse_workbook(sys.argv[1])
    print("сделок:", len(tr), "| сумма по строкам:", round(sum(t["amount"] or 0 for t in tr), 2))
    print("итоги дня:", tt)
