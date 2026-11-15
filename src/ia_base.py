"""Utilidades comuns às chamadas do Claude: custo, erros e a chamada com ferramenta de registro."""

from __future__ import annotations

import logging
from typing import Any

import anthropic

from .config import MULT_CACHE_WRITE, PRECOS_MODELOS
from .models import UsoTokens

log = logging.getLogger(__name__)

# Fallback do lado do servidor em caso de recusa (só Sonnet/Opus/Fable; o Haiku 5.5 rejeita).
BETA_FALLBACK = "server-side-fallback-2026-07-01"
PREFIXOS_COM_FALLBACK = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-2")
# Modelos que rejeitam tool_choice forçado ({"type": "tool"}) com HTTP 400.
PREFIXOS_SEM_TOOL_FORCADO = ("claude-sonnet-5-5", "claude-opus-5-5", "claude-fable-5-1", "claude-fable-5-2")
# USD por busca na web (US$ 10 por 1.000 buscas).
CUSTO_BUSCA_WEB = 0.01


class IAError(RuntimeError):
    """Falha numa análise/pesquisa (o item é re-tentado na próxima execução)."""


def calcular_uso(modelo: str, usage: Any) -> UsoTokens:
    p_in, p_out, p_read = PRECOS_MODELOS.get(modelo, (2.0, 10.0, 0.1))
    inp = getattr(usage, "input_tokens", 0) or 0
    out = getattr(usage, "output_tokens", 0) or 0
    cw = getattr(usage, "cache_creation_input_tokens", 0) or 0
    cr = getattr(usage, "cache_read_input_tokens", 0) or 0
    buscas = getattr(getattr(usage, "server_tool_use", None), "web_search_requests", 0) or 0
    custo = (inp * p_in + cw * p_in * MULT_CACHE_WRITE + cr * p_read + out * p_out) / 1_000_000
    custo += buscas * CUSTO_BUSCA_WEB
    return UsoTokens(input_tokens=inp, output_tokens=out, cache_write_tokens=cw,
                     cache_read_tokens=cr, custo_usd=custo, chamadas=1)


def tool_choice_para(modelo: str, nome_tool: str) -> dict[str, Any]:
    if modelo.startswith(PREFIXOS_SEM_TOOL_FORCADO):
        return {"type": "auto"}
    return {"type": "tool", "name": nome_tool}


def criar_mensagem(client: anthropic.Anthropic, **params: Any):
    """messages.create com fallback de recusa quando o modelo suporta."""
    modelo = params["model"]
    try:
        if modelo.startswith(PREFIXOS_COM_FALLBACK):
            return client.beta.messages.create(**params, betas=[BETA_FALLBACK], fallbacks="default")
        return client.messages.create(**params)
    except anthropic.AuthenticationError:
        raise  # fatal: o orquestrador encerra a execução
    except anthropic.BadRequestError as exc:
        raise IAError(f"Requisição inválida (400): {exc}") from exc
    except anthropic.RateLimitError as exc:
        raise IAError(f"Rate limit persistiu após retries: {exc}") from exc
    except anthropic.APIStatusError as exc:
        raise IAError(f"Erro da API ({exc.status_code}): {exc}") from exc
    except anthropic.APIConnectionError as exc:
        raise IAError(f"Falha de conexão com a API: {exc}") from exc


def extrair_tool(resp: Any, nome_tool: str) -> dict[str, Any]:
    if resp.stop_reason == "refusal":
        raise IAError("O modelo recusou a solicitação.")
    bloco = next((b for b in resp.content if b.type == "tool_use" and b.name == nome_tool), None)
    if bloco is None:
        if resp.stop_reason == "max_tokens":
            raise IAError("Resposta cortada por max_tokens.")
        raise IAError(f"O modelo não registrou o resultado (stop_reason={resp.stop_reason}).")
    return bloco.input
