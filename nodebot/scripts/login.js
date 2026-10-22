/**
 * Login único do WhatsApp: gera o QR (terminal + qr.png) para escanear.
 * Após o pareamento, o WhatsApp manda um "restart required" (515) — isto é
 * normal; reconectamos automaticamente até a conexão abrir de fato. Ao abrir,
 * resolve o JID do canal (pelo link no .env) e grava no .env.
 */
import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
  DisconnectReason,
} from "baileys";
import { Boom } from "@hapi/boom";
import QRCode from "qrcode";
import qrTerminal from "qrcode-terminal";
import pino from "pino";
import { readFileSync, writeFileSync } from "node:fs";
import { config } from "../src/config.js";
import { log } from "../src/logger.js";

const link = (process.env.WHATSAPP_CHANNEL_LINK || "").trim();

function setEnv(key, value) {
  let raw = readFileSync(".env", "utf8");
  const line = `${key}=${value}`;
  raw = raw.match(new RegExp(`^${key}=.*$`, "m"))
    ? raw.replace(new RegExp(`^${key}=.*$`, "m"), line)
    : raw.replace(/\n?$/, `\n${line}\n`);
  writeFileSync(".env", raw);
}

const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
const { version } = await fetchLatestBaileysVersion();

async function connect() {
  const sock = makeWASocket({
    version,
    auth: state,
    logger: pino({ level: "silent" }),
    printQRInTerminal: false,
  });
  sock.ev.on("creds.update", saveCreds);

  sock.ev.on("connection.update", async (u) => {
    const { connection, qr, lastDisconnect } = u;

    if (qr) {
      await QRCode.toFile("qr.png", qr, { width: 420, margin: 2 });
      console.log("\n=== Escaneie este QR com o WhatsApp (Aparelhos conectados) ===\n");
      qrTerminal.generate(qr, { small: true });
      log.info("QR acima. Também salvo em qr.png.");
    }

    if (connection === "open") {
      log.info("WhatsApp conectado! Sessão salva em auth/.");
      if (link) {
        try {
          const code = link.split("/channel/").pop().split(/[/?]/)[0];
          const meta = await sock.newsletterMetadata("invite", code);
          setEnv("WHATSAPP_CHANNEL_JID", meta.id);
          log.info(`Canal "${meta.name}" → JID ${meta.id} gravado no .env.`);
        } catch (e) {
          log.warn("Conectou, mas não resolvi o canal:", e.message);
        }
      }
      setTimeout(() => process.exit(0), 1500);
    }

    if (connection === "close") {
      const code = new Boom(lastDisconnect?.error)?.output?.statusCode;
      if (code === DisconnectReason.loggedOut) {
        log.error("Sessão encerrada. Apague auth/ e escaneie de novo.");
        process.exit(1);
      }
      log.info("Reconectando após pareamento (código " + code + ")...");
      connect();
    }
  });
}

connect();
