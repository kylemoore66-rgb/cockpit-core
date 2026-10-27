import math
import time

import pytest
from pytest import approx

np = pytest.importorskip("numpy")

from cockpit_core import stats
from cockpit_core.stats import (
    Estimate,
    binary_log_loss,
    brier,
    calibration,
    categorical_log_loss,
    cluster_bootstrap,
    holm,
    paired_cluster_bootstrap,
)


def test_bootstrap_respects_clusters():
    v = np.r_[np.ones(100), -np.ones(100)]
    c = np.r_[np.zeros(100), np.ones(100)]
    e = cluster_bootstrap(v, c)
    assert (e.lo, e.hi, e.n_events) == (approx(-1.0), approx(1.0), 2)
    assert e.n == 200 and e.mean == approx(0.0)


def test_bootstrap_is_deterministic():
    rng = np.random.default_rng(1)
    v = rng.normal(0.02, 1.0, 400)
    c = rng.integers(0, 25, 400)
    assert cluster_bootstrap(v, c) == cluster_bootstrap(v.copy(), c.copy())
    assert isinstance(cluster_bootstrap(v, c), Estimate)


def test_different_seed_changes_result():
    rng = np.random.default_rng(2)
    v = rng.normal(0.0, 1.0, 400)
    c = rng.integers(0, 25, 400)
    assert cluster_bootstrap(v, c, seed=1).lo != cluster_bootstrap(v, c, seed=2).lo


def test_all_positive_p_is_minimal():
    e = cluster_bootstrap(np.ones(50), np.repeat(np.arange(5), 10))
    assert e.p_one_sided == approx(1 / 5001)


def test_all_negative_p_is_maximal():
    e = cluster_bootstrap(-np.ones(50), np.repeat(np.arange(5), 10))
    assert e.p_one_sided == approx(1.0)


def test_bootstrap_mean_is_bet_weighted():
    # cluster 0: 1 bet of +10; cluster 1: 9 bets of 0 -> pooled mean 1.0, not 5.0
    v = np.r_[10.0, np.zeros(9)]
    c = np.r_[0, np.ones(9, dtype=int)]
    assert cluster_bootstrap(v, c).mean == approx(1.0)


def test_bootstrap_ci_brackets_mean_for_noisy_data():
    rng = np.random.default_rng(3)
    v = rng.normal(0.05, 1.0, 2000)
    c = rng.integers(0, 40, 2000)
    e = cluster_bootstrap(v, c)
    assert e.lo < e.mean < e.hi and e.n_events == 40


def test_tuple_clusters_match_string_labels():
    rng = np.random.default_rng(4)
    v = rng.normal(0.0, 1.0, 300)
    years = rng.integers(2019, 2022, 300)
    events = rng.integers(0, 6, 300)
    as_tuples = [(int(y), f"ev{e}") for y, e in zip(years, events)]
    as_strings = [f"{y}|ev{e}" for y, e in zip(years, events)]
    from_tuples = cluster_bootstrap(v, as_tuples)
    assert from_tuples == cluster_bootstrap(v, as_strings)
    assert from_tuples == cluster_bootstrap(v, np.array(as_tuples, dtype=object))
    # same event id in different years is a different cluster
    assert from_tuples.n_events == len(set(as_tuples))


def test_same_event_in_two_years_is_two_clusters():
    e = cluster_bootstrap(np.ones(4), [(2019, "x"), (2019, "x"), (2020, "x"), (2020, "x")])
    assert e.n_events == 2


def test_bootstrap_validation_errors():
    v, c = np.ones(4), np.array([0, 0, 1, 1])
    with pytest.raises(ValueError):
        cluster_bootstrap(v, c[:3])
    with pytest.raises(ValueError):
        cluster_bootstrap(np.array([]), np.array([]))
    with pytest.raises(ValueError):
        cluster_bootstrap(np.array([1.0, np.nan, 1.0, 1.0]), c)
    with pytest.raises(ValueError):
        cluster_bootstrap(np.array([1.0, np.inf, 1.0, 1.0]), c)
    with pytest.raises(ValueError):
        cluster_bootstrap(v, c, b=0)
    for alpha in (0.0, 1.0, -0.1, 1.5):
        with pytest.raises(ValueError):
            cluster_bootstrap(v, c, alpha=alpha)


