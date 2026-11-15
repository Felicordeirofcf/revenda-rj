"""Gera docs/index.html: painel estático autocontido (dados embutidos como JSON)."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .config import Catalogo
from sqlalchemy import select

from .database import AnuncioDB, Database, agora, utc
from .database import PesquisaDB
from .precos import calcular_referencias, escolher_referencia
from .promocoes import montar_achados, precos_de_revenda, tetos_de_compra
from .leiloes import montar_lotes
from .regiao import BAIRRO_PARA_ZONA

TEMPLATE = Path(__file__).with_name("dashboard_template.html")


def _iso(dt: datetime | None) -> str | None:
    return utc(dt).isoformat() if dt else None


def _anuncio(r: AnuncioDB, catalogo: Catalogo) -> dict[str, Any]:
    item = catalogo.por_id(r.item_id) if r.item_id else None
    horas = None
    if r.indisponivel_em:
        horas = round((utc(r.indisponivel_em) - r.data_referencia).total_seconds() / 3600, 1)
    return {
        "id": r.chave,
        "titulo": r.titulo,
        "url": r.url,
        "preco": r.preco,
        "preco_inicial": r.preco_inicial,
        "ref": r.preco_ref,
        "n_ref": r.n_ref,
        "ref_tipo": r.ref_tipo,
        "lucro": r.lucro_est,
        "margem": r.margem_pct,
        "suspeito": r.suspeito,
        "situacao": r.situacao,
        "motivo": r.motivo_situacao,
        "item_id": r.item_id,
        "item_nome": item.nome if item else r.item_id,
        "categoria": item.categoria if item else None,
        "variante": r.variante,
        "bairro": r.bairro,
        "cidade": r.cidade,
        "zona": r.zona,
        "imagens": r.imagens[:6],
        "publicado_em": _iso(r.publicado_em),
        "primeiro_visto": _iso(r.primeiro_visto),
        "virou_oportunidade_em": _iso(r.virou_oportunidade_em),
        "vendido_em": _iso(r.indisponivel_em),
        "horas_ate_sumir": horas,
        "lojista": r.profissional,
        "analise": r.analise,
        "fonte": r.fonte,
    }


def montar_dados(db: Database, regras: dict, catalogo: Catalogo, passagens: dict) -> dict[str, Any]:
    quando = agora()
    with db.sessao() as s:
        janela = quando - timedelta(days=regras.get("referencia_dias", 30))
        validos = list(db.precos_validos(s, janela, regras.get("incluir_lojistas_na_referencia", False)))
        refs = calcular_referencias(validos)
        minimo = regras.get("referencia_min_amostras", 5)

        anuncios = [_anuncio(r, catalogo) for r in db.por_situacao(s, "oportunidade", "observacao")]
        limite_vendidos = quando - timedelta(days=30)
        vendidos = [
            _anuncio(r, catalogo) for r in db.por_situacao(s, "vendido")
            if r.virou_oportunidade_em and r.indisponivel_em and utc(r.indisponivel_em) >= limite_vendidos
        ]

        # Foto representativa de cada produto: a do anúncio válido mais recente.
        fotos: dict[str, str] = {}
        for r in sorted(validos, key=lambda x: utc(x.ultimo_visto)):
            if r.imagem:
                fotos[r.item_id] = r.imagem

        produtos = []
        for item in catalogo.itens:
            ref, _ = escolher_referencia(item.id, None, refs, minimo)
            variantes = {
                k.split("|", 1)[1]: vars(v) for k, v in refs.items()
                if k.startswith(item.id + "|") and v.n >= 2
            }
            web = db.ultima_pesquisa(s, "produto", item.id, so_sucesso=True)
            sumiram = [a["horas_ate_sumir"] for a in vendidos if a["item_id"] == item.id and a["horas_ate_sumir"]]
            produtos.append({
                "id": item.id,
                "nome": item.nome,
                "categoria": item.categoria,
                "foto": fotos.get(item.id),
                "ref": vars(ref) if ref else None,
                "variantes": dict(sorted(variantes.items(), key=lambda kv: _ordem_variante(kv[0]))),
                "novo": ({**web.dados, "pesquisado_em": _iso(web.pesquisado_em)} if web else None),
                "oportunidades": sum(a["item_id"] == item.id and a["situacao"] == "oportunidade" for a in anuncios),
                "observacao": sum(a["item_id"] == item.id and a["situacao"] == "observacao" for a in anuncios),
                "horas_mediana_sumir": sorted(sumiram)[len(sumiram) // 2] if sumiram else None,
            })

        rotas = []
        for rota in passagens.get("rotas") or []:
            hist = db.historico_pesquisas(s, "passagem", rota["id"])
            ultima = hist[-1] if hist else None
            erro = db.ultima_pesquisa(s, "passagem", rota["id"])
            rotas.append({
                **{k: rota.get(k) for k in ("id", "nome", "destinos", "periodo", "min_dias", "max_dias", "preco_alvo", "ativa")},
                "ultima": ({**ultima.dados, "pesquisado_em": _iso(ultima.pesquisado_em)} if ultima else None),
                "historico": [{"t": _iso(p.pesquisado_em), "preco": p.melhor_preco} for p in hist if p.melhor_preco],
                "erro": erro.erro if erro and erro.erro else None,
            })

        # Promoções: caçador (últimas 48h) + pesquisas de preço novo (últimos 7 dias), só sites confiáveis.
        recentes = list(s.scalars(select(PesquisaDB).where(
            PesquisaDB.tipo == "promocoes", PesquisaDB.erro.is_(None),
            PesquisaDB.pesquisado_em >= (quando - timedelta(hours=48)).replace(tzinfo=None))))
        produtos_web = {}
        for item in catalogo.itens:
            w = db.ultima_pesquisa(s, "produto", item.id, so_sucesso=True)
            if w and quando - utc(w.pesquisado_em) <= timedelta(days=7):
                produtos_web[item.id] = w
        ultima_promo = db.ultima_pesquisa(s, "promocoes", "geral")
        todos_web = {i.id: w for i in catalogo.itens if (w := db.ultima_pesquisa(s, "produto", i.id, so_sucesso=True))}
        revenda = precos_de_revenda(catalogo, refs, todos_web, regras)
        promocoes = {
            "achados": montar_achados(recentes, produtos_web, catalogo, revenda, regras, quando),
            "tetos": tetos_de_compra(catalogo, revenda, regras),
            "ultima": ({"pesquisado_em": _iso(ultima_promo.pesquisado_em), "erro": ultima_promo.erro,
                        "resumo": ultima_promo.dados.get("resumo")} if ultima_promo else None),
            "lojas": (regras.get("promocoes") or {}).get("lojas_confiaveis") or [],
        }

        # Leilões de carros: pesquisas dos últimos 3 dias.
        cfg_leil = regras.get("leiloes") or {}
        pesq_leil = list(s.scalars(select(PesquisaDB).where(
            PesquisaDB.tipo == "leiloes", PesquisaDB.erro.is_(None),
            PesquisaDB.pesquisado_em >= (quando - timedelta(days=3)).replace(tzinfo=None))))
        ultima_leil = db.ultima_pesquisa(s, "leiloes", "geral")
        hoje_br = (quando - timedelta(hours=3)).date()
        leiloes = {
            "lotes": montar_lotes(pesq_leil, cfg_leil, hoje_br),
            "ultima": ({"pesquisado_em": _iso(ultima_leil.pesquisado_em), "erro": ultima_leil.erro,
                        "resumo": ultima_leil.dados.get("resumo")} if ultima_leil else None),
            "config": {k: cfg_leil.get(k) for k in ("lance_max", "comissao_leiloeiro_pct", "custos_fixos_reais",
                                                    "margem_min_pct", "desagio_revenda_pct", "sites", "regiao", "ativa")},
        }

        execucoes = [
            {"inicio": _iso(e.inicio), "fim": _iso(e.fim), "coletados": e.coletados, "novos": e.novos,
             "oportunidades": e.oportunidades, "novas": e.novas_oportunidades, "ia": e.analises_ia,
             "custo": e.custo_usd, "erros": e.erros}
            for e in db.ultimas_execucoes(s, 40)
        ]

    return {
        "gerado_em": quando.isoformat(),
        "regras": {k: regras.get(k) for k in (
            "orcamento_max", "margem_min_pct", "lucro_min_reais", "desconto_negociacao_pct",
            "custo_fixo_reais", "taxa_venda_pct", "zonas_aceitas", "idade_max_dias", "referencia_min_amostras",
            "busca_manual_olx")},
        "olx_ativa": bool(((regras.get("fontes") or {}).get("olx") or {}).get("ativa")),
        "anuncios": anuncios,
        "vendidos": vendidos,
        "produtos": produtos,
        "checklists": catalogo.checklists,
        "passagens": rotas,
        "promocoes": promocoes,
        "leiloes": leiloes,
        # Para a "Análise OLX" (favorito): o painel classifica no navegador os anúncios que o usuário trouxe.
        "analise_olx": {
            "catalogo": [{"id": i.id, "nome": i.nome, "categoria": i.categoria, "padrao": i.padrao.pattern,
                          "excluir": i.excluir.pattern if i.excluir else None, "variante": i.variante,
                          "preco_min": i.preco_min} for i in catalogo.itens],
            "exclusoes": regras.get("excluir_sempre") or {},
            "bairros": BAIRRO_PARA_ZONA,
            "municipios": regras.get("municipios_aceitos") or [],
            "zonas": regras.get("zonas_aceitas") or [],
            "aceitar_bairro_desconhecido": regras.get("aceitar_bairro_desconhecido", True),
            "revenda": {k: {"mediana": v.mediana, "n": v.n, "fonte": v.fonte} for k, v in revenda.items()},
        },
        "execucoes": execucoes,
    }


def _ordem_variante(v: str) -> int:
    num = int("".join(ch for ch in v if ch.isdigit()) or 0)
    return num * 1024 if v.endswith("TB") else num


def gerar_dashboard(db: Database, regras: dict, catalogo: Catalogo, passagens: dict, destino: Path) -> Path:
    dados = montar_dados(db, regras, catalogo, passagens)
    payload = json.dumps(dados, ensure_ascii=False, default=str).replace("</", "<\\/")
    html = TEMPLATE.read_text(encoding="utf-8").replace("/*__DADOS__*/null", payload)
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(html, encoding="utf-8")
    return destino
