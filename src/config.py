"""Configuração: variáveis de ambiente (.env/Actions) + arquivos YAML em config/."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

# USD por 1M de tokens: (entrada, saída, leitura de cache). Escrita de cache = 1,25x entrada.
PRECOS_MODELOS: dict[str, tuple[float, float, float]] = {
    "claude-haiku-5-5": (0.10, 0.50, 0.01),
    "claude-sonnet-5-5": (2.00, 10.00, 0.10),
    "claude-opus-5-5": (4.00, 20.00, 0.20),
}
MULT_CACHE_WRITE = 1.25


def _path(name: str, default: str) -> Path:
    p = Path(os.getenv(name) or default)
    return p if p.is_absolute() else ROOT_DIR / p


@dataclass(frozen=True)
class Settings:
    anthropic_api_key: str | None = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY") or None)
    regras_path: Path = field(default_factory=lambda: _path("REGRAS_PATH", "config/regras.yaml"))
    catalogo_path: Path = field(default_factory=lambda: _path("CATALOGO_PATH", "config/catalogo.yaml"))
    passagens_path: Path = field(default_factory=lambda: _path("PASSAGENS_PATH", "config/passagens.yaml"))
    database_path: Path = field(default_factory=lambda: _path("DATABASE_PATH", "data/revenda.db"))
    dashboard_path: Path = field(default_factory=lambda: _path("DASHBOARD_PATH", "docs/index.html"))
    log_level: str = field(default_factory=lambda: os.getenv("LOG_LEVEL", "INFO").upper())


@dataclass
class ItemCatalogo:
    id: str
    nome: str
    categoria: str
    buscas: list[str]
    padrao: re.Pattern
    excluir: re.Pattern | None = None
    variante: str | None = None
    preco_min: float = 0.0


@dataclass
class Catalogo:
    itens: list[ItemCatalogo]
    checklists: dict[str, list[str]]

    def por_id(self, item_id: str) -> ItemCatalogo | None:
        return next((i for i in self.itens if i.id == item_id), None)


def carregar_yaml(caminho: Path) -> dict[str, Any]:
    with caminho.open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def carregar_catalogo(caminho: Path) -> Catalogo:
    dados = carregar_yaml(caminho)
    itens: list[ItemCatalogo] = []
    ids: set[str] = set()
    for bruto in dados.get("itens") or []:
        if bruto["id"] in ids:
            raise ValueError(f"id duplicado no catálogo: {bruto['id']}")
        ids.add(bruto["id"])
        itens.append(
            ItemCatalogo(
                id=bruto["id"],
                nome=bruto["nome"],
                categoria=bruto["categoria"],
                buscas=list(bruto.get("buscas") or [bruto["nome"]]),
                padrao=re.compile(bruto["padrao"]),
                excluir=re.compile(bruto["excluir"]) if bruto.get("excluir") else None,
                variante=bruto.get("variante"),
                preco_min=float(bruto.get("preco_min") or 0),
            )
        )
    return Catalogo(itens=itens, checklists=dados.get("checklists") or {})


def get_settings() -> Settings:
    return Settings()
