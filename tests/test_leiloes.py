from datetime import date, datetime, timezone
from types import SimpleNamespace

from src.leiloes import conta_lote, montar_lotes

CFG = {"comissao_leiloeiro_pct": 5, "custos_fixos_reais": 2500, "margem_min_pct": 15, "lance_max": 50000,
       "desagio_revenda_pct": {"recuperado_financiamento": 12, "sinistro_media_monta": 35, "outro": 20},
       "sites": ["copart.com.br", "sodresantoro.com.br"]}


def lote(**kw):
    base = {"titulo": "Onix 2021", "marca_modelo": "Chevrolet Onix 1.0", "ano": 2021, "km": 50000,
            "tipo": "recuperado_financiamento", "condicao": "liga e anda", "lance_atual": 40000, "valor_fipe": 65000,
            "fipe_fonte": "tabela FIPE", "reparo_estimado": 1500, "data_leilao": "2026-11-20", "local": "Rio de Janeiro/RJ",
            "leiloeiro": "Copart", "url": "https://www.copart.com.br/lot/1", "alertas": []}
    return {**base, **kw}


def test_conta_lote():
    c = conta_lote(lote(), CFG)
    # total = 40000 + 2000 + 2500 + 1500 = 46000; revenda = 65000*0.88 = 57200; lucro 11200
    assert c["total"] == 46000 and c["revenda"] == 57200 and c["lucro"] == 11200
    assert round(c["margem"], 1) == 24.3
    # lance máximo que dá 15%: (57200/1.15 - 2500 - 1500)/1.05 ≈ 43561 -> 43600
    assert c["lance_maximo_lucrativo"] == 43600


def test_montar_lotes_filtra_e_classifica():
    agora = datetime(2026, 11, 15, tzinfo=timezone.utc)
    p = SimpleNamespace(pesquisado_em=agora, dados={"lotes": [
        lote(),
        lote(url="https://golpe-leilao.xyz/lot/2"),                                # site fora da lista
        lote(url="https://www.copart.com.br/lot/3", data_leilao="2026-11-01"),     # já passou
        lote(url="https://www.sodresantoro.com.br/lot/4", tipo="sinistro_grande_monta"),
        lote(url="https://www.copart.com.br/lot/5", valor_fipe=None),
        lote(url="https://www.copart.com.br/lot/6", lance_atual=60000, valor_fipe=90000),
    ]})
    lotes = montar_lotes([p], CFG, date(2026, 11, 15))
    sit = {l["url"].rsplit("/", 1)[1]: l["situacao"] for l in lotes}
    assert sit == {"1": "lucro", "5": "sem_fipe", "6": "acima_orcamento", "4": "pecas"}
    assert lotes[0]["situacao"] == "lucro"
