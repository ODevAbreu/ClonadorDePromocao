import { config } from "./config.js";

/** Extrai o texto do update do Telegram (post, mensagem, ou legenda de mídia). */
export function extractText(msg) {
  const text = (msg.text || msg.caption || "").trim();
  return text || null;
}

/** Aplica o template configurado ({texto} vira a mensagem original). */
export function format(text) {
  return config.template.replaceAll("{texto}", text);
}
