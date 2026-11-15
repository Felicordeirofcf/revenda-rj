from datetime import datetime, timezone
from types import SimpleNamespace

from src.precos import Referencia
from src.promocoes import dominio_confiavel, montar_achados, precos_de_revenda, tetos_de_compra

LOJAS = ["amazon.com.br", "kabum.com.br", "mercadolivre.com.br"]


def test_dominio_confiavel():
    assert dominio_confiavel("https://www.amazon.com.br/dp/X", LOJAS) == "amazon.com.br"
    assert dominio_confiavel("https://produto.mercadolivre.com.br/MLB-1", LOJAS) == "mercadolivre.com.br"
    assert dominio_confiavel("https://amazon.com.br.golpe.xyz/p", LOJAS) is None
    assert dominio_confiavel("https://fakeamazon.com.br/p", LOJAS) is None
    assert dominio_confiavel("javascript:alert(1)", LOJAS) is None
    assert dominio_confiavel(None, LOJAS) is None


def refs():
    return {"ps5": Referencia(mediana=2800, p25=2650, p75=2950, menor=2300, n=20),
            "iphone-13": Referencia(mediana=2300, p25=2200, p75=2400, menor=2000, n=3)}  # n < mínimo


def test_tetos(catalogo, regras):
    tetos = {t["id"]: t for t in tetos_de_compra(catalogo, precos_de_revenda(catalogo, refs(), {}, regras), regras)}
    assert "iphone-13" not in tetos  # referência fraca e sem pesquisa web
    # venda 2800*0.93=2604; -40 = 2564; /1.2 = 2136.7; 2564-100=2464 -> teto 2137
    assert tetos["ps5"]["teto"] == 2137


def test_montar_achados_filtra_site_e_margem(catalogo, regras):
    agora = datetime.now(timezone.utc)
    pesquisa = SimpleNamespace(pesquisado_em=agora, dados={"achados": [
        {"produto_id": "ps5", "titulo": "PS5 Slim", "loja": "Amazon", "vendido_por": "Amazon", "preco": 2000,
         "cupom": "Pix", "url": "https://www.amazon.com.br/ps5", "publicado": "hoje", "observacao": ""},
        {"produto_id": "ps5", "titulo": "PS5 golpe", "loja": "X", "vendido_por": "", "preco": 900,
         "cupom": "", "url": "https://ofertas-ps5.xyz/p", "publicado": "", "observacao": ""},
        {"produto_id": "ps5", "titulo": "PS5 caro", "loja": "Kabum", "vendido_por": "", "preco": 2500,
         "cupom": "", "url": "https://www.kabum.com.br/ps5", "publicado": "", "observacao": ""},
        {"produto_id": "ps5", "titulo": "PS5 via Pelando", "loja": "Kabum", "vendido_por": "", "preco": 1990,
         "cupom": "", "url": "https://www.pelando.com.br/d/abc", "publicado": "", "observacao": ""},
    ]})
    achados = montar_achados([pesquisa], {}, catalogo, precos_de_revenda(catalogo, refs(), {}, regras), regras, agora)
    urls = [a["url"] for a in achados]
    assert urls == ["https://www.amazon.com.br/ps5", "https://www.pelando.com.br/d/abc"]
    assert achados[0]["margem"] >= 20 and achados[1]["via_comunidade"] is True


def test_revenda_cai_para_pesquisa_web_quando_olx_falta(catalogo, regras):
    web = {"iphone-13": SimpleNamespace(dados={"preco_usado_tipico": 2400}),
           "iphone-12": SimpleNamespace(dados={"preco_usado_tipico": 50})}  # abaixo do mínimo plausível
    revenda = precos_de_revenda(catalogo, refs(), web, regras)
    assert revenda["ps5"].fonte == "olx"
    assert revenda["iphone-13"].fonte == "web" and revenda["iphone-13"].mediana == 2400
    assert "iphone-12" not in revenda
    tetos = {t["id"]: t for t in tetos_de_compra(catalogo, revenda, regras)}
    assert tetos["iphone-13"]["fonte"] == "web" and tetos["iphone-13"]["teto"] > 0
