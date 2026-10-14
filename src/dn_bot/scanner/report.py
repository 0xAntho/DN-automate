"""Affichage texte du classement des opportunités."""

from __future__ import annotations

import math
from datetime import UTC, datetime

from dn_bot.scanner.funding import annualize
from dn_bot.scanner.runner import ScanResult


def _pct(x: float | None) -> str:
    return "  n/d" if x is None else f"{x:+.1%}"


def _usd(x: float) -> str:
    return "n/d" if math.isinf(x) else f"{x:.2f}"


def _hours(x: float) -> str:
    return "∞" if math.isinf(x) else f"{x:.0f} h"


def format_result(result: ScanResult) -> str:
    when = datetime.fromtimestamp(result.timestamp_ms / 1000, UTC).strftime("%Y-%m-%d %H:%M:%S")
    lines = [f"Scan du {when} UTC"]
    header = (
        f"{'':2}{'Paire':<8}{'Long':<12}{'Short':<12}{'APR':>8}{'Coût $':>9}{'H_be':>8}"
        f"  {'24h':>7}{'3j':>7}{'7j':>7}{'30j':>7}  Détail"
    )
    lines.append(header)
    for o in result.opportunities:
        windows = "".join(
            f"{_pct(None if w.spread_hourly is None else annualize(w.spread_hourly)):>7}"
            for w in o.windows
        )
        detail = "; ".join(o.reasons + o.notes) or "ok"
        lines.append(
            f"{'✓ ' if o.passes else '  '}{o.symbol:<8}{o.long_exchange:<12}{o.short_exchange:<12}"
            f"{o.annualized_spread:>8.1%}{_usd(o.total_cost_usd):>9}{_hours(o.breakeven_hours):>8}"
            f"  {windows}  {detail}"
        )
    if not result.opportunities:
        lines.append("  (aucune paire évaluée)")
    for e in result.errors:
        lines.append(f"! {e.exchange} {e.market} : {e.message}")
    return "\n".join(lines)
