import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
  getUrlInfo,
} from "baileys";
import { Boom } from "@hapi/boom";
import qrcode from "qrcode-terminal";
import QRCode from "qrcode";
import pino from "pino";
import { join } from "node:path";
import { existsSync, rmSync } from "node:fs";
import { config } from "./config.js";
import { log } from "./logger.js";
import { setStatus } from "./status.js";

let sock = null;
let ready = false;
let sent = 0;
const queue = []; // mensagens que chegaram antes de o WhatsApp conectar

const UA =
  "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 " +
  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36";
const URL_RE = /https?:\/\/[^\s<>()\[\]{}"']+/i;

async function flush() {
  while (ready && queue.length) {
    const text = queue.shift();
    await deliver(text).catch((e) => log.error("Falha no envio:", e.message));
  }
}

/** Segue redirecionamentos (link curto/afiliado) até a URL final, com cara de navegador. */
async function resolveUrl(url) {
  try {
    const r = await fetch(url, {
      method: "GET",
      redirect: "follow",
      headers: { "user-agent": UA },
      signal: AbortSignal.timeout(8000),
    });
    return r.url || url;
  } catch {
    return url;
  }
}

/** Gera a prévia do link (com imagem) na URL final, buscando como navegador. */
async function buildPreview(text) {
  const match = text.match(URL_RE);
  if (!match) return undefined;
  try {
    const finalUrl = await resolveUrl(match[0]);
    const info = await getUrlInfo(finalUrl, {
      thumbnailWidth: 1024,
      fetchOpts: { timeout: 8000, headers: { "user-agent": UA } },
      uploadImage: sock.waUploadToServer,
    });
    const hasImg = Boolean(info?.jpegThumbnail || info?.highQualityThumbnail);
    log.info(`prévia: ${info?.title || "(sem título)"} | imagem=${hasImg}`);
    return info || undefined;
  } catch (e) {
    log.warn("prévia do link falhou:", e.message);
    return undefined;
  }
}

async function deliver(text) {
  if (!config.channelJid) {
    log.warn(
      "WHATSAPP_CHANNEL_JID não configurado — rode `npm run resolve-channel <link>`."
    );
    return;
  }
  const linkPreview = await buildPreview(text);
  await sock.sendMessage(config.channelJid, { text, linkPreview });
  const resumo = text.slice(0, 60).replace(/\n/g, " ");
  sent += 1;
  setStatus({ lastSent: resumo, lastSentAt: new Date().toISOString(), sentCount: sent });
  log.info("Enviado ao canal:", resumo);
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
    // Gera a prévia do link (com imagem) ao enviar — busca a imagem da URL
    // antes de mandar, então a foto do produto aparece no WhatsApp.
    generateHighQualityLinkPreview: true,
  });

  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", (update) => {
    const { connection, lastDisconnect, qr } = update;

    if (qr) {
      log.info("Escaneie o QR abaixo com o WhatsApp (uma única vez):");
      qrcode.generate(qr, { small: true });
      QRCode.toFile(join(config.dataDir, "qr.png"), qr, { width: 360, margin: 2 })
        .catch(() => {});
      setStatus({ state: "qr" });
    }

    if (connection === "open") {
      ready = true;
      log.info("WhatsApp conectado.");
      const qrPath = join(config.dataDir, "qr.png");
      if (existsSync(qrPath)) rmSync(qrPath, { force: true });
      setStatus({ state: "connected", channelJid: config.channelJid });
      flush();
    }

    if (connection === "close") {
      ready = false;
      const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
      const loggedOut = code === DisconnectReason.loggedOut;
      log.warn("WhatsApp desconectou.", loggedOut ? "(logout)" : "reconectando...");
      setStatus({ state: loggedOut ? "logged_out" : "disconnected" });
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
