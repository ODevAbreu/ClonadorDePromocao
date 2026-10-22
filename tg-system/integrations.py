"""Motor de integrações de afiliado (por tarefa).

Reescreve os links de uma mensagem para os seus, com os mecanismos estudados
no app original:

  - amazon       : reescrita pura da URL (coloca sua tag). Sem rede, sem conta.
  - generic      : define parâmetros de afiliado em domínios que você escolhe.
  - shopee       : API oficial (app_id/secret + assinatura SHA256).
  - mercadolivre : API do programa de afiliados (cookie da conta logada + tag).

As integrações de API usam curl_cffi (impersonate=chrome) para passar pelo
anti-bot, igual ao app original. Como curl_cffi é síncrono, rodamos em thread
separada para não travar o loop do worker.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}\"']+")

_RETRY_STATUS = (429, 500, 502, 503, 504)


def _host(url: str) -> str:
    return (urlsplit(url).hostname or "").lower()


def _set_params(url: str, params: dict[str, str], strip: list[str]) -> str:
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query, keep_blank_values=True))
    for key in strip:
        query.pop(key, None)
    query.update(params)
    return urlunsplit(parts._replace(query=urlencode(query)))


def _csv(raw: str) -> list[str]:
    return [x.strip() for x in (raw or "").split(",") if x.strip()]


def _post_with_retry(url: str, data: str, headers: dict) -> "object | None":
    """POST com curl_cffi (impersonate chrome) e retry exponencial. Síncrono."""
    import random

    from curl_cffi import requests as cffi

    session = cffi.Session(impersonate="chrome")
    for attempt in range(1, 6):
        try:
            resp = session.post(url, data=data, headers=headers, timeout=10,
                                 allow_redirects=True)
        except Exception:  # noqa: BLE001 - erro de rede: tenta de novo
            time.sleep(0.5 * attempt)
            continue
        if resp.status_code in (200, 202):
            return resp
        if resp.status_code in _RETRY_STATUS:
            time.sleep(2 ** attempt * 0.5 + random.uniform(0, 0.4))
            continue
        return None
    return None


# ---- integrações ---------------------------------------------------------
class AmazonIntegration:
    type = "amazon"

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.tag = (cfg.get("store_id") or "").strip()

    def matches(self, url: str) -> bool:
        return "amazon." in _host(url)

    async def rewrite(self, url: str) -> str:
        if not self.tag:
            return url
        # mantém /dp/<ASIN> (ou /gp/product/...), troca a tag pela sua
        return _set_params(url, {"tag": self.tag}, strip=["tag"])


class GenericParamIntegration:
    type = "generic"

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.domains = _csv(cfg.get("domains", ""))
        self.strip = _csv(cfg.get("strip", ""))
        self.params: dict[str, str] = {}
        for pair in (cfg.get("params") or "").split(";"):
            if "=" in pair:
                k, v = pair.split("=", 1)
                if k.strip():
                    self.params[k.strip()] = v.strip()

    def matches(self, url: str) -> bool:
        host = _host(url)
        return any(host == d or host.endswith("." + d) for d in self.domains)

    async def rewrite(self, url: str) -> str:
        if not self.params and not self.strip:
            return url
        return _set_params(url, self.params, self.strip)


class ShopeeIntegration:
    """API oficial da Shopee: GraphQL generateShortLink + assinatura SHA256."""

    type = "shopee"
    ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.app_id = (cfg.get("app_id") or "").strip()
        self.secret = (cfg.get("secret") or "").strip()
        self._cache: dict[str, str] = {}

    def matches(self, url: str) -> bool:
        return "shopee." in _host(url)

    def _sync(self, url: str) -> str:
        query = (
            'mutation{generateShortLink(input:{originUrl:"%s",subIds:[]})'
            "{shortLink}}" % url
        )
        body = json.dumps({"query": query}, separators=(",", ":"))
        ts = int(time.time())
        signature = hashlib.sha256(
            f"{self.app_id}{ts}{body}{self.secret}".encode()
        ).hexdigest()
        headers = {
            "Content-Type": "application/json",
            "Authorization": (
                f"SHA256 Credential={self.app_id}, Timestamp={ts}, "
                f"Signature={signature}"
            ),
        }
        resp = _post_with_retry(self.ENDPOINT, body, headers)
        if resp is not None:
            try:
                short = (resp.json().get("data", {})
                         .get("generateShortLink", {}).get("shortLink"))
                if short:
                    return short
            except Exception:  # noqa: BLE001
                pass
        return url

    async def rewrite(self, url: str) -> str:
        if not self.app_id or not self.secret:
            return url
        if url in self._cache:
            return self._cache[url]
        result = await asyncio.to_thread(self._sync, url)
        if result != url:
            self._cache[url] = result
        return result


class MercadoLivreIntegration:
    """API do programa de afiliados do ML: createLink com cookie + tag."""

    type = "mercadolivre"
    ENDPOINT = "https://www.mercadolivre.com.br/affiliate-program/api/v2/affiliates/createLink"

    def __init__(self, name: str, cfg: dict) -> None:
        self.name = name
        self.tag = (cfg.get("tag") or "").strip()
        self.cookie = (cfg.get("cookie") or "").strip()
        self._cache: dict[str, str] = {}

    def matches(self, url: str) -> bool:
        host = _host(url)
        return "mercadolivre." in host or "mercadolibre." in host

    def _sync(self, url: str) -> str:
        headers = {
            "Cookie": self.cookie,
            "accept": "application/json, text/plain, */*",
            "content-type": "application/json",
            "origin": "https://www.mercadolivre.com.br",
            "cache-control": "no-cache",
            "pragma": "no-cache",
            "priority": "u=1, i",
            "referer": url,
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }
        body = json.dumps({"urls": [url], "tag": self.tag})
        resp = _post_with_retry(self.ENDPOINT, body, headers)
        if resp is not None:
            try:
                urls = resp.json().get("urls", [])
                if urls:
                    short = urls[0].get("short_url")
                    if short:
                        return short
            except Exception:  # noqa: BLE001
                pass
        return url

    async def rewrite(self, url: str) -> str:
        if not self.tag or not self.cookie:
            return url
        if url in self._cache:
            return self._cache[url]
        result = await asyncio.to_thread(self._sync, url)
        if result != url:
            self._cache[url] = result
        return result


_REGISTRY = {
    "amazon": AmazonIntegration,
    "generic": GenericParamIntegration,
    "shopee": ShopeeIntegration,
    "mercadolivre": MercadoLivreIntegration,
}


def build_integrations(rows) -> list:
    """Converte linhas Integration (habilitadas) em objetos do motor."""
    out = []
    for row in rows:
        if not row.enabled:
            continue
        cls = _REGISTRY.get(row.type)
        if cls:
            try:
                out.append(cls(row.name, json.loads(row.config or "{}")))
            except json.JSONDecodeError:
                continue
    return out


async def rewrite_links(text: str, integrations: list) -> str:
    """Troca cada URL do texto pelo link de afiliado da 1ª integração que casa."""
    if not text or not integrations:
        return text
    for url in set(URL_RE.findall(text)):
        for integration in integrations:
            if integration.matches(url):
                new = await integration.rewrite(url)
                if new and new != url:
                    text = text.replace(url, new)
                break
    return text
