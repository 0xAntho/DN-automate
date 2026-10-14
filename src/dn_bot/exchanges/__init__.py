"""Adaptateurs d'exchange : une interface identique par plateforme."""

from dn_bot.exchanges.base import ExchangeError, ExchangeReader

__all__ = ["ExchangeError", "ExchangeReader", "build_readers"]


def build_readers(exchanges: dict, client=None) -> dict[str, ExchangeReader]:
    """Instancie un adaptateur par plateforme configurée."""
    from dn_bot.exchanges.arcus import ArcusReader
    from dn_bot.exchanges.hyperliquid import HyperliquidReader

    known = {"hyperliquid": HyperliquidReader, "arcus": ArcusReader}
    readers: dict[str, ExchangeReader] = {}
    for name, cfg in exchanges.items():
        if name not in known:
            raise ValueError(f"plateforme non prise en charge : {name}")
        readers[name] = known[name].from_config(cfg, client=client)
    return readers
