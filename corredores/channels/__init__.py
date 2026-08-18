"""Public quote/sales channels bound to an ESB organization (no portfolio logic)."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_CHANNELS_DIR = Path(__file__).resolve().parent


@lru_cache(maxsize=32)
def load_channel(slug: str) -> dict[str, Any]:
    path = _CHANNELS_DIR / f"{slug}.json"
    if not path.is_file():
        raise FileNotFoundError(f"channel config not found: {slug}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("channel_slug") != slug:
        raise ValueError(f"channel_slug mismatch in {path.name}")
    return data
