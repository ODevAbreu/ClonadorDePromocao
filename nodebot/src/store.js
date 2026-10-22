import { mkdirSync, readFileSync, writeFileSync, existsSync } from "node:fs";
import { join } from "node:path";
import { config } from "./config.js";

const MAX_KEYS = 5000; // evita o arquivo crescer para sempre
const file = join(config.dataDir, "processed.json");

mkdirSync(config.dataDir, { recursive: true });

let keys = [];
if (existsSync(file)) {
  try {
    keys = JSON.parse(readFileSync(file, "utf8"));
  } catch {
    keys = [];
  }
}
const seen = new Set(keys);

function persist() {
  writeFileSync(file, JSON.stringify([...seen].slice(-MAX_KEYS)));
}

/** Dedupe que sobrevive a reinícios: evita repostar ao reiniciar o bot. */
export const processed = {
  has: (key) => seen.has(key),
  add: (key) => {
    seen.add(key);
    if (seen.size > MAX_KEYS * 1.2) {
      const trimmed = [...seen].slice(-MAX_KEYS);
      seen.clear();
      trimmed.forEach((k) => seen.add(k));
    }
    persist();
  },
};
