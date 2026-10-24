import { mkdirSync, writeFileSync, readFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { config } from "./config.js";

const file = join(config.dataDir, "status.json");
mkdirSync(config.dataDir, { recursive: true });

let current = { state: "starting", channelJid: config.channelJid, updatedAt: null,
                lastSent: null, lastSentAt: null, sentCount: 0 };
if (existsSync(file)) {
  try {
    current = { ...current, ...JSON.parse(readFileSync(file, "utf8")) };
  } catch {
    /* ignora */
  }
}

/** Atualiza o status compartilhado (lido pelo painel do tg-system). */
export function setStatus(patch) {
  current = { ...current, ...patch, updatedAt: new Date().toISOString() };
  try {
    writeFileSync(file, JSON.stringify(current, null, 2));
  } catch {
    /* disco cheio etc.: não derruba o bot */
  }
}
