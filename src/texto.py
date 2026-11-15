"""Normalização de texto para casar regex (minúsculo, sem acento, espaços simples)."""

from __future__ import annotations

import re
import unicodedata


def normalizar(texto: str | None) -> str:
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", sem_acento.lower()).strip()


def parse_preco(valor) -> float | None:
    """Aceita 2500, 2500.0, "R$ 2.500", "2.500,90". Devolve None se não houver número."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor) if valor > 0 else None
    s = re.sub(r"[^\d,\.]", "", str(valor))
    if not s:
        return None
    if "," in s:  # formato BR: 2.500,90
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"\d{1,3}(\.\d{3})+", s):  # 2.500
        s = s.replace(".", "")
    try:
        v = float(s)
    except ValueError:
        return None
    return v if v > 0 else None


RE_ARMAZENAMENTO = re.compile(r"\b(32|64|128|256|512)\s*(gb|g|giga|gigas)\b|\b(1|2)\s*(tb|tera)\b")


def detectar_armazenamento(texto_norm: str) -> str | None:
    m = RE_ARMAZENAMENTO.search(texto_norm)
    if not m:
        return None
    if m.group(1):
        return f"{m.group(1)}GB"
    return f"{m.group(3)}TB"
