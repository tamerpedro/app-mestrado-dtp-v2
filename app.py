from __future__ import annotations

import base64
from collections import defaultdict
from html import escape
import io
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from openpyxl import Workbook

from src.auth import is_authorized, load_users
from src.docx_exporter import to_docx
from src.exporters import EXPORT_FIELDS, row_to_export_dict, selected_rows, to_csv, to_latex
from src.models import ActionItem, ContractContext, MatrixRow
from src.risk_library import load_risks
from src.scoring import IMPACT_OPTIONS, PROBABILITY_OPTIONS, risk_level
from src.storage import (
    DuplicateProcessError,
    Storage,
    context_from_process,
    matrix_row_from_dict,
    matrix_row_to_dict,
    storage_from_secrets,
)
from src.suggestions import suggest_risks
from src.validation import validate_process_name, validate_process_number


DATA_PATH = Path("data/riscos_base.csv")
LOGO_PATH = Path("assets/dataprev-logo.png")
CATEGORY_OPTIONS = ["planejamento", "selecao", "gestao", "solucao", "instalacao", "cronograma"]
CATEGORY_LABELS = {
    "planejamento": "Planejamento",
    "selecao": "Seleção de fornecedor",
    "gestao": "Gestão do contrato",
    "solucao": "Solução",
    "instalacao": "Instalação",
    "cronograma": "Cronograma",
}
STRATEGY_OPTIONS = ["Mitigar", "Aceitar", "Compartilhar", "Evitar"]
MODALITY_OPTIONS = [
    "Dispensa de Licitação P/ Valor",
    "Inexigibilidade",
    "Pregão Simples",
    "Pregão com POC",
    "Pregão com Consulta Pública",
    "Pregão com Consulta Pública e POC",
]


st.set_page_config(page_title="Matriz de Riscos TIC", layout="wide")


def secrets_dict() -> dict[str, Any]:
    try:
        return dict(st.secrets)
    except Exception:
        return {}


def require_login() -> str:
    if st.session_state.get("authenticated"):
        username = st.session_state.get("authenticated_user", "")
        with st.sidebar:
            st.caption(f"Usuário: {username}")
            if st.button("Sair"):
                st.session_state.clear()
                st.rerun()
        return username

    users = load_users(secrets_dict())
    st.title("Acesso restrito")
    st.caption("Entre com um usuário credenciado para acessar o aplicativo.")

    if not users:
        st.error("Nenhum usuário foi configurado para este aplicativo.")
        st.stop()

    with st.form("login_form"):
        username = st.text_input("Usuário")
        password = st.text_input("Senha", type="password")
        submitted = st.form_submit_button("Entrar")

    if submitted:
        if is_authorized(username, password, users):
            st.session_state["authenticated"] = True
            st.session_state["authenticated_user"] = username.strip()
            st.rerun()
        st.error("Usuário ou senha inválidos.")

    st.stop()


def get_storage() -> Storage:
    storage = storage_from_secrets(secrets_dict())
    storage.init_schema()
    return storage


