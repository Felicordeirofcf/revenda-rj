"""Promoções em lojas confiáveis: teto de compra por produto e filtragem/margem das ofertas achadas."""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Any, Iterable
from urllib.parse import urlparse

from .config import Catalogo
from .precos import Referencia, conta_margem, escolher_referencia


def dominio_confiavel(url: str | None, dominios: Iterable[str]) -> str | None:
    """Devolve o domínio da lista que casa com a URL (subdomínios incluídos) ou None."""
    if not url:
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    if p.scheme not in ("http", "https") or not p.hostname:
        return None
    host = p.hostname.lower()
    for d in dominios:
        d = d.lower().strip()
        if host == d or host.endswith("." + d):
            return d
    return None


def tetos_de_compra(catalogo: Catalogo, refs: dict[str, Referencia], regras: dict) -> list[dict[str, Any]]:
    """Maior preço de compra que ainda dá a margem e o lucro mínimos, por produto com referência."""
    minimo = regras.get("referencia_min_amostras", 5)
    margem = regras.get("margem_min_pct", 20) / 100
    lucro_min = regras.get("lucro_min_reais", 0)
    orcamento = regras.get("orcamento_max", float("inf"))
    tetos = []
    for item in catalogo.itens:
        ref, _ = escolher_referencia(item.id, None, refs, minimo)
        if not ref or ref.n < minimo:
            continue
        lucro_zero, _ = conta_margem(0, ref.mediana, regras)  # = venda estimada - custos
        teto = min(lucro_zero / (1 + margem), lucro_zero - lucro_min, orcamento)
        if teto > 0:
            tetos.append({"id": item.id, "nome": item.nome, "teto": round(teto), "mediana": ref.mediana, "n": ref.n})
    return tetos


def montar_achados(pesquisas: list[Any], produtos_web: dict[str, Any], catalogo: Catalogo,
                   refs: dict[str, Referencia], regras: dict, agora_: datetime) -> list[dict[str, Any]]:
    """Junta as ofertas do caçador de promoções e das pesquisas de preço novo, só de sites confiáveis,
    calcula a margem contra a mediana dos usados e devolve as que dão lucro (mais recentes primeiro)."""
    cfg = regras.get("promocoes") or {}
    lojas = cfg.get("lojas_confiaveis") or []
    comunidades = cfg.get("sites_de_promocao") or []
    minimo = regras.get("referencia_min_amostras", 5)
    margem_min = regras.get("margem_min_pct", 20)
    lucro_min = regras.get("lucro_min_reais", 0)

    candidatos: list[tuple[dict[str, Any], datetime, str]] = []
    for p in pesquisas:
        for a in (p.dados.get("achados") or []):
            candidatos.append((a, p.pesquisado_em, "caçador de promoções"))
    for item_id, web in produtos_web.items():
        for o in (web.dados.get("ofertas") or []):
            candidatos.append(({**o, "produto_id": item_id, "vendido_por": "", "cupom": o.get("observacao", ""),
                                "publicado": ""}, web.pesquisado_em, "pesquisa de preço novo"))

    vistos: set[str] = set()
    achados = []
    for a, quando, origem in sorted(candidatos, key=lambda c: c[1], reverse=True):
        url = a.get("url")
        loja_ok = dominio_confiavel(url, lojas)
        comunidade = None if loja_ok else dominio_confiavel(url, comunidades)
        if not (loja_ok or comunidade) or url in vistos:
            continue
        item = catalogo.por_id(a.get("produto_id", ""))
        ref, _ = escolher_referencia(item.id, None, refs, minimo) if item else (None, None)
        if not item or not ref or ref.n < minimo or not a.get("preco"):
            continue
        lucro, margem = conta_margem(float(a["preco"]), ref.mediana, regras)
        if margem < margem_min or lucro < lucro_min:
            continue
        vistos.add(url)
        achados.append({
            "id": "promo-" + hashlib.sha1(url.encode()).hexdigest()[:12],
            "produto_id": item.id, "produto": item.nome, "categoria": item.categoria,
            "titulo": a.get("titulo") or item.nome, "loja": a.get("loja") or (loja_ok or comunidade),
            "vendido_por": a.get("vendido_por") or "", "preco": float(a["preco"]), "cupom": a.get("cupom") or "",
            "url": url, "dominio": loja_ok or comunidade, "via_comunidade": bool(comunidade),
            "publicado": a.get("publicado") or "", "observacao": a.get("observacao") or "",
            "revenda": round(ref.mediana, 2), "n_ref": ref.n, "lucro": round(lucro, 2), "margem": round(margem, 1),
            "achado_em": quando.isoformat() if hasattr(quando, "isoformat") else str(quando), "origem": origem,
        })
    return achados
