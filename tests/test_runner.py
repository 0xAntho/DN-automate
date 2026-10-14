import sqlite3
from pathlib import Path

import pytest

from dn_bot.config import load_config, parse_config
from dn_bot.exchanges.base import ExchangeError
from dn_bot.scanner.report import format_result
from dn_bot.scanner.runner import Scanner
from dn_bot.storage import Storage
from tests.conftest import NOW_MS, flat_history, snapshot

ROOT = Path(__file__).resolve().parents[1]


class FakeReader:
    def __init__(self, name, funding, missing=(), history_rate=None):
        self.name = name
        self.funding = funding
        self.missing = set(missing)
        self.history_rate = funding if history_rate is None else history_rate
        self.history_calls = 0

    async def snapshots(self, markets):
        out = {}
        for m in markets:
            if m in self.missing:
                out[m] = ExchangeError(f"{m} absent")
            else:
                snap = snapshot(self.name, self.funding)
                out[m] = snap.__class__(**{**snap.__dict__, "market": m})
        return out

    async def funding_history(self, market, start_ms, end_ms):
        self.history_calls += 1
        return flat_history(self.history_rate, 720, end_ms)

    async def aclose(self):
        pass


def config(**scanner):
    return parse_config(
        {
            "scanner": scanner,
            "exchanges": {"hyperliquid": {}, "arcus": {}},
            "pairs": [
                {"symbol": "NVDA", "hyperliquid": "xyz:NVDA", "arcus": "NVDA-USD"},
                {"symbol": "TSLA", "hyperliquid": "xyz:TSLA", "arcus": "TSLA-USD"},
            ],
        }
    )


async def test_scan_once_end_to_end(tmp_path):
    readers = {
        "hyperliquid": FakeReader("hyperliquid", 0.00001),
        "arcus": FakeReader("arcus", 0.00011, missing={"TSLA-USD"}),
    }
    storage = Storage(str(tmp_path / "scan.db"))
    scanner = Scanner(config(), readers, storage, clock=lambda: NOW_MS / 1000)
    result = await scanner.scan_once()

    assert [o.symbol for o in result.opportunities] == ["NVDA"]
    opp = result.opportunities[0]
    assert (opp.long_exchange, opp.short_exchange) == ("hyperliquid", "arcus")
    assert opp.notional_usd == pytest.approx(300.0)
    assert opp.passes, opp.reasons
    assert [(e.exchange, e.market) for e in result.errors] == [("arcus", "TSLA-USD")]

    text = format_result(result)
    assert "NVDA" in text and "TSLA-USD absent" in text

    storage.close()
    conn = sqlite3.connect(tmp_path / "scan.db")
    assert conn.execute("SELECT COUNT(*) FROM opportunities").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM market_snapshots").fetchone()[0] == 3


async def test_history_is_cached():
    now = [NOW_MS / 1000]
    readers = {
        "hyperliquid": FakeReader("hyperliquid", 0.00001),
        "arcus": FakeReader("arcus", 0.00011),
    }
    scanner = Scanner(config(history_refresh_seconds=900), readers, clock=lambda: now[0])
    await scanner.scan_once()
    await scanner.scan_once()
    assert readers["arcus"].history_calls == 2  # un appel par marché, pas de rechargement
    now[0] += 901
    await scanner.scan_once()
    assert readers["arcus"].history_calls == 4


def test_example_config_parses():
    cfg = load_config(ROOT / "config.example.toml")
    assert cfg.notional_per_leg_usd == pytest.approx(300.0)
    assert {p.symbol for p in cfg.pairs} == {"NVDA", "TSLA", "AAPL"}
    assert cfg.pairs[0].markets == {"hyperliquid": "xyz:NVDA", "arcus": "NVDA-USD"}
    assert cfg.thresholds.stability_windows_hours == (24, 72, 168, 720)


def test_config_rejects_unknown_exchange():
    with pytest.raises(ValueError, match="inconnues"):
        parse_config(
            {
                "exchanges": {"hyperliquid": {}, "arcus": {}},
                "pairs": [{"symbol": "X", "hyperliquid": "X", "variational": "X"}],
            }
        )
