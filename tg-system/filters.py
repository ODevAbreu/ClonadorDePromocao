"""Motor de decisão e transformação (deny/allow + substituição).

Mesmas ideias que mapeamos por engenharia reversa, reescritas: detecção
separada da política, com a melhoria do casamento por palavra inteira.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


def split_items(raw: str) -> list[str]:
    return [item.strip() for item in (raw or "").split(",") if item.strip()]


def parse_replacements(raw: str) -> list[tuple[str, str]]:
    pairs: list[tuple[str, str]] = []
    for chunk in (raw or "").split(";"):
        if "=>" in chunk:
            old, new = chunk.split("=>", 1)
            if old.strip():
                pairs.append((old.strip(), new.strip()))
    return pairs


def _matched(text: str, items: list[str], whole_word: bool) -> list[str]:
    if not text or not items:
        return []
    low = text.lower()
    found: list[str] = []
    for item in items:
        term = item.lower()
        hit = (
            re.search(rf"\b{re.escape(term)}\b", low) is not None
            if whole_word
            else term in low
        )
        if hit and item not in found:
            found.append(item)
    return found


@dataclass
class ForwardPolicy:
    deny_items: list[str]
    allow_items: list[str]
    whole_word: bool = True

    def decide(self, text: str) -> tuple[bool, str]:
        if self.deny_items:
            hit = _matched(text, self.deny_items, self.whole_word)
            if hit:
                return False, f"bloqueado pelos termos: {', '.join(hit)}"
        if self.allow_items:
            if not _matched(text, self.allow_items, self.whole_word):
                return False, "nenhum termo permitido encontrado"
        return True, "ok"


def apply_replacements(text: str, replacements: list[tuple[str, str]]) -> str:
    if not text:
        return text
    for old, new in replacements:
        if old.startswith("re:"):
            text = re.sub(old[3:], new, text, flags=re.IGNORECASE)
        else:
            text = re.sub(re.escape(old), new, text, flags=re.IGNORECASE)
    return text
