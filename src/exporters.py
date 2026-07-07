from __future__ import annotations

import csv
import io

from .models import ActionItem, MatrixRow


EXPORT_FIELDS = [
    "id",
    "risco",
    "categoria",
    "causa",
    "consequencia",
    "probabilidade",
    "impacto",
    "nivel",
    "estrategia",
    "acao_preventiva",
    "acao_contingencia",
    "justificativa",
]


def selected_rows(rows: list[MatrixRow]) -> list[MatrixRow]:
    return [row for row in rows if row.selecionado]


def row_to_export_dict(row: MatrixRow) -> dict[str, str]:
    return {
        "id": row.id,
        "risco": row.risco,
        "categoria": row.categoria,
        "causa": row.causa,
        "consequencia": _join_text_items(row.consequencias),
        "probabilidade": row.probabilidade,
        "impacto": row.impacto,
        "nivel": row.nivel,
        "estrategia": row.estrategia,
        "acao_preventiva": _join_action_items(row.acoes_preventivas),
        "acao_contingencia": _join_action_items(row.acoes_contingencia),
        "justificativa": row.justificativa,
    }


def to_csv(rows: list[MatrixRow]) -> str:
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=EXPORT_FIELDS)
    writer.writeheader()
    for row in selected_rows(rows):
        writer.writerow(row_to_export_dict(row))
    return output.getvalue()


def to_latex(rows: list[MatrixRow]) -> str:
    lines = [
        r"\begin{longtable}{p{0.08\textwidth}p{0.22\textwidth}p{0.12\textwidth}p{0.12\textwidth}p{0.12\textwidth}p{0.28\textwidth}}",
        r"\textbf{ID} & \textbf{Risco} & \textbf{Prob.} & \textbf{Impacto} & \textbf{Nivel} & \textbf{Acao preventiva} \\",
        r"\hline",
    ]
    for row in selected_rows(rows):
        lines.append(
            " & ".join(
                [
                    _latex_escape(row.id),
                    _latex_escape(row.risco),
                    _latex_escape(row.probabilidade),
                    _latex_escape(row.impacto),
                    _latex_escape(row.nivel),
                    _latex_escape(_join_action_items(row.acoes_preventivas)),
                ]
            )
            + r" \\"
        )
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def _latex_escape(value: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
    }
    text = str(value or "")
    for source, target in replacements.items():
        text = text.replace(source, target)
    return text


def _join_text_items(items: list[str]) -> str:
    return "; ".join(item.strip() for item in items if item and item.strip())


def _join_action_items(actions: list[ActionItem]) -> str:
    formatted = []
    for action in actions:
        description = (action.descricao or "").strip()
        if not description:
            continue
        metadata = " - ".join(
            item.strip()
            for item in [action.situacao, action.responsavel]
            if item and item.strip()
        )
        formatted.append(f"{description} ({metadata})" if metadata else description)
    return "; ".join(formatted)
