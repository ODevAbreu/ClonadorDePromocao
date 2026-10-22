# Ponte Telegram → WhatsApp (canal)

Escuta posts de um canal/bot do Telegram e repassa para um **canal do WhatsApp**.
Roda **headless** (sem navegador, sem apertar Enter), pronto para VPS 24/7.

## Como funciona

```
Telegram (polling)  →  dedupe persistente  →  template  →  WhatsApp (Baileys)
```

- **Telegram**: `node-telegram-bot-api` em polling, escuta `channel_post` e `message`.
- **Dedupe**: `data/processed.json` evita repassar duas vezes (sobrevive a reinícios).
- **WhatsApp**: `baileys` conecta por WebSocket (sem navegador), login por QR só na 1ª vez; a sessão fica em `auth/`. Reconecta sozinho e enfileira mensagens enquanto conecta.

## Arquivos

| Arquivo | Papel |
|---|---|
| `src/config.js` | lê e valida o `.env` (falha cedo se faltar algo) |
| `src/telegram.js` | escuta o Telegram, dedupe, entrega o texto |
| `src/whatsapp.js` | conecta ao WhatsApp (Baileys) e envia ao canal |
| `src/format.js` | extrai o texto e aplica o template |
| `src/store.js` | dedupe persistente |
| `src/index.js` | liga tudo |
| `scripts/resolve-channel.js` | descobre o JID do canal pelo link |
| `legado/` | o código antigo (ponte.js etc.), só referência |

## Rodar

```bash
cp .env.example .env     # preencha TELEGRAM_BOT_TOKEN
npm install
npm start                # 1ª vez: aparece um QR no terminal — escaneie com o WhatsApp
```

Depois de logar, descubra o JID do canal e coloque no `.env`:

```bash
npm run resolve-channel https://whatsapp.com/channel/XXXXXXXX
# copie o WHATSAPP_CHANNEL_JID que ele imprimir para o .env e reinicie
```

## Na VPS (24/7)

```bash
npm install
npm start            # escaneie o QR uma vez (a sessão fica salva em auth/)
# Ctrl+C e então:
npm i -g pm2
pm2 start ecosystem.config.cjs
pm2 logs             # acompanhar
pm2 save && pm2 startup   # subir sozinho no boot
```

## Avisos honestos

- **Baileys é não-oficial.** O WhatsApp pode **banir o número** usado para automação; use um número de teste e com moderação.
- `auth/` é a sua sessão do WhatsApp (equivale a login) e `.env` tem o token — ambos no `.gitignore`. Não suba para lugar público nem deixe no OneDrive compartilhado.
- O envio a canal/newsletter depende da versão do Baileys e das regras do WhatsApp; teste com o seu canal real após o login.
