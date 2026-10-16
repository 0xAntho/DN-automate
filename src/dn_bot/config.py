"""Chargement de la configuration (fichier TOML, voir config.example.toml)."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Pair:
    symbol: str
    markets: dict[str, str]  # plateforme -> nom du marché sur cette plateforme


@dataclass(frozen=True)
class Thresholds:
    min_annualized_spread: float = 0.15
    max_entry_slippage_bps: float = 15.0
    stability_windows_hours: tuple[int, ...] = (24, 72, 168, 720)
    min_window_coverage: float = 0.9
    exit_safety_margin: float = 0.25
    exit_safety_margin_off_hours: float = 1.0
    count_favorable_basis: bool = True


@dataclass(frozen=True)
class Config:
    pairs: tuple[Pair, ...]
    exchanges: dict[str, dict[str, Any]]
    thresholds: Thresholds = field(default_factory=Thresholds)
    margin_per_leg_usd: float = 100.0
    leverage: float = 3.0
    interval_seconds: float = 60.0
    history_refresh_seconds: float = 900.0
    database_path: str = ""

    @property
    def notional_per_leg_usd(self) -> float:
        return self.margin_per_leg_usd * self.leverage


def load_config(path: str | Path) -> Config:
    with open(path, "rb") as f:
        return parse_config(tomllib.load(f))


def parse_config(raw: dict[str, Any]) -> Config:
    exchanges = dict(raw.get("exchanges", {}))
    if not exchanges:
        raise ValueError("aucune plateforme dans [exchanges]")

    pairs = []
    for entry in raw.get("pairs", []):
        entry = dict(entry)
        symbol = entry.pop("symbol")
        markets = {ex: str(name) for ex, name in entry.items() if ex in exchanges}
        unknown = set(entry) - set(exchanges)
        if unknown:
            raise ValueError(f"paire {symbol} : plateformes inconnues {sorted(unknown)}")
        if len(markets) < 2:
            raise ValueError(f"paire {symbol} : il faut au moins deux plateformes")
        pairs.append(Pair(symbol=symbol, markets=markets))
    if not pairs:
        raise ValueError("aucune paire dans [[pairs]]")

    t = dict(raw.get("thresholds", {}))
    if "stability_windows_hours" in t:
        t["stability_windows_hours"] = tuple(int(h) for h in t["stability_windows_hours"])
    thresholds = Thresholds(**t)

    scanner = raw.get("scanner", {})
    sizing = raw.get("sizing", {})
    return Config(
        pairs=tuple(pairs),
        exchanges=exchanges,
        thresholds=thresholds,
        margin_per_leg_usd=float(sizing.get("margin_per_leg_usd", 100.0)),
        leverage=float(sizing.get("leverage", 3.0)),
        interval_seconds=float(scanner.get("interval_seconds", 60.0)),
        history_refresh_seconds=float(scanner.get("history_refresh_seconds", 900.0)),
        database_path=str(scanner.get("database_path", "")),
    )
