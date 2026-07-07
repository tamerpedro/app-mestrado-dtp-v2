from __future__ import annotations

import re


PROCESS_NUMBER_RE = re.compile(r"^\d{5}\.\d{6}/\d{4}-\d{2}$")
MAX_PROCESS_NAME_LENGTH = 255


def validate_process_number(value: str) -> str:
    number = (value or "").strip()
    if not PROCESS_NUMBER_RE.fullmatch(number):
        raise ValueError("Número do processo deve seguir o padrão SEI 00000.000000/0000-00.")
    return number


def validate_process_name(value: str) -> str:
    name = " ".join((value or "").strip().split())
    if not name:
        raise ValueError("Nome do processo é obrigatório.")
    if len(name) > MAX_PROCESS_NAME_LENGTH:
        raise ValueError("Nome do processo deve ter no máximo 255 caracteres.")
    return name
