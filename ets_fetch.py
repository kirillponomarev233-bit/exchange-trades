"""Автоматическая загрузка итогов торгов ETS (ets.kz).

Путь на сайте: страница года -> страницы месяцев -> ссылки на файлы .xlsx (один файл на торговый день).
Скачанные файлы кладутся в папку data/ets и разбираются парсером ets_parser.

ВАЖНО: структура страниц сайта может измениться; в этом случае ошибка записывается в журнал
запусков (таблица scrape_runs), а уже собранные данные сохраняются.
Запасной вариант: скачать файлы вручную в папку samples и выполнить `python load.py ets samples`.
"""
import hashlib
import re
import time
from datetime import date
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

import db
import ets_parser

BASE = "https://ets.kz"
HEADERS = {"User-Agent": "Mozilla/5.0 (student practice project, trading results parser)"}
DATE_RE = re.compile(r"(\d{2})\.(\d{2})\.(\d{4})")
MONTH_TEXT_RE = re.compile(r"итоги\s+торгов\s+(\d{4})\s+год", re.I)


def _get(session, url, log, tries=3):
    for i in range(tries):
        try:
            r = session.get(url, headers=HEADERS, timeout=60)
            r.raise_for_status()
            return r
        except requests.RequestException as e:
            if i == tries - 1:
                raise
            log(f"  повтор {i + 1} для {url}: {e}")
            time.sleep(3 * (i + 1))


def _links(html, page_url):
    """Все ссылки страницы: [(абсолютный адрес, текст ссылки)]."""
    soup = BeautifulSoup(html, "lxml")   # html может быть байтами: кодировку определит сама библиотека
    out = []
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        out.append((urljoin(page_url, href), a.get_text(" ", strip=True)))
    return out


def _is_file(url):
    return urlparse(url).path.lower().endswith(".xlsx")


def file_date(url, text):
    """Дата торгов из названия файла (текст ссылки или адрес): ДД.ММ.ГГГГ."""
    for s in (text, unquote(urlparse(url).path)):
        m = DATE_RE.search(s or "")
        if m:
            try:
                return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            except ValueError:
                pass
    return None


def collect_files(session, base, year, pause, log):
    """Возвращает список (адрес файла, текст ссылки) за год."""
    year_url = f"{base}/documents/trading-results/itogi-torgov-{year}/"
    log(f"ETS: страница года {year_url}")
    links = _links(_get(session, year_url, log).content, year_url)
    host, year_path = urlparse(year_url).netloc, urlparse(year_url).path.rstrip("/")
    months, files = [], []
    for url, text in links:
        if _is_file(url):
            files.append((url, text))
            continue
        p = urlparse(url)
        if p.netloc != host or p.path.rstrip("/") == year_path:
            continue
        m = MONTH_TEXT_RE.search(text or "")
        under_year = p.path.startswith(year_path + "/")
        if (under_year or (m and m.group(1) == str(year))) and url not in months:
            months.append(url)
    log(f"ETS: страниц месяцев найдено: {len(months)}")
    for month_url in months:
        time.sleep(pause)
        for url, text in _links(_get(session, month_url, log).content, month_url):
            if _is_file(url):
                files.append((url, text))
    seen, unique = set(), []
    for url, text in files:
        if url not in seen:
            seen.add(url)
            unique.append((url, text))
    log(f"ETS: файлов .xlsx найдено: {len(unique)}")
    return unique


def sync(conn, since, until, folder, pause=1.5, base=BASE, log=print):
    """Скачивает файлы ETS за период [since, until], разбирает и сохраняет в базу.
    Возвращает (добавлено, пропущено_как_дубли, предупреждение). Если часть файлов не удалось
    обработать, остальные всё равно сохраняются, а предупреждение попадает в журнал запусков.
    Ошибка поднимается, только если на сайте вообще не найдено файлов."""
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    candidates = []
    for year in range(since.year, until.year + 1):
        candidates += collect_files(session, base, year, pause, log)

    added = skipped = 0
    failures = []
    for url, text in candidates:
        d = file_date(url, text)
        if d is not None and not (since <= d <= until):
            continue
        name = f"ets_{d.isoformat()}.xlsx" if d else "ets_" + hashlib.sha1(url.encode()).hexdigest()[:10] + ".xlsx"
        path = folder / name
        try:
            if not path.exists():
                time.sleep(pause)
                data = _get(session, url, log).content
                if not data.startswith(b"PK"):              # .xlsx — это zip-архив
                    raise ValueError("ответ не похож на файл Excel (.xlsx)")
                path.write_bytes(data)
            trades, totals = ets_parser.parse_workbook(path)
            a, s = db.save(conn, trades, totals)
            added, skipped = added + a, skipped + s
            log(f"  {name}: сделок {len(trades)}, добавлено {a}, дублей {s}")
        except Exception as e:                              # один плохой файл не останавливает остальные
            failures.append(f"{name}: {type(e).__name__}: {e}")
            log(f"  ОШИБКА {name}: {e}")
    if not candidates:
        raise RuntimeError("на сайте не найдено ни одного файла .xlsx — возможно, изменилась структура страниц")
    warning = f"не обработано файлов: {len(failures)}; первая ошибка: {failures[0]}" if failures else None
    return added, skipped, warning
