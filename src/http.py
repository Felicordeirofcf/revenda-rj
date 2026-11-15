"""httpx.Client com retry exponencial, respeito a Retry-After e intervalo mínimo entre requisições."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36"
)
STATUS_RETENTAVEIS = {408, 425, 429, 500, 502, 503, 504}


class FonteError(RuntimeError):
    """Erro irrecuperável numa fonte (o orquestrador registra e segue)."""


class HttpClient:
    def __init__(self, *, intervalo_minimo: float = 1.0, max_tentativas: int = 3, timeout: float = 25.0,
                 transport: httpx.BaseTransport | None = None, sleep=time.sleep):
        self._client = httpx.Client(
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "pt-BR,pt;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
            transport=transport,
        )
        self.intervalo_minimo = intervalo_minimo
        self.max_tentativas = max_tentativas
        self._ultimo = 0.0
        self._sleep = sleep

    def close(self) -> None:
        self._client.close()

    def _esperar_intervalo(self) -> None:
        decorrido = time.monotonic() - self._ultimo
        if decorrido < self.intervalo_minimo:
            self._sleep(self.intervalo_minimo - decorrido + random.random() * 0.5)
        self._ultimo = time.monotonic()

    @staticmethod
    def _retry_after(resp: httpx.Response) -> float | None:
        valor = resp.headers.get("Retry-After")
        if not valor:
            return None
        try:
            return max(0.0, float(valor))
        except ValueError:
            try:
                return max(0.0, (parsedate_to_datetime(valor) - datetime.now(timezone.utc)).total_seconds())
            except (TypeError, ValueError):
                return None

    def get(self, url: str, params: dict[str, Any] | None = None) -> httpx.Response:
        ultimo_erro: Exception | None = None
        for tentativa in range(1, self.max_tentativas + 1):
            self._esperar_intervalo()
            try:
                resp = self._client.get(url, params=params)
            except httpx.TransportError as exc:
                ultimo_erro = exc
                espera = min(30.0, 2 ** tentativa + random.random())
                log.warning("Falha de rede em %s (%s), tentativa %d/%d", url, exc.__class__.__name__,
                            tentativa, self.max_tentativas)
                self._sleep(espera)
                continue
            if resp.status_code in STATUS_RETENTAVEIS:
                espera = self._retry_after(resp) or min(60.0, 2 ** tentativa + random.random())
                if espera > 120:
                    raise FonteError(f"Rate limit em {url}: Retry-After de {espera:.0f}s")
                log.warning("HTTP %d em %s, tentativa %d/%d", resp.status_code, url, tentativa, self.max_tentativas)
                ultimo_erro = httpx.HTTPStatusError(f"HTTP {resp.status_code}", request=resp.request, response=resp)
                self._sleep(espera)
                continue
            return resp
        raise FonteError(f"Desisti de {url} após {self.max_tentativas} tentativas: {ultimo_erro}")
