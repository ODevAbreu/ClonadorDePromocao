"""Painel web de configuração (FastAPI). Roda o worker junto, no mesmo loop."""
from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import config
import json

from clone_worker import clone_runner
from models import (
    Account,
    CloneTask,
    ForwardTask,
    Integration,
    SessionLocal,
    get_setting,
    init_db,
    set_setting,
)
from tg_manager import manager
from worker import worker

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")

templates = Jinja2Templates(directory="templates")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    t1 = asyncio.create_task(worker.run())         # forward ao vivo
    t2 = asyncio.create_task(clone_runner.run())   # trabalhos de clone
    yield
    worker.stop()
    clone_runner.stop()
    t1.cancel()
    t2.cancel()


app = FastAPI(title="tg-system", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


# ---- páginas -------------------------------------------------------------
@app.get("/", response_class=HTMLResponse)
def home(request: Request):
    with SessionLocal() as db:
        tasks = db.query(ForwardTask).all()
        accounts = db.query(Account).all()
        return templates.TemplateResponse(
            "index.html",
            {"request": request, "tasks": tasks, "accounts": accounts},
        )


@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request):
    api_id = get_setting("API_ID") or (str(config.API_ID) if config.API_ID else "")
    api_hash = get_setting("API_HASH") or config.API_HASH
    configured = bool(api_id and api_hash)
    # mostra o hash mascarado, para não vazar na tela
    masked = (api_hash[:4] + "…" + api_hash[-4:]) if api_hash and len(api_hash) > 8 else ""
    return templates.TemplateResponse(
        "settings.html",
        {"request": request, "api_id": api_id, "configured": configured, "masked": masked},
    )


@app.post("/settings/save")
async def settings_save(api_id: str = Form(...), api_hash: str = Form("")):
    set_setting("API_ID", api_id.strip())
    if api_hash.strip():  # só sobrescreve o hash se você digitar um novo
        set_setting("API_HASH", api_hash.strip())
    return RedirectResponse("/settings?saved=1", status_code=303)


@app.get("/clone", response_class=HTMLResponse)
def clone_page(request: Request):
    with SessionLocal() as db:
        tasks = db.query(CloneTask).all()
        accounts = db.query(Account).all()
        return templates.TemplateResponse(
            "clone.html", {"request": request, "tasks": tasks, "accounts": accounts}
        )


@app.get("/clone/new", response_class=HTMLResponse)
def clone_new(request: Request):
    with SessionLocal() as db:
        accounts = db.query(Account).filter(Account.status == "authenticated").all()
        integrations = db.query(Integration).all()
        return templates.TemplateResponse(
            "clone_form.html",
            {"request": request, "accounts": accounts, "task": None,
             "integrations": integrations, "selected_ids": set()},
        )


@app.get("/clone/{task_id}/edit", response_class=HTMLResponse)
def clone_edit(request: Request, task_id: int):
    with SessionLocal() as db:
        task = db.get(CloneTask, task_id)
        accounts = db.query(Account).filter(Account.status == "authenticated").all()
        integrations = db.query(Integration).all()
        selected_ids = {i.id for i in task.integrations} if task else set()
        return templates.TemplateResponse(
            "clone_form.html",
            {"request": request, "accounts": accounts, "task": task,
             "integrations": integrations, "selected_ids": selected_ids},
        )


@app.post("/clone/save")
async def clone_save(
    task_id: str = Form(""),
    name: str = Form(...),
    account_id: int = Form(...),
    source_id: str = Form(...),
    source_name: str = Form(""),
    target_id: str = Form(...),
    target_name: str = Form(""),
    deny_items: str = Form(""),
    allow_items: str = Form(""),
    whole_word: str = Form("off"),
    replacements: str = Form(""),
    delay_between: float = Form(2.0),
    rest_every: int = Form(0),
    rest_seconds: float = Form(0.0),
    integration_ids: list[str] = Form(default=[]),
):
    with SessionLocal() as db:
        task = db.get(CloneTask, int(task_id)) if task_id else CloneTask()
        task.name = name
        task.account_id = account_id
        task.source_id = source_id
        task.source_name = source_name
        task.target_id = target_id
        task.target_name = target_name
        task.deny_items = deny_items
        task.allow_items = allow_items
        task.whole_word = whole_word == "on"
        task.replacements = replacements
        task.delay_between = delay_between
        task.rest_every = rest_every
        task.rest_seconds = rest_seconds
        ids = [int(x) for x in integration_ids if x.strip().isdigit()]
        task.integrations = (
            db.query(Integration).filter(Integration.id.in_(ids)).all() if ids else []
        )
        db.add(task)
        db.commit()
    return RedirectResponse("/clone", status_code=303)


