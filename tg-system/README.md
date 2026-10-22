# tg-system

Sistema de encaminhamento de Telegram com **painel web de configuração** +
**worker headless**, para rodar 24/7 num VPS sem PC ligado. Construído do zero a
partir do estudo de engenharia reversa de um app desktop — a mesma lógica,
numa arquitetura própria e de nuvem.

## Arquitetura

```
Painel web (FastAPI)  ──escreve──►  Banco (SQLite)  ◄──lê──  Worker (Telethon)
  contas · grupos ·                  contas, tarefas,          roda os forwards
  filtros · tarefas                  filtros                   ao vivo
```

Tudo roda num processo só (`uvicorn panel:app`): o painel e o worker dividem o
mesmo loop asyncio e **um único client por conta** (via `tg_manager`, para não
duplicar sessão). O worker reconcilia os handlers com o banco a cada 5s — mudou
a config, ligou/desligou uma tarefa, ele se ajusta sozinho.

## Funcionalidades (v1 — Forward)

- **Contas**: adicionar por telefone, login por **código no navegador** (+ 2FA se houver), remover.
- **Seleção de grupos por lista**: escolhe origem e destino num dropdown com os grupos/canais reais da conta (sem digitar IDs).
- **Filtros** (a lógica estudada): `deny` (bloqueia se contém), `allow` (só passa se contém), com casamento por **palavra inteira** (corrige o bug de substring do app original).
- **Substituições** de texto (literal ou `re:` regex).
- **Anti-flood**: espera configurável antes de repassar.
- **Liga/desliga** por tarefa, edição e remoção.

## Arquivos

| Arquivo | Papel |
|---|---|
| `config.py` | credenciais/paths do `.env` |
| `models.py` | `Account` e `ForwardTask` (SQLAlchemy) |
| `filters.py` | motor deny/allow + substituição |
| `tg_manager.py` | um client por conta + fluxo de login |
| `worker.py` | reconcilia handlers de forward com o banco |
| `panel.py` | FastAPI: páginas e endpoints; sobe o worker no lifespan |
| `templates/` | HTML do painel |
| `smoke_test.py` | teste de fumaça (sobe o app, checa rotas/DB, sem Telegram) |

## Rodar localmente

```bash
python -m venv .venv
.venv/Scripts/activate            # Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env              # preencha API_ID e API_HASH (my.telegram.org)
uvicorn panel:app --reload
```
Abra <http://127.0.0.1:8000> → **Contas** (adicione e logue uma conta) → **Tarefas** (crie um forward escolhendo os grupos).

Teste de fumaça: `python smoke_test.py`

## Rodar no VPS 24/7 (Docker)

```bash
cp .env.example .env              # preencha as credenciais
docker compose up -d --build      # painel em http://SEU_VPS:8000
docker compose logs -f
```
O volume `./data` guarda banco e sessões. `restart: unless-stopped` religa sozinho.

> **Exponha o painel com cuidado**: a porta 8000 fica aberta. Use atrás de uma
> VPN, firewall liberando só o seu IP, ou um proxy reverso com HTTPS + senha.
> O banco contém as sessões (credenciais) das contas.

## Próximos passos

- **Clone** (histórico): copiar mensagens antigas, com paginação/retomada.
- **Álbuns/mídia agrupada** (o app tratava `events.Album`).
- **Histórico/estatísticas** por tarefa (quantas repassadas/bloqueadas).
- Autenticação do painel (login) e Postgres para escala.

## Avisos

- Sessão = credencial. O banco e a pasta `data/` são segredos (já no `.gitignore`).
- Login de IP novo (VPS) pode gerar reverificação/ban — use `PROXY_URL` da mesma região.
- Automação em massa vive no limite dos Termos do Telegram; use com responsabilidade.
