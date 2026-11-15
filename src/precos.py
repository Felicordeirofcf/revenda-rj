"""Preço de referência (mediana do mercado) e conta de margem de cada anúncio."""

from __future__ import annotations

import statistics
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable

from .database import AnuncioDB, agora


@dataclass
class Referencia:
    mediana: float
    p25: float
    p75: float
    menor: float
    n: int
    fonte: str = "olx"  # "olx" (anúncios coletados) ou "web" (preço típico de usado achado pelo Claude)


def _quantil(valores: list[float], q: float) -> float:
    if len(valores) == 1:
        return valores[0]
    pos = (len(valores) - 1) * q
    i = int(pos)
    frac = pos - i
    return valores[i] + (valores[min(i + 1, len(valores) - 1)] - valores[i]) * frac


def referencia_de(precos: list[float]) -> Referencia | None:
    if not precos:
        return None
    med = statistics.median(precos)
    # Remove extremos (acessório que escapou, golpe, lacrado com nota) e recalcula.
    filtrados = sorted(p for p in precos if 0.5 * med <= p <= 1.8 * med) or sorted(precos)
    return Referencia(
        mediana=statistics.median(filtrados),
        p25=_quantil(filtrados, 0.25),
        p75=_quantil(filtrados, 0.75),
        menor=filtrados[0],
        n=len(filtrados),
    )


def calcular_referencias(linhas: Iterable[AnuncioDB]) -> dict[str, Referencia]:
    """Chaves: 'item_id' (modelo, todas as variantes) e 'item_id|variante'."""
    grupos: dict[str, list[float]] = defaultdict(list)
    for r in linhas:
        grupos[r.item_id].append(r.preco)
        if r.variante:
            grupos[f"{r.item_id}|{r.variante}"].append(r.preco)
    return {k: ref for k, v in grupos.items() if (ref := referencia_de(v))}


def escolher_referencia(item_id: str, variante: str | None, refs: dict[str, Referencia],
                        minimo: int) -> tuple[Referencia | None, str | None]:
    if variante:
        ref = refs.get(f"{item_id}|{variante}")
        if ref and ref.n >= minimo:
            return ref, "variante"
    ref = refs.get(item_id)
    if ref is None:
        return None, None
    return ref, "modelo"


def conta_margem(preco: float, mediana: float, regras: dict) -> tuple[float, float]:
    venda = mediana * (1 - regras.get("desconto_negociacao_pct", 0) / 100)
    custos = regras.get("custo_fixo_reais", 0) + venda * regras.get("taxa_venda_pct", 0) / 100
    lucro = venda - preco - custos
    return lucro, (lucro / preco * 100 if preco else 0.0)


def avaliar(r: AnuncioDB, refs: dict[str, Referencia], regras: dict, quando: datetime | None = None) -> None:
    """Preenche preco_ref, lucro, margem e situacao. Não mexe em 'vendido'."""
    quando = quando or agora()
    if r.situacao == "vendido":
        return
    r.preco_ref = r.n_ref = r.ref_tipo = r.lucro_est = r.margem_pct = None
    r.suspeito = False

    def situacao(s: str, motivo: str | None) -> None:
        r.situacao, r.motivo_situacao = s, motivo

    if r.item_id is None or r.motivo_exclusao:
        return situacao("descartado", r.motivo_exclusao)
    if not r.regiao_ok:
        return situacao("descartado", f"fora das regiões aceitas ({r.cidade or '?'} / {r.bairro or '?'})")

    ref, tipo = escolher_referencia(r.item_id, r.variante, refs, regras.get("referencia_min_amostras", 5))
    if ref:
        r.preco_ref, r.n_ref, r.ref_tipo = round(ref.mediana, 2), ref.n, tipo
        lucro, margem = conta_margem(r.preco, ref.mediana, regras)
        r.lucro_est, r.margem_pct = round(lucro, 2), round(margem, 1)
        r.suspeito = r.preco < ref.mediana * regras.get("preco_suspeito_pct", 45) / 100

    if r.profissional and not regras.get("alertar_lojistas", False):
        return situacao("normal", "anúncio de loja")
    idade_max = timedelta(days=regras.get("idade_max_dias", 7))
    if quando - r.data_referencia > idade_max:
        return situacao("normal", "anúncio antigo")
    if r.preco > regras.get("orcamento_max", float("inf")):
        return situacao("normal", "acima do orçamento")
    if ref is None:
        return situacao("observacao", "ainda sem preço de referência para este produto")

    margem_min = regras.get("margem_min_pct", 20)
    lucro_min = regras.get("lucro_min_reais", 0)
    ia = r.analise or {}
    if ia and (not ia.get("produto_confere", True) or ia.get("recomendacao") == "evitar"):
        return situacao("descartado", f"IA: {ia.get('resumo', 'recomendou evitar')}")

    fraca = ref.n < regras.get("referencia_min_amostras", 5)
    if r.margem_pct >= margem_min and r.lucro_est >= lucro_min:
        if fraca:
            return situacao("observacao", f"margem boa, mas referência fraca ({ref.n} anúncios)")
        if r.virou_oportunidade_em is None:
            r.virou_oportunidade_em = quando
        return situacao("oportunidade", None)
    if r.margem_pct >= margem_min / 2 and r.lucro_est > 0:
        return situacao("observacao", f"margem de {r.margem_pct:.0f}%: perto do alvo, vale negociar")
    return situacao("normal", None)
