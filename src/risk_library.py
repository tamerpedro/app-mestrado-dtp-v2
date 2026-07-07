from __future__ import annotations

import csv
from pathlib import Path

from .models import RiskItem


FIELDNAMES = [
    "id",
    "titulo",
    "categoria",
    "tipo_contratacao",
    "palavras_chave",
    "causa",
    "consequencia",
    "probabilidade_padrao",
    "impacto_padrao",
    "acao_preventiva",
    "acao_contingencia",
    "responsavel_sugerido",
]


def _split_list(value: str) -> list[str]:
    return [item.strip().lower() for item in (value or "").split(";") if item.strip()]


def _normalize_header(value: str | None) -> str:
    return (value or "").lstrip("\ufeff").strip().lower()


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as csvfile:
        reader = csv.reader(csvfile)
        try:
            headers = [_normalize_header(field) for field in next(reader)]
        except StopIteration:
            raise ValueError("Biblioteca de riscos vazia.") from None

        missing = [field for field in FIELDNAMES if field not in headers]
        if missing:
            raise ValueError(f"Colunas obrigatorias ausentes na biblioteca de riscos: {', '.join(missing)}")

        rows: list[dict[str, str]] = []
        for values in reader:
            if not any((value or "").strip() for value in values):
                continue
            row = {header: values[index] if index < len(values) else "" for index, header in enumerate(headers)}
            rows.append(row)
        return rows


def _required_row_value(row: dict[str, str], field: str, line_number: int) -> str:
    value = row.get(field, "")
    if value is None:
        value = ""
    value = value.strip()
    if value:
        return value
    raise ValueError(f"Valor obrigatorio ausente na coluna '{field}', linha {line_number}.")


def _optional_row_value(row: dict[str, str], field: str, default: str = "") -> str:
    value = row.get(field, default)
    if value is None:
        return default
    return value.strip() or default


def load_risks(path: str | Path) -> list[RiskItem]:
    risks: list[RiskItem] = []
    for index, row in enumerate(_read_csv_rows(Path(path)), start=2):
        risks.append(
            RiskItem(
                id=_required_row_value(row, "id", index),
                titulo=_required_row_value(row, "titulo", index),
                categoria=_optional_row_value(row, "categoria", "planejamento"),
                tipo_contratacao=_split_list(_required_row_value(row, "tipo_contratacao", index)),
                palavras_chave=_split_list(_optional_row_value(row, "palavras_chave")),
                causa=_required_row_value(row, "causa", index),
                consequencia=_required_row_value(row, "consequencia", index),
                probabilidade_padrao=_required_row_value(row, "probabilidade_padrao", index),
                impacto_padrao=_required_row_value(row, "impacto_padrao", index),
                acao_preventiva=_required_row_value(row, "acao_preventiva", index),
                acao_contingencia=_required_row_value(row, "acao_contingencia", index),
                responsavel_sugerido=_optional_row_value(row, "responsavel_sugerido"),
            )
        )
    return risks
