function stamp() {
  return new Date().toISOString().replace("T", " ").slice(0, 19);
}

function line(level, args) {
  return [`${stamp()} | ${level} |`, ...args];
}

export const log = {
  info: (...a) => console.log(...line("INFO ", a)),
  warn: (...a) => console.warn(...line("WARN ", a)),
  error: (...a) => console.error(...line("ERROR", a)),
};
