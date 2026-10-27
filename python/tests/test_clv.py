import math

import pytest
from pytest import approx

from cockpit_core.clv import clv


def test_clv_examples():
    assert clv(3.0, 0.4) == approx(math.log(1.2)) and clv(2.0, 0.5) == 0.0


@pytest.mark.parametrize("odds, prob", [(1.0, 0.5), (0.9, 0.5), (2.0, 0.0), (2.0, 1.0), (2.0, -0.1)])
def test_clv_rejects_bad_inputs(odds, prob):
    with pytest.raises(ValueError):
        clv(odds, prob)


def test_clv_matches_fixture(cases):
    for case in cases["clv"]:
        assert clv(case["bet_price"], case["fair_close_prob"]) == approx(case["clv"], abs=1e-9)