def apply_theme() -> None:
    st.markdown(
        """
        <style>
        :root {
            --dtp-blue: #005ca9;
            --dtp-blue-dark: #003c71;
            --dtp-cyan: #00a3e0;
            --dtp-green: #79b829;
            --dtp-yellow: #f5c400;
            --dtp-border: rgba(0, 163, 224, .28);
            --dtp-soft: rgba(0, 92, 169, .12);
        }
        .block-container { padding-top: 2.35rem; max-width: 1280px; }
        [data-testid="stSidebar"] { border-right: 1px solid var(--dtp-border); }
        .dtp-sidebar-brand {
            border-left: 5px solid var(--dtp-green);
            border-bottom: 1px solid var(--dtp-border);
            padding: .75rem 0 .9rem .9rem;
            margin: -.35rem 0 1.15rem 0;
        }
        .dtp-sidebar-brand strong {
            display: block;
            color: var(--dtp-cyan);
            font-size: 1.35rem;
            line-height: 1.1;
        }
        .dtp-sidebar-brand span {
            color: inherit;
            font-size: .82rem;
            opacity: .82;
        }
        .dtp-hero {
            position: relative;
            padding: 1.2rem 1.35rem 1.05rem 1.35rem;
            border: 1px solid var(--dtp-border);
            border-left: 7px solid var(--dtp-blue);
            border-radius: 8px;
            background:
                linear-gradient(90deg, rgba(0, 92, 169, .20), rgba(0, 163, 224, .07)),
                var(--dtp-soft);
            margin-bottom: 1.2rem;
        }
        .dtp-hero-main {
            display: flex;
            align-items: center;
            gap: 1.15rem;
            min-width: 0;
        }
        .dtp-logo-wrap {
            flex: 0 0 auto;
            width: clamp(72px, 9vw, 112px);
            aspect-ratio: 1.14;
            display: grid;
            place-items: center;
            padding: .45rem;
            border-radius: 8px;
            background: rgba(255, 255, 255, .92);
            box-shadow: 0 10px 24px rgba(0, 60, 113, .12);
        }
        .dtp-logo-wrap img {
            width: 100%;
            height: auto;
            display: block;
        }
        .dtp-logo-fallback {
            color: var(--dtp-blue-dark);
            font-weight: 800;
            font-size: 1.05rem;
            line-height: 1;
            letter-spacing: 0;
        }
        .dtp-hero-copy { min-width: 0; }
        .dtp-kicker {
            display: inline-flex;
            align-items: center;
            gap: .45rem;
            color: var(--dtp-cyan);
            font-size: .78rem;
            font-weight: 700;
            text-transform: uppercase;
            letter-spacing: .04em;
        }
        .dtp-kicker::before {
            content: "";
            width: .7rem;
            height: .7rem;
            border-radius: 2px;
            background: linear-gradient(135deg, var(--dtp-green), var(--dtp-yellow));
        }
        .dtp-hero h1 {
            margin: .35rem 0 .25rem 0;
            font-size: clamp(2rem, 3.5vw, 3.15rem);
            line-height: 1.05;
            letter-spacing: 0;
        }
        .dtp-hero p {
            margin: 0;
            max-width: 860px;
            opacity: .86;
        }
        .dtp-status-grid {
            display: grid;
            grid-template-columns: repeat(4, minmax(0, 1fr));
            gap: .7rem;
            margin: 1rem 0 0 0;
        }
        .dtp-status {
            border-top: 3px solid var(--dtp-cyan);
            background: rgba(255, 255, 255, .045);
            border-radius: 6px;
            padding: .7rem .75rem;
            min-height: 4.3rem;
        }
        .dtp-status span {
            display: block;
            font-size: .72rem;
            opacity: .72;
            margin-bottom: .25rem;
        }
        .dtp-status strong {
            display: block;
            font-size: 1rem;
            line-height: 1.25;
        }
        .dtp-panel-title {
            display: flex;
            align-items: center;
            gap: .55rem;
            margin: .25rem 0 .75rem 0;
        }
        .dtp-panel-title::before {
            content: "";
            width: .35rem;
            height: 1.45rem;
            border-radius: 999px;
            background: var(--dtp-green);
        }
        .dtp-section-label {
            margin: 1rem 0 .35rem 0;
            padding-top: .35rem;
            border-top: 1px solid var(--dtp-border);
            color: var(--dtp-cyan);
            font-weight: 700;
        }
        .stTabs [data-baseweb="tab-list"] {
            gap: .45rem;
            border-bottom: 1px solid var(--dtp-border);
        }
        .stTabs [data-baseweb="tab"] {
            border-radius: 6px 6px 0 0;
            padding: .7rem 1rem;
            letter-spacing: 0;
        }
        .stTabs [aria-selected="true"] {
            color: var(--dtp-cyan);
            border-bottom: 3px solid var(--dtp-green);
        }
        .stButton > button, .stDownloadButton > button {
            border-color: var(--dtp-border);
            border-radius: 6px;
        }
        .stButton > button:hover, .stDownloadButton > button:hover {
            border-color: var(--dtp-cyan);
            color: var(--dtp-cyan);
        }
        [data-testid="stMetric"] {
            border-left: 4px solid var(--dtp-green);
            padding-left: .75rem;
        }
        @media (max-width: 900px) {
            .dtp-status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
        }
        @media (max-width: 560px) {
            .dtp-status-grid { grid-template-columns: 1fr; }
            .dtp-hero { padding: 1rem; }
            .dtp-hero-main { align-items: flex-start; gap: .8rem; }
            .dtp-logo-wrap { width: 64px; padding: .35rem; }
            .dtp-kicker { font-size: .72rem; }
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def image_to_data_uri(path: Path) -> str:
    if not path.exists():
        return ""
    encoded = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def render_header(
    title: str,
    subtitle: str,
    *,
    context: ContractContext | None = None,
    rows: list[MatrixRow] | None = None,
    process: dict[str, Any] | None = None,
) -> None:
    rows = rows or []
    selected = [row for row in rows if row.selecionado]
    not_included = [row for row in rows if not row.selecionado]
    high_count = sum(1 for row in selected if is_high_or_critical(row))
    status_items: list[tuple[str, Any]] = []
    if process:
        status_items.append(("Processo", process.get("numero_processo", "")))
    if context:
        status_items.append(("Criticidade", context.criticidade.title()))
    if rows:
        status_items.extend(
            [
                ("Riscos sugeridos", f"{len(selected)} no total | {high_count} altos"),
                ("Riscos não incluídos", len(not_included)),
            ]
        )
    status_html = "".join(
        f'<div class="dtp-status"><span>{escape(label)}</span><strong>{escape(str(value))}</strong></div>'
        for label, value in status_items[:4]
    )
    logo_uri = image_to_data_uri(LOGO_PATH)
    logo_html = (
        f'<div class="dtp-logo-wrap"><img src="{logo_uri}" alt="Logotipo Dataprev"></div>'
        if logo_uri
        else '<div class="dtp-logo-wrap"><span class="dtp-logo-fallback">Dataprev</span></div>'
    )
    st.markdown(
        f"""
        <section class="dtp-hero">
            <div class="dtp-hero-main">
                {logo_html}
                <div class="dtp-hero-copy">
                    <div class="dtp-kicker">Dataprev | Contratações de TIC</div>
                    <h1>{escape(title)}</h1>
                    <p>{escape(subtitle)}</p>
                </div>
            </div>
            {f'<div class="dtp-status-grid">{status_html}</div>' if status_html else ''}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_panel_title(title: str) -> None:
    st.markdown(f'<h3 class="dtp-panel-title">{escape(title)}</h3>', unsafe_allow_html=True)


def render_section_label(label: str) -> None:
    st.markdown(f'<div class="dtp-section-label">{escape(label)}</div>', unsafe_allow_html=True)


def category_label(category: str) -> str:
    return CATEGORY_LABELS.get(category or "planejamento", (category or "planejamento").title())


def process_form_defaults(process: dict[str, Any] | None = None) -> dict[str, Any]:
    process = process or {}
    return {
        "numero_processo": process.get("numero_processo", ""),
        "nome_processo": process.get("nome_processo", ""),
        "objeto": process.get("objeto", "Contratação de solução de TIC"),
        "tipo_contratacao": process.get("tipo_contratacao", "aquisicao"),
        "valor_estimado": float(process.get("valor_estimado") or 0),
        "criticidade": process.get("criticidade", "media"),
        "prazo": process.get("prazo", "12 meses"),
        "modalidade": process.get("modalidade", "Pregão Simples"),
        "contexto": process.get("contexto", "Necessidade de padronizar a matriz de riscos da contratação."),
        "status": process.get("status", "ativo"),
    }


def render_process_fields(defaults: dict[str, Any], key_prefix: str) -> dict[str, Any]:
    col1, col2 = st.columns([1, 2])
    with col1:
        numero = st.text_input(
            "Número do processo",
            value=defaults["numero_processo"],
            placeholder="44129.011262/2025-95",
            key=f"{key_prefix}_numero",
        )
    with col2:
        nome = st.text_input(
            "Nome do processo",
            value=defaults["nome_processo"],
            max_chars=255,
            key=f"{key_prefix}_nome",
        )

    objeto = st.text_area("Objeto", value=defaults["objeto"], key=f"{key_prefix}_objeto")
    col1, col2, col3 = st.columns(3)
    with col1:
        tipo = st.selectbox(
            "Tipo",
            ["aquisicao", "servico", "software"],
            index=safe_index(["aquisicao", "servico", "software"], defaults["tipo_contratacao"]),
            key=f"{key_prefix}_tipo",
        )
        criticidade = st.selectbox(
            "Criticidade",
            ["baixa", "media", "alta"],
            index=safe_index(["baixa", "media", "alta"], defaults["criticidade"]),
            key=f"{key_prefix}_criticidade",
        )
    with col2:
        valor = st.number_input(
            "Valor estimado",
            min_value=0.0,
            step=1000.0,
            value=float(defaults["valor_estimado"]),
            key=f"{key_prefix}_valor",
        )
        status = st.selectbox(
            "Status",
            ["ativo", "concluido", "suspenso", "arquivado"],
            index=safe_index(["ativo", "concluido", "suspenso", "arquivado"], defaults["status"]),
            key=f"{key_prefix}_status",
        )
    with col3:
        prazo = st.text_input("Prazo", value=defaults["prazo"], key=f"{key_prefix}_prazo")
        modalidade = st.selectbox(
            "Modalidade",
            MODALITY_OPTIONS,
            index=safe_index(MODALITY_OPTIONS, defaults["modalidade"], default=2),
            key=f"{key_prefix}_modalidade",
        )

    contexto = st.text_area("Contexto", value=defaults["contexto"], key=f"{key_prefix}_contexto")
    return {
        "numero_processo": numero,
        "nome_processo": nome,
        "objeto": objeto,
        "tipo_contratacao": tipo,
        "valor_estimado": valor,
        "criticidade": criticidade,
        "prazo": prazo,
        "modalidade": modalidade,
        "contexto": contexto,
        "status": status,
    }


def render_process_list(storage: Storage, username: str) -> None:
    render_header("Processos", "Gerencie matrizes de risco por processo de contratação.")
    query = st.text_input("Buscar por número ou nome do processo")
    processes = storage.list_processes(query)

    with st.expander("Novo processo", expanded=not processes):
        with st.form("new_process_form"):
            data = render_process_fields(process_form_defaults(), "new")
            submitted = st.form_submit_button("Criar processo e matriz inicial")
        if submitted:
            try:
                validate_process_number(data["numero_processo"])
                validate_process_name(data["nome_processo"])
                process_id = storage.create_process(data, username)
                context = ContractContext(
                    objeto=data["objeto"],
                    tipo_contratacao=data["tipo_contratacao"],
                    valor_estimado=float(data["valor_estimado"] or 0),
                    criticidade=data["criticidade"],
                    prazo=data["prazo"],
                    modalidade=data["modalidade"],
                    contexto=data["contexto"],
                )
                storage.initialize_matrix(process_id, suggest_risks(load_risks(DATA_PATH), context), username)
                st.session_state["current_process_id"] = process_id
                st.success("Processo criado.")
                st.rerun()
            except DuplicateProcessError as exc:
                st.error(str(exc))
            except ValueError as exc:
                st.error(str(exc))

    render_panel_title("Processos cadastrados")
    if not processes:
        st.info("Nenhum processo cadastrado.")
        return

    for process in processes:
        col1, col2, col3, col4 = st.columns([1.2, 2.2, .8, .8])
        col1.write(f"**{process['numero_processo']}**")
        col2.write(process["nome_processo"])
        col3.write(process["status"])
        if col4.button("Abrir", key=f"open_{process['id']}"):
            st.session_state["current_process_id"] = process["id"]
            st.rerun()


def render_process_detail(storage: Storage, username: str, process_id: int) -> None:
    process = storage.get_process(process_id)
    if not process:
        st.session_state.pop("current_process_id", None)
        st.error("Processo não encontrado.")
        st.stop()

    col1, col2 = st.columns([1, 4])
    if col1.button("Voltar"):
        st.session_state.pop("current_process_id", None)
        st.rerun()
    col2.caption(f"{process['numero_processo']} | {process['nome_processo']}")

    rows = storage.list_matrix_rows(process_id)
    context = context_from_process(process)
    render_header("Matriz de Riscos TIC", process["nome_processo"], context=context, rows=rows, process=process)

    tab_data, tab_suggestions, tab_review, tab_history, tab_export = st.tabs(
        ["Dados do processo", "Sugestões", "Revisão humana", "Histórico", "Exportação"]
    )

    with tab_data:
        render_panel_title("Dados do processo")
        with st.form("edit_process_form"):
            data = render_process_fields(process_form_defaults(process), f"edit_{process_id}")
            submitted = st.form_submit_button("Salvar dados do processo")
        if submitted:
            try:
                storage.update_process(process_id, data, username)
                st.success("Dados do processo salvos.")
                st.rerun()
            except (DuplicateProcessError, ValueError) as exc:
                st.error(str(exc))

    with tab_suggestions:
        render_suggestions_tab(storage, username, process_id, context, rows)

    with tab_review:
        render_review_tab(storage, username, process_id, rows)

    with tab_history:
        render_history_tab(storage, process_id)

    with tab_export:
        render_export_tab(storage, username, process_id, context, rows)


def render_suggestions_tab(
    storage: Storage,
    username: str,
    process_id: int,
    context: ContractContext,
    rows: list[MatrixRow],
) -> None:
    all_library_rows = suggest_risks(load_risks(DATA_PATH), context, minimum_score=0, max_per_category=None)
    included_rows = [row for row in rows if row.selecionado]
    not_included_rows = build_not_included_rows(rows, all_library_rows)

    render_panel_title("Riscos sugeridos")
    render_suggestion_metrics(included_rows, first_label="Sugestões")
    render_grouped_suggestion_tables(included_rows, "Nenhum risco sugerido para esta matriz.")
    render_suggestion_mover(
        included_rows,
        "Selecionar risco sugerido",
        "Remover",
        "remove_suggested",
        lambda risk_id: exclude_risk(storage, username, process_id, rows, risk_id),
    )

    render_panel_title("Riscos não incluídos")
    render_suggestion_metrics(not_included_rows, first_label="Disponíveis")
    render_grouped_suggestion_tables(not_included_rows, "Nenhum risco fora da lista sugerida.")
    render_suggestion_mover(
        not_included_rows,
        "Selecionar risco não incluído",
        "Incluir",
        "include_not_suggested",
        lambda risk_id: include_risk(storage, username, process_id, rows, not_included_rows, risk_id),
    )


def is_high_or_critical(row: MatrixRow) -> bool:
    return normalize_text(row.nivel) in {"alto", "critico", "crítico"}


def normalize_text(value: str) -> str:
    return (value or "").strip().lower()


def build_not_included_rows(rows: list[MatrixRow], library_rows: list[MatrixRow]) -> list[MatrixRow]:
    current_by_id = {row.id: row for row in rows}
    not_included = [row for row in rows if not row.selecionado]
    not_included.extend(row for row in library_rows if row.id not in current_by_id)
    return sort_rows_by_category(not_included)


def sort_rows_by_category(rows: list[MatrixRow]) -> list[MatrixRow]:
    category_order = {category: index for index, category in enumerate(CATEGORY_OPTIONS)}
    return sorted(rows, key=lambda row: (category_order.get(row.categoria, len(category_order)), row.id))


def grouped_row_indexes(rows: list[MatrixRow]) -> list[tuple[str, list[tuple[int, MatrixRow]]]]:
    grouped: dict[str, list[tuple[int, MatrixRow]]] = defaultdict(list)
    for index, row in enumerate(rows):
        grouped[row.categoria or "planejamento"].append((index, row))
    category_order = {category: index for index, category in enumerate(CATEGORY_OPTIONS)}
    return sorted(grouped.items(), key=lambda item: (category_order.get(item[0], len(category_order)), item[0]))


def render_suggestion_metrics(rows: list[MatrixRow], *, first_label: str) -> None:
    col1, col2, col3 = st.columns(3)
    col1.metric(first_label, len(rows))
    col2.metric("Riscos altos/críticos", sum(1 for row in rows if is_high_or_critical(row)))
    col3.metric("Categorias", len({row.categoria for row in rows}))


def render_grouped_suggestion_tables(rows: list[MatrixRow], empty_message: str) -> None:
    if not rows:
        st.info(empty_message)
        return

    for category, indexed_rows in grouped_row_indexes(rows):
        category_rows = [row for _, row in indexed_rows]
        with st.expander(f"{category_label(category)} ({len(category_rows)})", expanded=True):
            st.dataframe([row_summary(row) for row in category_rows], use_container_width=True, hide_index=True)


def render_suggestion_mover(
    rows: list[MatrixRow],
    select_label: str,
    button_label: str,
    key_prefix: str,
    on_move,
) -> None:
    if not rows:
        return

    col1, col2 = st.columns([4, 1])
    with col1:
        selected_id = st.selectbox(
            select_label,
            [row.id for row in rows],
            format_func=lambda risk_id: suggestion_label(rows, risk_id),
            key=f"{key_prefix}_select",
        )
    with col2:
        st.write("")
        st.write("")
        if st.button(button_label, key=f"{key_prefix}_button"):
            on_move(selected_id)


def include_risk(
    storage: Storage,
    username: str,
    process_id: int,
    rows: list[MatrixRow],
    available_rows: list[MatrixRow],
    risk_id: str,
) -> None:
    updated_rows: list[MatrixRow] = []
    found = False
    for row in rows:
        if row.id == risk_id:
            updated_rows.append(clone_row(row, selecionado=True))
            found = True
        else:
            updated_rows.append(clone_row(row))

    if not found:
        row = next(item for item in available_rows if item.id == risk_id)
        updated_rows.append(clone_row(row, selecionado=True))

    storage.save_matrix_rows(process_id, sort_rows_by_category(updated_rows), username)
    st.success("Risco incluído na matriz.")
    st.rerun()


def exclude_risk(
    storage: Storage,
    username: str,
    process_id: int,
    rows: list[MatrixRow],
    risk_id: str,
) -> None:
    updated_rows = [
        clone_row(row, selecionado=False) if row.id == risk_id else clone_row(row)
        for row in rows
    ]
    storage.save_matrix_rows(process_id, sort_rows_by_category(updated_rows), username)
    st.success("Risco movido para não incluídos.")
    st.rerun()


def clone_row(row: MatrixRow, **overrides: Any) -> MatrixRow:
    payload = matrix_row_to_dict(row)
    payload.update(overrides)
    return matrix_row_from_dict(payload)


def render_review_tab(storage: Storage, username: str, process_id: int, rows: list[MatrixRow]) -> None:
    render_panel_title("Revisão humana")
    edited_rows = rows_from_editor(st.data_editor(
        rows_to_editor(rows),
        num_rows="dynamic",
        use_container_width=True,
        hide_index=True,
        column_config={
            "selecionado": st.column_config.CheckboxColumn("Incluir"),
            "categoria": st.column_config.SelectboxColumn("Categoria", options=CATEGORY_OPTIONS),
            "probabilidade": st.column_config.SelectboxColumn("Probabilidade", options=PROBABILITY_OPTIONS),
            "impacto": st.column_config.SelectboxColumn("Impacto", options=IMPACT_OPTIONS),
            "estrategia": st.column_config.SelectboxColumn("Estratégia", options=STRATEGY_OPTIONS),
        },
    ))

    if st.button("Salvar revisão da matriz"):
        storage.save_matrix_rows(process_id, edited_rows, username)
        st.success("Matriz salva.")
        st.rerun()


def render_history_tab(storage: Storage, process_id: int) -> None:
    render_panel_title("Histórico de mudanças")
    events = storage.list_events(process_id)
    if not events:
        st.info("Nenhum evento registrado.")
        return
    st.dataframe(
        [
            {
                "data": event["created_at"],
                "usuário": event["username"],
                "ação": event["event_type"],
                "risco": event.get("risk_id") or "",
            }
            for event in events
        ],
        use_container_width=True,
        hide_index=True,
    )
    with st.expander("Detalhes técnicos do log"):
        st.json(events)


def render_export_tab(
    storage: Storage,
    username: str,
    process_id: int,
    context: ContractContext,
    rows: list[MatrixRow],
) -> None:
    render_panel_title("Matriz final")
    selected = selected_rows(rows)
    col1, col2, col3 = st.columns(3)
    col1.metric("Riscos selecionados", len(selected))
    col2.metric("Ações preventivas", sum(len(row.acoes_preventivas) for row in selected))
    col3.metric("Ações de contingência", sum(len(row.acoes_contingencia) for row in selected))
    st.dataframe([row_to_export_dict(row) for row in selected], use_container_width=True, hide_index=True)

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.download_button(
            "Baixar CSV",
            to_csv(selected),
            "matriz_riscos.csv",
            "text/csv",
            on_click=storage.record_export,
            args=(process_id, username, "csv", len(selected)),
        )
    with col2:
        st.download_button(
            "Baixar Excel",
            rows_to_xlsx(selected),
            "matriz_riscos.xlsx",
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            on_click=storage.record_export,
            args=(process_id, username, "xlsx", len(selected)),
        )
    with col3:
        st.download_button(
            "Baixar LaTeX",
            to_latex(selected),
            "matriz_riscos.tex",
            "text/plain",
            on_click=storage.record_export,
            args=(process_id, username, "latex", len(selected)),
        )
    with col4:
        st.download_button(
            "Baixar Word",
            to_docx(selected, context),
            "mapa_de_gerenciamento_de_riscos.docx",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            on_click=storage.record_export,
            args=(process_id, username, "docx", len(selected)),
        )


def rows_to_editor(rows: list[MatrixRow]) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "id": row.id,
                "selecionado": row.selecionado,
                "risco": row.risco,
                "categoria": row.categoria,
                "causa": row.causa,
                "consequencias": "\n".join(row.consequencias),
                "probabilidade": row.probabilidade,
                "impacto": row.impacto,
                "nivel": row.nivel,
                "estrategia": row.estrategia,
                "acoes_preventivas": "\n".join(action.descricao for action in row.acoes_preventivas),
                "acoes_contingencia": "\n".join(action.descricao for action in row.acoes_contingencia),
                "justificativa": row.justificativa,
            }
            for row in rows
        ]
    )


