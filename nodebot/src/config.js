import "dotenv/config";

function required(name) {
  const value = (process.env[name] || "").trim();
  if (!value) {
    throw new Error(
      `Variável de ambiente obrigatória ausente: ${name} (veja .env.example)`
    );
  }
  return value;
}

export const config = {
  // Telegram
  telegramToken: required("TELEGRAM_BOT_TOKEN"),

  // WhatsApp (canal). O JID termina em @newsletter.
  // Se você só tem o link de convite, rode: npm run resolve-channel <link>
  channelJid: (process.env.WHATSAPP_CHANNEL_JID || "").trim(),

  // Texto final. {texto} é substituído pela mensagem do Telegram.
  template: process.env.MESSAGE_TEMPLATE ||
    "📢 Promoção nova\n\n{texto}\n\n#promocao #oferta",

  // Pastas de estado (não versionar)
  authDir: process.env.AUTH_DIR || "./auth",
  dataDir: process.env.DATA_DIR || "./data",
};
