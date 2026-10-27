"""Settlement: (win, refund) fractions, dead heats, matchup tie rules and exact profit."""

from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest
from pytest import approx

from cockpit_core.settle import (
    HALF_LOSS,
    HALF_WIN,
    LOSS,
    VOID,
    WIN,
    Settlement,
    TieRule,
    dead_heat,
    matchup_settlement,
    profit,
    tie_rule_from_text,
    unit_profit,
)

VOID_RULE, DEAD_HEAT, LOSES = TieRule.VOID, TieRule.DEAD_HEAT, TieRule.LOSES


def _outright(f) -> Settlement:
    """An outright settled with win fraction f (f < 1 is a dead heat)."""
    return Settlement(Fraction(f).limit_denominator(1000), Fraction(0))


# --- ported from golf's settle tests (23 functions, every case and expected value kept) ---


@pytest.mark.parametrize("f,expected", [(1, 10.0), (0, -1.0), (0.5, 4.5), (1 / 3, 2.6667)])
def test_outright_dead_heat(f, expected):
    assert unit_profit(11.0, _outright(f)) == approx(expected, abs=1e-4)


@pytest.mark.parametrize(
    "ranks,rule,expected",
    [
        ((1, 2), VOID_RULE, 0.91),
        ((2, 1), VOID_RULE, -1.0),
        ((1, 1), VOID_RULE, 0.0),
        ((1, 1), DEAD_HEAT, -0.045),
        ((1, 1), LOSES, -1.0),
        ((1, None), VOID_RULE, 0.0),
    ],
)
def test_two_way_matchup(ranks, rule, expected):
    assert unit_profit(1.91, matchup_settlement(ranks, 0, rule)) == approx(expected, abs=1e-4)


@pytest.mark.parametrize("ranks,expected", [((1, 1, 3), 0.4), ((1, 1, 1), -0.0667), ((2, 1, 3), -1.0)])
def test_three_ball_dead_heat(ranks, expected):
    assert unit_profit(2.8, matchup_settlement(ranks, 0, DEAD_HEAT)) == approx(expected, abs=1e-4)


def test_win_fraction_out_of_range_rejected():
    with pytest.raises(ValueError):
        unit_profit(3.0, _outright(1.5))


def test_unknown_tie_text_rejected():
    pytest.raises(ValueError, tie_rule_from_text, "coin flip")


def test_outright_odds_must_exceed_one():
    with pytest.raises(ValueError):
        unit_profit(1.0, _outright(0.5))
    with pytest.raises(ValueError):
        unit_profit(0.9, _outright(0.5))


def test_outright_negative_fraction_rejected():
    with pytest.raises(ValueError):
        unit_profit(3.0, _outright(-0.1))


@pytest.mark.parametrize(
    "bad",
    [-0.01, 1.01, float("nan"), None, Fraction(-1, 100), Fraction(101, 100), True, "0.5", Decimal("NaN")],
)
def test_settlement_rejects_bad_values(bad):
    # Golf's win_fraction_from_numeric bad-value list, plus exact and wrong-type equivalents.
    # Every one is a ValueError (never a TypeError), for the win and the refund alike.
    with pytest.raises(ValueError):
        Settlement(bad, Fraction(0))
    with pytest.raises(ValueError):
        Settlement(Fraction(0), bad)


@pytest.mark.parametrize("v", [0, 0.25, 1])
def test_settlement_accepts_valid_fraction(v):
    s = _outright(v)
    assert s.win == v
    assert isinstance(s.win, Fraction)


@pytest.mark.parametrize("pick", [-1, 2, 5])
def test_matchup_bad_pick_index_rejected(pick):
    with pytest.raises(ValueError):
        matchup_settlement((1, 2), pick, VOID_RULE)


@pytest.mark.parametrize("odds", [1.0, 0.5, float("nan")])
def test_matchup_odds_must_exceed_one(odds):
    with pytest.raises(ValueError):
        unit_profit(odds, matchup_settlement((1, 2), 0, VOID_RULE))


@pytest.mark.parametrize("ranks", [(1,), (1, 2, 3, 4), ()])
def test_matchup_group_size_must_be_two_or_three(ranks):
    with pytest.raises(ValueError):
        matchup_settlement(ranks, 0, VOID_RULE)


def test_matchup_none_voids_even_when_pick_is_not_the_missing_player():
    assert unit_profit(2.8, matchup_settlement((1, 2, None), 0, LOSES)) == 0.0


def test_matchup_uses_best_rank_not_literal_one():
    # Within-group ranks need not start at 1; the minimum is the winner.
    assert unit_profit(2.0, matchup_settlement((3, 5), 0, VOID_RULE)) == approx(1.0)
    assert unit_profit(2.0, matchup_settlement((5, 3), 0, VOID_RULE)) == approx(-1.0)