def rows_from_editor(frame: pd.DataFrame) -> list[MatrixRow]:
    rows: list[MatrixRow] = []
    for index, record in enumerate(frame.fillna("").to_dict(orient="records"), start=1):
        risk_id = str(record.get("id") or f"MAN{index:03d}").strip()
        probability = str(record.get("probabilidade") or "3-Média")
        impact = str(record.get("impacto") or "3-Médio")
        rows.append(
            MatrixRow(
                id=risk_id,
                risco=str(record.get("risco", "")).strip(),
                categoria=str(record.get("categoria") or "planejamento"),
                causa=str(record.get("causa", "")).strip(),
                consequencias=split_lines(str(record.get("consequencias", ""))),
                probabilidade=probability,
                impacto=impact,
                nivel=risk_level(probability, impact),
                estrategia=str(record.get("estrategia") or "Mitigar"),
                acoes_preventivas=[ActionItem(value) for value in split_lines(str(record.get("acoes_preventivas", "")))],
                acoes_contingencia=[ActionItem(value) for value in split_lines(str(record.get("acoes_contingencia", "")))],
                justificativa=str(record.get("justificativa", "")).strip(),
                selecionado=bool(record.get("selecionado", True)),
                tags=["manual"] if risk_id.startswith("MAN") else [],
            )
        )
    return [row for row in rows if row.risco]


