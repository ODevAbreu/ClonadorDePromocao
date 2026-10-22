"""Worker de forward: reconcilia os handlers do Telegram com o banco.

A cada poucos segundos lê as tarefas habilitadas e garante que cada uma
tem seu handler ativo. Se a config muda (ou a tarefa é desligada/apagada),
reconstrói. Roda no mesmo loop asyncio do painel (via lifespan do FastAPI).
"""
from __future__ import annotations

import asyncio
import logging

from telethon import events

from filters import ForwardPolicy, apply_replacements, parse_replacements, split_items
from integrations import build_integrations, rewrite_links
from models import ForwardTask, Integration, SessionLocal
from tg_manager import manager

log = logging.getLogger("worker")

POLL_SECONDS = 5


class ForwardWorker:
    def __init__(self) -> None:
        # task_id -> (signature, client, handler_callback)
        self._active: dict[int, tuple] = {}
        self._running = False

    async def run(self) -> None:
        self._running = True
        log.info("Worker de forward iniciado.")
        while self._running:
            try:
                await self._reconcile()
            except Exception as exc:  # noqa: BLE001
                log.error("Erro na reconciliação: %s", exc)
            await asyncio.sleep(POLL_SECONDS)

    def stop(self) -> None:
        self._running = False

    async def _reconcile(self) -> None:
        with SessionLocal() as db:
            tasks = db.query(ForwardTask).filter(ForwardTask.enabled.is_(True)).all()
            desired = {}
            for t in tasks:
                if t.account and t.account.status == "authenticated":
                    desired[t.id] = self._snapshot(t)

        # remove handlers que saíram ou mudaram
        for task_id in list(self._active):
            sig, client, cb = self._active[task_id]
            if task_id not in desired or desired[task_id]["sig"] != sig:
                client.remove_event_handler(cb)
                del self._active[task_id]
                log.info("Handler removido/atualizado: tarefa %s", task_id)

        # adiciona os que faltam
        for task_id, snap in desired.items():
            if task_id not in self._active:
                try:
                    await self._install(task_id, snap)
                except Exception as exc:  # noqa: BLE001
                    self._mark_account_failed(snap["account_id"], exc)

    @staticmethod
    def _bump(task_id: int) -> None:
        """Soma +1 ao contador de repasses da tarefa."""
        with SessionLocal() as db:
            t = db.get(ForwardTask, task_id)
            if t:
                t.forwarded_count = (t.forwarded_count or 0) + 1
                db.commit()

    @staticmethod
    def _mark_account_failed(account_id: int, exc: Exception) -> None:
        """Sessão inválida/queda: marca a conta e para de tentar (sem spam de log)."""
        from models import Account

        with SessionLocal() as db:
            acc = db.get(Account, account_id)
            if acc and acc.status == "authenticated":
                acc.status = "failed"
                db.commit()
                log.warning("Conta %s marcada como 'failed': %s", account_id, exc)

    @staticmethod
    def _snapshot(t: ForwardTask) -> dict:
        # as integrações da tarefa entram na assinatura: se mudarem, reconstrói
        ig_sig = tuple(sorted((i.id, i.type, i.config, i.enabled) for i in t.integrations))
        return {
            "sig": t.signature() + (ig_sig,),
            "integrations": build_integrations(list(t.integrations)),
            "account_id": t.account_id,
            "session": t.account.session_string,
            "source": int(t.source_id) if t.source_id.lstrip("-").isdigit() else t.source_id,
            "target": int(t.target_id) if t.target_id.lstrip("-").isdigit() else t.target_id,
            "policy": ForwardPolicy(split_items(t.deny_items),
                                    split_items(t.allow_items), t.whole_word),
            "replacements": parse_replacements(t.replacements),
            "delay": t.delay_before_forward,
            "name": t.name,
        }

    async def _install(self, task_id: int, snap: dict) -> None:
        client = await manager.get_client(snap["account_id"], snap["session"])
        if not await client.is_user_authorized():
            log.warning("Conta %s não autorizada; pulando tarefa %s",
                        snap["account_id"], task_id)
            return

        policy = snap["policy"]
        replacements = snap["replacements"]
        delay = snap["delay"]
        target = snap["target"]
        name = snap["name"]
        integrations = snap["integrations"]   # só as desta tarefa
        tid = task_id

        async def handler(event: events.NewMessage.Event) -> None:
            text = event.message.message or ""
            allowed, reason = policy.decide(text)
            if not allowed:
                log.info("[%s] DESCARTADA (%s)", name, reason)
                return
            if delay > 0:
                await asyncio.sleep(delay)
            new_text = apply_replacements(text, replacements)
            new_text = await rewrite_links(new_text, integrations)
            try:
                if event.message.media:
                    await client.send_file(target, event.message.media, caption=new_text)
                else:
                    await client.send_message(target, new_text)
                self._bump(tid)
                log.info("[%s] REPASSADA: %r", name, new_text[:50])
            except Exception as exc:  # noqa: BLE001
                log.error("[%s] ERRO: %s", name, exc)

        client.add_event_handler(handler, events.NewMessage(chats=snap["source"]))
        self._active[task_id] = (snap["sig"], client, handler)
        log.info("Handler instalado: tarefa %s (%s)", task_id, name)


worker = ForwardWorker()