def test_three_ball_shared_best_void_and_loses():
    assert unit_profit(2.8, matchup_settlement((1, 1, 3), 1, VOID_RULE)) == 0.0
    assert unit_profit(2.8, matchup_settlement((1, 1, 3), 1, LOSES)) == -1.0


def test_three_ball_pick_beaten_by_tied_pair_loses():
    assert unit_profit(2.8, matchup_settlement((2, 1, 1), 0, DEAD_HEAT)) == -1.0


def test_three_ball_unique_winner_pays_full_odds():
    assert unit_profit(2.8, matchup_settlement((3, 1, 2), 1, LOSES)) == approx(1.8)


@pytest.mark.parametrize(
    "text,rule",
    [("void", VOID_RULE), ("  Void ", VOID_RULE), ("Separate  Bet\toffered", LOSES), ("SEPARATE BET OFFERED", LOSES)],
)
def test_tie_rule_from_text_normalises(text, rule):
    assert tie_rule_from_text(text) is rule


@pytest.mark.parametrize("bad", ["", "dead heat", "dead-heat rules apply"])
def test_tie_rule_unknown_strings_rejected(bad):
    with pytest.raises(ValueError):
        tie_rule_from_text(bad)


NAN = float("nan")


@pytest.mark.parametrize(
    "ranks",
    [
        (np.ma.masked, 2),
        (1, np.ma.masked),
        (NAN, 2),
        (1, NAN),
        (1.5, 2),
        (True, 2),
        (1, 0),
        (1.0, 2),
        (np.float64(1.0), 2),
        ("1", 2),
        (-1, 2),
    ],
)
def test_matchup_bad_rank_raises_naming_it(ranks):
    with pytest.raises(ValueError, match="rank"):
        matchup_settlement(ranks, 0, VOID_RULE)


def test_matchup_withdrawn_none_still_voids():
    assert unit_profit(1.91, matchup_settlement((None, 2), 0, VOID_RULE)) == 0.0
    assert unit_profit(1.91, matchup_settlement((1, None), 0, DEAD_HEAT)) == 0.0


def test_matchup_numpy_integer_ranks_work():
    assert unit_profit(1.91, matchup_settlement((np.int64(1), np.int64(2)), 0, VOID_RULE)) == approx(0.91)
    assert unit_profit(2.8, matchup_settlement(np.array([1, 1, 3], dtype=np.int32), 0, DEAD_HEAT)) == approx(0.4)


@pytest.mark.parametrize("bad", [None, 3, b"void"])
def test_tie_rule_from_text_non_string_raises_naming_value(bad):
    with pytest.raises(ValueError, match=repr(bad).replace("(", r"\(")):
        tie_rule_from_text(bad)


# --- new: exact settlement and money ---


def test_settlement_matches_fixture(cases):
    assert len(cases["settlement"]) == 10
    for case in cases["settlement"]:
        s = Settlement(Fraction(case["win"]), Fraction(case["refund"]))
        got = profit(Decimal(case["stake"]), Decimal(case["price"]), s)
        assert got == Decimal(case["profit"]), case["name"]
        assert str(got) == case["profit"], case["name"]


def test_dead_heat_constructor():
    assert dead_heat(2, 3) == Settlement(Fraction(2, 3), Fraction(0))
    assert dead_heat(1, 1) == WIN
    with pytest.raises(ValueError):
        dead_heat(4, 3)
    with pytest.raises(ValueError):
        dead_heat(0, 0)


@pytest.mark.parametrize("places,tied", [(0, 3), (-1, 3), (1, 0), (True, 2), (1.0, 2), (1, None)])
def test_dead_heat_rejects_bad_counts(places, tied):
    with pytest.raises(ValueError):
        dead_heat(places, tied)


def test_named_outcomes():
    assert WIN == Settlement(Fraction(1), Fraction(0))
    assert LOSS == Settlement(Fraction(0), Fraction(0))
    assert HALF_WIN == Settlement(Fraction(1, 2), Fraction(1, 2))
    assert HALF_LOSS == Settlement(Fraction(0), Fraction(1, 2))
    assert VOID == Settlement(Fraction(0), Fraction(1))


def test_settlement_win_plus_refund_cannot_exceed_one():
    with pytest.raises(ValueError):
        Settlement(Fraction(1, 2), Fraction(2, 3))
    assert Settlement(Fraction(1, 3), Fraction(2, 3)).refund == Fraction(2, 3)


def test_settlement_is_frozen():
    with pytest.raises(AttributeError):
        WIN.win = Fraction(0)  # type: ignore[misc]


