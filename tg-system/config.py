"""Configuração global do sistema (credenciais de API e caminhos)."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()

API_ID = int(os.getenv("API_ID", "0"))
API_HASH = os.getenv("API_HASH", "")
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///data/tg-system.db")
PROXY_URL = os.getenv("PROXY_URL") or None
# Senha simples para abrir o painel (deixe vazio para liberar — só em rede confiável).
PANEL_PASSWORD = os.getenv("PANEL_PASSWORD", "")


def require_api() -> None:
    if not API_ID or not API_HASH:
        raise RuntimeError(
            "Configure API_ID e API_HASH no .env (pegue em https://my.telegram.org)."
        )
