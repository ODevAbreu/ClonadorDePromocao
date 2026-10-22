"""Runner de clonagem: executa trabalhos que percorrem o histórico.

Diferente do forward (escuta ao vivo), o clone é um trabalho com começo, meio
e fim. Ele percorre as mensagens da origem do mais antigo para o mais novo,
aplica o mesmo pipeline (filtro -> substituição -> integração) e repassa ao
destino, guardando o progresso (last_message_id) para pausar e retomar.

Controle pelo status no banco:
  idle    -> parado (reinicia do começo se last_message_id=0)
  running -> o runner inicia o trabalho
  paused  -> o trabalho em andamento percebe e para, guardando o progresso
  done    -> terminou o histórico
  error   -> falhou (detail explica)
"""
from __future__ import annotations

import asyncio
import logging

from filters import ForwardPolicy, apply_replacements, parse_replacements, split_items
from integrations import build_integrations, rewrite_links
from models import CloneTask, SessionLocal
from tg_manager import manager

log = logging.getLogger("clone")

POLL_SECONDS = 3
PERSIST_EVERY = 10  # grava progresso a cada N mensagens


class CloneRunner:
    def __init__(self) -> None:
        self._jobs: dict[int, asyncio.Task] = {}
        self._running = False

    async def run(self) -> None:
        self._running = True
        log.info("Runner de clone iniciado.")
        while self._running:
            try:
                await self._reconcile()
            except Exception as exc:  # noqa: BLE001
                log.error("Erro na reconciliação de clone: %s", exc)
            await asyncio.sleep(POLL_SECONDS)

    def stop(self) -> None:
        self._running = False

    async def _reconcile(self) -> None:
        with SessionLocal() as db:
            running = db.query(CloneTask).filter(CloneTask.status == "running").all()
            wanted = {t.id for t in running if t.account and t.account.status == "authenticated"}
        # inicia trabalhos que faltam
        for task_id in wanted:
            if task_id not in self._jobs or self._jobs[task_id].done():
                self._jobs[task_id] = asyncio.create_task(self._run_job(task_id))
        # limpa referências de trabalhos já concluídos
        for task_id in [t for t in self._jobs if self._jobs[t].done()]:
            del self._jobs[task_id]

    @staticmethod
    def _load(task_id: int) -> dict | None:
        with SessionLocal() as db:
            t = db.get(CloneTask, task_id)
            if not t or not t.account:
                return None
            return {
                "session": t.account.session_string,
                "account_id": t.account_id,
                "source": int(t.source_id) if t.source_id.lstrip("-").isdigit() else t.source_id,
                "target": int(t.target_id) if t.target_id.lstrip("-").isdigit() else t.target_id,
                "policy": ForwardPolicy(split_items(t.deny_items),
                                        split_items(t.allow_items), t.whole_word),
                "replacements": parse_replacements(t.replacements),
                "integrations": build_integrations(list(t.integrations)),
                "delay": t.delay_between,
                "rest_every": t.rest_every,
                "rest_seconds": t.rest_seconds,
                "last_id": t.last_message_id,
                "name": t.name,
            }

    @staticmethod
    def _status(task_id: int) -> str:
        with SessionLocal() as db:
            t = db.get(CloneTask, task_id)
            return t.status if t else "idle"

    @staticmethod
    def _save_progress(task_id: int, last_id: int, count: int,
                       status: str | None = None, detail: str | None = None) -> None:
        with SessionLocal() as db:
            t = db.get(CloneTask, task_id)
            if not t:
                return
            t.last_message_id = last_id
            t.cloned_count = count
            if status is not None:
                t.status = status
            if detail is not None:
                t.detail = detail
            db.commit()

    async def _run_job(self, task_id: int) -> None:
        snap = self._load(task_id)
        if snap is None:
            return
        name = snap["name"]
        log.info("[clone %s] iniciando em offset_id=%s", name, snap["last_id"])
        self._save_progress(task_id, snap["last_id"], 0, detail="Conectando...")

        try:
            client = await manager.get_client(snap["account_id"], snap["session"])
            if not await client.is_user_authorized():
                self._save_progress(task_id, snap["last_id"], 0, "error",
                                    "Conta não autorizada.")
                return

            policy = snap["policy"]
            replacements = snap["replacements"]
            integrations = snap["integrations"]
            target = snap["target"]
            count = 0
            last_id = snap["last_id"]
            since_rest = 0

            # reverse=True: do mais antigo para o mais novo; offset_id retoma
            async for msg in client.iter_messages(snap["source"], reverse=True,
                                                   offset_id=snap["last_id"]):
                # respeita pausa/parada pedida pelo painel
                st = self._status(task_id)
                if st != "running":
                    self._save_progress(task_id, last_id, count,
                                        detail=f"Pausado em {count} mensagens.")
                    log.info("[clone %s] pausado/parado (status=%s)", name, st)
                    return

                text = msg.message or ""
                allowed, _ = policy.decide(text)
                if allowed and (text or msg.media):
                    new_text = apply_replacements(text, replacements)
                    new_text = await rewrite_links(new_text, integrations)
                    try:
                        if msg.media:
                            await client.send_file(target, msg.media, caption=new_text)
                        else:
                            await client.send_message(target, new_text)
                        count += 1
                        since_rest += 1
                    except Exception as exc:  # noqa: BLE001
                        log.error("[clone %s] erro ao enviar msg %s: %s", name, msg.id, exc)

                last_id = msg.id
                if count % PERSIST_EVERY == 0:
                    self._save_progress(task_id, last_id, count,
                                        detail=f"{count} mensagens clonadas...")

                # descanso programado (anti-flood)
                if snap["rest_every"] and since_rest >= snap["rest_every"]:
                    since_rest = 0
                    self._save_progress(task_id, last_id, count,
                                        detail=f"Descansando {snap['rest_seconds']}s...")
                    await asyncio.sleep(snap["rest_seconds"])
                elif snap["delay"] > 0:
                    await asyncio.sleep(snap["delay"])

            self._save_progress(task_id, last_id, count, "done",
                                f"Concluído: {count} mensagens clonadas.")
            log.info("[clone %s] concluído (%s mensagens)", name, count)

        except Exception as exc:  # noqa: BLE001
            self._save_progress(task_id, snap["last_id"], 0, "error", str(exc)[:290])
            log.error("[clone %s] erro: %s", name, exc)


clone_runner = CloneRunner()
