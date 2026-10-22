import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} from "baileys";
import { Boom } from "@hapi/boom";
import qrcode from "qrcode-terminal";
import pino from "pino";
import { config } from "./config.js";
import { log } from "./logger.js";

let sock = null;
let ready = false;
const queue = []; // mensagens que chegaram antes de o WhatsApp conectar

async function flush() {
  while (ready && queue.length) {
    const text = queue.shift();
    await deliver(text).catch((e) => log.error("Falha no envio:", e.message));
  }
}

async function deliver(text) {
  if (!config.channelJid) {
    log.warn(
      "WHATSAPP_CHANNEL_JID não configurado — rode `npm run resolve-channel <link>`."
    );
    return;
  }
  await sock.sendMessage(config.channelJid, { text });
  log.info("Enviado ao canal:", text.slice(0, 60).replace(/\n/g, " "));
}

/** Conecta ao WhatsApp via Baileys, mostra QR na 1ª vez e reconecta sozinho. */
export async function startWhatsApp() {
  const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
  const { version } = await fetchLatestBaileysVersion();

  sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      log.info("Escaneie o QR abaixo com o WhatsApp (uma única vez):");
      qrcode.generate(qr, { small: true });
    }

    if (connection === "open") {
      ready = true;
      log.info("WhatsApp conectado.");
      flush();
    }

    if (connection === "close") {
      ready = false;
      const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      log.warn("WhatsApp desconectou.", loggedOut ? "(logout)" : "reconectando...");
      if (!loggedOut) {
        setTimeout(() => startWhatsApp().catch((e) => log.error(e.message)), 3000);
      } else {
        log.error("Sessão encerrada. Apague a pasta auth/ e logue de novo.");
      }
    }
  });

  return sock;
}

/** Envia um texto ao canal; enfileira se ainda não estiver conectado. */
export async function sendToChannel(text) {
  if (!ready) {
    queue.push(text);
    return;
  }
  await deliver(text);
}

export function getSocket() {
  return sock;
}
