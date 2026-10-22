"""Testes do motor de integrações.

Amazon e genérica: testados de ponta a ponta (sem rede).
Shopee e Mercado Livre: testamos matching, config e o 'curto-circuito' quando
faltam credenciais (a parte de rede você valida com suas credenciais reais).
"""
import asyncio

from integrations import (
    AmazonIntegration,
    GenericParamIntegration,
    MercadoLivreIntegration,
    ShopeeIntegration,
    build_integrations,
    rewrite_links,
)


def check(desc, got, expected):
    ok = got == expected
    print(f"[{'PASS' if ok else 'FALHA'}] {desc}: {got!r}")
    assert ok, f"esperava {expected!r}"


class FakeRow:
    def __init__(self, name, type, config, enabled=True):
        self.name, self.type, self.config, self.enabled = name, type, config, enabled


async def main():
    # ---- Amazon ----
    amz = AmazonIntegration("amz", {"store_id": "leogardias02-20"})
    check("amazon /dp sem tag",
          await amz.rewrite("https://www.amazon.com.br/dp/B0ABC"),
          "https://www.amazon.com.br/dp/B0ABC?tag=leogardias02-20")
    check("amazon troca tag alheia",
          await amz.rewrite("https://www.amazon.com.br/dp/B0ABC?tag=outro-21"),
          "https://www.amazon.com.br/dp/B0ABC?tag=leogardias02-20")
    check("amazon /gp/product preserva path",
          await amz.rewrite("https://www.amazon.com.br/gp/product/B0XYZ?th=1"),
          "https://www.amazon.com.br/gp/product/B0XYZ?th=1&tag=leogardias02-20")
    check("amazon .com tambem casa", amz.matches("https://www.amazon.com/dp/X"), True)
    check("amazon nao casa outro site", amz.matches("https://loja.com/x"), False)

    # ---- genérica ----
    gen = GenericParamIntegration("g", {"domains": "loja.com",
                                        "params": "aff=meucodigo", "strip": "gclid"})
    check("generic add param + remove gclid",
          await gen.rewrite("https://loja.com/p?gclid=123"),
          "https://loja.com/p?aff=meucodigo")
    check("generic casa subdominio", gen.matches("https://www.loja.com/x"), True)

    # ---- Shopee: matching e curto-circuito sem credencial ----
    shp = ShopeeIntegration("s", {})  # sem app_id/secret
    check("shopee casa dominio", shp.matches("https://shopee.com.br/item"), True)
    check("shopee sem credencial mantem url",
          await shp.rewrite("https://shopee.com.br/x"), "https://shopee.com.br/x")

    # ---- Mercado Livre: matching e curto-circuito sem credencial ----
    ml = MercadoLivreIntegration("ml", {"tag": "t"})  # sem cookie
    check("ml casa dominio", ml.matches("https://www.mercadolivre.com.br/p/X"), True)
    check("ml sem cookie mantem url",
          await ml.rewrite("https://www.mercadolivre.com.br/p/X"),
          "https://www.mercadolivre.com.br/p/X")

    # ---- build_integrations a partir de "linhas" do banco ----
    rows = [
        FakeRow("amz", "amazon", '{"store_id": "leogardias02-20"}'),
        FakeRow("pausada", "amazon", '{"store_id": "x"}', enabled=False),
        FakeRow("ml", "mercadolivre", '{"tag": "t", "cookie": ""}'),
    ]
    built = build_integrations(rows)
    check("build ignora pausada (2 ativas)", len(built), 2)

    # ---- pipeline num texto com vários links ----
    text = ("ofertas: https://www.amazon.com.br/dp/B0ZZ e https://loja.com/p "
            "e https://shopee.com.br/x (shopee sem cred fica igual)")
    out = await rewrite_links(text, [amz, gen, shp])
    check("pipeline troca amazon+loja, mantem shopee",
          out,
          "ofertas: https://www.amazon.com.br/dp/B0ZZ?tag=leogardias02-20 e "
          "https://loja.com/p?aff=meucodigo e "
          "https://shopee.com.br/x (shopee sem cred fica igual)")

    print("\nTodos os testes de integração passaram.")


asyncio.run(main())
