"""Gerencia um único TelegramClient por conta no processo inteiro.

Painel e worker usam ESTE objeto, para nunca haver duas conexões com a
mesma sessão (evita AuthKeyDuplicatedError). Também concentra o fluxo de
login (enviar código, confirmar código, senha 2FA).
"""
from __future__ import annotations

import asyncio

from telethon import TelegramClient
from telethon.sessions import StringSession

import config
import models


def resolve_api() -> tuple[int, str]:
    """API_ID/API_HASH vêm do painel (banco); se vazios, caem no .env."""
    api_id = models.get_setting("API_ID") or (str(config.API_ID) if config.API_ID else "")
    api_hash = models.get_setting("API_HASH") or config.API_HASH
    if not api_id or not api_hash:
        raise RuntimeError(
            "Configure API_ID e API_HASH na aba Configurações (pegue em my.telegram.org)."
        )
    return int(api_id), api_hash


def _proxy():
    if config.PROXY_URL:
        import python_socks

        return python_socks.parse_proxy_url(config.PROXY_URL)
    return None


class ClientManager:
    def __init__(self) -> None:
        self._clients: dict[int, TelegramClient] = {}   # account_id -> client ativo
        self._pending: dict[str, TelegramClient] = {}   # phone -> client em login
        self._lock = asyncio.Lock()

    # ---- fluxo de login (usado pelo painel) ---------------------------------
    async def start_login(self, phone: str) -> None:
        """Cria um client novo e envia o código SMS/app para o telefone."""
        api_id, api_hash = resolve_api()
        client = TelegramClient(StringSession(), api_id, api_hash, proxy=_proxy())
        await client.connect()
        await client.send_code_request(phone)
        old = self._pending.pop(phone, None)
        if old:
            await old.disconnect()
        self._pending[phone] = client

    async def confirm_login(self, phone: str, code: str,
                            password: str | None = None) -> str:
        """Confirma o código (e senha 2FA se houver). Retorna a session_string."""
        from telethon.errors import SessionPasswordNeededError

        client = self._pending.get(phone)
        if client is None:
            raise RuntimeError("Nenhum login pendente para este telefone.")
        try:
            await client.sign_in(phone=phone, code=code)
        except SessionPasswordNeededError:
            if not password:
                raise RuntimeError("2FA_REQUIRED")
            await client.sign_in(password=password)
        return client.session.save()

    async def finish_login(self, account_id: int, phone: str) -> None:
        """Move o client de 'pendente' para 'ativo' sob o id da conta."""
        client = self._pending.pop(phone, None)
        if client is not None:
            self._clients[account_id] = client

    # ---- uso pelo worker e pelo seletor de grupos ---------------------------
    async def get_client(self, account_id: int, session_string: str) -> TelegramClient:
        async with self._lock:
            client = self._clients.get(account_id)
            if client is None:
                api_id, api_hash = resolve_api()
                client = TelegramClient(StringSession(session_string),
                                        api_id, api_hash, proxy=_proxy())
                self._clients[account_id] = client
            if not client.is_connected():
                await client.connect()
            return client

    async def is_authorized(self, account_id: int, session_string: str) -> bool:
        client = await self.get_client(account_id, session_string)
        return await client.is_user_authorized()

    async def list_dialogs(self, account_id: int, session_string: str) -> list[dict]:
        """Grupos e canais da conta, para o seletor do painel."""
        client = await self.get_client(account_id, session_string)
        dialogs = []
        async for d in client.iter_dialogs():
            if d.is_group or d.is_channel:
                dialogs.append({"id": str(d.id), "name": d.name or str(d.id)})
        return dialogs

    async def drop(self, account_id: int) -> None:
        client = self._clients.pop(account_id, None)
        if client is not None and client.is_connected():
            await client.disconnect()


manager = ClientManager()