def rows_to_xlsx(rows: list[MatrixRow]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Matriz de Riscos"
    worksheet.append(EXPORT_FIELDS)
    for row in selected_rows(rows):
        data = row_to_export_dict(row)
        worksheet.append([data[field] for field in EXPORT_FIELDS])
    stream = io.BytesIO()
    workbook.save(stream)
    return stream.getvalue()


def row_summary(row: MatrixRow) -> dict[str, Any]:
    return {
        "id": row.id,
        "risco": row.risco,
        "categoria": CATEGORY_LABELS.get(row.categoria, row.categoria),
        "probabilidade": row.probabilidade,
        "impacto": row.impacto,
        "nível": row.nivel,
        "incluído": row.selecionado,
    }


def suggestion_label(rows: list[MatrixRow], risk_id: str) -> str:
    row = next(item for item in rows if item.id == risk_id)
    return f"{row.id} - {row.risco}"


def split_lines(value: str) -> list[str]:
    return [line.strip() for line in value.splitlines() if line.strip()]


def safe_index(options: list[str], value: str, default: int = 0) -> int:
    return options.index(value) if value in options else default


def main() -> None:
    username = require_login()
    apply_theme()
    storage = get_storage()

    with st.sidebar:
        st.markdown(
            """
            <div class="dtp-sidebar-brand">
                <strong>Dataprev</strong>
                <span>Mapa de Riscos TIC</span>
            </div>
            """,
            unsafe_allow_html=True,
        )
        st.caption("Banco: Supabase/Postgres via secrets ou SQLite local de desenvolvimento.")

    process_id = st.session_state.get("current_process_id")
    if process_id:
        render_process_detail(storage, username, int(process_id))
    else:
        render_process_list(storage, username)


if __name__ == "__main__":
    main()
