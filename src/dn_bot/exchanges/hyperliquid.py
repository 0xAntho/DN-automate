"""Adaptateur Hyperliquid en lecture (POST /info), y compris les dex HIP-3 comme trade.xyz.

Un marché HIP-3 se nomme "<dex>:<actif>" (ex. "xyz:NVDA") ; un marché du dex principal
se nomme simplement par son actif (ex. "BTC").
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import Any

import httpx

from dn_bot.exchanges.base import ExchangeError, request_json
from dn_bot.models import BookLevel, FundingPoint, MarketSnapshot, OrderBook

FUNDING_HISTORY_PAGE = 500  # nombre maximum de lignes renvoyées par fundingHistory


def dex_of(market: str) -> str:
    return market.split(":", 1)[0] if ":" in market else ""


class HyperliquidReader:
    name = "hyperliquid"

    def __init__(
        self,
        base_url: str = "https://api.hyperliquid.xyz",
        taker_fee: float = 0.00045,
        hip3_fee_multiplier: dict[str, float] | None = None,
        growth_mode_fee_factor: float = 0.1,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._url = base_url.rstrip("/") + "/info"
        self._taker_fee = taker_fee
        self._hip3_multiplier = hip3_fee_multiplier or {}
        self._growth_factor = growth_mode_fee_factor
        self._client = client or httpx.AsyncClient(timeout=10.0)

    @classmethod
    def from_config(cls, cfg: dict[str, Any], client: httpx.AsyncClient | None = None):
        return cls(
            base_url=cfg.get("base_url", "https://api.hyperliquid.xyz"),
            taker_fee=float(cfg.get("taker_fee", 0.00045)),
            hip3_fee_multiplier={
                k: float(v) for k, v in cfg.get("hip3_fee_multiplier", {}).items()
            },
            growth_mode_fee_factor=float(cfg.get("growth_mode_fee_factor", 0.1)),
            client=client,
        )

    async def _info(self, body: dict[str, Any]) -> Any:
        return await request_json(self._client, "POST", self._url, json=body)

    async def snapshots(self, markets: list[str]) -> dict[str, MarketSnapshot | Exception]:
        by_dex: dict[str, list[str]] = defaultdict(list)
        for m in markets:
            by_dex[dex_of(m)].append(m)

        contexts: dict[str, tuple[dict, dict] | Exception] = {}

        async def load_dex(dex: str) -> None:
            body: dict[str, Any] = {"type": "metaAndAssetCtxs"}
            if dex:
                body["dex"] = dex
            try:
                meta, ctxs = await self._info(body)
                for asset, ctx in zip(meta["universe"], ctxs, strict=True):
                    contexts[asset["name"]] = (asset, ctx)
            except Exception as exc:  # noqa: BLE001 - l'erreur est rendue par marché
                for m in by_dex[dex]:
                    contexts[m] = exc

        await asyncio.gather(*(load_dex(d) for d in by_dex))

        async def one(market: str) -> MarketSnapshot | Exception:
            found = contexts.get(market)
            if found is None:
                return ExchangeError(f"marché {market} introuvable sur Hyperliquid")
            if isinstance(found, Exception):
                return found
            try:
                return self._snapshot(market, *found, await self.order_book(market))
            except Exception as exc:  # noqa: BLE001
                return exc

        results = await asyncio.gather(*(one(m) for m in markets))
        return dict(zip(markets, results, strict=True))

    def _snapshot(self, market: str, asset: dict, ctx: dict, book: OrderBook) -> MarketSnapshot:
        dex = dex_of(market)
        fee = self._taker_fee
        notes = []
        if dex:
            fee *= self._hip3_multiplier.get(dex, 2.0)
        if asset.get("growthMode") == "enabled":
            fee *= self._growth_factor
            notes.append("growth mode")
        return MarketSnapshot(
            exchange=self.name,
            market=market,
            funding_rate_hourly=float(ctx["funding"]),
            mark_price=float(ctx["markPx"]),
            taker_fee=fee,
            book=book,
            tradable=not asset.get("isDelisted", False),
            notes=tuple(notes),
        )

    async def order_book(self, market: str) -> OrderBook:
        data = await self._info({"type": "l2Book", "coin": market})
        bids, asks = data["levels"]
        return OrderBook(
            bids=tuple(BookLevel(float(lv["px"]), float(lv["sz"])) for lv in bids),
            asks=tuple(BookLevel(float(lv["px"]), float(lv["sz"])) for lv in asks),
            timestamp_ms=int(data["time"]),
        )

    async def funding_history(self, market: str, start_ms: int, end_ms: int) -> list[FundingPoint]:
        points: list[FundingPoint] = []
        start = start_ms
        while start <= end_ms:
            rows = await self._info(
                {"type": "fundingHistory", "coin": market, "startTime": start, "endTime": end_ms}
            )
            if not rows:
                break
            points.extend(FundingPoint(int(r["time"]), float(r["fundingRate"])) for r in rows)
            if len(rows) < FUNDING_HISTORY_PAGE:
                break
            start = int(rows[-1]["time"]) + 1
        points.sort(key=lambda p: p.time_ms)
        return points

    async def aclose(self) -> None:
        await self._client.aclose()
