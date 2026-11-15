import json
from datetime import timedelta

import httpx

from src.config import Settings
from src.database import AnuncioDB, Database, PesquisaDB
from src.dashboard import gerar_dashboard
from src.fontes.olx import OlxFonte
from src.http import HttpClient
from src.main import Robo
from src.pesquisa_web import NOME_TOOL as TOOL_WEB
from src.triagem import NOME_TOOL as TOOL_TRIAGEM

from .conftest import ClienteFalso, ad_dict, pagina_busca, pagina_detalhe, resposta_tool

MERCADO_IPHONE13 = [2300, 2350, 2400, 2250, 2450, 2380, 2320]


def anuncios_mock():
    ads = [ad_dict(100 + i, f"iPhone 13 128GB azul {i}", p, bairro="Tijuca") for i, p in enumerate(MERCADO_IPHONE13)]
    ads += [
        ad_dict(1, "iPhone 13 128GB com nota fiscal", 1600, bairro="Méier"),             # oportunidade
        ad_dict(2, "iPhone 13 128gb", 1850, bairro="Centro"),                           # observação (~14%)
        ad_dict(3, "iPhone 13 128gb barato", 1500, cidade="Duque de Caxias", bairro="Centro"),  # fora da região
        ad_dict(4, "Capa iPhone 13", 1500),                                              # acessório
        ad_dict(5, "iPhone 13 128gb loja garantia", 1500, prof=True),                    # lojista
        ad_dict(6, "iPhone 13 128gb golpe", 1150, bairro="Copacabana"),                  # IA manda evitar
    ]
    return ads


def handler(req: httpx.Request) -> httpx.Response:
    url = str(req.url)
    if "q=iphone+13" in url and "pro" not in url:
        return httpx.Response(200, text=pagina_busca(anuncios_mock()))
    if "/celulares/" in url:
        return httpx.Response(200, text=pagina_detalhe("iPhone 13 128GB, bateria 88%, com nota fiscal e caixa."))
    return httpx.Response(200, text=pagina_busca([]))


def triagem(recomendacao="ir_ver", confere=True):
    return {"produto_confere": confere, "armazenamento": "128GB", "estado": "seminovo_otimo",
            "acompanha": ["caixa", "nota fiscal"], "sinais_risco": [], "nivel_risco": "baixo",
            "recomendacao": recomendacao, "resumo": "Anúncio coerente.", "perguntas_vendedor": ["Saúde da bateria?"],
            "oferta_sugerida": 1500}


def montar(tmp_path, regras, catalogo, passagens, client):
    db = Database(tmp_path / "t.db")
    http = HttpClient(intervalo_minimo=0, transport=httpx.MockTransport(handler), sleep=lambda s: None)
    fonte = OlxFonte(regras["fontes"]["olx"] | {"paginas": 1}, http)
    settings = Settings(anthropic_api_key="x")
    return db, Robo(settings, db, regras, catalogo, passagens, client, fontes={"olx": fonte})


