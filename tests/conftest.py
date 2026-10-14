from __future__ import annotations

from dn_bot.models import BookLevel, FundingPoint, MarketSnapshot, OrderBook

HOUR_MS = 3_600_000
NOW_MS = 1_792_000_000_000  # mi-octobre 2026


def book(mid: float, half_spread: float = 0.05, size: float = 100.0, levels: int = 5) -> OrderBook:
    """Carnet symétrique : `levels` niveaux de `size` actifs, espacés de half_spread."""
    bids = tuple(BookLevel(mid - half_spread * (i + 1), size) for i in range(levels))
    asks = tuple(BookLevel(mid + half_spread * (i + 1), size) for i in range(levels))
    return OrderBook(bids=bids, asks=asks, timestamp_ms=NOW_MS)


def snapshot(
    exchange: str,
    funding: float,
    mid: float = 100.0,
    fee: float = 0.0005,
    off_hours: bool = False,
    **book_kwargs,
) -> MarketSnapshot:
    return MarketSnapshot(
        exchange=exchange,
        market=f"{exchange}:TEST",
        funding_rate_hourly=funding,
        mark_price=mid,
        taker_fee=fee,
        book=book(mid, **book_kwargs),
        off_hours=off_hours,
    )


def flat_history(rate: float, hours: int = 720, now_ms: int = NOW_MS) -> list[FundingPoint]:
    return [FundingPoint(now_ms - i * HOUR_MS, rate) for i in range(hours)]
