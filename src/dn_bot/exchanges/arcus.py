"""Adaptateur Arcus en lecture (API REST publique /v1, sans authentification)."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

from dn_bot.exchanges.base import ExchangeError, request_json
from dn_bot.models import BookLevel, FundingPoint, MarketSnapshot, OrderBook

FUNDING_PAGE = 1000  # limite maximale de GET /v1/fundingRates
BOOK_LEVELS = 100  # niveaux par côté, maximum accepté par GET /v1/l2OrderBook
FEE_TIERS_TTL_S = 3600.0


class ArcusReader:
    name = "arcus"

    def __init__(
        self,
        base_url: str = "https://api.arcus.xyz",
        fee_tier_level: int = 0,
        fallback_taker_fee: float = 0.0005,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._fee_level = fee_tier_level
        self._fallback_fee = fallback_taker_fee
        self._client = client or httpx.AsyncClient(timeout=10.0)
        self._taker_fee: float | None = None
        self._fee_loaded_at = 0.0

    @classmethod
    def from_config(cls, cfg: dict[str, Any], client: httpx.AsyncClient | None = None):
        return cls(
            base_url=cfg.get("base_url", "https://api.arcus.xyz"),
            fee_tier_level=int(cfg.get("fee_tier_level", 0)),
            fallback_taker_fee=float(cfg.get("fallback_taker_fee", 0.0005)),
            client=client,
        )

    async def _get(self, path: str, **params: Any) -> Any:
        return await request_json(self._client, "GET", self._base + path, params=params or None)

    async def taker_fee(self) -> float:
        """Frais taker du palier configuré, lus dans /v1/feetiers (en ppm du notionnel)."""
        now = time.monotonic()
        if self._taker_fee is not None and now - self._fee_loaded_at < FEE_TIERS_TTL_S:
            return self._taker_fee
        try:
            data = await self._get("/v1/feetiers")
            row = next(t for t in data["tiers"] if int(t["level"]) == self._fee_level)
            self._taker_fee = int(row["taker_fee_ppm"]) / 1_000_000
        except (ExchangeError, StopIteration, KeyError, ValueError):
            if self._taker_fee is None:
                return self._fallback_fee
        self._fee_loaded_at = now
        return self._taker_fee

    async def snapshots(self, markets: list[str]) -> dict[str, MarketSnapshot | Exception]:
        try:
            data, fee = await asyncio.gather(self._get("/v1/markets"), self.taker_fee())
        except Exception as exc:  # noqa: BLE001 - l'erreur est rendue par marché
            return dict.fromkeys(markets, exc)
        infos = {m["marketDisplayName"].upper(): m for m in data["markets"]}

        async def one(market: str) -> MarketSnapshot | Exception:
            info = infos.get(market.upper())
            if info is None:
                return ExchangeError(f"marché {market} introuvable sur Arcus")
            try:
                return self._snapshot(market, info, fee, await self.order_book(market))
            except Exception as exc:  # noqa: BLE001
                return exc

        results = await asyncio.gather(*(one(m) for m in markets))
        return dict(zip(markets, results, strict=True))

    def _snapshot(self, market: str, info: dict, fee: float, book: OrderBook) -> MarketSnapshot:
        # nextFundingRate : prévision pour la prochaine échéance (taux fixe hors séance).
        rate = info.get("nextFundingRate") or info.get("fundingRate")
        if rate is None:
            raise ExchangeError(f"pas de funding publié pour {market} sur Arcus")
        mark = float(info.get("markPrice") or 0) or (book.mid or 0.0)
        off_hours = bool(info.get("isOutsideRth"))
        return MarketSnapshot(
            exchange=self.name,
            market=market,
            funding_rate_hourly=float(rate),
            mark_price=mark,
            taker_fee=fee,
            book=book,
            off_hours=off_hours,
            tradable=info.get("status") == "ONLINE",
            notes=("hors séance",) if off_hours else (),
        )

    async def order_book(self, market: str) -> OrderBook:
        data = await self._get(f"/v1/l2OrderBook/{market}", nLevels=BOOK_LEVELS)
        return OrderBook(
            bids=tuple(BookLevel(float(p), float(s)) for p, s in data["bids"]),
            asks=tuple(BookLevel(float(p), float(s)) for p, s in data["asks"]),
            timestamp_ms=int(data["timestamp"]) // 1000,
        )

    async def funding_history(self, market: str, start_ms: int, end_ms: int) -> list[FundingPoint]:
        # L'API attend des microsecondes ; l'ordre de tri des réponses n'est pas documenté.
        lo, hi = start_ms * 1000, end_ms * 1000
        seen: dict[int, float] = {}
        while lo <= hi:
            data = await self._get(
                "/v1/fundingRates", market=market, **{"from": lo, "to": hi}, limit=FUNDING_PAGE
            )
            rows = data["fundingRates"]
            for r in rows:
                seen[int(r["time"])] = float(r["fundingRate"])
            if len(rows) < FUNDING_PAGE:
                break
            first, last = int(rows[0]["time"]), int(rows[-1]["time"])
            if first <= last:
                lo = last + 1
            else:
                hi = last - 1
        return [FundingPoint(t // 1000, r) for t, r in sorted(seen.items())]

    async def aclose(self) -> None:
        await self._client.aclose()
