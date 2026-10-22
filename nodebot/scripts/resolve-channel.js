/**
 * Descobre o JID do canal (…@newsletter) a partir do link de convite.
 * Uso: npm run resolve-channel https://whatsapp.com/channel/XXXXXXXX
 * Precisa de uma sessão já logada em auth/ (rode `npm start` e escaneie o QR antes).
 */
import {
  makeWASocket,
  useMultiFileAuthState,
  fetchLatestBaileysVersion,
} from "baileys";
import pino from "pino";
import { config } from "../src/config.js";
import { log } from "../src/logger.js";

const link = process.argv[2];
if (!link) {
  console.error("Uso: npm run resolve-channel <link-do-canal>");
  process.exit(1);
}
const code = link.split("/channel/").pop().split(/[/?]/)[0];

const { state, saveCreds } = await useMultiFileAuthState(config.authDir);
const { version } = await fetchLatestBaileysVersion();
const sock = makeWASocket({
  version,
  auth: state,
  logger: pino({ level: "silent" }),
});
sock.ev.on("creds.update", saveCreds);

sock.ev.on("connection.update", async ({ connection }) => {
  if (connection !== "open") return;
  try {
    const meta = await sock.newsletterMetadata("invite", code);
    log.info("Canal encontrado:", meta?.name);
    log.info("Coloque isto no .env  ->  WHATSAPP_CHANNEL_JID=" + meta?.id);
  } catch (e) {
    log.error("Não consegui resolver o canal:", e.message);
  } finally {
    process.exit(0);
  }
});
