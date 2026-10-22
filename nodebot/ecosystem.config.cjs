// PM2: mantém o bot rodando 24/7 na VPS e reinicia se cair.
// Uso: pm2 start ecosystem.config.cjs  |  pm2 logs  |  pm2 save && pm2 startup
module.exports = {
  apps: [
    {
      name: "tg-whatsapp-bridge",
      script: "src/index.js",
      interpreter: "node",
      autorestart: true,
      max_restarts: 50,
      restart_delay: 3000,
      env: { NODE_ENV: "production" },
    },
  ],
};
