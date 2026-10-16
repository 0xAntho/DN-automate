import pytest

from dn_bot.models import FundingPoint
from dn_bot.scanner.funding import annualize, window_average, window_spreads
from tests.conftest import HOUR_MS, NOW_MS, flat_history


def test_annualize():
    assert annualize(0.0001) == pytest.approx(0.876)


def test_window_average_uses_only_window():
    points = flat_history(0.0001, hours=24) + [FundingPoint(NOW_MS - 30 * HOUR_MS, 1.0)]
    assert window_average(points, NOW_MS, 24, 0.9) == pytest.approx(0.0001)


def test_window_average_requires_coverage():
    points = flat_history(0.0001, hours=20)
    assert window_average(points, NOW_MS, 24, 0.9) is None
    assert window_average(points, NOW_MS, 24, 0.8) == pytest.approx(0.0001)


def test_window_spreads_partial_history():
    # Arcus récent : 5 jours d'historique seulement, les fenêtres 7 j et 30 j manquent.
    long_h = flat_history(0.00001, hours=120)
    short_h = flat_history(0.00005, hours=720)
    spreads = window_spreads(long_h, short_h, NOW_MS, (24, 72, 168, 720), 0.9)
    assert [s.hours for s in spreads] == [24, 72, 168, 720]
    assert spreads[0].spread_hourly == pytest.approx(0.00004)
    assert spreads[1].spread_hourly == pytest.approx(0.00004)
    assert spreads[2].spread_hourly is None
    assert spreads[3].spread_hourly is None
