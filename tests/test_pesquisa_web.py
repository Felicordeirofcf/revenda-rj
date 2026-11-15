from types import SimpleNamespace

import pytest

from src.ia_base import IAError
from src.pesquisa_web import NOME_TOOL, PesquisadorWeb

from .conftest import ClienteFalso, resposta_tool

OFERTAS = {"encontrou": True, "ofertas": [], "preco_usado_tipico": None, "resumo": "nada"}


def test_continua_apos_pause_turn():
    pausa = SimpleNamespace(stop_reason="pause_turn", content=[SimpleNamespace(type="server_tool_use")],
                            usage=SimpleNamespace(input_tokens=10, output_tokens=5,
                                                  server_tool_use=SimpleNamespace(web_search_requests=3)))
    client = ClienteFalso({NOME_TOOL: [pausa, resposta_tool(NOME_TOOL, OFERTAS, buscas=1)]})
    dados, uso = PesquisadorWeb(client, "claude-sonnet-5-5").preco_novo("PS5", ["ps5"])
    assert dados == OFERTAS and uso.chamadas == 2
    assert uso.custo_usd >= 0.04  # 4 buscas
    segunda = client.chamadas[1]
    assert segunda["messages"][-1]["role"] == "assistant"
    assert segunda["tool_choice"] == {"type": "auto"}
    busca = segunda["tools"][0]
    assert busca["type"] == "web_search_20260209" and busca["user_location"]["country"] == "BR"


def test_recusa_vira_erro():
    recusa = SimpleNamespace(stop_reason="refusal", content=[], usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    client = ClienteFalso({NOME_TOOL: [recusa]})
    with pytest.raises(IAError, match="recusou"):
        PesquisadorWeb(client, "claude-sonnet-5-5").passagem(
            {"destinos": ["REC"], "periodo": "jan", "min_dias": 7}, "2026-11-15")


def test_haiku_usa_busca_basica_e_cai_para_sonnet_se_recusado():
    import anthropic
    import httpx

    chamadas = []

    def create(**params):
        chamadas.append(params)
        if params["model"] == "claude-haiku-5-5":
            req = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
            raise anthropic.BadRequestError("tool not supported", response=httpx.Response(400, request=req), body=None)
        return resposta_tool(NOME_TOOL, OFERTAS)

    client = ClienteFalso({})
    client.messages.create = create
    client.beta.messages.create = create
    pesq = PesquisadorWeb(client, "claude-haiku-5-5", modelo_reserva="claude-sonnet-5-5")
    dados, _ = pesq.preco_novo("PS5", ["ps5"])
    assert dados == OFERTAS
    assert chamadas[0]["tools"][0]["type"] == "web_search_20250305"
    assert chamadas[1]["model"] == "claude-sonnet-5-5" and chamadas[1]["tools"][0]["type"] == "web_search_20260209"
    pesq.preco_novo("PS5", ["ps5"])
    assert chamadas[2]["model"] == "claude-sonnet-5-5"  # não volta a tentar o Haiku