def test_paired_difference_sign():
    rng = np.random.default_rng(5)
    b = rng.normal(0.0, 1.0, 300)
    a = b + 0.1
    c = rng.integers(0, 20, 300)
    e = paired_cluster_bootstrap(a, b, c)
    assert e.mean == approx(0.1) and e.lo > 0 and e.p_one_sided == approx(1 / 5001)


def test_paired_matches_unpaired_on_difference():
    rng = np.random.default_rng(6)
    a, b = rng.normal(0, 1, 200), rng.normal(0, 1, 200)
    c = rng.integers(0, 10, 200)
    assert paired_cluster_bootstrap(a, b, c) == cluster_bootstrap(a - b, c)


def test_paired_length_mismatch():
    with pytest.raises(ValueError):
        paired_cluster_bootstrap(np.ones(3), np.ones(4), np.zeros(3))


def test_bootstrap_performance_guard():
    rng = np.random.default_rng(7)
    v = rng.normal(0.0, 1.0, 10_000)
    c = rng.integers(0, 300, 10_000)
    start = time.perf_counter()
    e = cluster_bootstrap(v, c, b=5000)
    assert time.perf_counter() - start < 15.0
    assert e.n == 10_000 and e.n_events == 300


def test_holm_step_down():
    assert holm({"a": 0.01, "b": 0.04, "c": 0.03}) == {"a": True, "b": False, "c": False}


def test_holm_all_pass_and_empty():
    assert holm({}) == {}
    assert holm({"a": 0.001, "b": 0.002, "c": 0.003}) == {"a": True, "b": True, "c": True}


def test_holm_stops_at_first_failure():
    # sorted: 0.01 <= .05/3 ok; 0.03 > .05/2 fails; 0.031 must not be rescued
    assert holm({"a": 0.01, "b": 0.03, "c": 0.031}) == {"a": True, "b": False, "c": False}


def test_holm_boundary_and_ties():
    assert holm({"a": 0.05}) == {"a": True}
    assert holm({"a": 0.0251, "b": 0.0251}) == {"a": False, "b": False}
    assert holm({"a": 0.025, "b": 0.025}) == {"a": True, "b": True}
    assert holm({"a": 0.2}, alpha=0.1) == {"a": False}


def test_fractional_log_loss():
    assert binary_log_loss(np.array([0.5]), np.array([0.5])) == approx(math.log(2))


def test_binary_log_loss_clips_extremes():
    assert math.isfinite(binary_log_loss(np.array([0.0, 1.0]), np.array([1.0, 0.0])))
    assert binary_log_loss(np.array([0.8, 0.2]), np.array([1.0, 0.0])) == approx(-math.log(0.8))


def test_categorical_log_loss():
    assert categorical_log_loss(np.array([0.5, 0.25])) == approx((math.log(2) + math.log(4)) / 2)
    assert math.isfinite(categorical_log_loss(np.array([0.0])))


def test_brier():
    assert brier(np.array([0.5, 1.0]), np.array([1.0, 1.0])) == approx(0.125)


def test_calibration_bins():
    p = np.array([0.05, 0.07, 0.55, 1.0, 0.95])
    y = np.array([0.0, 1.0, 1.0, 1.0, 0.0])
    out = calibration(p, y, bins=10)
    assert [n for _, _, n in out] == [2, 1, 2]  # empty bins skipped; p=1.0 in the last bin
    assert out[0][:2] == approx((0.06, 0.5))
    assert out[1][:2] == approx((0.55, 1.0))
    assert out[2][:2] == approx((0.975, 0.5))


# --- reproducibility, Holm family, Estimate invariants ---


def _bets(n=2000, k=60, seed=11):
    rng = np.random.default_rng(seed)
    return rng.normal(0.01, 1.0, n), rng.integers(0, k, n)


def test_bootstrap_is_invariant_to_row_order():
    v, c = _bets()
    base = cluster_bootstrap(v, c)
    assert base.n_events == 60
    rng = np.random.default_rng(99)
    for _ in range(20):
        perm = rng.permutation(v.size)
        assert cluster_bootstrap(v[perm], c[perm]) == base  # exact, not approx


