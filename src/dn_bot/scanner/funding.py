"""Moyennes de funding sur des fenêtres glissantes (24 h, 3 j, 7 j, 30 j)."""

from __future__ import annotations

from dataclasses import dataclass

from dn_bot.models import FundingPoint

HOUR_MS = 3_600_000
HOURS_PER_YEAR = 24 * 365


def annualize(rate_hourly: float) -> float:
    return rate_hourly * HOURS_PER_YEAR


def window_average(
    points: list[FundingPoint], now_ms: int, window_hours: int, min_coverage: float
) -> float | None:
    """Moyenne des taux horaires sur la fenêtre, ou None si l'historique la couvre trop peu.

    Les deux plateformes paient le funding chaque heure : une fenêtre de N heures contient
    normalement N points.
    """
    start = now_ms - window_hours * HOUR_MS
    rates = [p.rate_hourly for p in points if start < p.time_ms <= now_ms]
    if not rates or len(rates) < min_coverage * window_hours:
        return None
    return sum(rates) / len(rates)


@dataclass(frozen=True)
class WindowSpread:
    hours: int
    # Funding du short moins funding du long ; None = pas assez d'historique.
    spread_hourly: float | None


def window_spreads(
    long_history: list[FundingPoint],
    short_history: list[FundingPoint],
    now_ms: int,
    windows_hours: tuple[int, ...],
    min_coverage: float,
) -> list[WindowSpread]:
    out = []
    for hours in windows_hours:
        long_avg = window_average(long_history, now_ms, hours, min_coverage)
        short_avg = window_average(short_history, now_ms, hours, min_coverage)
        spread = None if long_avg is None or short_avg is None else short_avg - long_avg
        out.append(WindowSpread(hours=hours, spread_hourly=spread))
    return out