def test_matchup_dead_heat_is_one_over_k():
    assert matchup_settlement((1, 1, 1), 2, DEAD_HEAT) == Settlement(Fraction(1, 3), Fraction(0))
    assert matchup_settlement((1, 1), 0, VOID_RULE) == VOID
    assert matchup_settlement((1, 1), 0, LOSES) == LOSS
    assert matchup_settlement((1, 2), 0, LOSES) == WIN


def test_profit_dead_heat_does_not_round_fraction_first():
    # 1/6 as 0.1667 first would give 11 * (0.1667 * 2.25 - 1) = -6.874... -> -6.87. Exact is -6.875 -> -6.88.
    assert profit(Decimal(11), Decimal("2.25"), Settlement(Fraction(1, 6), Fraction(0))) == Decimal("-6.88")


def test_profit_just_below_half_cent_rounds_down():
    # Exact profit 0.00499999...(9 repeating to 60 places) must give 0.00, never be lifted onto 0.005 by the
    # precision-40 division and then rounded up to 0.01.
    stake = Decimal(1)
    price = Decimal("1." + "0" * 2 + "4" + "9" * 60)  # 1.00499...9; win 1 -> profit 0.00499...9
    assert profit(stake, price, WIN) == Decimal("0.00")
    assert profit(stake, Decimal("1.005"), WIN) == Decimal("0.01")
    # Mirror image on the loss side: -0.00499...9 is -0.00, and -0.005 is -0.01.
    assert profit(Decimal("0.00" + "4" + "9" * 60), Decimal(2), LOSS) == Decimal("0.00")
    assert profit(Decimal("0.005"), Decimal(2), LOSS) == Decimal("-0.01")


def test_profit_never_returns_negative_zero():
    got = profit(Decimal("0.004"), Decimal(2), LOSS)  # exact -0.004
    assert got == Decimal("0.00")
    assert str(got) == "0.00"


@pytest.mark.parametrize(
    "stake,price",
    [
        (100.0, Decimal(2)),
        (Decimal(100), 2.0),
        (100, Decimal(2)),
        (Decimal("NaN"), Decimal(2)),
        (Decimal("Infinity"), Decimal(2)),
        (Decimal(-1), Decimal(2)),
        (Decimal(100), Decimal(1)),
        (Decimal(100), Decimal("0.5")),
        (Decimal(100), Decimal("NaN")),
        (None, Decimal(2)),
        (True, Decimal(2)),
    ],
)
def test_profit_rejects_bad_money_inputs(stake, price):
    with pytest.raises(ValueError):
        profit(stake, price, WIN)


def test_profit_and_unit_profit_need_a_settlement():
    with pytest.raises(TypeError):
        profit(Decimal(1), Decimal(2), (1, 0))  # type: ignore[arg-type]
    with pytest.raises(TypeError):
        unit_profit(2.0, (1, 0))  # type: ignore[arg-type]


@pytest.mark.parametrize("odds", [None, True, float("inf")])
def test_unit_profit_rejects_bad_odds(odds):
    with pytest.raises(ValueError):
        unit_profit(odds, WIN)


def test_unit_profit_is_w_times_o_plus_r_minus_one():
    assert unit_profit(3.0, HALF_WIN) == approx(1.0)
    assert unit_profit(3.0, HALF_LOSS) == approx(-0.5)
    assert unit_profit(3.0, VOID) == 0.0
    assert unit_profit(3, WIN) == approx(2.0)


def test_tie_rule_values():
    assert [r.value for r in TieRule] == ["void", "dead_heat", "loses"]


@pytest.mark.parametrize("rule", list(TieRule))
@pytest.mark.parametrize(
    "ranks,pick", [((1, 1), 0), ((1, 1, 1), 2), ((1, 1, 3), 1), ((1, 2), 0), ((2, 1), 0), ((1, None), 0)]
)
def test_str_tie_rule_settles_like_enum(rule, ranks, pick):
    # A rule read back from JSON or the database is a plain str; it must never fall through to a loss.
    assert type(rule.value) is str
    assert matchup_settlement(ranks, pick, rule.value) == matchup_settlement(ranks, pick, rule)


def test_str_tie_rule_tied_best_outcomes():
    assert matchup_settlement((1, 1), 0, "void") == VOID
    assert matchup_settlement((1, 1), 0, "dead_heat") == Settlement(Fraction(1, 2), Fraction(0))
    assert matchup_settlement((1, 1), 0, "loses") == LOSS


@pytest.mark.parametrize("bad", ["coin flip", "", "VOID", None, 1])
def test_unknown_tie_rule_raises(bad):
    with pytest.raises(ValueError):
        matchup_settlement((1, 1), 0, bad)
    with pytest.raises(ValueError):
        matchup_settlement((1, 2), 0, bad)  # fail closed even when the rule would not be consulted