def _clone_set_status(task_id: int, status: str, reset: bool = False) -> None:
    with SessionLocal() as db:
        task = db.get(CloneTask, task_id)
        if task:
            task.status = status
            if reset:
                task.last_message_id = 0
                task.cloned_count = 0
                task.detail = ""
            db.commit()


@app.post("/clone/{task_id}/start")
async def clone_start(task_id: int):
    _clone_set_status(task_id, "running")
    return RedirectResponse("/clone", status_code=303)


@app.post("/clone/{task_id}/pause")
async def clone_pause(task_id: int):
    _clone_set_status(task_id, "paused")
    return RedirectResponse("/clone", status_code=303)


@app.post("/clone/{task_id}/reset")
async def clone_reset(task_id: int):
    _clone_set_status(task_id, "idle", reset=True)
    return RedirectResponse("/clone", status_code=303)


@app.post("/clone/{task_id}/delete")
async def clone_delete(task_id: int):
    with SessionLocal() as db:
        task = db.get(CloneTask, task_id)
        if task:
            task.status = "idle"  # para o job em andamento, se houver
            db.delete(task)
            db.commit()
    return RedirectResponse("/clone", status_code=303)


@app.get("/integrations", response_class=HTMLResponse)
def integrations_page(request: Request):
    with SessionLocal() as db:
        items = db.query(Integration).all()
        # expõe o config já decodificado para o template
        view = []
        for it in items:
            cfg = {}
            try:
                cfg = json.loads(it.config or "{}")
            except json.JSONDecodeError:
                pass
            view.append({"obj": it, "cfg": cfg})
        return templates.TemplateResponse(
            "integrations.html", {"request": request, "items": view}
        )


@app.post("/integrations/save")
async def integrations_save(
    type: str = Form(...),
    name: str = Form(...),
    store_id: str = Form(""),
    domains: str = Form(""),
    params: str = Form(""),
    strip: str = Form(""),
    app_id: str = Form(""),
    secret: str = Form(""),
    ml_tag: str = Form(""),
    ml_cookie: str = Form(""),
):
    if type == "amazon":
        cfg = {"store_id": store_id.strip()}
    elif type == "generic":
        cfg = {"domains": domains.strip(), "params": params.strip(), "strip": strip.strip()}
    elif type == "shopee":
        cfg = {"app_id": app_id.strip(), "secret": secret.strip()}
    elif type == "mercadolivre":
        cfg = {"tag": ml_tag.strip(), "cookie": ml_cookie.strip()}
    else:
        cfg = {}
    with SessionLocal() as db:
        db.add(Integration(name=name, type=type, config=json.dumps(cfg), enabled=True))
        db.commit()
    return RedirectResponse("/integrations", status_code=303)


@app.post("/integrations/{item_id}/toggle")
async def integrations_toggle(item_id: int):
    with SessionLocal() as db:
        it = db.get(Integration, item_id)
        if it:
            it.enabled = not it.enabled
            db.commit()
    return RedirectResponse("/integrations", status_code=303)


@app.post("/integrations/{item_id}/delete")
async def integrations_delete(item_id: int):
    with SessionLocal() as db:
        it = db.get(Integration, item_id)
        if it:
            db.delete(it)
            db.commit()
    return RedirectResponse("/integrations", status_code=303)


@app.get("/accounts", response_class=HTMLResponse)
def accounts_page(request: Request):
    with SessionLocal() as db:
        accounts = db.query(Account).all()
        return templates.TemplateResponse(
            "accounts.html", {"request": request, "accounts": accounts}
        )


@app.get("/tasks/new", response_class=HTMLResponse)
def task_new(request: Request):
    with SessionLocal() as db:
        accounts = db.query(Account).filter(Account.status == "authenticated").all()
        integrations = db.query(Integration).all()
        return templates.TemplateResponse(
            "task_form.html",
            {"request": request, "accounts": accounts, "task": None,
             "integrations": integrations, "selected_ids": set()},
        )


