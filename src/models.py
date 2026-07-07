from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContractContext:
    objeto: str
    tipo_contratacao: str
    valor_estimado: float
    criticidade: str
    prazo: str
    modalidade: str
    contexto: str


@dataclass(frozen=True)
class RiskItem:
    id: str
    titulo: str
    categoria: str
    tipo_contratacao: list[str]
    palavras_chave: list[str]
    causa: str
    consequencia: str
    probabilidade_padrao: str
    impacto_padrao: str
    acao_preventiva: str
    acao_contingencia: str
    responsavel_sugerido: str


@dataclass
class ActionItem:
    descricao: str
    situacao: str = "Não iniciado"
    responsavel: str = ""


@dataclass
class MatrixRow:
    id: str
    risco: str
    categoria: str
    causa: str
    consequencias: list[str]
    probabilidade: str
    impacto: str
    nivel: str
    estrategia: str
    acoes_preventivas: list[ActionItem]
    acoes_contingencia: list[ActionItem]
    justificativa: str = ""
    selecionado: bool = True
    tags: list[str] = field(default_factory=list)

    @property
    def consequencia(self) -> str:
        return "; ".join(item for item in self.consequencias if item)

    @property
    def acao_preventiva(self) -> str:
        return "; ".join(action.descricao for action in self.acoes_preventivas if action.descricao)

    @property
    def acao_contingencia(self) -> str:
        return "; ".join(action.descricao for action in self.acoes_contingencia if action.descricao)
