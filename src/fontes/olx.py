"""Coletor da OLX.

As páginas da OLX são Next.js: os dados vêm num <script id="__NEXT_DATA__"> com JSON. Em vez de
depender de um caminho fixo (que muda com frequência), procuramos recursivamente as listas de
anúncios (dicts com "subject" + "url"/"listId") e o anúncio da página de detalhe (dict com "body").
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Iterable, Iterator
from urllib.parse import quote_plus

from ..http import FonteError, HttpClient
from ..models import Anuncio
from ..texto import parse_preco

log = logging.getLogger(__name__)

RE_NEXT_DATA = re.compile(r'<script[^>]*id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
MARCADORES_BLOQUEIO = ("cf-chl", "challenge-platform", "Just a moment", "Access denied", "Attention Required")


def extrair_next_data(html: str) -> dict[str, Any]:
    m = RE_NEXT_DATA.search(html)
    if not m:
        if any(x in html for x in MARCADORES_BLOQUEIO):
            raise FonteError("OLX respondeu com página de verificação anti-robô (Cloudflare)")
        raise FonteError("OLX: __NEXT_DATA__ não encontrado (layout mudou?)")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        raise FonteError(f"OLX: JSON inválido em __NEXT_DATA__: {exc}") from exc


def _percorrer(obj: Any) -> Iterator[Any]:
    pilha = [obj]
    while pilha:
        atual = pilha.pop()
        yield atual
        if isinstance(atual, dict):
            pilha.extend(atual.values())
        elif isinstance(atual, list):
            pilha.extend(atual)


def _eh_anuncio(d: Any) -> bool:
    return isinstance(d, dict) and "subject" in d and ("listId" in d or "url" in d)


def encontrar_anuncios(dados: dict[str, Any]) -> list[dict[str, Any]]:
    """Maior lista de dicts que parecem anúncios (evita pegar 'anúncios relacionados' pequenos)."""
    melhores: list[dict[str, Any]] = []
    for no in _percorrer(dados):
        if isinstance(no, list) and no and sum(_eh_anuncio(x) for x in no) >= max(1, len(no) // 2):
            lista = [x for x in no if _eh_anuncio(x)]
            if len(lista) > len(melhores):
                melhores = lista
    return melhores


def _data(valor: Any) -> datetime | None:
    if valor in (None, ""):
        return None
    try:
        if isinstance(valor, (int, float)) or str(valor).isdigit():
            ts = float(valor)
            if ts > 1e12:  # milissegundos
                ts /= 1000
            return datetime.fromtimestamp(ts, tz=timezone.utc)
        dt = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (ValueError, OSError, OverflowError):
        return None


def _imagem(d: dict[str, Any]) -> str | None:
    if isinstance(d.get("thumbnail"), str):
        return d["thumbnail"]
    imgs = d.get("images") or d.get("imagens") or []
    if imgs and isinstance(imgs, list):
        primeira = imgs[0]
        if isinstance(primeira, str):
            return primeira
        if isinstance(primeira, dict):
            return primeira.get("original") or primeira.get("originalWebp") or primeira.get("url") or primeira.get("thumbnail")
    return None


def _local(d: dict[str, Any]) -> tuple[str | None, str | None, str | None]:
    det = d.get("locationDetails") or {}
    cidade = det.get("municipality") or d.get("municipality")
    bairro = det.get("neighbourhood") or det.get("neighborhood") or d.get("neighbourhood")
    uf = det.get("uf") or d.get("uf")
    if not cidade and isinstance(d.get("location"), str):
        # Formato antigo: "Rio de Janeiro, Tijuca - DDD 21"
        partes = [p.strip() for p in re.split(r"[,\-]", d["location"]) if p.strip()]
        if partes:
            cidade = partes[0]
        if len(partes) > 1 and not partes[1].upper().startswith("DDD"):
            bairro = partes[1]
    return cidade, bairro, uf


def anuncio_de_dict(d: dict[str, Any], termo: str | None = None) -> Anuncio | None:
    url = d.get("url") or d.get("friendlyUrl")
    id_externo = str(d.get("listId") or d.get("id") or "") or None
    if not url or not id_externo:
        return None
    preco = parse_preco(d.get("priceValue") if d.get("priceValue") not in (None, "") else d.get("price"))
    cidade, bairro, uf = _local(d)
    return Anuncio(
        fonte="olx",
        id_externo=id_externo,
        url=url,
        titulo=str(d.get("subject") or d.get("title") or "").strip(),
        preco=preco,
        cidade=cidade,
        bairro=bairro,
        uf=uf,
        publicado_em=_data(d.get("date") or d.get("origListTime") or d.get("listTime")),
        profissional=bool(d.get("professionalAd") or d.get("isProfessional")),
        imagem=_imagem(d),
        descricao=d.get("body"),
        termo_busca=termo,
    )


def detalhe_de_html(html: str) -> dict[str, Any]:
    dados = extrair_next_data(html)
    for no in _percorrer(dados):
        if isinstance(no, dict) and isinstance(no.get("body"), str) and ("subject" in no or "listId" in no):
            imagens = []
            for img in no.get("images") or []:
                if isinstance(img, dict):
                    u = img.get("original") or img.get("originalWebp") or img.get("url")
                    if u:
                        imagens.append(u)
                elif isinstance(img, str):
                    imagens.append(img)
            return {"descricao": no["body"], "imagens": imagens[:6]}
    raise FonteError("OLX: descrição não encontrada na página do anúncio")


class OlxFonte:
    nome = "olx"

    def __init__(self, config: dict[str, Any], http: HttpClient | None = None):
        self.config = config
        self.http = http or HttpClient(intervalo_minimo=float(config.get("intervalo_seg", 2.5)))
        self.url_busca = config["url_busca"]
        self.paginas = int(config.get("paginas", 1))
        self.erros: list[str] = []

    def buscar(self, termo: str) -> Iterable[Anuncio]:
        base = self.url_busca.format(q=quote_plus(termo))
        for pagina in range(1, self.paginas + 1):
            url = base if pagina == 1 else f"{base}{'&' if '?' in base else '?'}o={pagina}"
            resp = self.http.get(url)
            if resp.status_code == 403:
                raise FonteError(f"OLX bloqueou a busca '{termo}' (HTTP 403)")
            if resp.status_code != 200:
                raise FonteError(f"OLX: HTTP {resp.status_code} em '{termo}' p.{pagina}")
            brutos = encontrar_anuncios(extrair_next_data(resp.text))
            if not brutos:
                break
            for d in brutos:
                anuncio = anuncio_de_dict(d, termo)
                if anuncio:
                    yield anuncio

    def detalhar(self, anuncio: Anuncio) -> dict[str, Any]:
        resp = self.http.get(anuncio.url)
        if resp.status_code in (404, 410):
            return {"indisponivel": True}
        if resp.status_code != 200:
            raise FonteError(f"OLX: HTTP {resp.status_code} ao abrir {anuncio.url}")
        return detalhe_de_html(resp.text)

    def close(self) -> None:
        self.http.close()
