FROM node:22-slim

WORKDIR /app

# instala só as dependências primeiro (cache de camada)
COPY package.json package-lock.json* ./
RUN npm install --omit=dev

COPY . .

# auth/ (sessão do WhatsApp) e data/ (dedupe) vêm de volumes — ver docker-compose
CMD ["node", "src/index.js"]
