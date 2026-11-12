# База данных

СУБД: SQLite (файл `trades.db`, стандартный модуль Python `sqlite3`). Схема создаётся автоматически
в `db.py` (`db.connect`). Данные нормализованы: справочники вынесены в отдельные таблицы, обе биржи
лежат в одной таблице сделок.

## ER-диаграмма
```
exchanges 1───* trades *───1 products
                 │ *───1 participants (buyer_id)
                 │ *───1 participants (seller_id)
                 │ *───1 brokers (buyer_broker_id)
                 └ *───1 brokers (seller_broker_id)
exchanges 1───* daily_totals        scrape_runs (журнал, без связей)
```

## Таблицы
| Таблица | Поля | Назначение |
|---|---|---|
| `exchanges` | id, code (ETS/CCX), name | биржи |
| `products` | id, tnved, name; UNIQUE(tnved,name) | товары |
| `participants` | id, name, bin; UNIQUE(name,bin) | покупатели и продавцы (одна таблица, роль задаёт колонка в `trades`) |
| `brokers` | id, name UNIQUE | брокеры |
| `trades` | id, exchange_id, trade_date, product_id, buyer_id, seller_id, buyer_broker_id, seller_broker_id, deals_count, price_open/close/max/min/avg, amount, delivery_terms, product_code, dedup_hash UNIQUE | сделки (строки итогов торгов) |
| `daily_totals` | exchange_id, trade_date, day_turnover, deals_count; PK(exchange_id,trade_date) | оборот дня по данным биржи — для сверки |
| `scrape_runs` | id, started_at, finished_at, source, period, added, skipped, status, message | журнал запусков (ok / warning / error / running) |

## Индексы
`trades`: по дате, (биржа, дата), товару, покупателю, продавцу, брокерам, сумме, базису поставки;
`participants(bin)`, `products(name)`. Под них построены фильтры портала.

## Дедупликация
`dedup_hash` = SHA-1 от (биржа, дата, ТН ВЭД, товар, код, покупатель+БИН, брокер, продавец+БИН, брокер,
сумма, средняя цена, число сделок, базис). Повторная загрузка не создаёт дублей (`INSERT OR IGNORE`).
Если в одной загрузке встречаются полностью одинаковые строки, это разные сделки: второй и далее
экземпляры получают хеш с номером вхождения (так была найдена и исправлена потеря строк 08.09 на CCX).

## Сверка
`python load.py check` сравнивает сумму сделок за день с оборотом дня, заявленным биржей
(`daily_totals`); на данных за 19 дней расхождений нет.

## Данные
Полный дамп — `trades_dump.sql` (`python dump_db.py --restore` создаёт базу из него).
