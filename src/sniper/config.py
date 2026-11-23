"""Einstellungen aus Umgebungsvariablen, mit denselben Namen wie im Reseller-Dashboard."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    port: int
    app_password: str
    app_user: str
    ebay_client_id: str
    ebay_client_secret: str

    @classmethod
    def from_env(cls, env: Mapping[str, str] = os.environ) -> Settings:
        return cls(
            data_dir=Path(env.get("DATA_DIR") or "/data"),
            port=int(env.get("PORT") or 8095),
            app_password=env.get("APP_PASSWORD", ""),
            app_user=env.get("APP_USER") or "admin",
            ebay_client_id=env.get("EBAY_CLIENT_ID", ""),
            ebay_client_secret=env.get("EBAY_CLIENT_SECRET", ""),
        )
