"""Парсер итогов торгов биржи Каспий (ccx.kz).

Данные приходят готовой HTML-таблицей; период и страница задаются в адресе:
https://ccx.kz/trading-and-analytics/trading-results?date_from=ГГГГ-ММ-ДД&date_to=ГГГГ-ММ-ДД&page=N

Колонки читаем ПО ПОЗИЦИИ (16 штук), а не по тексту заголовков,
чтобы парсер не зависел от языка страницы (kz / ru / en).
"""
import hashlib
import re
import time
from datetime import date, datetime

import requests
from bs4 import BeautifulSoup

URL = "https://ccx.kz/trading-and-analytics/trading-results"
EXCHANGE = "CCX"
HEADERS = {"User-Agent": "Mozilla/5.0 (student practice project, trading results parser)"}
PAUSE_SECONDS = 1.5   # пауза между запросами: не нагружаем чужой сайт
MAX_PAGES = 200       # защита от бесконечного цикла

# Позиции столбцов в таблице
COLS = ["date", "day_turnover", "tnved", "product", "price_open", "price_close",
        "price_max", "price_min", "price_avg", "amount", "buyer_broker",
        "buyer", "seller_broker", "seller", "deals_count", "delivery_terms"]
BIN_RE = re.compile(r"^(.*?)\s*(\d{12})$")


def _text(td):
    return td.get_text(" ", strip=True).replace("\xa0", " ")


def _num(s):
    s = (s or "").replace("\xa0", "").replace(" ", "").replace(",", ".")
    if s in ("", "-", "—"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _none(s):
    s = (s or "").strip()
    return None if s in ("", "-", "—") else s


def _split_bin(s):
    """'ТОО KARA TASS 221140037278' -> ('ТОО KARA TASS', '221140037278')."""
    s = _none(s)
    if not s:
        return None, None
    m = BIN_RE.match(s)
    return (m.group(1).strip(), m.group(2)) if m else (s, None)


def make_hash(rec):
    key = "|".join(str(rec.get(k)) for k in (
        "exchange", "trade_date", "tnved", "product", "buyer", "buyer_bin",
        "seller", "seller_bin", "amount", "price_avg", "deals_count",
        "delivery_terms"))
    return hashlib.sha1(key.encode("utf-8")).hexdigest()


def parse_html(html):
    """Возвращает (сделки, итоги_по_дням) из одной страницы."""
    soup = BeautifulSoup(html, "lxml")
    table = soup.find("table")
    if table is None:
        return [], []
    trades, totals = [], []
    for tr in table.find_all("tr")[1:]:            # [0] — шапка
        tds = [_text(td) for td in tr.find_all("td")]
        if len(tds) < len(COLS):
            continue
        r = dict(zip(COLS, tds))
        try:
            d = datetime.strptime(r["date"], "%d.%m.%Y").date().isoformat()
        except ValueError:
            continue
        # Итоговая строка дня: нет кода ТН ВЭД, но есть оборот за день
        if _none(r["tnved"]) is None and _num(r["day_turnover"]) is not None:
            totals.append({"exchange": EXCHANGE, "trade_date": d,
                           "day_turnover": _num(r["day_turnover"]),
                           "deals_count": int(_num(r["deals_count"]) or 0)})
            continue
        buyer, buyer_bin = _split_bin(r["buyer"])
        seller, seller_bin = _split_bin(r["seller"])
        rec = {
            "exchange": EXCHANGE, "trade_date": d,
            "tnved": _none(r["tnved"]), "product": _none(r["product"]),
            "price_open": _num(r["price_open"]), "price_close": _num(r["price_close"]),
            "price_max": _num(r["price_max"]), "price_min": _num(r["price_min"]),
            "price_avg": _num(r["price_avg"]), "amount": _num(r["amount"]),
            "buyer": buyer, "buyer_bin": buyer_bin,
            "buyer_broker": _none(r["buyer_broker"]),
            "seller": seller, "seller_bin": seller_bin,
            "seller_broker": _none(r["seller_broker"]),
            "deals_count": int(_num(r["deals_count"]) or 0),
            "delivery_terms": _none(r["delivery_terms"]),
        }
        rec["dedup_hash"] = make_hash(rec)
        trades.append(rec)
    return trades, totals


def fetch_range(date_from: date, date_to: date, lang="ru", session=None, log=print):
    """Скачивает все страницы за период. Возвращает (сделки, итоги_по_дням)."""
    s = session or requests.Session()
    all_trades, all_totals, seen = [], [], set()
    for page in range(1, MAX_PAGES + 1):
        params = {"date_from": date_from.isoformat(), "date_to": date_to.isoformat(),
                  "page": page, "lang": lang}
        resp = s.get(URL, params=params, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        resp.encoding = "utf-8"                   # не полагаемся на угадывание кодировки
        trades, totals = parse_html(resp.text)
        sig = tuple(t["dedup_hash"] for t in trades)
        if not trades and not totals:
            break                                  # страниц больше нет
        if sig in seen:
            log(f"стр. {page} повторяет предыдущую — останавливаемся")
            break                                  # сайт игнорирует page
        seen.add(sig)
        all_trades += trades
        all_totals += totals
        log(f"стр. {page}: сделок {len(trades)}, итогов дня {len(totals)}")
        time.sleep(PAUSE_SECONDS)
    return all_trades, all_totals


if __name__ == "__main__":
    import sys, json
    html = open(sys.argv[1], encoding="utf-8").read()
    tr, tt = parse_html(html)
    print("сделок:", len(tr), "| итогов дня:", tt)
    print("сумма по строкам:", round(sum(t["amount"] or 0 for t in tr), 2))
    print("сделок (число):", sum(t["deals_count"] for t in tr))
    print(json.dumps(tr[0], ensure_ascii=False, indent=2))
