"""Smoke test: sobe o app via TestClient e checa rotas/DB/templates.

IMPORTANTE: usa um banco ISOLADO e temporário. Nunca toca no banco real
(data/tg-system.db) — ele apaga tabelas, então jamais pode rodar em produção.
"""
import os
import tempfile

# Banco isolado, definido ANTES de importar config/models. python-dotenv não
# sobrescreve variáveis já presentes no ambiente, então isto vence o .env.
_tmp = os.path.join(tempfile.gettempdir(), "tg_system_smoketest.db")
if os.path.exists(_tmp):
    os.remove(_tmp)
os.environ["DATABASE_URL"] = "sqlite:///" + _tmp.replace("\\", "/")

from fastapi.testclient import TestClient  # noqa: E402

import config  # noqa: E402

# trava de segurança: aborta se por algum motivo apontar para o banco real
assert "smoketest" in config.DATABASE_URL, "smoke_test tentou usar o banco real!"

import panel  # noqa: E402
from models import Account, ForwardTask, SessionLocal, init_db  # noqa: E402

init_db()
with SessionLocal() as db:
    acc = Account(name="Teste", phone="+5500000000000",
                  session_string="x", status="authenticated")
    db.add(acc); db.commit()
    task = ForwardTask(name="t1", account_id=acc.id, source_id="-100111",
                       source_name="Origem", target_id="-100222",
                       target_name="Destino", deny_items="spam", whole_word=True)
    db.add(task); db.commit()
    task_id = task.id

with TestClient(panel.app) as c:
    assert c.get("/").status_code == 200
    assert "t1" in c.get("/").text
    assert c.get("/accounts").status_code == 200
    assert c.get("/integrations").status_code == 200
    assert c.get("/settings").status_code == 200
    assert c.get("/clone").status_code == 200
    assert c.get("/clone/new").status_code == 200
    assert c.get("/tasks/new").status_code == 200
    assert c.get(f"/tasks/{task_id}/edit").status_code == 200
    assert c.post(f"/tasks/{task_id}/toggle", follow_redirects=False).status_code == 303
    # cria uma clonagem e exercita os controles
    r = c.post("/clone/save", follow_redirects=False, data={
        "name": "c1", "account_id": acc.id, "source_id": "-100111",
        "target_id": "-100222", "delay_between": 1})
    assert r.status_code == 303
    assert "c1" in c.get("/clone").text
    cid = 1
    assert c.post(f"/clone/{cid}/start", follow_redirects=False).status_code == 303
    assert c.post(f"/clone/{cid}/pause", follow_redirects=False).status_code == 303
    assert c.post(f"/clone/{cid}/reset", follow_redirects=False).status_code == 303

try:
    os.remove(_tmp)
except OSError:
    pass  # o SQLite pode ainda segurar o handle; é só um arquivo temporário
print("SMOKE OK (banco isolado) — páginas, DB e rotas respondendo.")
