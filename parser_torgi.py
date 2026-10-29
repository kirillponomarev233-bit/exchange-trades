#!/usr/bin/env python3
"""
Парсер Excel-файлов «Итоги торгов».

Использование:
    python parser_torgi.py "02.09.2026 САУДА-САТТЫҚ НӘТИЖЕЛЕРІ_ ИТОГИ ТОРГОВ.xlsx"

По умолчанию создаёт рядом с исходным файлом:
    *_parsed.json
    *_parsed.csv

Зависимость:
    pip install openpyxl
"""

import argparse
import csv
import json
import re
from pathlib import Path
from typing import Any

from openpyxl import load_workbook


# Столбцы в исходном шаблоне: B–Q.
FIELDS = {
    2: "buyer_name",
    3: "buyer_bin",
    4: "buyer_broker",
    5: "seller_name",
    6: "seller_bin",
    7: "seller_broker",
    8: "product_name",
    9: "tn_ved_code",
    10: "product_code",
    11: "deal_count",
    12: "opening_price",
    13: "closing_price",
    14: "max_deal_price",
    15: "min_deal_price",
    16: "weighted_average_price",
    17: "total_amount",
}

NUMERIC_FIELDS = {
    "deal_count",
    "opening_price",
    "closing_price",
    "max_deal_price",
    "min_deal_price",
    "weighted_average_price",
    "total_amount",
}


def clean(value: Any) -> Any:
    """Убирает лишние пробелы и переносы строк, не меняя числовые значения."""
    if isinstance(value, str):
        value = re.sub(r"\s+", " ", value).strip()
        return value or None
    return value


def find_header_row(ws) -> int:
    """Ищет строку заголовков по русскому/казахскому названию покупателя."""
    for row in range(1, min(ws.max_row, 20) + 1):
        values = [str(ws.cell(row, col).value or "").lower() for col in range(1, ws.max_column + 1)]
        joined = " ".join(values)
        if "наименование покупателя" in joined or "сатып алушының атауы" in joined:
            return row
    raise ValueError(f"Не удалось найти строку заголовков на листе {ws.title!r}.")


def find_report_date(ws) -> str | None:
    """Извлекает дату из заголовка отчёта, если она есть."""
    for row in range(1, min(ws.max_row, 6) + 1):
        for col in range(1, ws.max_column + 1):
            value = clean(ws.cell(row, col).value)
            if isinstance(value, str):
                match = re.search(r"\b(\d{2}\.\d{2}\.\d{4})\b", value)
                if match:
                    return match.group(1)
    return None


def parse_workbook(input_path: Path) -> dict[str, Any]:
    # data_only=True считывает сохранённые Excel значения формул, если они есть.
    # В некоторых файлах Excel не сохраняет результат формулы; тогда итог пересчитываем сами.
    workbook = load_workbook(input_path, data_only=True, read_only=True)
    reports = []

    for ws in workbook.worksheets:
        header_row = find_header_row(ws)
        deals = []

        for row_idx in range(header_row + 1, ws.max_row + 1):
            # В шаблоне строка с итогом содержит слово «Итого» в поле товара.
            row_values = {field: clean(ws.cell(row_idx, col).value) for col, field in FIELDS.items()}

            if all(value is None for value in row_values.values()):
                continue

            product_name = str(row_values.get("product_name") or "").strip().lower()
            if product_name == "итого" or product_name == "қорытынды":
                continue

            # Строки без покупателя и товара не являются сделками.
            if not row_values.get("buyer_name") and not row_values.get("product_name"):
                continue

            # БИН и коды сохраняем строками, чтобы не потерять ведущие нули.
            for key in NUMERIC_FIELDS:
                value = row_values.get(key)
                if value is not None:
                    try:
                        row_values[key] = float(value) if key != "deal_count" else int(float(value))
                    except (TypeError, ValueError):
                        pass

            deals.append(row_values)

        total_amount = sum(
            float(deal["total_amount"])
            for deal in deals
            if isinstance(deal.get("total_amount"), (int, float))
        )
        total_deal_count = sum(
            int(deal["deal_count"])
            for deal in deals
            if isinstance(deal.get("deal_count"), (int, float))
        )

        reports.append({
            "sheet": ws.title,
            "report_date": find_report_date(ws),
            "deal_count_rows": len(deals),
            "total_deals": total_deal_count,
            "total_amount": round(total_amount, 2),
            "deals": deals,
        })

    workbook.close()
    return {
        "source_file": input_path.name,
        "reports": reports,
    }


def write_csv(data: dict[str, Any], output_path: Path) -> None:
    columns = list(FIELDS.values())
    with output_path.open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["sheet", "report_date", *columns], extrasaction="ignore")
        writer.writeheader()
        for report in data["reports"]:
            for deal in report["deals"]:
                writer.writerow({
                    "sheet": report["sheet"],
                    "report_date": report["report_date"],
                    **deal,
                })


def main() -> None:
    parser = argparse.ArgumentParser(description="Извлекает сделки из Excel-отчёта об итогах торгов.")
    parser.add_argument("input", help="Путь к исходному .xlsx файлу")
    parser.add_argument("--json", dest="json_path", help="Путь для JSON (по умолчанию рядом с исходным файлом)")
    parser.add_argument("--csv", dest="csv_path", help="Путь для CSV (по умолчанию рядом с исходным файлом)")
    args = parser.parse_args()

    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise SystemExit(f"Файл не найден: {input_path}")
    if input_path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise SystemExit("Поддерживаются файлы .xlsx и .xlsm.")

    data = parse_workbook(input_path)
    json_path = Path(args.json_path) if args.json_path else input_path.with_name(input_path.stem + "_parsed.json")
    csv_path = Path(args.csv_path) if args.csv_path else input_path.with_name(input_path.stem + "_parsed.csv")

    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    write_csv(data, csv_path)

    print(f"Готово. Листов обработано: {len(data['reports'])}")
    for report in data["reports"]:
        print(
            f"Лист {report['sheet']}: сделок/строк — {report['deal_count_rows']}, "
            f"количество сделок — {report['total_deals']}, "
            f"сумма — {report['total_amount']:.2f}"
        )
    print(f"JSON: {json_path}")
    print(f"CSV:  {csv_path}")


if __name__ == "__main__":
    main()