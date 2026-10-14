"""Simulation de remplissage dans un carnet pour une taille en USD."""

from __future__ import annotations

from dataclasses import dataclass

from dn_bot.models import BookLevel


@dataclass(frozen=True)
class Fill:
    avg_price: float
    quantity: float
    notional: float


def simulate_fill(levels: tuple[BookLevel, ...], notional_usd: float) -> Fill | None:
    """Remplit `notional_usd` en consommant les niveaux dans l'ordre.

    Rend None si le carnet visible ne suffit pas à remplir toute la taille.
    """
    if notional_usd <= 0:
        raise ValueError("la taille doit être positive")
    remaining = notional_usd
    quantity = 0.0
    for level in levels:
        if level.price <= 0 or level.size <= 0:
            continue
        level_notional = level.price * level.size
        take = min(remaining, level_notional)
        quantity += take / level.price
        remaining -= take
        if remaining <= 1e-9:
            return Fill(avg_price=notional_usd / quantity, quantity=quantity, notional=notional_usd)
    return None


def slippage_cost(fill: Fill, mid: float, side: str) -> float:
    """Coût en USD par rapport au mid : positif si on paie plus (achat) ou reçoit moins (vente)."""
    if side == "buy":
        return fill.quantity * (fill.avg_price - mid)
    if side == "sell":
        return fill.quantity * (mid - fill.avg_price)
    raise ValueError(f"côté inconnu : {side}")


def slippage_bps(fill: Fill, mid: float, side: str) -> float:
    return slippage_cost(fill, mid, side) / fill.notional * 10_000
