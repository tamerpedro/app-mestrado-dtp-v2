PROBABILITY_OPTIONS = [
    "1-Muito Baixa",
    "2-Baixa",
    "3-Média",
    "4-Alta",
    "5-Muito Alta",
]

IMPACT_OPTIONS = [
    "1-Muito Baixo",
    "2-Baixo",
    "3-Médio",
    "4-Alto",
    "5-Muito Alto",
]

SCORES = {
    "muito baixa": 1,
    "baixa": 2,
    "media": 3,
    "alta": 4,
    "muito alta": 5,
    "muito baixo": 1,
    "baixo": 2,
    "medio": 3,
    "alto": 4,
    "muito alto": 5,
}


def normalize_level(value: str) -> str:
    value = (value or "").strip().lower()
    if "-" in value and value[0].isdigit():
        value = value.split("-", 1)[1].strip()
    replacements = {
        "média": "media",
        "medio": "medio",
        "médio": "medio",
        "crítico": "critico",
    }
    return replacements.get(value, value)


def score_value(value: str) -> int:
    value = (value or "").strip()
    if value and value[0].isdigit():
        return int(value[0])
    return SCORES.get(normalize_level(value), 0)


def risk_score(probabilidade: str, impacto: str) -> int:
    return score_value(probabilidade) * score_value(impacto)


def risk_level(probabilidade: str, impacto: str) -> str:
    score = risk_score(probabilidade, impacto)
    if score >= 15:
        return "crítico"
    if score >= 8:
        return "alto"
    if score >= 4:
        return "moderado"
    if score >= 1:
        return "pequeno"
    return "indefinido"


def canonical_probability(value: str) -> str:
    normalized = normalize_level(value)
    for option in PROBABILITY_OPTIONS:
        if normalize_level(option) == normalized:
            return option
    return "3-Média"


def canonical_impact(value: str) -> str:
    normalized = normalize_level(value)
    for option in IMPACT_OPTIONS:
        if normalize_level(option) == normalized:
            return option
    return "3-Médio"
