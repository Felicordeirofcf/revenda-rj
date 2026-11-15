"""Identifica qual produto do catálogo é o anúncio e aplica as exclusões por título."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .config import Catalogo, ItemCatalogo
from .texto import detectar_armazenamento, normalizar


@dataclass
class Classificacao:
    item: ItemCatalogo | None
    variante: str | None
    motivo_exclusao: str | None  # None = anúncio válido

    @property
    def chave_item(self) -> str | None:
        return self.item.id if self.item else None

    @property
    def chave_variante(self) -> str | None:
        if not self.item:
            return None
        return f"{self.item.id}|{self.variante}" if self.variante else None


class Classificador:
    def __init__(self, catalogo: Catalogo, regras: dict):
        self.catalogo = catalogo
        exc = regras.get("excluir_sempre") or {}
        self.re_acessorios = [re.compile(p) for p in exc.get("acessorios") or []]
        self.re_negocio = [re.compile(p) for p in exc.get("negocio") or []]
        negacoes = exc.get("negacoes") or []
        alternativas = "|".join(re.escape(n) for n in sorted(negacoes, key=len, reverse=True))
        # negação + até 2 palavras antes do termo: "sem defeito", "nunca foi bloqueado", "sem nenhum defeito"
        self.re_negacao = re.compile(rf"\b({alternativas})\s+(\w+\s+){{0,2}}$") if alternativas else None

    def _negado(self, texto: str, inicio: int) -> bool:
        if not self.re_negacao:
            return False
        return bool(self.re_negacao.search(texto[max(0, inicio - 30):inicio]))

    def motivo_negocio(self, texto_norm: str) -> str | None:
        for regex in self.re_negocio:
            for m in regex.finditer(texto_norm):
                if not self._negado(texto_norm, m.start()):
                    return f"termo excluído: '{m.group(0)}'"
        return None

    def identificar(self, titulo_norm: str) -> tuple[ItemCatalogo | None, re.Match | None]:
        for item in self.catalogo.itens:
            m = item.padrao.search(titulo_norm)
            if m and not (item.excluir and item.excluir.search(titulo_norm)):
                return item, m
        return None, None

    def classificar(self, titulo: str, preco: float | None) -> Classificacao:
        t = normalizar(titulo)
        item, match = self.identificar(t)
        if item is None:
            return Classificacao(None, None, "não corresponde a nenhum produto do catálogo")
        variante = detectar_armazenamento(t) if item.variante == "armazenamento" else None

        motivo = self.motivo_negocio(t)
        if motivo:
            return Classificacao(item, variante, motivo)
        for regex in self.re_acessorios:
            m = regex.search(t)
            if m and m.start() < match.start():
                return Classificacao(item, variante, f"parece acessório/peça: '{m.group(0)}'")
        if preco is None:
            return Classificacao(item, variante, "sem preço")
        if preco < item.preco_min:
            return Classificacao(item, variante, f"preço abaixo do mínimo plausível (R$ {item.preco_min:.0f})")
        return Classificacao(item, variante, None)
