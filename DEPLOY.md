# Deploy na VPS — ClonadorDePromocao

Dois serviços num monorepo, subindo com **um comando** via Docker Compose:

- **tg-system** — painel web (Forward + Clone + integrações). Porta 8000.
- **nodebot** — ponte Telegram → canal do WhatsApp. Sem porta (só conecta).

> Kubernetes não é necessário aqui: são dois contêineres pequenos num único host.
> K8s só valeria a pena com muitas réplicas/escala horizontal, que não é o caso.
> Docker Compose faz tudo com muito menos custo e complexidade.

## Pré-requisitos na VPS (uma vez)

Linux (Ubuntu/Debian) com Docker e o plugin Compose:

```bash
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker $USER   # relogue depois disto
```

O relógio da VPS já sincroniza por NTP — o problema de horário que trava os
grupos no PC local **não** acontece lá.

## Passo a passo

```bash
# 1. clonar
git clone https://github.com/ODevAbreu/ClonadorDePromocao.git
cd ClonadorDePromocao

# 2. criar os .env (NÃO vêm no git — são segredos)
cp tg-system/.env.example tg-system/.env   # preencha API_ID e API_HASH
cp nodebot/.env.example  nodebot/.env       # preencha TELEGRAM_BOT_TOKEN e o canal

# 3. subir tudo
docker compose up -d --build

# 4. logar o WhatsApp (1ª vez): o QR aparece no log do nodebot
docker compose logs -f nodebot
#   -> escaneie o QR com o WhatsApp (Aparelhos conectados). A sessão fica
#      salva em nodebot/auth/ e não precisa repetir.

# 5. configurar o painel: abra http://SEU_IP:8000
#   -> Configurações: cole API_ID/API_HASH (ou já no .env)
#   -> Contas: logue a conta do Telegram (código no app)
#   -> Forward/Clone: crie as tarefas
```

## O que persiste (volumes) e o que recriar

| Dado | Onde | Observação |
|---|---|---|
| Banco do painel (contas, tarefas, integrações) | `tg-system/data/` | volume; sobrevive a `down`/`up` |
| Sessão do Telegram (tg-system) | dentro do banco acima | — |
| Sessão do WhatsApp (nodebot) | `nodebot/auth/` | volume; escaneia o QR só 1x |
| Dedupe do nodebot | `nodebot/data/` | volume |
| Segredos | `*/.env` | **recriar na VPS**, nunca no git |

### Migrar seus dados locais (opcional)
Para não recadastrar contas/tarefas, copie **manualmente** (scp/sftp), nunca por git:
- `tg-system/data/tg-system.db` → mesmo caminho na VPS
- `nodebot/auth/` → mesmo caminho na VPS (evita reescanear o QR; mas logar de
  IP novo pode pedir reverificação)

## Comandos do dia a dia

```bash
docker compose ps                 # status
docker compose logs -f tg-system  # logs do painel
docker compose logs -f nodebot    # logs da ponte
docker compose restart nodebot    # reiniciar um serviço
docker compose down               # parar tudo
docker compose up -d --build      # aplicar mudanças após git pull
```

## HTTPS / acesso ao painel (recomendado)

A porta 8000 fica aberta. Para expor com segurança, ponha um proxy reverso com
HTTPS e senha na frente (ex.: Caddy):

```
# Caddyfile
painel.seudominio.com {
    reverse_proxy localhost:8000
    basicauth { seu_usuario SENHA_HASH }
}
```

Ou restrinja por firewall (libere a 8000 só para o seu IP), ou acesse por VPN.

## Avisos

- **Baileys e Telethon são não-oficiais / automação.** Logar de um IP novo (VPS)
  pode gerar reverificação ou **ban** das contas. Use números de teste, o mesmo
  proxy/região quando possível, e sem exageros de volume.
- `auth/`, `data/` e `.env` são **credenciais**. Já estão no `.gitignore`.
