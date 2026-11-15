"""Orquestrador: coleta -> classifica -> referência de preço -> margem -> IA -> pesquisa web -> painel.

Uso:
    python -m src.main                 # execução completa
    python -m src.main --sem-ia        # não chama o Claude (só coleta e conta de margem)
    python -m src.main --so-painel     # só regenera docs/index.html a partir do banco
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
from sqlalchemy import func, select

from .classificador import Classificador
from .config import Catalogo, Settings, carregar_catalogo, carregar_yaml, get_settings
from .dashboard import gerar_dashboard
from .database import AnuncioDB, Database, ExecucaoDB, PesquisaDB, agora, utc
from .fontes import REGISTRO
from .http import FonteError
from .ia_base import IAError
from .models import UsoTokens
from .pesquisa_web import PesquisadorWeb
from .precos import avaliar, calcular_referencias
from .promocoes import precos_de_revenda, tetos_de_compra
from .regiao import regiao_aceita
from .triagem import Triador

log = logging.getLogger("revenda")

MAX_BLOQUEIOS_SEGUIDOS = 3  # depois disso a fonte é abandonada nesta execução


class Robo:
    def __init__(self, settings: Settings, db: Database, regras: dict[str, Any], catalogo: Catalogo,
                 passagens: dict[str, Any], client: anthropic.Anthropic | None = None,
                 fontes: dict[str, Any] | None = None):
        self.settings = settings
        self.db = db
        self.regras = regras
        self.catalogo = catalogo
        self.passagens = passagens
        self.client = client
        self.classificador = Classificador(catalogo, regras)
        self.fontes = fontes if fontes is not None else self._criar_fontes()
        self.erros: list[str] = []
        self.uso = UsoTokens()

    def _criar_fontes(self) -> dict[str, Any]:
        fontes = {}
        for nome, cfg in (self.regras.get("fontes") or {}).items():
            if cfg.get("ativa", True) and nome in REGISTRO:
                fontes[nome] = REGISTRO[nome](cfg)
        return fontes

    def erro(self, msg: str) -> None:
        log.error(msg)
        self.erros.append(msg)

    # ------------------------------------------------------------------ coleta
    def coletar(self, s, quando: datetime) -> tuple[int, int]:
        coletados = novos = 0
        for nome, fonte in self.fontes.items():
            bloqueios = 0
            termos = list(dict.fromkeys(t for item in self.catalogo.itens for t in item.buscas))
            for termo in termos:
                try:
                    for anuncio in fonte.buscar(termo):
                        if anuncio.uf and anuncio.uf.upper() != "RJ":
                            continue
                        row, novo = self.db.upsert(s, anuncio, quando)
                        self.classificar(row)
                        coletados += 1
                        novos += int(novo)
                    bloqueios = 0
                except FonteError as exc:
                    self.erro(f"[{nome}] {termo}: {exc}")
                    bloqueios += 1
                    if bloqueios >= MAX_BLOQUEIOS_SEGUIDOS:
                        self.erro(f"[{nome}] {bloqueios} falhas seguidas; pulando o resto desta fonte.")
                        break
                s.flush()
        return coletados, novos

    def classificar(self, row: AnuncioDB) -> None:
        c = self.classificador.classificar(row.titulo, row.preco)
        row.item_id, row.variante, row.motivo_exclusao = c.chave_item, c.variante, c.motivo_exclusao
        ok, zona = regiao_aceita(row.cidade, row.bairro, self.regras)
        row.regiao_ok, row.zona = ok, zona

    # ------------------------------------------------------------------ avaliação
    def avaliar_todos(self, s, quando: datetime) -> None:
        janela = quando - timedelta(days=self.regras.get("referencia_dias", 30))
        refs = calcular_referencias(self.db.precos_validos(
            s, janela, self.regras.get("incluir_lojistas_na_referencia", False)))
        self.referencias = refs
        recentes = quando - timedelta(days=self.regras.get("idade_max_dias", 7) + 1)
        for r in self.db.ativos(s, recentes):
            avaliar(r, refs, self.regras, quando)
        # Oportunidades/observações que saíram da janela voltam a "normal".
        for r in self.db.por_situacao(s, "oportunidade", "observacao"):
            if utc(r.ultimo_visto) < recentes:
                r.situacao, r.motivo_situacao = "normal", "anúncio antigo"

    # ------------------------------------------------------------------ detalhes + IA
    def detalhar_e_triar(self, s, quando: datetime, usar_ia: bool) -> int:
        cfg_olx = (self.regras.get("fontes") or {}).get("olx", {})
        max_det = int(cfg_olx.get("max_detalhes_por_execucao", 40))
        ia_cfg = self.regras.get("ia") or {}
        max_ia = int(ia_cfg.get("max_analises_por_execucao", 40))
        triador = Triador(self.client, self.catalogo, ia_cfg.get("modelo", "claude-haiku-5-5"),
                          ia_cfg.get("effort", "low")) if (usar_ia and self.client) else None

        def precisa_ia(r: AnuncioDB) -> bool:
            return triador is not None and (r.analisado_em is None or r.preco_analisado != r.preco)

        pendentes = [
            r for r in self.db.por_situacao(s, "oportunidade", "observacao")
            if r.preco_ref and (r.descricao is None or precisa_ia(r))
        ]
        pendentes.sort(key=lambda r: (r.situacao != "oportunidade", -(r.margem_pct or 0)))
        analisados = 0
        for r in pendentes[:max_det]:
            fonte = self.fontes.get(r.fonte)
            if fonte is None:
                continue
            if r.descricao is None or (precisa_ia(r) and r.analisado_em is not None):  # preço mudou: relê
                try:
                    det = fonte.detalhar(r)
                except FonteError as exc:
                    self.erro(f"[{r.fonte}] detalhe {r.url}: {exc}")
                    continue
                r.checado_em = quando
                if det.get("indisponivel"):
                    r.situacao, r.indisponivel_em = "vendido", quando
                    continue
                r.descricao = det.get("descricao")
                if det.get("imagens"):
                    r.imagens_json = json.dumps(det["imagens"])
            if not precisa_ia(r) or analisados >= max_ia:
                continue
            try:
                analise, uso = triador.analisar(r)
            except IAError as exc:
                r.erro_analise = str(exc)
                self.erro(f"[IA] {r.titulo[:60]}: {exc}")
                continue
            self.uso.somar(uso)
            r.analise_json = analise.model_dump_json()
            r.analisado_em, r.preco_analisado, r.erro_analise = quando, r.preco, None
            analisados += 1
            avaliar(r, self.referencias, self.regras, quando)
        return analisados

    def checar_disponibilidade(self, s, quando: datetime, limite: int = 10) -> None:
        """Reabre oportunidades antigas para saber se já foram vendidas (mede a velocidade do mercado)."""
        corte = quando - timedelta(hours=6)
        alvo = [r for r in self.db.por_situacao(s, "oportunidade")
                if r.checado_em is None or utc(r.checado_em) < corte][:limite]
        for r in alvo:
            fonte = self.fontes.get(r.fonte)
            if not fonte:
                continue
            try:
                det = fonte.detalhar(r)
            except FonteError as exc:
                self.erro(f"[{r.fonte}] checagem {r.url}: {exc}")
                continue
            r.checado_em = quando
            if det.get("indisponivel"):
                r.situacao, r.indisponivel_em = "vendido", quando

    # ------------------------------------------------------------------ pesquisa web
    def gasto_mes(self, s, quando: datetime) -> float:
        inicio = quando.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        exec_ = s.scalar(select(func.coalesce(func.sum(ExecucaoDB.custo_usd), 0.0))
                         .where(ExecucaoDB.inicio >= inicio)) or 0.0
        return float(exec_) + self.uso.custo_usd

    def pesquisar_web(self, s, quando: datetime) -> None:
        cfg = self.regras.get("pesquisa_web") or {}
        if not cfg.get("ativa") or not self.client:
            return
        teto = float(cfg.get("teto_mensal_usd", 15))
        if self.gasto_mes(s, quando) >= teto:
            self.erro(f"[web] teto mensal de US$ {teto:.2f} atingido; pesquisas pausadas até o próximo mês.")
            return
        reserva = cfg.get("modelo_reserva")
        pesq = PesquisadorWeb(self.client, cfg.get("modelo", "claude-haiku-5-5"), cfg.get("effort", "low"),
                              int(cfg.get("max_buscas_por_pesquisa", 2)), modelo_reserva=reserva)

        def vencido(tipo: str, alvo: str, intervalo: timedelta) -> bool:
            ultima = self.db.ultima_pesquisa(s, tipo, alvo)
            return ultima is None or quando - utc(ultima.pesquisado_em) >= intervalo

        def registrar(tipo: str, alvo: str, fn) -> None:
            if self.gasto_mes(s, quando) >= teto:
                return
            try:
                dados, uso = fn()
            except IAError as exc:
                self.erro(f"[web] {tipo} {alvo}: {exc}")
                s.add(PesquisaDB(tipo=tipo, alvo_id=alvo, pesquisado_em=quando, erro=str(exc)))
                return
            self.uso.somar(uso)
            lista = {"produto": dados.get("ofertas"), "passagem": dados.get("voos")}.get(tipo, dados.get("achados"))
            precos = [o["preco"] for o in (lista or []) if o.get("preco")]
            s.add(PesquisaDB(tipo=tipo, alvo_id=alvo, pesquisado_em=quando,
                             melhor_preco=min(precos) if precos else None,
                             dados_json=json.dumps(dados, ensure_ascii=False), custo_usd=uso.custo_usd))

        # Promoções primeiro: se o teto mensal apertar, é o que mais importa.
        promo = self.regras.get("promocoes") or {}
        if promo.get("ativa") and hasattr(self, "referencias"):
            intervalo = timedelta(hours=float(promo.get("refazer_a_cada_horas", 6)))
            produtos_web = {i.id: w for i in self.catalogo.itens
                            if (w := self.db.ultima_pesquisa(s, "produto", i.id, so_sucesso=True))}
            revenda = precos_de_revenda(self.catalogo, self.referencias, produtos_web, self.regras)
            tetos = tetos_de_compra(self.catalogo, revenda, self.regras)
            if tetos and vencido("promocoes", "geral", intervalo):
                pesq_promo = PesquisadorWeb(self.client, pesq.modelo, cfg.get("effort", "low"),
                                            int(promo.get("max_buscas_por_pesquisa", 3)), modelo_reserva=reserva)
                dominios = list(promo.get("lojas_confiaveis") or []) + list(promo.get("sites_de_promocao") or [])
                hoje_ = quando.astimezone(timezone(timedelta(hours=-3))).date().isoformat()
                registrar("promocoes", "geral", lambda: pesq_promo.promocoes(tetos, hoje_, dominios))

        pc = cfg.get("produtos") or {}
        intervalo = timedelta(days=float(pc.get("refazer_a_cada_dias", 3)))
        devidos = [i for i in self.catalogo.itens if vencido("produto", i.id, intervalo)]
        nunca = any(self.db.ultima_pesquisa(s, "produto", i.id) is None for i in devidos)
        limite = int(pc.get("max_por_execucao_inicial" if nunca else "max_por_execucao", pc.get("max_por_execucao", 2)))
        # Prioridade: produtos nunca pesquisados primeiro.
        devidos.sort(key=lambda i: self.db.ultima_pesquisa(s, "produto", i.id) is not None)
        for item in devidos[:limite]:
            registrar("produto", item.id, lambda item=item: pesq.preco_novo(item.nome, item.buscas))

        pp = cfg.get("passagens") or {}
        intervalo = timedelta(hours=float(pp.get("refazer_a_cada_horas", 20)))
        rotas = [r for r in (self.passagens.get("rotas") or []) if r.get("ativa", True)]
        devidas = [r for r in rotas if vencido("passagem", r["id"], intervalo)]
        hoje = quando.astimezone(timezone(timedelta(hours=-3))).date().isoformat()
        for rota in devidas[: int(pp.get("max_por_execucao", 3))]:
            registrar("passagem", rota["id"], lambda rota=rota: pesq.passagem(rota, hoje))

    # ------------------------------------------------------------------ execução
    def executar(self, usar_ia: bool = True, usar_web: bool = True) -> ExecucaoDB:
        quando = agora()
        with self.db.sessao() as s:
            execucao = ExecucaoDB(inicio=quando)
            s.add(execucao)
            antes = {r.chave for r in self.db.por_situacao(s, "oportunidade")}
            try:
                execucao.coletados, execucao.novos = self.coletar(s, quando)
                self.avaliar_todos(s, quando)
                execucao.analises_ia = self.detalhar_e_triar(s, quando, usar_ia)
                self.checar_disponibilidade(s, quando)
                if usar_web:
                    self.pesquisar_web(s, quando)
                self.db.limpar_antigos(s)
            finally:
                atuais = self.db.por_situacao(s, "oportunidade")
                execucao.oportunidades = len(atuais)
                execucao.novas_oportunidades = sum(r.chave not in antes for r in atuais)
                execucao.custo_usd = round(self.uso.custo_usd, 4)
                execucao.erros_json = json.dumps(self.erros[:50], ensure_ascii=False)
                execucao.fim = agora()
                s.commit()
            return execucao

    def fechar(self) -> None:
        for f in self.fontes.values():
            f.close()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Robô de revenda RJ")
    ap.add_argument("--sem-ia", action="store_true", help="não chama o Claude na triagem")
    ap.add_argument("--sem-web", action="store_true", help="não faz pesquisas na web (preço novo/passagens)")
    ap.add_argument("--so-painel", action="store_true", help="só regenera o painel")
    args = ap.parse_args(argv)

    settings = get_settings()
    logging.basicConfig(level=settings.log_level, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    regras = carregar_yaml(settings.regras_path)
    catalogo = carregar_catalogo(settings.catalogo_path)
    passagens = carregar_yaml(settings.passagens_path) if settings.passagens_path.exists() else {}
    db = Database(settings.database_path)

    codigo = 0
    if not args.so_painel:
        client = None
        if settings.anthropic_api_key:
            client = anthropic.Anthropic(api_key=settings.anthropic_api_key, max_retries=4, timeout=300.0)
        else:
            log.warning("ANTHROPIC_API_KEY ausente: rodando sem IA e sem pesquisa web.")
        robo = Robo(settings, db, regras, catalogo, passagens, client)
        try:
            ex = robo.executar(usar_ia=not args.sem_ia, usar_web=not args.sem_web)
        except anthropic.AuthenticationError:
            log.error("ANTHROPIC_API_KEY inválida. Confira o secret no GitHub.")
            codigo = 1
        else:
            log.info("Coletados %d (novos %d) | oportunidades %d (novas %d) | IA %d | US$ %.4f | erros %d",
                     ex.coletados, ex.novos, ex.oportunidades, ex.novas_oportunidades, ex.analises_ia,
                     ex.custo_usd, len(ex.erros))
        finally:
            robo.fechar()
    gerar_dashboard(db, regras, catalogo, passagens, settings.dashboard_path)
    log.info("Painel gerado em %s", settings.dashboard_path)
    return codigo


if __name__ == "__main__":
    sys.exit(main())
