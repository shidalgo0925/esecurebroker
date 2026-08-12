"""Subject id helpers — kept free of web imports to avoid circular deps."""

from __future__ import annotations

_ACTOR_PREFIX = "piloto:"


def actor_id_for_username(username: str) -> str:
    return f"{_ACTOR_PREFIX}{username.strip()}"
