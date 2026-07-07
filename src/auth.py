from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping


PBKDF2_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 260_000


def hash_password(password: str, salt: str = "app-mestrado") -> str:
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        PBKDF2_ITERATIONS,
    ).hex()
    return f"{PBKDF2_PREFIX}${PBKDF2_ITERATIONS}${salt}${digest}"


def _verify_password(password: str, stored_value: str) -> bool:
    parts = stored_value.split("$", 3)
    if len(parts) == 4 and parts[0] == PBKDF2_PREFIX:
        _, iterations, salt, expected_digest = parts
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            salt.encode("utf-8"),
            int(iterations),
        ).hex()
        return hmac.compare_digest(digest, expected_digest)

    return hmac.compare_digest(password, stored_value)


def _to_plain_dict(value: object) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    return {
        str(username): str(password)
        for username, password in value.items()
        if str(username).strip() and str(password)
    }


def _users_from_env(environ: Mapping[str, str]) -> dict[str, str]:
    username = environ.get("APP_USERNAME", "").strip()
    password = environ.get("APP_PASSWORD", "")
    if username and password:
        return {username: password}
    return {}


def load_users(
    secrets: Mapping[str, object] | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    environ = environ or os.environ
    users = _users_from_env(environ)

    if secrets:
        auth_config = secrets.get("auth", {})
        if isinstance(auth_config, Mapping):
            users.update(_to_plain_dict(auth_config.get("users")))
            users.update(_to_plain_dict(auth_config.get("password_hashes")))

    return users


def is_authorized(username: str, password: str, users: Mapping[str, str]) -> bool:
    stored_value = users.get(username.strip())
    if not stored_value:
        return False
    return _verify_password(password, stored_value)
