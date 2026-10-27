"""Money and canonical formatting ignore the caller's decimal context.

Each function is run once under the default context and once under a hostile one (Inexact and Rounded
trapped, ROUND_CEILING, precision 6, lowercase exponents). The results must be identical and nothing
may raise a decimal signal.
"""

from decimal import ROUND_CEILING, Decimal, Inexact, Rounded, localcontext
from fractions import Fraction

from cockpit_core.canonical import fmt_price, fmt_prob
from cockpit_core.kelly import StakeSettings, size_stake
from cockpit_core.odds import decimal_from_american
from cockpit_core.settle import Settlement, profit


def _hostile(fn):
    with localcontext() as ctx:
        ctx.traps[Inexact] = True
        ctx.traps[Rounded] = True
        ctx.rounding = ROUND_CEILING
        ctx.prec = 6
        ctx.capitals = 0
        return fn()


def _same_under_hostile_context(fn):
    expected = fn()
    got = _hostile(fn)
    assert got == expected
    assert str(got) == str(expected)
    return got


def _stake_call(case: dict):
    def call():
        return size_stake(
            fair_prob=Decimal(case["fair_prob"]),
            price=Decimal(case["price"]),
            bankroll=Decimal(case["bankroll"]),
            settings=StakeSettings(
                kelly_multiplier=Decimal(case["kelly_multiplier"]),
                bet_cap=Decimal(case["bet_cap"]),
                participant_cap=Decimal(case["participant_cap"]),
                event_cap=Decimal(case["event_cap"]),
            ),
            participant_exposure=Decimal(case["participant_exposure"]),
            event_exposure=Decimal(case["event_exposure"]),
        )

    return call


def test_size_stake_ignores_caller_context(cases):
    for case in cases["stakes"]:
        assert str(_same_under_hostile_context(_stake_call(case))) == case["stake"], case["name"]


def test_profit_ignores_caller_context(cases):
    for case in cases["settlement"]:
        s = Settlement(Fraction(case["win"]), Fraction(case["refund"]))
        got = _same_under_hostile_context(lambda c=case, s=s: profit(Decimal(c["stake"]), Decimal(c["price"]), s))
        assert str(got) == case["profit"], case["name"]


def test_decimal_from_american_ignores_caller_context():
    for a in (-110, -150, -101, 100, -100, 450, 333):
        _same_under_hostile_context(lambda a=a: decimal_from_american(a))


def test_fmt_prob_and_price_ignore_caller_context():
    for p in (0.1234565, 0.1834, Decimal("0.1234565"), "0.5"):
        _same_under_hostile_context(lambda p=p: fmt_prob(p))
    for o in (2.00005, "6.5", Decimal("1.5")):
        _same_under_hostile_context(lambda o=o: fmt_price(o))
