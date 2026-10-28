import math

import pytest
from pytest import approx

from cockpit_core.devig import devig, devig_partial, estimator_probs, shin_from_implied
from cockpit_core.odds import Method, implied

MULTIPLICATIVE, POWER, SHIN = Method.MULTIPLICATIVE, Method.POWER, Method.SHIN


def test_multiplicative_two_way():
    assert devig([1.9, 1.9], MULTIPLICATIVE) == approx([0.5, 0.5])


def test_multiplicative_three_way():
    assert devig([2.0, 3.0, 5.0], MULTIPLICATIVE) == approx([0.48387, 0.32258, 0.19355], abs=1e-5)


def test_power_three_way():
    assert devig([2.0, 3.0, 5.0], POWER) == approx([0.4888, 0.3215, 0.1897], abs=5e-4)


def test_power_and_shin_shade_longshots_more():
    m, p, s = (devig([2.0, 3.0, 5.0], x) for x in (MULTIPLICATIVE, POWER, SHIN))
    assert p[2] < m[2] and s[2] < m[2] and p[0] > m[0] and sum(s) == approx(1.0, abs=1e-9)


def test_shin_symmetric_two_way():
    assert devig([1.9, 1.9], SHIN) == approx([0.5, 0.5])


def test_shin_without_overround_returns_implied():
    assert devig([2.0, 2.0], SHIN) == approx([0.5, 0.5])


def test_topn_overround_normalises_to_n():
    assert devig([1.4, 1.6, 2.2, 3.0], MULTIPLICATIVE, 2) == approx([0.6716, 0.5876, 0.4274, 0.3134], abs=1e-4)


def test_topn_underround_normalises_to_n():
    assert devig([1.5, 1.8, 2.5, 4.0], MULTIPLICATIVE, 2) == approx([0.7122, 0.5935, 0.4273, 0.2671], abs=1e-4)


def test_topn_cap_binds():
    assert devig([1.001, 4, 4, 4], MULTIPLICATIVE, 2) == approx([0.995, 0.335, 0.335, 0.335], abs=1e-4)


def test_shin_rejects_topn():
    with pytest.raises(ValueError):
        devig([2.0, 2.0, 2.0], SHIN, 2)


def test_bad_odds_rejected():
    with pytest.raises(ValueError):
        implied(1.0)
    with pytest.raises(ValueError):
        implied(None)


def test_implied_is_reciprocal():
    assert implied(4.0) == approx(0.25)


def test_empty_odds_rejected():
    with pytest.raises(ValueError):
        devig([], MULTIPLICATIVE)


@pytest.mark.parametrize("bad", [1.0, 0.5, None])
def test_devig_rejects_bad_odds(bad):
    with pytest.raises(ValueError):
        devig([2.0, bad], MULTIPLICATIVE)


@pytest.mark.parametrize("total", [0, -1, 4, 5])
def test_expected_total_out_of_range_rejected(total):
    with pytest.raises(ValueError):
        devig([2.0, 3.0, 4.0, 5.0], MULTIPLICATIVE, total)


def test_multiplicative_infeasible_cap_rejected():
    # three runners can hold at most 3 * 0.995 = 2.985, so a total of 2.99 is infeasible
    with pytest.raises(ValueError):
        devig([2.0, 3.0, 5.0], MULTIPLICATIVE, 2.99)


def test_power_topn_sums_to_total_and_keeps_order():
    out = devig([1.4, 1.6, 2.2, 3.0], POWER, 2)
    assert sum(out) == approx(2.0, abs=1e-9)
    assert out == sorted(out, reverse=True)


def test_power_root_outside_bracket_rejected():
    with pytest.raises(ValueError):
        devig([1.0001, 1.0001], POWER, 1.999999999)


def test_shin_unequal_three_way_sums_to_one():
    out = devig([2.0, 3.0, 5.0], SHIN)
    assert sum(out) == approx(1.0, abs=1e-9)
    assert all(0 < p < 1 for p in out)


def test_shin_unequal_three_way_values():
    assert devig([2.0, 3.0, 5.0], SHIN) == approx([0.4876, 0.3223, 0.1901], abs=5e-4)


