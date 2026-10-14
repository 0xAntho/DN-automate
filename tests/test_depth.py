import pytest

from dn_bot.models import BookLevel
from dn_bot.scanner.depth import simulate_fill, slippage_bps, slippage_cost

ASKS = (BookLevel(100.0, 1.0), BookLevel(101.0, 2.0))


def test_fill_within_first_level():
    fill = simulate_fill(ASKS, 50.0)
    assert fill.avg_price == pytest.approx(100.0)
    assert fill.quantity == pytest.approx(0.5)


def test_fill_walks_the_book():
    fill = simulate_fill(ASKS, 302.0)  # 100 $ au premier niveau, 202 $ au second
    assert fill.quantity == pytest.approx(1.0 + 2.0)
    assert fill.avg_price == pytest.approx(302.0 / 3.0)


def test_fill_insufficient_depth():
    assert simulate_fill(ASKS, 1_000.0) is None


def test_slippage_signs():
    fill = simulate_fill(ASKS, 302.0)
    mid = 99.5
    assert slippage_cost(fill, mid, "buy") == pytest.approx(3.0 * (302.0 / 3.0 - mid))
    assert slippage_bps(fill, mid, "buy") > 0
    bids = (BookLevel(99.0, 10.0),)
    sell = simulate_fill(bids, 99.0)
    assert slippage_cost(sell, mid, "sell") == pytest.approx(0.5)