@app.get("/tasks/{task_id}/edit", response_class=HTMLResponse)
def task_edit(request: Request, task_id: int):
    with SessionLocal() as db:
        task = db.get(ForwardTask, task_id)
        accounts = db.query(Account).filter(Account.status == "authenticated").all()
        integrations = db.query(Integration).all()
        selected_ids = {i.id for i in task.integrations} if task else set()
        return templates.TemplateResponse(
            "task_form.html",
            {"request": request, "accounts": accounts, "task": task,
             "integrations": integrations, "selected_ids": selected_ids},
        )


# ---- login de conta (2 passos) -------------------------------------------
@app.post("/accounts/send-code")
async def send_code(phone: str = Form(...)):
    try:
        await manager.start_login(phone)
        return JSONResponse({"ok": True})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


@app.post("/accounts/confirm")
async def confirm(name: str = Form(...), phone: str = Form(...),
                  code: str = Form(...), password: str = Form("")):
    try:
        session_string = await manager.confirm_login(phone, code, password or None)
    except Exception as exc:  # noqa: BLE001
        msg = "Senha de 2FA necessária." if str(exc) == "2FA_REQUIRED" else str(exc)
        return JSONResponse({"ok": False, "error": msg}, status_code=400)

    with SessionLocal() as db:
        acc = db.query(Account).filter(Account.phone == phone).first() or Account(phone=phone)
        acc.name = name
        acc.session_string = session_string
        acc.status = "authenticated"
        db.add(acc)
        db.commit()
        account_id = acc.id
    await manager.finish_login(account_id, phone)
    return JSONResponse({"ok": True})


@app.post("/accounts/{account_id}/delete")
async def delete_account(account_id: int):
    await manager.drop(account_id)
    with SessionLocal() as db:
        acc = db.get(Account, account_id)
        if acc:
            db.delete(acc)
            db.commit()
    return RedirectResponse("/accounts", status_code=303)


@app.get("/accounts/{account_id}/dialogs")
async def dialogs(account_id: int):
    with SessionLocal() as db:
        acc = db.get(Account, account_id)
        if not acc or acc.status != "authenticated":
            return JSONResponse({"ok": False, "error": "conta não autenticada"}, 400)
        session = acc.session_string
    try:
        groups = await manager.list_dialogs(account_id, session)
        return JSONResponse({"ok": True, "dialogs": groups})
    except Exception as exc:  # noqa: BLE001
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=400)


# ---- CRUD de tarefas ------------------------------------------------------
@app.post("/tasks/save")
async def task_save(
    task_id: str = Form(""),
    name: str = Form(...),
    account_id: int = Form(...),
    source_id: str = Form(...),
    source_name: str = Form(""),
    target_id: str = Form(...),
    target_name: str = Form(""),
    deny_items: str = Form(""),
    allow_items: str = Form(""),
    whole_word: str = Form("off"),
    replacements: str = Form(""),
    delay_before_forward: float = Form(0.0),
    integration_ids: list[str] = Form(default=[]),
):
    with SessionLocal() as db:
        task = db.get(ForwardTask, int(task_id)) if task_id else ForwardTask()
        task.name = name
        task.account_id = account_id
        task.source_id = source_id
        task.source_name = source_name
        task.target_id = target_id
        task.target_name = target_name
        task.deny_items = deny_items
        task.allow_items = allow_items
        task.whole_word = whole_word == "on"
        task.replacements = replacements
        task.delay_before_forward = delay_before_forward
        # vincula as integrações marcadas a esta tarefa
        ids = [int(x) for x in integration_ids if x.strip().isdigit()]
        task.integrations = (
            db.query(Integration).filter(Integration.id.in_(ids)).all() if ids else []
        )
        db.add(task)
        db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/tasks/{task_id}/toggle")
async def task_toggle(task_id: int):
    with SessionLocal() as db:
        task = db.get(ForwardTask, task_id)
        if task:
            task.enabled = not task.enabled
            db.commit()
    return RedirectResponse("/", status_code=303)


@app.post("/tasks/{task_id}/delete")
async def task_delete(task_id: int):
    with SessionLocal() as db:
        task = db.get(ForwardTask, task_id)
        if task:
            db.delete(task)
            db.commit()
    return RedirectResponse("/", status_code=303)
