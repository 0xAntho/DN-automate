"""Interface commune des adaptateurs, en lecture seule pour l'instant.

L'exécuteur ajoutera plus tard les méthodes d'ordres ; le scanner n'utilise que la lecture.
"""

from __future__ import annotations

import asyncio
from typing import Any, Protocol

import httpx

from dn_bot.models import FundingPoint, MarketSnapshot


class ExchangeError(RuntimeError):
    pass


class ExchangeReader(Protocol):
    name: str

    async def snapshots(self, markets: list[str]) -> dict[str, MarketSnapshot | Exception]:
        """Funding, prix, frais et carnet de chaque marché demandé.

        Une erreur sur un marché est rendue à sa place au lieu d'interrompre les autres.
        """
        ...

    async def funding_history(self, market: str, start_ms: int, end_ms: int) -> list[FundingPoint]:
        """Taux de funding horaires appliqués entre start_ms et end_ms, triés par date."""
        ...

    async def aclose(self) -> None: ...


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    retries: int = 3,
    **kwargs: Any,
) -> Any:
    """Requête HTTP avec reprise sur 429 et erreurs 5xx ou réseau."""
    delay = 1.0
    for attempt in range(retries + 1):
        try:
            resp = await client.request(method, url, **kwargs)
        except httpx.TransportError as exc:
            if attempt == retries:
                raise ExchangeError(f"{method} {url} : {exc}") from exc
            await asyncio.sleep(delay)
            delay *= 2
            continue
        if resp.status_code == 429 or resp.status_code >= 500:
            if attempt == retries:
                raise ExchangeError(f"{method} {url} : HTTP {resp.status_code}")
            await asyncio.sleep(_retry_after(resp, delay))
            delay *= 2
            continue
        if resp.status_code >= 400:
            raise ExchangeError(f"{method} {url} : HTTP {resp.status_code} {resp.text[:200]}")
        return resp.json()
    raise AssertionError("unreachable")


def _retry_after(resp: httpx.Response, default: float) -> float:
    header = resp.headers.get("Retry-After")
    try:
        return max(float(header), 0.0) if header is not None else default
    except ValueError:
        return default
