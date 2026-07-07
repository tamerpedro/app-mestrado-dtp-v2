from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterator

from .models import ActionItem, ContractContext, MatrixRow
from .validation import validate_process_name, validate_process_number


DEFAULT_SQLITE_URL = "sqlite:///.tmp/app_mestrado.db"


class DuplicateProcessError(ValueError):
    pass


class Storage:
    def __init__(self, url: str = DEFAULT_SQLITE_URL):
        self.url = url or DEFAULT_SQLITE_URL
        self.dialect = "postgres" if self.url.startswith(("postgres://", "postgresql://")) else "sqlite"

    @contextmanager
    def connect(self) -> Iterator[Any]:
        if self.dialect == "postgres":
            import psycopg
            from psycopg.rows import dict_row

            connection = psycopg.connect(self.url, row_factory=dict_row)
        else:
            path = self._sqlite_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            connection = sqlite3.connect(path)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")

        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            for statement in self._schema_statements():
                connection.execute(statement)

    def create_process(self, data: dict[str, Any], username: str) -> int:
        number = validate_process_number(data.get("numero_processo", ""))
        name = validate_process_name(data.get("nome_processo", ""))
        now = utc_now()
        fields = {
            "numero_processo": number,
            "nome_processo": name,
            "objeto": data.get("objeto", ""),
            "tipo_contratacao": data.get("tipo_contratacao", "aquisicao"),
            "valor_estimado": float(data.get("valor_estimado") or 0),
            "criticidade": data.get("criticidade", "media"),
            "prazo": data.get("prazo", ""),
            "modalidade": data.get("modalidade", ""),
            "contexto": data.get("contexto", ""),
            "status": data.get("status", "ativo"),
            "created_by": username,
            "created_at": now,
            "updated_at": now,
        }
        columns = list(fields)
        values = [fields[column] for column in columns]
        placeholders = ", ".join(["?"] * len(columns))
        sql = f"INSERT INTO procurements ({', '.join(columns)}) VALUES ({placeholders})"
        if self.dialect == "postgres":
            sql += " RETURNING id"

        try:
            with self.connect() as connection:
                cursor = connection.execute(self._sql(sql), values)
                process_id = int(cursor.fetchone()[0]) if self.dialect == "postgres" else int(cursor.lastrowid)
                self._record_event(
                    connection,
                    "process_created",
                    username,
                    process_id,
                    None,
                    None,
                    fields,
                )
                return process_id
        except Exception as exc:
            if "UNIQUE" in str(exc).upper() or "duplicate" in str(exc).lower():
                raise DuplicateProcessError(f"Processo {number} já existe.") from exc
            raise

    def update_process(self, process_id: int, data: dict[str, Any], username: str) -> None:
        before = self.get_process(process_id)
        if not before:
            raise ValueError("Processo não encontrado.")

        fields = {
            "numero_processo": validate_process_number(data.get("numero_processo", before["numero_processo"])),
            "nome_processo": validate_process_name(data.get("nome_processo", before["nome_processo"])),
            "objeto": data.get("objeto", before["objeto"]),
            "tipo_contratacao": data.get("tipo_contratacao", before["tipo_contratacao"]),
            "valor_estimado": float(data.get("valor_estimado", before["valor_estimado"]) or 0),
            "criticidade": data.get("criticidade", before["criticidade"]),
            "prazo": data.get("prazo", before["prazo"]),
            "modalidade": data.get("modalidade", before["modalidade"]),
            "contexto": data.get("contexto", before["contexto"]),
            "status": data.get("status", before["status"]),
            "updated_at": utc_now(),
        }
        assignments = ", ".join([f"{column} = ?" for column in fields])
        values = [*fields.values(), process_id]
        with self.connect() as connection:
            connection.execute(self._sql(f"UPDATE procurements SET {assignments} WHERE id = ?"), values)
            after = {**before, **fields}
            self._record_event(connection, "process_updated", username, process_id, None, before, after)

    def list_processes(self, query: str = "") -> list[dict[str, Any]]:
        query = (query or "").strip().lower()
        with self.connect() as connection:
            if query:
                like = f"%{query}%"
                cursor = connection.execute(
                    self._sql(
                        """
                        SELECT * FROM procurements
                        WHERE LOWER(numero_processo) LIKE ? OR LOWER(nome_processo) LIKE ?
                        ORDER BY updated_at DESC, id DESC
                        """
                    ),
                    [like, like],
                )
            else:
                cursor = connection.execute("SELECT * FROM procurements ORDER BY updated_at DESC, id DESC")
            return [row_to_dict(row) for row in cursor.fetchall()]

    def get_process(self, process_id: int) -> dict[str, Any] | None:
        with self.connect() as connection:
            cursor = connection.execute(self._sql("SELECT * FROM procurements WHERE id = ?"), [process_id])
            row = cursor.fetchone()
            return row_to_dict(row) if row else None

    def initialize_matrix(self, process_id: int, rows: list[MatrixRow], username: str) -> None:
        with self.connect() as connection:
            count = connection.execute(
                self._sql("SELECT COUNT(*) FROM matrix_rows WHERE process_id = ?"),
                [process_id],
            ).fetchone()[0]
            if count:
                return
            for index, row in enumerate(rows):
                self._insert_matrix_row(connection, process_id, row, index)
            self._touch_process(connection, process_id)
            self._record_event(
                connection,
                "matrix_initialized",
                username,
                process_id,
                None,
                None,
                {"rows": [matrix_row_to_dict(row) for row in rows]},
            )

    def list_matrix_rows(self, process_id: int) -> list[MatrixRow]:
        with self.connect() as connection:
            cursor = connection.execute(
                self._sql("SELECT * FROM matrix_rows WHERE process_id = ? ORDER BY sort_order, id"),
                [process_id],
            )
            return [matrix_row_from_record(row_to_dict(row)) for row in cursor.fetchall()]

    def save_matrix_rows(self, process_id: int, rows: list[MatrixRow], username: str) -> None:
        before_rows = [matrix_row_to_dict(row) for row in self.list_matrix_rows(process_id)]
        before_by_id = {row["id"]: row for row in before_rows}
        after_rows = [matrix_row_to_dict(row) for row in rows]
        after_by_id = {row["id"]: row for row in after_rows}

        with self.connect() as connection:
            connection.execute(self._sql("DELETE FROM matrix_rows WHERE process_id = ?"), [process_id])
            for index, row in enumerate(rows):
                self._insert_matrix_row(connection, process_id, row, index)
            self._touch_process(connection, process_id)

            before_ids = set(before_by_id)
            after_ids = set(after_by_id)
            for risk_id in sorted(after_ids - before_ids):
                self._record_event(connection, "risk_added", username, process_id, risk_id, None, after_by_id[risk_id])
            for risk_id in sorted(before_ids - after_ids):
                self._record_event(connection, "risk_removed", username, process_id, risk_id, before_by_id[risk_id], None)
            for risk_id in sorted(before_ids & after_ids):
                before = before_by_id[risk_id]
                after = after_by_id[risk_id]
                if before == after:
                    continue
                if before.get("selecionado") is False and after.get("selecionado") is True:
                    event_type = "risk_included"
                elif before.get("selecionado") is True and after.get("selecionado") is False:
                    event_type = "risk_excluded"
                else:
                    event_type = "risk_updated"
                self._record_event(connection, event_type, username, process_id, risk_id, before, after)

    def record_export(self, process_id: int, username: str, export_type: str, rows_count: int) -> None:
        with self.connect() as connection:
            self._record_event(
                connection,
                "export_generated",
                username,
                process_id,
                None,
                None,
                {"export_type": export_type, "rows_count": rows_count},
            )

    def list_events(self, process_id: int) -> list[dict[str, Any]]:
        with self.connect() as connection:
            cursor = connection.execute(
                self._sql("SELECT * FROM matrix_events WHERE process_id = ? ORDER BY created_at DESC, id DESC"),
                [process_id],
            )
            events = []
            for row in cursor.fetchall():
                item = row_to_dict(row)
                item["before_json"] = json.loads(item["before_json"]) if item.get("before_json") else None
                item["after_json"] = json.loads(item["after_json"]) if item.get("after_json") else None
                events.append(item)
            return events

    def _sqlite_path(self) -> Path:
        raw = self.url.removeprefix("sqlite:///")
        return Path(raw)

    def _sql(self, sql: str) -> str:
        return sql.replace("?", "%s") if self.dialect == "postgres" else sql

    def _schema_statements(self) -> list[str]:
        if self.dialect == "postgres":
            return [
                """
                CREATE TABLE IF NOT EXISTS procurements (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    numero_processo TEXT NOT NULL UNIQUE,
                    nome_processo TEXT NOT NULL,
                    objeto TEXT NOT NULL DEFAULT '',
                    tipo_contratacao TEXT NOT NULL DEFAULT 'aquisicao',
                    valor_estimado DOUBLE PRECISION NOT NULL DEFAULT 0,
                    criticidade TEXT NOT NULL DEFAULT 'media',
                    prazo TEXT NOT NULL DEFAULT '',
                    modalidade TEXT NOT NULL DEFAULT '',
                    contexto TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'ativo',
                    created_by TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS matrix_rows (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    process_id INTEGER NOT NULL REFERENCES procurements(id) ON DELETE CASCADE,
                    risk_id TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    selecionado BOOLEAN NOT NULL DEFAULT TRUE,
                    sort_order INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                )
                """,
                """
                CREATE TABLE IF NOT EXISTS matrix_events (
                    id INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                    process_id INTEGER NOT NULL REFERENCES procurements(id) ON DELETE CASCADE,
                    risk_id TEXT,
                    event_type TEXT NOT NULL,
                    username TEXT NOT NULL,
                    before_json TEXT,
                    after_json TEXT,
                    created_at TEXT NOT NULL
                )
                """,
            ]

        return [
            """
            CREATE TABLE IF NOT EXISTS procurements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                numero_processo TEXT NOT NULL UNIQUE,
                nome_processo TEXT NOT NULL,
                objeto TEXT NOT NULL DEFAULT '',
                tipo_contratacao TEXT NOT NULL DEFAULT 'aquisicao',
                valor_estimado REAL NOT NULL DEFAULT 0,
                criticidade TEXT NOT NULL DEFAULT 'media',
                prazo TEXT NOT NULL DEFAULT '',
                modalidade TEXT NOT NULL DEFAULT '',
                contexto TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'ativo',
                created_by TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS matrix_rows (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_id INTEGER NOT NULL REFERENCES procurements(id) ON DELETE CASCADE,
                risk_id TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                selecionado INTEGER NOT NULL DEFAULT 1,
                sort_order INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS matrix_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                process_id INTEGER NOT NULL REFERENCES procurements(id) ON DELETE CASCADE,
                risk_id TEXT,
                event_type TEXT NOT NULL,
                username TEXT NOT NULL,
                before_json TEXT,
                after_json TEXT,
                created_at TEXT NOT NULL
            )
            """,
        ]

    def _insert_matrix_row(self, connection: Any, process_id: int, row: MatrixRow, sort_order: int) -> None:
        payload = matrix_row_to_dict(row)
        connection.execute(
            self._sql(
                """
                INSERT INTO matrix_rows (process_id, risk_id, payload_json, selecionado, sort_order, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """
            ),
            [
                process_id,
                row.id,
                json.dumps(payload, ensure_ascii=False),
                bool(row.selecionado) if self.dialect == "postgres" else int(bool(row.selecionado)),
                sort_order,
                utc_now(),
            ],
        )

    def _record_event(
        self,
        connection: Any,
        event_type: str,
        username: str,
        process_id: int,
        risk_id: str | None,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> None:
        connection.execute(
            self._sql(
                """
                INSERT INTO matrix_events
                    (process_id, risk_id, event_type, username, before_json, after_json, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """
            ),
            [
                process_id,
                risk_id,
                event_type,
                username,
                json.dumps(before, ensure_ascii=False) if before is not None else None,
                json.dumps(after, ensure_ascii=False) if after is not None else None,
                utc_now(),
            ],
        )

    def _touch_process(self, connection: Any, process_id: int) -> None:
        connection.execute(
            self._sql("UPDATE procurements SET updated_at = ? WHERE id = ?"),
            [utc_now(), process_id],
        )


def storage_from_secrets(secrets: dict[str, Any] | None = None) -> Storage:
    secrets = secrets or {}
    database = secrets.get("database", {}) if isinstance(secrets, dict) else {}
    url = ""
    if isinstance(database, dict):
        url = str(database.get("url", "") or "")
    return Storage(url or DEFAULT_SQLITE_URL)


def context_from_process(process: dict[str, Any]) -> ContractContext:
    return ContractContext(
        objeto=process.get("objeto", ""),
        tipo_contratacao=process.get("tipo_contratacao", "aquisicao"),
        valor_estimado=float(process.get("valor_estimado") or 0),
        criticidade=process.get("criticidade", "media"),
        prazo=process.get("prazo", ""),
        modalidade=process.get("modalidade", ""),
        contexto=process.get("contexto", ""),
    )


def matrix_row_to_dict(row: MatrixRow) -> dict[str, Any]:
    return asdict(row)


def matrix_row_from_record(record: dict[str, Any]) -> MatrixRow:
    payload = json.loads(record["payload_json"]) if "payload_json" in record else record
    return matrix_row_from_dict(payload)


def matrix_row_from_dict(payload: dict[str, Any]) -> MatrixRow:
    return MatrixRow(
        id=str(payload.get("id", "")),
        risco=str(payload.get("risco", "")),
        categoria=str(payload.get("categoria", "planejamento")),
        causa=str(payload.get("causa", "")),
        consequencias=list(payload.get("consequencias") or []),
        probabilidade=str(payload.get("probabilidade", "3-Média")),
        impacto=str(payload.get("impacto", "3-Médio")),
        nivel=str(payload.get("nivel", "moderado")),
        estrategia=str(payload.get("estrategia", "Mitigar")),
        acoes_preventivas=[ActionItem(**item) for item in payload.get("acoes_preventivas", [])],
        acoes_contingencia=[ActionItem(**item) for item in payload.get("acoes_contingencia", [])],
        justificativa=str(payload.get("justificativa", "")),
        selecionado=bool(payload.get("selecionado", True)),
        tags=list(payload.get("tags") or []),
    )


def row_to_dict(row: Any) -> dict[str, Any]:
    if isinstance(row, dict):
        return dict(row)
    return dict(row)


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()
