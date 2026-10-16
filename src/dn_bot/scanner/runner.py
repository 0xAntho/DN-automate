"""Boucle du scanner : collecte, évaluation de chaque paire et chaque couple de plateformes."""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass

from dn_bot.config import Config
from dn_bot.exchanges.base import ExchangeReader
from dn_bot.models import FundingPoint, MarketSnapshot
from dn_bot.scanner.funding import HOUR_MS
from dn_bot.scanner.ranking import Opportunity, evaluate, rank
from dn_bot.storage import Storage

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanError:
    exchange: str
    market: str
    message: str


@dataclass(frozen=True)
class ScanResult:
    timestamp_ms: int
    opportunities: list[Opportunity]
    snapshots: list[MarketSnapshot]
    errors: list[ScanError]


class Scanner:
    def __init__(
        self,
        config: Config,
        readers: dict[str, ExchangeReader],
        storage: Storage | None = None,
        clock: Callable[[], float] = time.time,
    ) -> None:
        self.config = config
        self.readers = readers
        self.storage = storage
        self._clock = clock
        self._history: dict[tuple[str, str], tuple[float, list[FundingPoint]]] = {}

    async def scan_once(self) -> ScanResult:
        now_ms = int(self._clock() * 1000)
        errors: list[ScanError] = []

        markets_by_ex = {
            ex: sorted({p.markets[ex] for p in self.config.pairs if ex in p.markets})
            for ex in self.readers
        }
        results = await asyncio.gather(
            *(self.readers[ex].snapshots(ms) for ex, ms in markets_by_ex.items())
        )
        snaps: dict[tuple[str, str], MarketSnapshot] = {}
        for ex, by_market in zip(markets_by_ex, results, strict=True):
            for market, snap in by_market.items():
                if isinstance(snap, Exception):
                    errors.append(ScanError(ex, market, str(snap)))
                else:
                    snaps[(ex, market)] = snap

        histories = await self._histories(list(snaps), now_ms, errors)

        opportunities = []
        for pair in self.config.pairs:
            available = [ex for ex in pair.markets if (ex, pair.markets[ex]) in snaps]
            for ex_a, ex_b in itertools.combinations(available, 2):
                a = snaps[(ex_a, pair.markets[ex_a])]
                b = snaps[(ex_b, pair.markets[ex_b])]
                history = {
                    ex_a: histories.get((ex_a, a.market), []),
                    ex_b: histories.get((ex_b, b.market), []),
                }
                opportunities.append(
                    evaluate(
                        pair.symbol,
                        a,
                        b,
                        history,
                        self.config.notional_per_leg_usd,
                        self.config.thresholds,
                        now_ms,
                    )
                )

        result = ScanResult(now_ms, rank(opportunities), list(snaps.values()), errors)
        if self.storage is not None:
            self.storage.save_scan(result)
        return result

    async def _histories(
        self, keys: list[tuple[str, str]], now_ms: int, errors: list[ScanError]
    ) -> dict[tuple[str, str], list[FundingPoint]]:
        """Historique de funding par marché, mis en cache (il ne bouge qu'une fois par heure)."""
        span_ms = max(self.config.thresholds.stability_windows_hours) * HOUR_MS
        now_s = now_ms / 1000
        stale = [
            k
            for k in keys
            if k not in self._history
            or now_s - self._history[k][0] >= self.config.history_refresh_seconds
        ]

        async def load(key: tuple[str, str]) -> None:
            ex, market = key
            try:
                points = await self.readers[ex].funding_history(market, now_ms - span_ms, now_ms)
            except Exception as exc:  # noqa: BLE001 - on garde l'ancien cache s'il existe
                errors.append(ScanError(ex, market, f"historique de funding : {exc}"))
                return
            self._history[key] = (now_s, points)

        await asyncio.gather(*(load(k) for k in stale))
        return {k: self._history[k][1] for k in keys if k in self._history}

    async def run_forever(self, on_result: Callable[[ScanResult], None]) -> None:
        while True:
            started = self._clock()
            try:
                on_result(await self.scan_once())
            except Exception:
                log.exception("échec du passage du scanner")
            elapsed = self._clock() - started
            await asyncio.sleep(max(self.config.interval_seconds - elapsed, 1.0))
