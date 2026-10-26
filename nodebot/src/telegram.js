import TelegramBot from "node-telegram-bot-api";
import { config } from "./config.js";
import { log } from "./logger.js";
import { processed } from "./store.js";
import { extractText } from "./format.js";

/**
 * Escuta o Telegram e entrega cada novo texto (post de canal ou mensagem)
 * para `onText`. Dedupe persistente evita repasses duplicados ao reiniciar.
 */
export function startTelegram(onText) {
  const bot = new TelegramBot(config.telegramToken, { polling: true });

  async function handle(msg) {
    try {
      const text = extractText(msg);
      if (!text) return;

      const key = `${msg.chat.id}:${msg.message_id}`;
      if (processed.has(key)) return;
      processed.add(key);

      // se a mensagem tem foto (produto), baixa para reenviar como imagem
      let image = null;
      if (Array.isArray(msg.photo) && msg.photo.length) {
        try {
          const fileId = msg.photo[msg.photo.length - 1].file_id; // maior resolução
          const link = await bot.getFileLink(fileId);
          const resp = await fetch(link);
          image = Buffer.from(await resp.arrayBuffer());
        } catch (e) {
          log.warn("não baixei a imagem do Telegram:", e.message);
        }
      }

      await onText(text, image);
    } catch (err) {
      log.error("Falha ao processar update do Telegram:", err.message);
    }
  }

  bot.on("channel_post", handle);
  bot.on("message", handle);
  bot.on("polling_error", (e) => log.warn("polling_error:", e.message));

  log.info("Telegram conectado (polling).");
  return bot;
}
