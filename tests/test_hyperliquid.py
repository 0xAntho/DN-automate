import json

import httpx
import pytest

from dn_bot.exchanges.base import ExchangeError
from dn_bot.exchanges.hyperliquid import HyperliquidReader

META_XYZ = [
    {
        "universe": [
            {"name": "xyz:NVDA", "szDecimals": 3, "maxLeverage": 20, "growthMode": "enabled"},
            {"name": "xyz:TSLA", "szDecimals": 3, "maxLeverage": 10},
        ]
    },
    [
        {"funding": "0.0000125", "markPx": "190.5", "oraclePx": "190.4", "openInterest": "1"},
        {"funding": "-0.00002", "markPx": "250.0", "oraclePx": "250.1", "openInterest": "1"},
    ],
]


def l2(coin, mid):
    return {
        "coin": coin,
        "time": 1_792_000_000_000,
        "levels": [
            [
                {"px": str(mid - 0.1), "sz": "10", "n": 1},
                {"px": str(mid - 0.2), "sz": "20", "n": 2},
            ],
            [
                {"px": str(mid + 0.1), "sz": "10", "n": 1},
                {"px": str(mid + 0.2), "sz": "20", "n": 2},
            ],
        ],
    }


def make_reader(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return HyperliquidReader(
        taker_fee=0.0004275, hip3_fee_multiplier={"xyz": 2.0}, client=client, **kwargs
    )


async def test_snapshots_hip3_fees_and_growth_mode():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        if body["type"] == "metaAndAssetCtxs":
            assert body["dex"] == "xyz"
            return httpx.Response(200, json=META_XYZ)
        if body["type"] == "l2Book":
            return httpx.Response(200, json=l2(body["coin"], 190.5))
        raise AssertionError(body)

    reader = make_reader(handler)
    snaps = await reader.snapshots(["xyz:NVDA", "xyz:TSLA", "xyz:NOPE"])

    nvda, tsla = snaps["xyz:NVDA"], snaps["xyz:TSLA"]
    assert nvda.funding_rate_hourly == pytest.approx(0.0000125)
    assert nvda.mark_price == pytest.approx(190.5)
    assert nvda.taker_fee == pytest.approx(0.0004275 * 2 * 0.1)  # HIP-3 x2, growth mode -90 %
    assert nvda.notes == ("growth mode",)
    assert tsla.taker_fee == pytest.approx(0.0004275 * 2)
    assert tsla.book.best_bid == pytest.approx(190.4)
    assert tsla.book.best_ask == pytest.approx(190.6)
    assert isinstance(snaps["xyz:NOPE"], ExchangeError)
    # Un seul appel metaAndAssetCtxs pour tout le dex.
    assert sum(c["type"] == "metaAndAssetCtxs" for c in calls) == 1


async def test_meta_failure_is_reported_per_market(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    def handler(request):
        return httpx.Response(500)

    snaps = await make_reader(handler).snapshots(["xyz:NVDA"])
    assert isinstance(snaps["xyz:NVDA"], ExchangeError)


async def test_funding_history_paginates():
    start, end = 0, 10_000_000
    pages = []

    def handler(request):
        body = json.loads(request.content)
        assert body["type"] == "fundingHistory"
        pages.append(body["startTime"])
        if body["startTime"] == start:
            rows = [{"coin": "xyz:NVDA", "fundingRate": "0.00001", "time": i} for i in range(500)]
        else:
            assert body["startTime"] == 500
            rows = [
                {"coin": "xyz:NVDA", "fundingRate": "0.00002", "time": 500 + i} for i in range(3)
            ]
        return httpx.Response(200, json=rows)

    points = await make_reader(handler).funding_history("xyz:NVDA", start, end)
    assert pages == [0, 500]
    assert len(points) == 503
    assert points[-1].rate_hourly == pytest.approx(0.00002)


async def test_retries_on_429(monkeypatch):
    monkeypatch.setattr("asyncio.sleep", _no_sleep)
    attempts = []

    def handler(request):
        attempts.append(1)
        if len(attempts) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(200, json=l2("xyz:NVDA", 100.0))

    book = await make_reader(handler).order_book("xyz:NVDA")
    assert len(attempts) == 2
    assert book.mid == pytest.approx(100.0)


async def _no_sleep(_):
    return None
