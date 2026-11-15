import httpx
import pytest

from src.fontes.olx import OlxFonte, anuncio_de_dict, detalhe_de_html, encontrar_anuncios, extrair_next_data
from src.http import FonteError, HttpClient
from src.models import Anuncio

from .conftest import ad_dict, pagina_busca, pagina_detalhe


def fonte_com(handler, paginas=1):
    http = HttpClient(intervalo_minimo=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    return OlxFonte({"url_busca": "https://www.olx.com.br/estado-rj?q={q}&sf=1", "paginas": paginas}, http)


def test_busca_extrai_anuncios():
    ads = [ad_dict(1, "iPhone 13 128GB", 2500), ad_dict(2, "PS5", 2800, bairro="Centro")]
    # Lista pequena de "relacionados" não deve ser escolhida no lugar da principal.
    html = pagina_busca(ads).replace('"totalOfAds"', '"rel": [' + __import__("json").dumps(ad_dict(9, "x", 1)) + '], "totalOfAds"')
    fonte = fonte_com(lambda req: httpx.Response(200, text=html))
    res = list(fonte.buscar("iphone 13"))
    assert [a.id_externo for a in res] == ["1", "2"]
    a = res[0]
    assert a.preco == 2500 and a.bairro == "Tijuca" and a.cidade == "Rio de Janeiro" and a.uf == "RJ"
    assert a.imagem.endswith("1.jpg") and a.publicado_em is not None and a.termo_busca == "iphone 13"


def test_paginacao_para_quando_vazia():
    urls = []
    def handler(req):
        urls.append(str(req.url))
        return httpx.Response(200, text=pagina_busca([ad_dict(1, "a", 1)] if "o=2" not in str(req.url) else []))
    list(fonte_com(handler, paginas=3).buscar("x"))
    assert len(urls) == 2 and "o=2" in urls[1]


def test_bloqueio_cloudflare():
    fonte = fonte_com(lambda req: httpx.Response(200, text="<html>Just a moment... cf-chl</html>"))
    with pytest.raises(FonteError, match="anti-robô"):
        list(fonte.buscar("x"))


def test_403():
    fonte = fonte_com(lambda req: httpx.Response(403, text="no"))
    with pytest.raises(FonteError, match="403"):
        list(fonte.buscar("x"))


def test_formato_antigo_de_local():
    a = anuncio_de_dict({"listId": 5, "subject": "x", "price": "R$ 1.000", "url": "https://u",
                         "location": "Rio de Janeiro, Méier - DDD 21"})
    assert a.cidade == "Rio de Janeiro" and a.bairro == "Méier" and a.preco == 1000


def test_detalhe():
    det = detalhe_de_html(pagina_detalhe("Aparelho com nota fiscal", 4))
    assert det["descricao"] == "Aparelho com nota fiscal" and len(det["imagens"]) == 4


def test_detalhe_404():
    fonte = fonte_com(lambda req: httpx.Response(404))
    a = Anuncio(fonte="olx", id_externo="1", url="https://x", titulo="t", preco=1)
    assert fonte.detalhar(a) == {"indisponivel": True}


def test_sem_next_data():
    with pytest.raises(FonteError, match="layout"):
        extrair_next_data("<html></html>")
    assert encontrar_anuncios({"a": [1, 2]}) == []
