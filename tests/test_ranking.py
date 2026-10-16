import math

import pytest

from dn_bot.config import Thresholds
from dn_bot.scanner.ranking import evaluate, rank
from tests.conftest import NOW_MS, flat_history, snapshot

N = 300.0
T = Thresholds(exit_safety_margin=0.0)


def history(long_rate, short_rate, hours=720):
    return {"hl": flat_history(long_rate, hours), "ar": flat_history(short_rate, hours)}


def test_direction_and_breakeven():
    # 0,01 %/h d'écart : 0,03 $/h sur 300 $ ; coût connu à l'avance.
    a = snapshot("hl", funding=0.00001, fee=0.0005)
    b = snapshot("ar", funding=0.00011, fee=0.0005)
    opp = evaluate("TEST", a, b, history(0.00001, 0.00011), N, T, NOW_MS)
    assert (opp.long_exchange, opp.short_exchange) == ("hl", "ar")
    assert opp.spread_hourly == pytest.approx(0.0001)
    assert opp.gain_per_hour_usd == pytest.approx(0.03)
    assert opp.fees_usd == pytest.approx(2 * N * 0.001)  # 4 ordres taker à 0,05 %
    # Carnet à 0,05 $ du mid sur 100 $ : 5 bps de glissement par ordre, 4 ordres.
    assert opp.entry_slippage_usd == pytest.approx(2 * N * 0.0005)
    assert opp.exit_slippage_usd == pytest.approx(2 * N * 0.0005)
    assert opp.basis_usd == pytest.approx(0.0)
    assert opp.total_cost_usd == pytest.approx(0.6 + 0.6)
    assert opp.breakeven_hours == pytest.approx(1.2 / 0.03)
    assert opp.passes, opp.reasons


def test_direction_flips_with_funding():
    a = snapshot("hl", funding=0.0002)
    b = snapshot("ar", funding=-0.0001)
    opp = evaluate("TEST", a, b, {}, N, T, NOW_MS)
    assert (opp.long_exchange, opp.short_exchange) == ("ar", "hl")
    assert opp.spread_hourly == pytest.approx(0.0003)


def test_rejects_low_spread():
    a = snapshot("hl", funding=0.00001)
    b = snapshot("ar", funding=0.00002)  # 8,8 % annualisé < 15 %
    opp = evaluate("TEST", a, b, history(0.00001, 0.00002), N, T, NOW_MS)
    assert not opp.passes
    assert any("annualisé" in r for r in opp.reasons)


def test_zero_spread_is_infinite_breakeven():
    a = snapshot("hl", funding=0.0001)
    b = snapshot("ar", funding=0.0001)
    opp = evaluate("TEST", a, b, history(0.0001, 0.0001), N, T, NOW_MS)
    assert math.isinf(opp.breakeven_hours)
    assert "écart de funding nul" in opp.reasons


def test_rejects_unstable_history():
    a = snapshot("hl", funding=0.00001)
    b = snapshot("ar", funding=0.00011)
    hist = history(0.00011, 0.00001)  # en moyenne, l'écart était dans l'autre sens
    opp = evaluate("TEST", a, b, hist, N, T, NOW_MS)
    assert any("instable" in r for r in opp.reasons)


def test_rejects_without_history():
    a = snapshot("hl", funding=0.00001)
    b = snapshot("ar", funding=0.00011)
    opp = evaluate("TEST", a, b, {}, N, T, NOW_MS)
    assert "historique de funding insuffisant" in opp.reasons


def test_uses_available_windows_only():
    a = snapshot("hl", funding=0.00001)
    b = snapshot("ar", funding=0.00011)
    hist = {"hl": flat_history(0.00001, 720), "ar": flat_history(0.00011, 100)}
    opp = evaluate("TEST", a, b, hist, N, T, NOW_MS)
    assert opp.passes, opp.reasons
    assert [w.spread_hourly is None for w in opp.windows] == [False, False, True, True]


def test_rejects_thin_book():
    a = snapshot("hl", funding=0.00001, size=0.5, levels=2)  # ~100 $ de profondeur
    b = snapshot("ar", funding=0.00011)
    opp = evaluate("TEST", a, b, history(0.00001, 0.00011), N, T, NOW_MS)
    assert "profondeur insuffisante pour la taille visée" in opp.reasons
    assert math.isinf(opp.breakeven_hours)


def test_rejects_wide_spread():
    a = snapshot("hl", funding=0.00001, half_spread=0.5)  # 50 bps
    b = snapshot("ar", funding=0.00011)
    opp = evaluate("TEST", a, b, history(0.00001, 0.00011), N, T, NOW_MS)
    assert any("glissement" in r for r in opp.reasons)


def test_basis_in_our_favour_lowers_cost():
    a = snapshot("hl", funding=0.00001, mid=100.0)
    b = snapshot("ar", funding=0.00011, mid=100.2)  # on est short sur la plus chère
    opp = evaluate("TEST", a, b, history(0.00001, 0.00011), N, T, NOW_MS)
    assert opp.basis_usd > 0
    no_basis = evaluate(
        "TEST",
        a,
        b,
        history(0.00001, 0.00011),
        N,
        Thresholds(exit_safety_margin=0.0, count_favorable_basis=False),
        NOW_MS,
    )
    assert opp.total_cost_usd == pytest.approx(no_basis.total_cost_usd - opp.basis_usd)


def test_basis_against_us_adds_cost():
    a = snapshot("hl", funding=0.00001, mid=100.2)  # on est long sur la plus chère
    b = snapshot("ar", funding=0.00011, mid=100.0)
    opp = evaluate(
        "TEST",
        a,
        b,
        history(0.00001, 0.00011),
        N,
        Thresholds(exit_safety_margin=0.0, count_favorable_basis=False),
        NOW_MS,
    )
    assert opp.basis_usd < 0
    expected = opp.fees_usd + opp.entry_slippage_usd + opp.exit_slippage_usd - opp.basis_usd
    assert opp.total_cost_usd == pytest.approx(expected)


def test_off_hours_widens_exit_margin():
    t = Thresholds(exit_safety_margin=0.25, exit_safety_margin_off_hours=1.0)
    a = snapshot("hl", funding=0.00001)
    b_in = snapshot("ar", funding=0.00011)
    b_off = snapshot("ar", funding=0.00011, off_hours=True)
    hist = history(0.00001, 0.00011)
    during = evaluate("TEST", a, b_in, hist, N, t, NOW_MS)
    after = evaluate("TEST", a, b_off, hist, N, t, NOW_MS)
    assert after.off_hours
    assert after.exit_slippage_usd == pytest.approx(during.exit_slippage_usd / 1.25 * 2.0)


def test_rank_orders_passing_by_breakeven():
    hist = history(0.0, 0.0003)
    fast = evaluate("FAST", snapshot("hl", 0.0), snapshot("ar", 0.0003), hist, N, T, NOW_MS)
    slow = evaluate(
        "SLOW", snapshot("hl", 0.0), snapshot("ar", 0.0001), history(0.0, 0.0001), N, T, NOW_MS
    )
    failing = evaluate("FAIL", snapshot("hl", 0.0), snapshot("ar", 0.0003), {}, N, T, NOW_MS)
    assert [o.symbol for o in rank([failing, slow, fast])] == ["FAST", "SLOW", "FAIL"]
