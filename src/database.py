"""Persistência em SQLite (SQLAlchemy 2). O arquivo data/revenda.db é commitado pelo Actions."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .models import Anuncio


def agora() -> datetime:
    return datetime.now(timezone.utc)


def utc(dt: datetime | None) -> datetime | None:
    """SQLite devolve datetimes sem fuso; tudo aqui é UTC."""
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


class Base(DeclarativeBase):
    pass


class AnuncioDB(Base):
    __tablename__ = "anuncios"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chave: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    fonte: Mapped[str] = mapped_column(String(20))
    id_externo: Mapped[str] = mapped_column(String(64))
    url: Mapped[str] = mapped_column(Text)
    titulo: Mapped[str] = mapped_column(Text)
    preco: Mapped[float | None] = mapped_column(Float)
    preco_inicial: Mapped[float | None] = mapped_column(Float)
    cidade: Mapped[str | None] = mapped_column(String(80))
    bairro: Mapped[str | None] = mapped_column(String(80))
    zona: Mapped[str | None] = mapped_column(String(40))
    regiao_ok: Mapped[bool] = mapped_column(Boolean, default=False)
    profissional: Mapped[bool] = mapped_column(Boolean, default=False)
    imagem: Mapped[str | None] = mapped_column(Text)
    imagens_json: Mapped[str | None] = mapped_column(Text)
    descricao: Mapped[str | None] = mapped_column(Text)
    publicado_em: Mapped[datetime | None] = mapped_column(DateTime)
    primeiro_visto: Mapped[datetime] = mapped_column(DateTime, default=agora)
    ultimo_visto: Mapped[datetime] = mapped_column(DateTime, default=agora, index=True)

    item_id: Mapped[str | None] = mapped_column(String(40), index=True)
    variante: Mapped[str | None] = mapped_column(String(20))
    motivo_exclusao: Mapped[str | None] = mapped_column(Text)

    preco_ref: Mapped[float | None] = mapped_column(Float)
    n_ref: Mapped[int | None] = mapped_column(Integer)
    ref_tipo: Mapped[str | None] = mapped_column(String(20))
    lucro_est: Mapped[float | None] = mapped_column(Float)
    margem_pct: Mapped[float | None] = mapped_column(Float)
    suspeito: Mapped[bool] = mapped_column(Boolean, default=False)
    # oportunidade | observacao | normal | descartado | vendido
    situacao: Mapped[str] = mapped_column(String(20), default="normal", index=True)
    motivo_situacao: Mapped[str | None] = mapped_column(Text)
    virou_oportunidade_em: Mapped[datetime | None] = mapped_column(DateTime)

    analise_json: Mapped[str | None] = mapped_column(Text)
    analisado_em: Mapped[datetime | None] = mapped_column(DateTime)
    preco_analisado: Mapped[float | None] = mapped_column(Float)
    erro_analise: Mapped[str | None] = mapped_column(Text)
    checado_em: Mapped[datetime | None] = mapped_column(DateTime)
    indisponivel_em: Mapped[datetime | None] = mapped_column(DateTime)

    @property
    def analise(self) -> dict[str, Any] | None:
        return json.loads(self.analise_json) if self.analise_json else None

    @property
    def imagens(self) -> list[str]:
        return json.loads(self.imagens_json) if self.imagens_json else ([self.imagem] if self.imagem else [])

    @property
    def data_referencia(self) -> datetime:
        return utc(self.publicado_em) or utc(self.primeiro_visto)


class ExecucaoDB(Base):
    __tablename__ = "execucoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    inicio: Mapped[datetime] = mapped_column(DateTime, default=agora)
    fim: Mapped[datetime | None] = mapped_column(DateTime)
    coletados: Mapped[int] = mapped_column(Integer, default=0)
    novos: Mapped[int] = mapped_column(Integer, default=0)
    oportunidades: Mapped[int] = mapped_column(Integer, default=0)
    novas_oportunidades: Mapped[int] = mapped_column(Integer, default=0)
    analises_ia: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[float] = mapped_column(Float, default=0.0)
    erros_json: Mapped[str] = mapped_column(Text, default="[]")

    @property
    def erros(self) -> list[str]:
        return json.loads(self.erros_json or "[]")


class PesquisaDB(Base):
    """Resultado de pesquisa na web: preço novo de produto ou passagem aérea."""

    __tablename__ = "pesquisas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(20), index=True)  # produto | passagem
    alvo_id: Mapped[str] = mapped_column(String(60), index=True)
    pesquisado_em: Mapped[datetime] = mapped_column(DateTime, default=agora)
    melhor_preco: Mapped[float | None] = mapped_column(Float)
    dados_json: Mapped[str | None] = mapped_column(Text)
    erro: Mapped[str | None] = mapped_column(Text)
    custo_usd: Mapped[float] = mapped_column(Float, default=0.0)

    @property
    def dados(self) -> dict[str, Any]:
        return json.loads(self.dados_json) if self.dados_json else {}


class Database:
    def __init__(self, caminho: Path | str):
        url = "sqlite:///:memory:" if str(caminho) == ":memory:" else f"sqlite:///{caminho}"
        if str(caminho) != ":memory:":
            Path(caminho).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, future=True)
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False, future=True)

    def sessao(self) -> Session:
        return self.Session()

    # ---- gravação ------------------------------------------------------------
    @staticmethod
    def upsert(s: Session, a: Anuncio, quando: datetime | None = None) -> tuple[AnuncioDB, bool]:
        quando = quando or agora()
        row = s.scalar(select(AnuncioDB).where(AnuncioDB.chave == a.chave))
        novo = row is None
        if novo:
            row = AnuncioDB(chave=a.chave, fonte=a.fonte, id_externo=a.id_externo, preco_inicial=a.preco,
                            primeiro_visto=quando)
            s.add(row)
        row.url = a.url
        row.titulo = a.titulo
        if a.preco is not None:
            row.preco = a.preco
        row.cidade = a.cidade or row.cidade
        row.bairro = a.bairro or row.bairro
        row.profissional = a.profissional
        row.imagem = a.imagem or row.imagem
        row.publicado_em = a.publicado_em or row.publicado_em
        row.ultimo_visto = quando
        if row.situacao == "vendido":  # reapareceu
            row.situacao, row.indisponivel_em = "normal", None
        return row, novo

    # ---- consultas -----------------------------------------------------------
    @staticmethod
    def precos_validos(s: Session, desde: datetime, incluir_lojistas: bool) -> Iterable[AnuncioDB]:
        q = select(AnuncioDB).where(
            AnuncioDB.item_id.is_not(None),
            AnuncioDB.motivo_exclusao.is_(None),
            AnuncioDB.preco.is_not(None),
            AnuncioDB.ultimo_visto >= desde,
        )
        if not incluir_lojistas:
            q = q.where(AnuncioDB.profissional.is_(False))
        return s.scalars(q)

    @staticmethod
    def ativos(s: Session, desde: datetime) -> list[AnuncioDB]:
        return list(s.scalars(select(AnuncioDB).where(AnuncioDB.ultimo_visto >= desde)))

    @staticmethod
    def por_situacao(s: Session, *situacoes: str) -> list[AnuncioDB]:
        return list(s.scalars(select(AnuncioDB).where(AnuncioDB.situacao.in_(situacoes))))

    @staticmethod
    def ultimas_execucoes(s: Session, n: int = 30) -> list[ExecucaoDB]:
        return list(s.scalars(select(ExecucaoDB).order_by(ExecucaoDB.id.desc()).limit(n)))

    @staticmethod
    def ultima_pesquisa(s: Session, tipo: str, alvo_id: str, so_sucesso: bool = False) -> PesquisaDB | None:
        q = select(PesquisaDB).where(PesquisaDB.tipo == tipo, PesquisaDB.alvo_id == alvo_id)
        if so_sucesso:
            q = q.where(PesquisaDB.erro.is_(None))
        return s.scalar(q.order_by(PesquisaDB.pesquisado_em.desc()).limit(1))

    @staticmethod
    def historico_pesquisas(s: Session, tipo: str, alvo_id: str, limite: int = 60) -> list[PesquisaDB]:
        q = (select(PesquisaDB).where(PesquisaDB.tipo == tipo, PesquisaDB.alvo_id == alvo_id,
                                       PesquisaDB.erro.is_(None))
             .order_by(PesquisaDB.pesquisado_em.desc()).limit(limite))
        return list(reversed(list(s.scalars(q))))

    @staticmethod
    def limpar_antigos(s: Session, dias: int = 90) -> int:
        """Apaga anúncios não vistos há muito tempo, exceto os que já foram oportunidade."""
        limite = agora() - timedelta(days=dias)
        velhos = list(s.scalars(select(AnuncioDB).where(
            AnuncioDB.ultimo_visto < limite, AnuncioDB.virou_oportunidade_em.is_(None))))
        for r in velhos:
            s.delete(r)
        return len(velhos)
