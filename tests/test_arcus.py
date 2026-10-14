import httpx
import pytest

from dn_bot.exchanges.arcus import ArcusReader
from dn_bot.exchanges.base import ExchangeError

MARKETS = {
    "markets": [
        {
            "marketDisplayName": "NVDA-USD",
            "marketId": 7,
            "status": "ONLINE",
            "category": "EQUITIES",
            "markPrice": "190.60",
            "oraclePrice": "190.60",
            "fundingRate": "0.00003",
            "nextFundingRate": "0.00004",
            "nextFundingAt": 1792000800,
            "isOutsideRth": False,
        },
        {
            "marketDisplayName": "TSLA-USD",
            "marketId": 8,
            "status": "ONLINE",
            "category": "EQUITIES",
            "markPrice": "0",
            "fundingRate": "0.0000065",
            "nextFundingRate": "0.0000065",
            "isOutsideRth": True,
        },
        {"marketDisplayName": "AAPL-USD", "marketId": 9, "status": "OFFLINE", "fundingRate": "0"},
    ]
}
FEE_TIERS = {
    "tiers": [
        {
            "level": 0,
            "name": "Base",
            "volume_threshold": 0,
            "maker_fee_ppm": 150,
            "taker_fee_ppm": 450,
        },
        {
            "level": 1,
            "name": "Bronze",
            "volume_threshold": 10**11,
            "maker_fee_ppm": 120,
            "taker_fee_ppm": 400,
        },
    ]
}
BOOK = {
    "bids": [["190.50", "5"], ["190.40", "10"]],
    "asks": [["190.70", "5"], ["190.80", "10"]],
    "lastSequenceId": 1,
    "globalSequenceId": 1,
    "timestamp": 1_792_000_000_000_000,
}


def make_reader(handler, **kwargs):
    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return ArcusReader(client=client, **kwargs)


def default_handler(request):
    path = request.url.path
    if path == "/v1/markets":
        return httpx.Response(200, json=MARKETS)
    if path == "/v1/feetiers":
        return httpx.Response(200, json=FEE_TIERS)
    if path.startswith("/v1/l2OrderBook/"):
        assert request.url.params["nLevels"] == "100"
        return httpx.Response(200, json=BOOK)
    raise AssertionError(path)


async def test_snapshots():
    reader = make_reader(default_handler)
    snaps = await reader.snapshots(["NVDA-USD", "TSLA-USD", "AAPL-USD", "MSFT-USD"])

    nvda = snaps["NVDA-USD"]
    assert nvda.funding_rate_hourly == pytest.approx(0.00004)  # prévision nextFundingRate
    assert nvda.taker_fee == pytest.approx(450 / 1_000_000)
    assert nvda.mark_price == pytest.approx(190.60)
    assert nvda.book.best_bid == pytest.approx(190.50)
    assert nvda.book.timestamp_ms == 1_792_000_000_000
    assert not nvda.off_hours and nvda.tradable

    tsla = snaps["TSLA-USD"]
    assert tsla.off_hours and tsla.notes == ("hors séance",)
    assert tsla.mark_price == pytest.approx(190.60)  # markPrice "0" : on prend le mid du carnet

    assert not snaps["AAPL-USD"].tradable
    assert isinstance(snaps["MSFT-USD"], ExchangeError)


async def test_fee_tier_level_and_fallback(monkeypatch):
    reader = make_reader(default_handler, fee_tier_level=1)
    assert await reader.taker_fee() == pytest.approx(400 / 1_000_000)

    monkeypatch.setattr("asyncio.sleep", _no_sleep)

    def failing(request):
        return httpx.Response(503)

    reader = make_reader(failing, fallback_taker_fee=0.0007)
    assert await reader.taker_fee() == pytest.approx(0.0007)


async def test_funding_history_uses_microseconds_and_paginates():
    seen = []

    def handler(request):
        params = request.url.params
        assert params["market"] == "NVDA-USD"
        seen.append((int(params["from"]), int(params["to"])))
        lo, hi = seen[-1]
        # Réponse triée par date décroissante, 1 000 lignes par page.
        grid = range(end_ms * 1000, start_ms * 1000 - 1, -3_600_000_000)
        times = [t for t in grid if lo <= t <= hi][:1000]
        rows = [
            {"marketId": 7, "marketDisplayName": "NVDA-USD", "fundingRate": "0.00001", "time": t}
            for t in times
        ]
        return httpx.Response(200, json={"fundingRates": rows, "total": len(rows)})

    end_ms = 1_792_000_000_000
    start_ms = end_ms - 1500 * 3_600_000
    points = await make_reader(handler).funding_history("NVDA-USD", start_ms, end_ms)
    assert seen[0] == (start_ms * 1000, end_ms * 1000)
    assert len(seen) == 2
    assert len(points) == 1501
    assert points[0].time_ms == start_ms and points[-1].time_ms == end_ms


async def _no_sleep(_):
    return None
