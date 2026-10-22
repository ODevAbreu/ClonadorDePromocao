import { log } from "./logger.js";
import { startWhatsApp } from "./whatsapp.js";
import { sendToChannel } from "./whatsapp.js";
import { startTelegram } from "./telegram.js";
import { format } from "./format.js";

async function main() {
  log.info("Iniciando ponte Telegram → WhatsApp...");

  // WhatsApp conecta em segundo plano; mensagens que chegarem antes ficam na fila.
  startWhatsApp().catch((e) => log.error("WhatsApp:", e.message));

  startTelegram(async (text) => {
    await sendToChannel(format(text));
  });

  const shutdown = (sig) => {
    log.info(`Recebido ${sig}, encerrando.`);
    process.exit(0);
  };
  process.on("SIGINT", () => shutdown("SIGINT"));
  process.on("SIGTERM", () => shutdown("SIGTERM"));
}

main().catch((e) => {
  log.error("Falha fatal:", e.message);
  process.exit(1);
});
