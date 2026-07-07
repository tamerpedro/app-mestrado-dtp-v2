from __future__ import annotations

from pathlib import Path

import pytest

from src.auth import hash_password, is_authorized, load_users
from src.exporters import to_csv
from src.models import ContractContext
from src.risk_library import load_risks
from src.scoring import risk_level, risk_score
from src.storage import DuplicateProcessError, Storage, matrix_row_from_dict, matrix_row_to_dict
from src.suggestions import suggest_risks
from src.validation import validate_process_name, validate_process_number


def test_process_number_validation():
    assert validate_process_number("44129.011262/2025-95") == "44129.011262/2025-95"

    for invalid in ["44129011262/2025-95", "44129.011262.2025-95", "abc"]:
        with pytest.raises(ValueError):
            validate_process_number(invalid)


def test_process_name_validation():
    assert validate_process_name("  Contratação de solução TIC  ") == "Contratação de solução TIC"

    with pytest.raises(ValueError):
        validate_process_name("")
    with pytest.raises(ValueError):
        validate_process_name("x" * 256)


def test_loads_risk_library_and_suggests_rows():
    risks = load_risks(Path("data/riscos_base.csv"))
    context = ContractContext(
        objeto="Contratação de subscrições Microsoft 365 e Copilot",
        tipo_contratacao="software",
        valor_estimado=100000.0,
        criticidade="alta",
        prazo="12 meses",
        modalidade="Pregão Simples",
        contexto="Licenciamento, subscrição, suporte e segurança da informação.",
    )

    rows = suggest_risks(risks, context)

    assert len(risks) == 62
    assert rows
    assert all(row.selecionado for row in rows)


def test_scoring_and_csv_export():
    assert risk_score("3-Média", "4-Alto") == 12
    assert risk_level("3-Média", "4-Alto") == "alto"

    risks = load_risks(Path("data/riscos_base.csv"))
    context = ContractContext("Solução de TIC", "software", 0, "media", "12 meses", "Pregão Simples", "")
    rows = suggest_risks(risks, context)
    csv_payload = to_csv(rows)

    assert csv_payload.startswith("id,risco,categoria")


def test_auth_accepts_plain_and_hashed_passwords():
    users = load_users(secrets={"auth": {"users": {"pedro": "senha"}}}, environ={})
    assert is_authorized("pedro", "senha", users)
    assert not is_authorized("pedro", "errada", users)

    hashed = {"pedro": hash_password("senha-segura", salt="teste")}
    assert is_authorized("pedro", "senha-segura", hashed)


def test_matrix_row_serialization_roundtrip():
    risks = load_risks(Path("data/riscos_base.csv"))
    context = ContractContext("Solução de TIC", "software", 0, "media", "12 meses", "Pregão Simples", "")
    row = suggest_risks(risks, context)[0]

    restored = matrix_row_from_dict(matrix_row_to_dict(row))

    assert restored.id == row.id
    assert restored.risco == row.risco
    assert restored.acoes_preventivas[0].descricao == row.acoes_preventivas[0].descricao


def test_storage_creates_process_matrix_and_events(tmp_path):
    storage = Storage(f"sqlite:///{tmp_path / 'test.db'}")
    storage.init_schema()
    risks = load_risks(Path("data/riscos_base.csv"))
    context = ContractContext("Solução de TIC", "software", 0, "media", "12 meses", "Pregão Simples", "")
    rows = suggest_risks(risks, context)
    data = {
        "numero_processo": "44129.011262/2025-95",
        "nome_processo": "Contratação de solução TIC",
        "objeto": context.objeto,
        "tipo_contratacao": context.tipo_contratacao,
        "valor_estimado": context.valor_estimado,
        "criticidade": context.criticidade,
        "prazo": context.prazo,
        "modalidade": context.modalidade,
        "contexto": context.contexto,
    }

    process_id = storage.create_process(data, "pedro")
    storage.initialize_matrix(process_id, rows, "pedro")

    with pytest.raises(DuplicateProcessError):
        storage.create_process(data, "pedro")

    stored_rows = storage.list_matrix_rows(process_id)
    stored_rows[0].selecionado = False
    storage.save_matrix_rows(process_id, stored_rows, "maria")
    events = storage.list_events(process_id)

    assert storage.get_process(process_id)["numero_processo"] == "44129.011262/2025-95"
    assert len(stored_rows) == len(rows)
    assert {event["event_type"] for event in events} >= {
        "process_created",
        "matrix_initialized",
        "risk_excluded",
    }