def test_shin_from_implied_matches_shin_on_odds_and_validates():
    # Shin on implied probabilities directly. 2.0/3.0/5.0 -> implied 0.5, 1/3, 0.2.
    assert shin_from_implied([0.5, 1 / 3, 0.2]) == approx(devig([2.0, 3.0, 5.0], SHIN), abs=1e-12)
    # [0.5, 0.3, 0.25] (booksum 1.05): z = 0.025064 -> 0.481495, 0.283934, 0.234571 (sum 1).
    assert shin_from_implied([0.5, 0.3, 0.25]) == approx([0.481495, 0.283934, 0.234571], abs=1e-6)
    for bad in ([], [0.5, 0.0], [0.5, 1.0], [1.2, 0.1], [0.5, -0.1], [0.5, float("nan")], [0.5, float("inf")]):
        with pytest.raises(ValueError):
            shin_from_implied(bad)


def test_shin_underround_returns_multiplicative():
    odds = [2.2, 3.5, 6.0]  # implied sums to ~0.908, unequal so the result is discriminating
    out = devig(odds, SHIN)
    assert out == approx(devig(odds, MULTIPLICATIVE))
    assert sum(out) == approx(1.0)
    assert out[0] != approx(0.5)


def test_shin_no_overround_unequal_returns_implied():
    assert devig([2.0, 4.0, 4.0], SHIN) == approx([0.5, 0.25, 0.25])


def test_multiplicative_cap_cascades_to_a_second_pass():
    # Pass 1 caps only the 1.01 runner (1.15 scales to ~0.98); rescaling the rest then pushes
    # 1.15 over the cap, so a second pass must cap it too before the 5.0 runners settle.
    out = devig([1.01, 1.15, 5, 5, 5, 5], MULTIPLICATIVE, 3)
    assert out == approx([0.995, 0.995, 0.2525, 0.2525, 0.2525, 0.2525], abs=1e-4)
    assert sum(out) == approx(3.0)


def test_order_preserved():
    assert devig([5.0, 2.0, 3.0], MULTIPLICATIVE) == approx([0.19355, 0.48387, 0.32258], abs=1e-5)


# Partial-book de-vig, ported from GolfProject (Rulings 71, 76, 77, 83, 89a). Synthetic odds; the pinned
# numbers were computed from golf's own code.
A = [3.0, 4.0, 5.0, 8.0, 10.0, 12.0, 15.0, 20.0, 25.0, 30.0]
C = [2.9, 4.2, 5.0, 8.5, 9.5, 12.0, 16.0, 19.0, 23.0]


def test_estimator_probs_match_golf():
    assert estimator_probs(A, Method.MULTIPLICATIVE, 1)[9] == approx(0.02600780234070221, abs=1e-12)
    assert estimator_probs(A, Method.POWER, 3)[0] == approx(0.5441926214220171, abs=1e-12)
    assert estimator_probs(A, Method.SHIN, 1)[9] == approx(0.01730676345176251, abs=1e-12)


def test_devig_partial_match_golf():
    assert devig_partial(C, Method.MULTIPLICATIVE, 0.9)[0] == approx(0.24871833912339567, abs=1e-12)
    shin = devig_partial(C, Method.SHIN, 0.9)
    assert shin[0] == approx(0.2771562745425425, abs=1e-12) and math.fsum(shin) == approx(0.9, abs=1e-12)
    assert devig_partial(C, Method.POWER, 2.85)[0] == approx(0.554599772331006, abs=1e-12)
    assert devig_partial(C, Method.SHIN, 1.0) == devig(C, Method.SHIN)


def test_partial_bounds_and_shin_limits():
    for bad in (0.0, -0.1, 9.0):
        pytest.raises(ValueError, devig_partial, C, Method.POWER, bad)
    with pytest.raises(ValueError, match="single-winner"):
        estimator_probs(A, Method.SHIN, 3)


def test_devig_partial_refuses_shin_above_one():
    # Shin is single-winner: a total above 1 must raise, never fall back to multiplicative.
    with pytest.raises(ValueError, match="single-winner"):
        devig_partial(C, Method.SHIN, 1.5)
    assert devig_partial(C, Method.SHIN, 1) == devig(C, Method.SHIN)  # total == 1 is still exactly devig
    assert math.fsum(devig_partial(C, Method.SHIN, 0.9)) == approx(0.9, abs=1e-12)  # below 1 unchanged


@pytest.mark.parametrize("method", [Method.MULTIPLICATIVE, Method.POWER, Method.SHIN])
@pytest.mark.parametrize("bad", [True, False, None, "1", math.nan, math.inf, -math.inf, 0, 0.0, -1])
def test_estimator_probs_rejects_invalid_n_winners(method, bad):
    with pytest.raises(ValueError, match="n_winners"):
        estimator_probs(A, method, bad)
