from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from collections.abc import Iterable

from .models import ActionItem, ContractContext, MatrixRow, RiskItem
from .scoring import risk_level

MAX_SUGGESTIONS_PER_CATEGORY = 2
_TOKEN_RE = re.compile(r"[a-z0-9]+")


def _normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value or "")
    without_accents = "".join(char for char in normalized if not unicodedata.combining(char))
    return without_accents.lower()


def _tokens(value: str) -> set[str]:
    return {token for token in _TOKEN_RE.findall(_normalize_text(value)) if len(token) >= 3}


def _text_blob(context: ContractContext) -> str:
    return _normalize_text(
        " ".join(
            [
                context.objeto,
                context.tipo_contratacao,
                context.criticidade,
                context.prazo,
                context.modalidade,
                context.contexto,
            ]
        )
    )


def _keyword_score(keyword: str, objeto_text: str, blob_text: str, objeto_tokens: set[str], blob_tokens: set[str]) -> int:
    normalized_keyword = _normalize_text(keyword).strip()
    if not normalized_keyword:
        return 0

    score = 0
    keyword_tokens = _tokens(normalized_keyword)
    if normalized_keyword in objeto_text:
        score += 5
    elif keyword_tokens and keyword_tokens.issubset(objeto_tokens):
        score += 4
    elif normalized_keyword in blob_text:
        score += 2
    elif keyword_tokens and keyword_tokens.issubset(blob_tokens):
        score += 1
    return score


def _text_overlap_score(values: Iterable[str], objeto_tokens: set[str], blob_tokens: set[str]) -> int:
    candidate_tokens: set[str] = set()
    for value in values:
        candidate_tokens.update(_tokens(value))

    if not candidate_tokens:
        return 0

    object_overlap = len(candidate_tokens & objeto_tokens)
    blob_overlap = len(candidate_tokens & blob_tokens)
    if object_overlap >= 2:
        return 2
    if object_overlap == 1 or blob_overlap >= 2:
        return 1
    return 0


def suggestion_score(risk: RiskItem, context: ContractContext) -> int:
    score = 0
    objeto_text = _normalize_text(context.objeto)
    blob_text = _text_blob(context)
    objeto_tokens = _tokens(context.objeto)
    blob_tokens = _tokens(blob_text)
    contract_type = _normalize_text(context.tipo_contratacao).strip()

    if contract_type in risk.tipo_contratacao:
        score += 1

    for keyword in risk.palavras_chave:
        score += _keyword_score(keyword, objeto_text, blob_text, objeto_tokens, blob_tokens)

    score += _text_overlap_score([risk.titulo, risk.causa, risk.consequencia], objeto_tokens, blob_tokens)

    if score > 1 and context.criticidade.strip().lower() == "alta" and risk.impacto_padrao in {"alto", "muito alto"}:
        score += 1

    return score


def _to_matrix_row(risk: RiskItem, score: int) -> MatrixRow:
    return MatrixRow(
        id=risk.id,
        risco=risk.titulo,
        categoria=risk.categoria,
        causa=risk.causa,
        consequencias=[risk.consequencia],
        probabilidade=risk.probabilidade_padrao,
        impacto=risk.impacto_padrao,
        nivel=risk_level(risk.probabilidade_padrao, risk.impacto_padrao),
        estrategia="Mitigar",
        acoes_preventivas=[ActionItem(risk.acao_preventiva)],
        acoes_contingencia=[ActionItem(risk.acao_contingencia)],
        justificativa=f"Sugerido por aderencia ao objeto e ao contexto da contratacao. Pontuacao: {score}.",
        tags=risk.tipo_contratacao,
    )


def suggest_risks(
    risks: list[RiskItem],
    context: ContractContext,
    minimum_score: int = 2,
    max_per_category: int | None = MAX_SUGGESTIONS_PER_CATEGORY,
) -> list[MatrixRow]:
    ranked = sorted(
        ((suggestion_score(risk, context), risk) for risk in risks),
        key=lambda item: (item[0], item[1].categoria, item[1].id),
        reverse=True,
    )
    rows: list[MatrixRow] = []
    category_counts: dict[str, int] = defaultdict(int)
    for score, risk in ranked:
        if score < minimum_score:
            continue
        if max_per_category is not None and category_counts[risk.categoria] >= max_per_category:
            continue
        rows.append(_to_matrix_row(risk, score))
        category_counts[risk.categoria] += 1
    return rows
