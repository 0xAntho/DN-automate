"""Calcul et classement des opportunités delta neutre entre deux plateformes.

Pour une paire et un couple de plateformes :
  1. on est long là où le funding horaire est le plus bas, short là où il est le plus haut ;
  2. le gain horaire attendu vaut notionnel x (funding short - funding long) ;
  3. le coût d'aller-retour additionne les frais taker des 4 ordres, le glissement d'entrée
     simulé dans les carnets, le glissement de sortie estimé sur les carnets actuels (majoré
     d'une marge de sécurité) et l'écart de prix entre plateformes s'il est contre nous ;
  4. le temps de remboursement (H_be) = coût / gain horaire sert à classer, sans maximum.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from dn_bot.config import Thresholds
from dn_bot.models import FundingPoint, MarketSnapshot
from dn_bot.scanner.depth import simulate_fill, slippage_bps, slippage_cost
from dn_bot.scanner.funding import WindowSpread, annualize, window_spreads


@dataclass(frozen=True)
class Opportunity:
    symbol: str
    long_exchange: str
    short_exchange: str
    long_market: str
    short_market: str
    funding_long_hourly: float
    funding_short_hourly: float
    notional_usd: float
    fees_usd: float
    entry_slippage_usd: float
    exit_slippage_usd: float
    basis_usd: float  # positif = en notre faveur (on est short sur la plateforme la plus chère)
    total_cost_usd: float
    entry_slippage_bps_long: float | None
    entry_slippage_bps_short: float | None
    windows: tuple[WindowSpread, ...]
    off_hours: bool
    reasons: tuple[str, ...]  # critères non remplis ; vide = l'opportunité passe
    notes: tuple[str, ...] = field(default_factory=tuple)

    @property
    def spread_hourly(self) -> float:
        return self.funding_short_hourly - self.funding_long_hourly

    @property
    def annualized_spread(self) -> float:
        return annualize(self.spread_hourly)

    @property
    def gain_per_hour_usd(self) -> float:
        return self.notional_usd * self.spread_hourly

    @property
    def breakeven_hours(self) -> float:
        gain = self.gain_per_hour_usd
        if gain <= 0 or math.isinf(self.total_cost_usd):
            return math.inf
        return max(self.total_cost_usd, 0.0) / gain

    @property
    def passes(self) -> bool:
        return not self.reasons


def evaluate(
    symbol: str,
    a: MarketSnapshot,
    b: MarketSnapshot,
    history: dict[str, list[FundingPoint]],
    notional_usd: float,
    thresholds: Thresholds,
    now_ms: int,
) -> Opportunity:
    """Évalue le couple (a, b) ; `history` donne l'historique de funding par plateforme."""
    long, short = (a, b) if a.funding_rate_hourly <= b.funding_rate_hourly else (b, a)
    reasons: list[str] = []
    off_hours = long.off_hours or short.off_hours

    for snap in (long, short):
        if not snap.tradable:
            reasons.append(f"{snap.exchange} : marché fermé ou retiré")

    # Coûts : frais des 4 ordres taker (entrée et sortie sur chaque jambe).
    fees = 2 * notional_usd * (long.taker_fee + short.taker_fee)

    mid_long, mid_short = long.book.mid, short.book.mid
    entry_slip = exit_slip = basis = math.inf
    bps_long = bps_short = None
    if mid_long is None or mid_short is None:
        reasons.append("carnet vide sur une plateforme")
    else:
        entry_long = simulate_fill(long.book.asks, notional_usd)
        entry_short = simulate_fill(short.book.bids, notional_usd)
        exit_long = simulate_fill(long.book.bids, notional_usd)
        exit_short = simulate_fill(short.book.asks, notional_usd)
        if None in (entry_long, entry_short, exit_long, exit_short):
            reasons.append("profondeur insuffisante pour la taille visée")
        else:
            bps_long = slippage_bps(entry_long, mid_long, "buy")
            bps_short = slippage_bps(entry_short, mid_short, "sell")
            entry_slip = slippage_cost(entry_long, mid_long, "buy") + slippage_cost(
                entry_short, mid_short, "sell"
            )
            margin = (
                thresholds.exit_safety_margin_off_hours
                if off_hours
                else thresholds.exit_safety_margin
            )
            exit_slip = (
                slippage_cost(exit_long, mid_long, "sell")
                + slippage_cost(exit_short, mid_short, "buy")
            ) * (1 + margin)
            basis = notional_usd * (mid_short - mid_long) / ((mid_short + mid_long) / 2)
            worst = max(bps_long, bps_short)
            if worst > thresholds.max_entry_slippage_bps:
                reasons.append(
                    f"glissement d'entrée {worst:.1f} bps > {thresholds.max_entry_slippage_bps:g}"
                )

    if math.isinf(basis):
        total_cost = math.inf
    else:
        basis_effect = basis if (basis < 0 or thresholds.count_favorable_basis) else 0.0
        total_cost = fees + entry_slip + exit_slip - basis_effect

    # Funding actuel.
    spread = short.funding_rate_hourly - long.funding_rate_hourly
    if spread <= 0:
        reasons.append("écart de funding nul")
    elif annualize(spread) < thresholds.min_annualized_spread:
        reasons.append(
            f"écart annualisé {annualize(spread):.1%} < {thresholds.min_annualized_spread:.0%}"
        )

    # Stabilité : même sens et au-dessus du seuil sur chaque fenêtre disponible.
    windows = window_spreads(
        history.get(long.exchange, []),
        history.get(short.exchange, []),
        now_ms,
        thresholds.stability_windows_hours,
        thresholds.min_window_coverage,
    )
    available = [w for w in windows if w.spread_hourly is not None]
    if not available:
        reasons.append("historique de funding insuffisant")
    for w in available:
        if annualize(w.spread_hourly) < thresholds.min_annualized_spread:
            reasons.append(f"écart instable sur {_window_label(w.hours)}")

    return Opportunity(
        symbol=symbol,
        long_exchange=long.exchange,
        short_exchange=short.exchange,
        long_market=long.market,
        short_market=short.market,
        funding_long_hourly=long.funding_rate_hourly,
        funding_short_hourly=short.funding_rate_hourly,
        notional_usd=notional_usd,
        fees_usd=fees,
        entry_slippage_usd=entry_slip,
        exit_slippage_usd=exit_slip,
        basis_usd=basis,
        total_cost_usd=total_cost,
        entry_slippage_bps_long=bps_long,
        entry_slippage_bps_short=bps_short,
        windows=tuple(windows),
        off_hours=off_hours,
        reasons=tuple(reasons),
        notes=tuple(f"{s.exchange} : {n}" for s in (long, short) for n in s.notes),
    )


def rank(opportunities: list[Opportunity]) -> list[Opportunity]:
    """Celles qui passent d'abord, puis par temps de remboursement croissant."""
    return sorted(
        opportunities,
        key=lambda o: (not o.passes, o.breakeven_hours, -o.annualized_spread),
    )


def _window_label(hours: int) -> str:
    return f"{hours // 24} j" if hours % 24 == 0 and hours > 24 else f"{hours} h"
