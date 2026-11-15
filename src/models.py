"""Modelos de dados trocados entre coletores, regras, IA e banco."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


@dataclass
class Anuncio:
    fonte: str
    id_externo: str
    url: str
    titulo: str
    preco: float | None
    cidade: str | None = None
    bairro: str | None = None
    uf: str | None = None
    publicado_em: datetime | None = None
    profissional: bool = False
    imagem: str | None = None
    descricao: str | None = None
    termo_busca: str | None = None
    extras: dict = field(default_factory=dict)

    @property
    def chave(self) -> str:
        return hashlib.sha1(f"{self.fonte}:{self.id_externo}".encode()).hexdigest()[:16]


class AnaliseIA(BaseModel):
    """Saída tipada da triagem do Claude (tool com JSON Schema estrito)."""

    produto_confere: bool = Field(description="O anúncio é mesmo do produto do catálogo, inteiro, para venda.")
    armazenamento: str | None = None
    estado: Literal["novo_lacrado", "seminovo_otimo", "bom", "marcas_de_uso", "com_problema", "nao_informado"]
    acompanha: list[str] = Field(default_factory=list)
    sinais_risco: list[str] = Field(default_factory=list)
    nivel_risco: Literal["baixo", "medio", "alto"]
    recomendacao: Literal["ir_ver", "negociar_antes", "evitar"]
    resumo: str
    perguntas_vendedor: list[str] = Field(default_factory=list)
    oferta_sugerida: int | None = None


@dataclass
class UsoTokens:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    custo_usd: float = 0.0
    chamadas: int = 0

    def somar(self, outro: "UsoTokens") -> None:
        self.input_tokens += outro.input_tokens
        self.output_tokens += outro.output_tokens
        self.cache_write_tokens += outro.cache_write_tokens
        self.cache_read_tokens += outro.cache_read_tokens
        self.custo_usd += outro.custo_usd
        self.chamadas += outro.chamadas
