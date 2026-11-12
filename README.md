# Итоги торгов бирж ETS и Каспий (CCX)

Учебный проект (практика): сбор итогов торгов с сайтов ets.kz и ccx.kz, общая база данных,
веб-портал с фильтрами и ежедневный планировщик.

## Что внутри
| Файл | Назначение |
|---|---|
| `ets_parser.py` | разбор Excel-файлов итогов торгов ETS |
| `ets_fetch.py` | автоматическая загрузка файлов ETS с сайта |
| `ccx_parser.py` | разбор и загрузка HTML-таблицы итогов торгов Каспий (CCX) |
| `db.py` | схема базы SQLite, сохранение, дедупликация, журнал запусков |
| `load.py` | ручная загрузка и проверки (`stats`, `check`) |
| `scheduler.py` + `config.ini` | ежедневный запуск по расписанию и ручной запуск |
| `portal.py`, `queries.py`, `static/index.html` | веб-портал |
| `dump_db.py` | выгрузка базы в `trades_dump.sql` и восстановление |
| `tests/` | автотесты |
| `docs/` | описание БД, анализ источников, отчёт, шпаргалка для демо |

## Установка (чистая машина, Windows PowerShell)
Нужен Python 3.11+ (https://www.python.org, галочка «Add to PATH»).
```powershell
git clone https://github.com/kirillponomarev233-bit/exchange-trades.git
cd exchange-trades
python -m venv venv
venv\Scripts\Activate.ps1
pip install -r requirements.txt
```
(Linux/macOS: `source venv/bin/activate`.) Если PowerShell не даёт активировать окружение:
`Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`.

## Вариант А. Быстрый старт — база из дампа (без интернета)
```powershell
python dump_db.py --restore      # создаёт trades.db из trades_dump.sql
python portal.py                 # открыть http://127.0.0.1:8000
```

## Вариант Б. Собрать данные самому
```powershell
python scheduler.py --once --from 2026-09-01 --to 2026-10-31   # история за период, обе биржи
python scheduler.py --once --only ccx                           # одна биржа, последние N дней из config.ini
python load.py check                                            # сверка сумм сделок с оборотом дня
python portal.py
```
Если автоматическая загрузка ETS не сработала (сайт изменился), скачайте файлы .xlsx вручную
в папку `samples` и выполните `python load.py ets samples` — ручной путь проверен на реальных файлах.

## Портал
`python portal.py` → http://127.0.0.1:8000. Таблица с сортировкой по заголовкам и пагинацией,
фильтры (биржа, период, товар, продавец/покупатель по названию или БИН, брокер, диапазон суммы,
место поставки/базис) применяются без перезагрузки страницы. Вкладка «Состояние данных» — журнал
запусков, число записей и даты по биржам. Кнопка «Excel» выгружает текущую выборку.
Порт можно сменить: `$env:PORT=8080; python portal.py`.

## Планировщик
Расписание — в `config.ini` (`[schedule] run_at = 07:30`, повтор при неудаче `retry_minutes`).
```powershell
python scheduler.py              # держать окно открытым; каждый день в run_at соберёт последние N дней
python scheduler.py --once       # ручной запуск
```
Без постоянного окна: «Планировщик заданий Windows» → создать задачу → действие
`venv\Scripts\python.exe` с аргументами `scheduler.py --once`, «Начать в» — папка проекта.
Результат каждого запуска пишется в таблицу `scrape_runs` (статусы: ok, warning, error).

## Тесты
```powershell
python -m unittest discover -s tests -v
```

## База данных
Описание таблиц, связей и индексов — `docs/DATABASE.md`. Дамп с данными — `trades_dump.sql`.

## Известные ограничения (честно)
- Ни одна биржа не отдаёт объём и единицу измерения — в базе их нет; есть сумма, цены и число сделок.
- Базис поставки ETS (EXW, FCA, CPT…) берётся регулярным выражением из названия товара; если базис
  в названии не указан, поле пустое.
- Автозагрузка ETS проверялась на тестовом сайте-имитации и на ручных файлах; на живом ets.kz
  результат зависит от того, не изменилась ли структура страниц (см. `docs/REPORT_DRAFT.md`).
- Сайты бирж могут запрещать автоматический сбор — соблюдайте паузы (`pause_seconds`) и условия сайтов.
