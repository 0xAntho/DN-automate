"""Types de données partagés par les adaptateurs et le scanner."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BookLevel:
    price: float
    size: float  # en unités de l'actif


@dataclass(frozen=True)
class OrderBook:
    bids: tuple[BookLevel, ...]  # du meilleur au moins bon (prix décroissants)
    asks: tuple[BookLevel, ...]  # du meilleur au moins bon (prix croissants)
    timestamp_ms: int

    @property
    def best_bid(self) -> float | None:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> float | None:
        return self.asks[0].price if self.asks else None

    @property
    def mid(self) -> float | None:
        if self.best_bid is None or self.best_ask is None:
            return None
        return (self.best_bid + self.best_ask) / 2


@dataclass(frozen=True)
class FundingPoint:
    time_ms: int
    rate_hourly: float  # décimal, positif = les longs paient les shorts


@dataclass(frozen=True)
class MarketSnapshot:
    """État d'un marché sur une plateforme à un instant donné."""

    exchange: str
    market: str  # nom du marché sur la plateforme (ex. "xyz:NVDA", "NVDA-USD")
    funding_rate_hourly: float  # taux horaire attendu pour la prochaine échéance
    mark_price: float
    taker_fee: float  # frais taker effectifs sur ce marché, en décimal
    book: OrderBook
    off_hours: bool = False  # actif hors séance (prix interne, funding au taux de base)
    tradable: bool = True
    notes: tuple[str, ...] = field(default_factory=tuple)
