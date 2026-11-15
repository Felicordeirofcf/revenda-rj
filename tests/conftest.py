from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.config import carregar_catalogo, carregar_yaml

ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def regras():
    return carregar_yaml(ROOT / "config" / "regras.yaml")


@pytest.fixture
def catalogo():
    return carregar_catalogo(ROOT / "config" / "catalogo.yaml")


@pytest.fixture
def passagens():
    return carregar_yaml(ROOT / "config" / "passagens.yaml")


def ad_dict(list_id, subject, price, bairro="Tijuca", cidade="Rio de Janeiro", horas=2, prof=False, img=True):
    ts = int((datetime.now(timezone.utc) - timedelta(hours=horas)).timestamp())
    d = {
        "listId": list_id,
        "subject": subject,
        "price": f"R$ {price:,.0f}".replace(",", "."),
        "url": f"https://rj.olx.com.br/rio-de-janeiro-e-regiao/celulares/{list_id}",
        "date": ts,
        "professionalAd": prof,
        "locationDetails": {"municipality": cidade, "neighbourhood": bairro, "uf": "RJ"},
    }
    if img:
        d["thumbnail"] = f"https://img.olx.com.br/thumbs/{list_id}.jpg"
    return d


def pagina_busca(ads) -> str:
    dados = {"props": {"pageProps": {"ads": ads, "totalOfAds": len(ads)}}}
    return f'<html><body><script id="__NEXT_DATA__" type="application/json">{json.dumps(dados)}</script></body></html>'


def pagina_detalhe(body: str, n_imgs: int = 3) -> str:
    dados = {"props": {"pageProps": {"ad": {"listId": 1, "subject": "x", "body": body,
             "images": [{"original": f"https://img.olx.com.br/images/{i}.jpg"} for i in range(n_imgs)]}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(dados)}</script></html>'


def resposta_tool(nome: str, dados: dict, stop="tool_use", buscas=0):
    return SimpleNamespace(
        stop_reason=stop,
        content=[SimpleNamespace(type="text", text="ok"), SimpleNamespace(type="tool_use", name=nome, input=dados)],
        usage=SimpleNamespace(input_tokens=1000, output_tokens=200, cache_creation_input_tokens=0,
                              cache_read_input_tokens=800, server_tool_use=SimpleNamespace(web_search_requests=buscas)),
    )


class ClienteFalso:
    """Imita anthropic.Anthropic: devolve respostas por nome de tool presente na requisição."""

    def __init__(self, respostas: dict[str, list]):
        self.respostas = respostas
        self.chamadas: list[dict] = []
        self.messages = SimpleNamespace(create=self._create)
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self._create))

    def _create(self, **params):
        self.chamadas.append(params)
        nomes = [t.get("name") for t in params["tools"]]
        for nome in nomes:
            if nome in self.respostas and self.respostas[nome]:
                fila = self.respostas[nome]
                return fila.pop(0) if len(fila) > 1 else fila[0]
        raise AssertionError(f"sem resposta falsa para {nomes}")
