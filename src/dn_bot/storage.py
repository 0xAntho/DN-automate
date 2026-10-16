"""Enregistrement des passages du scanner dans SQLite (PostgreSQL viendra avec le déploiement)."""

from __future__ import annotations

import json
import math
import sqlite3
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dn_bot.scanner.runner import ScanResult

SCHEMA = """
CREATE TABLE IF NOT EXISTS market_snapshots (
    ts_ms INTEGER NOT NULL,
    exchange TEXT NOT NULL,
    market TEXT NOT NULL,
    funding_rate_hourly REAL NOT NULL,
    mark_price REAL NOT NULL,
    best_bid REAL,
    best_ask REAL,
    taker_fee REAL NOT NULL,
    off_hours INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_market_snapshots ON market_snapshots (exchange, market, ts_ms);

CREATE TABLE IF NOT EXISTS opportunities (
    ts_ms INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    long_exchange TEXT NOT NULL,
    short_exchange TEXT NOT NULL,
    funding_long_hourly REAL NOT NULL,
    funding_short_hourly REAL NOT NULL,
    annualized_spread REAL NOT NULL,
    total_cost_usd REAL,
    breakeven_hours REAL,
    passes INTEGER NOT NULL,
    reasons TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_opportunities ON opportunities (symbol, ts_ms);
"""


def _finite(x: float) -> float | None:
    return None if x is None or math.isinf(x) or math.isnan(x) else x


class Storage:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path)
        self.conn.executescript(SCHEMA)

    def save_scan(self, result: ScanResult) -> None:
        ts = result.timestamp_ms
        with self.conn:
            self.conn.executemany(
                "INSERT INTO market_snapshots VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        ts,
                        s.exchange,
                        s.market,
                        s.funding_rate_hourly,
                        s.mark_price,
                        s.book.best_bid,
                        s.book.best_ask,
                        s.taker_fee,
                        int(s.off_hours),
                    )
                    for s in result.snapshots
                ],
            )
            self.conn.executemany(
                "INSERT INTO opportunities VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    (
                        ts,
                        o.symbol,
                        o.long_exchange,
                        o.short_exchange,
                        o.funding_long_hourly,
                        o.funding_short_hourly,
                        o.annualized_spread,
                        _finite(o.total_cost_usd),
                        _finite(o.breakeven_hours),
                        int(o.passes),
                        json.dumps(list(o.reasons), ensure_ascii=False),
                    )
                    for o in result.opportunities
                ],
            )

    def close(self) -> None:
        self.conn.close()