def test_pipeline_completo(tmp_path, regras, catalogo, passagens):
    respostas_triagem = [resposta_tool(TOOL_TRIAGEM, triagem())]
    client = ClienteFalso({
        TOOL_TRIAGEM: respostas_triagem,
        TOOL_WEB: [resposta_tool(TOOL_WEB, {"encontrou": True, "ofertas": [
            {"loja": "Loja X", "titulo": "iPhone 13", "preco": 3999, "url": "https://loja.x/p", "observacao": "no Pix"}],
            "preco_usado_tipico": 2300, "resumo": "Estável."}, buscas=2)],
    })
    # O golpe de R$ 900 recebe "evitar" da IA.
    original = client._create
    todas = []
    def create(**params):
        todas.append(params)
        conteudo = params["messages"][0]["content"]
        if isinstance(conteudo, str) and "golpe" in conteudo:
            return resposta_tool(TOOL_TRIAGEM, triagem("evitar") | {"nivel_risco": "alto", "resumo": "Preço de golpe."})
        if params["tools"][-1]["name"] == TOOL_WEB and "voos" in json.dumps(params["tools"][-1]["input_schema"]):
            return resposta_tool(TOOL_WEB, {"encontrou": True, "voos": [
                {"destino": "MCZ", "ida": "2027-01-10", "volta": "2027-01-18", "preco": 850, "companhia": "LATAM",
                 "escalas": "direto", "fonte": "Google Flights", "url": "https://g.co/f"}], "resumo": "Bom preço."})
        return original(**params)
    client.messages.create = create
    client.beta.messages.create = create

    db, robo = montar(tmp_path, regras, catalogo, passagens, client)
    ex = robo.executar()
    assert ex.erros == [], ex.erros

    with db.sessao() as s:
        def por_id(i):
            return s.query(AnuncioDB).filter_by(id_externo=str(i)).one()
        op = por_id(1)
        assert op.situacao == "oportunidade", (op.situacao, op.motivo_situacao, op.margem_pct)
        assert op.ref_tipo == "variante" and op.n_ref >= 7 and op.margem_pct > 20
        assert op.analise["recomendacao"] == "ir_ver" and op.descricao.startswith("iPhone 13")
        assert len(op.imagens) == 3
        assert por_id(2).situacao == "observacao"
        assert por_id(3).situacao == "descartado" and "fora das regiões" in por_id(3).motivo_situacao
        assert por_id(4).situacao == "descartado" and "acessório" in por_id(4).motivo_exclusao
        assert por_id(5).situacao == "normal" and por_id(5).motivo_situacao == "anúncio de loja"
        golpe = por_id(6)
        assert golpe.situacao == "descartado" and golpe.motivo_situacao.startswith("IA:")
        assert s.query(PesquisaDB).filter_by(tipo="produto").count() == 2      # max_por_execucao
        assert s.query(PesquisaDB).filter_by(tipo="passagem").count() == 2
        assert s.query(PesquisaDB).filter_by(tipo="promocoes").count() == 1  # caçador de promoções
    assert ex.oportunidades == 1 and ex.novas_oportunidades == 1 and ex.custo_usd > 0

    # Prompt caching: o bloco de checklists é marcado como cacheável.
    tri = next(c for c in client.chamadas if c["tools"][0]["name"] == TOOL_TRIAGEM)
    assert tri["system"][-1]["cache_control"] == {"type": "ephemeral"}
    assert tri["tool_choice"] == {"type": "tool", "name": TOOL_TRIAGEM}

    # 2ª execução: nada novo para a IA (mesmo preço), pesquisas web ainda não venceram.
    n = len(todas)
    ex2 = robo.executar()
    assert ex2.analises_ia == 0 and ex2.novas_oportunidades == 0
    novas = todas[n:]
    # Só as próximas 2 pesquisas de produto (as passagens ainda não venceram; triagem não repete).
    assert len(novas) == 2 and all(c["model"] == "claude-haiku-5-5" for c in novas)
    assert all("ofertas" in c["tools"][-1]["input_schema"]["properties"] for c in novas)
    gerar = gerar_dashboard(db, regras, catalogo, passagens, tmp_path / "index.html")
    html = gerar.read_text()
    assert "const DADOS = {" in html and "iPhone 13 128GB com nota fiscal" in html and "Loja X" in html


def test_sem_ia_nao_relê_detalhe_toda_vez(tmp_path, regras, catalogo, passagens):
    db, robo = montar(tmp_path, regras, catalogo, passagens, None)
    robo.executar(usar_ia=False, usar_web=False)
    with db.sessao() as s:
        assert s.query(AnuncioDB).filter(AnuncioDB.descricao.is_not(None)).count() == 3
    contagem = {"n": 0}
    orig = robo.fontes["olx"].detalhar
    def contar(a):
        contagem["n"] += 1
        return orig(a)
    robo.fontes["olx"].detalhar = contar
    robo.executar(usar_ia=False, usar_web=False)
    assert contagem["n"] <= 1  # só a checagem de disponibilidade (passou < 6h -> 0)


def test_anuncio_vendido(tmp_path, regras, catalogo, passagens):
    db, robo = montar(tmp_path, regras, catalogo, passagens, None)
    robo.executar(usar_ia=False, usar_web=False)
    with db.sessao() as s:
        op = s.query(AnuncioDB).filter_by(id_externo="1").one()
        op.checado_em = op.checado_em - timedelta(hours=7)
        s.commit()
    robo.fontes["olx"].detalhar = lambda a: {"indisponivel": True}
    robo.executar(usar_ia=False, usar_web=False)
    with db.sessao() as s:
        op = s.query(AnuncioDB).filter_by(id_externo="1").one()
        # Reaparece na busca -> volta a ser avaliado normalmente
        assert op.situacao in {"oportunidade", "vendido"}