def test_paired_bootstrap_is_invariant_to_row_order():
    a, c = _bets(seed=12)
    b_ = np.random.default_rng(13).normal(0.0, 1.0, a.size)
    base = paired_cluster_bootstrap(a, b_, c)
    rng = np.random.default_rng(98)
    for _ in range(20):
        perm = rng.permutation(a.size)
        assert paired_cluster_bootstrap(a[perm], b_[perm], c[perm]) == base


@pytest.mark.parametrize("chunk", [37, 10**9])
def test_chunk_size_does_not_change_the_estimate(monkeypatch, chunk):
    v, c = _bets(n=500, k=40, seed=14)
    base = cluster_bootstrap(v, c)
    monkeypatch.setattr(stats, "_CHUNK_ELEMENTS", chunk)
    assert cluster_bootstrap(v, c) == base


def test_replicates_pool_bets_not_cluster_means():
    # One cluster holds a single +10 bet; 19 clusters hold 99 bets of 0 each. A replicate that
    # draws the +10 cluster c times has pooled mean 10c / (c + 99 (20 - c)) (tiny) but a
    # mean of cluster means of c / 2. The upper CI end separates the two.
    v = np.r_[10.0, np.zeros(19 * 99)]
    c = np.r_[0, np.repeat(np.arange(1, 20), 99)]
    e = cluster_bootstrap(v, c)
    assert e.mean == approx(10.0 / (1 + 19 * 99))
    assert e.lo == 0.0
    assert 0.0 < e.hi < 0.1  # mean-of-means would put hi at about 1.5


def test_holm_family_must_match_exactly():
    fam = {"a", "b", "c"}
    assert holm({"a": 0.01, "b": 1.0, "c": 0.5}, family=fam) == {"a": True, "b": False, "c": False}
    with pytest.raises(ValueError, match="family"):
        holm({"a": 0.01, "b": 0.02}, family=fam)  # a pre-registered candidate is missing
    with pytest.raises(ValueError, match="family"):
        holm({"a": 0.01, "b": 0.02, "c": 0.5, "d": 0.3}, family=fam)  # an extra one
    assert holm({"a": 0.01}) == {"a": True}  # no family given: unchanged behaviour


def test_holm_family_as_a_bare_string_is_refused():
    # family="abc" would silently become the set of characters {"a", "b", "c"}.
    with pytest.raises(TypeError, match="family"):
        holm({"a": 0.01, "b": 0.02, "c": 0.5}, family="abc")  # type: ignore[arg-type]


def test_holm_missing_candidate_cannot_shrink_the_family():
    # With c dropped, a would pass at 0.02 <= 0.05/2; with c at p = 1.0 it needs <= 0.05/3.
    fam = ["a", "b", "c"]
    assert holm({"a": 0.02, "b": 0.9, "c": 1.0}, family=fam)["a"] is False


GOOD = {"n": 10, "n_events": 3, "mean": 0.1, "lo": -0.1, "hi": 0.3, "p_one_sided": 0.2}


@pytest.mark.parametrize(
    "bad",
    [
        {"n": 0, "n_events": 0},
        {"n_events": -1},
        {"n_events": 11},
        {"mean": float("nan")},
        {"lo": float("nan")},
        {"hi": float("inf")},
        {"lo": 0.4},
        {"p_one_sided": 0.0},
        {"p_one_sided": 1.01},
        {"p_one_sided": float("nan")},
    ],
)
def test_estimate_rejects_impossible_values(bad):
    with pytest.raises(ValueError):
        Estimate(**{**GOOD, **bad})


def test_estimate_accepts_edge_values():
    Estimate(**{**GOOD, "n_events": 0, "lo": 0.3, "p_one_sided": 1.0})
    Estimate(**{**GOOD, "n": 1, "n_events": 1})


def test_golden_value_with_default_seed():
    # Pinned on numpy 2.5.4. If a numpy (or code) change moves these numbers, treat it as a
    # methodology change: it changes every reported CI and p-value, so re-pin only on purpose.
    v = np.array([0.5, -1.0, 0.25, 2.0, -1.0, -1.0, 0.75, 1.5, -0.5, 0.1, -1.0, 3.0])
    c = np.array([0, 0, 1, 1, 1, 2, 2, 3, 3, 4, 4, 4])
    assert cluster_bootstrap(v, c) == Estimate(
        n=12, n_events=5, mean=0.3, lo=-0.05, hi=0.573076923076923, p_one_sided=0.054789042191561686
    )
