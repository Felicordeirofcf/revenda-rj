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
