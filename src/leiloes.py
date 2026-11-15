"""Leilões de carros: conta de lucro de cada lote encontrado pela pesquisa web."""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime
from typing import Any

from .promocoes import dominio_confiavel

SO_PECAS = {"sinistro_grande_monta", "sucata"}


def conta_lote(lote: dict[str, Any], cfg: dict[str, Any]) -> dict[str, Any]:
    """Compra total = lance + comissão + custos fixos + reparo. Revenda = FIPE − deságio do tipo de lote."""
    lance = float(lote.get("lance_atual") or 0)
    comissao = lance * float(cfg.get("comissao_leiloeiro_pct", 5)) / 100
    custos = float(cfg.get("custos_fixos_reais", 2500))
    reparo = float(lote.get("reparo_estimado") or 0)
    total = lance + comissao + custos + reparo
    fipe = lote.get("valor_fipe")
    tipo = lote.get("tipo") or "outro"
    desagios = cfg.get("desagio_revenda_pct") or {}
    desagio = float(desagios.get(tipo, desagios.get("outro", 20)))
    revenda = float(fipe) * (1 - desagio / 100) if fipe and tipo not in SO_PECAS else None
    lucro = revenda - total if revenda is not None else None
    margem = lucro / total * 100 if lucro is not None and total else None
    return {"lance": lance, "comissao": round(comissao, 2), "custos": custos, "reparo": reparo,
            "total": round(total, 2), "fipe": fipe, "desagio_pct": desagio,
            "revenda": round(revenda, 2) if revenda is not None else None,
            "lucro": round(lucro, 2) if lucro is not None else None,
            "margem": round(margem, 1) if margem is not None else None,
            "lance_maximo_lucrativo": _lance_maximo(revenda, cfg, reparo)}


def _lance_maximo(revenda: float | None, cfg: dict[str, Any], reparo: float) -> float | None:
    """Maior lance que ainda dá a margem mínima (para você não se empolgar no pregão)."""
    if revenda is None:
        return None
    m = float(cfg.get("margem_min_pct", 15)) / 100
    c = float(cfg.get("comissao_leiloeiro_pct", 5)) / 100
    custos = float(cfg.get("custos_fixos_reais", 2500))
    lance = (revenda / (1 + m) - custos - reparo) / (1 + c)
    return round(lance, -2) if lance > 0 else 0.0


def _data(s: str) -> date | None:
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", s or "")
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3))) if m else None
    except ValueError:
        return None


def montar_lotes(pesquisas: list[Any], cfg: dict[str, Any], hoje: date) -> list[dict[str, Any]]:
    sites = cfg.get("sites") or []
    margem_min = float(cfg.get("margem_min_pct", 15))
    lance_max = float(cfg.get("lance_max", float("inf")))
    vistos: set[str] = set()
    lotes = []
    for p in sorted(pesquisas, key=lambda x: x.pesquisado_em, reverse=True):
        for lote in p.dados.get("lotes") or []:
            url = lote.get("url")
            dominio = dominio_confiavel(url, sites)
            if not dominio or url in vistos or not lote.get("lance_atual"):
                continue
            quando = _data(lote.get("data_leilao", ""))
            if quando and quando < hoje:
                continue  # leilão já passou
            vistos.add(url)
            conta = conta_lote(lote, cfg)
            if lote.get("tipo") in SO_PECAS:
                situacao = "pecas"
            elif conta["margem"] is None:
                situacao = "sem_fipe"
            elif conta["lance"] > lance_max:
                situacao = "acima_orcamento"
            elif conta["margem"] >= margem_min:
                situacao = "lucro"
            elif conta["margem"] > 0:
                situacao = "apertado"
            else:
                situacao = "prejuizo"
            lotes.append({
                **{k: lote.get(k) for k in ("titulo", "marca_modelo", "ano", "km", "tipo", "condicao", "fipe_fonte",
                                            "data_leilao", "local", "leiloeiro", "url", "alertas")},
                "id": "leilao-" + hashlib.sha1(url.encode()).hexdigest()[:12],
                "dominio": dominio, "conta": conta, "situacao": situacao,
                "achado_em": p.pesquisado_em.isoformat() if isinstance(p.pesquisado_em, datetime) else str(p.pesquisado_em),
            })
    ordem = {"lucro": 0, "apertado": 1, "sem_fipe": 2, "acima_orcamento": 3, "prejuizo": 4, "pecas": 5}
    return sorted(lotes, key=lambda x: (ordem[x["situacao"]], -(x["conta"]["margem"] or -999)))
