import numpy as np
import pytest

from volttrace import stl


def sig(**kw):
    return {k: np.asarray(v, dtype=float) for k, v in kw.items()}


def test_predicate_and_always_robustness():
    s = sig(x=[1, 2, 3, 2])
    assert stl.robustness(stl.parse("always(x <= 5)"), s, 1.0) == pytest.approx(2.0)
    assert stl.robustness(stl.parse("always(x <= 2.5)"), s, 1.0) == pytest.approx(-0.5)
    assert stl.robustness(stl.parse("eventually(x >= 3)"), s, 1.0) == pytest.approx(0.0)


def test_constant_on_the_left_is_flipped():
    s = sig(x=[1, 4])
    assert stl.robustness(stl.parse("always(3 >= x)"), s, 1.0) == pytest.approx(-1.0)


def test_scale_normalises_margin():
    s = sig(v=[600, 570])
    assert stl.robustness(stl.parse("always(v >= 560)"), s, 1.0, {"v": 50}) == pytest.approx(0.2)


def test_bounded_eventually_inside_implication():
    # trigger at k=2; response arrives at k=4 (2 s later)
    s = sig(a=[0, 0, 2, 2, 2, 2], b=[9, 9, 9, 9, 1, 1])
    late = stl.parse("always(implies(a >= 1, eventually(b <= 2, 0, 1)))")
    ok = stl.parse("always(implies(a >= 1, eventually(b <= 2, 0, 2)))")
    assert stl.robustness(late, s, 1.0) < 0
    assert stl.robustness(ok, s, 1.0) >= 0


def test_window_is_clipped_at_trace_end_not_vacuous():
    s = sig(b=[5, 5, 5])
    phi = stl.parse("eventually(b <= 1, 0, 10)")
    assert stl.robustness(phi, s, 1.0) == pytest.approx(-4.0)


def test_unbounded_matches_brute_force():
    rng = np.random.default_rng(0)
    x = rng.normal(size=50)
    r = stl.parse("always(x <= 1)").rho(sig(x=x), 1.0, {})
    brute = np.array([np.min(1 - x[k:]) for k in range(50)])
    assert np.allclose(r, brute)


def test_bounded_matches_brute_force():
    rng = np.random.default_rng(1)
    x = rng.normal(size=40)
    r = stl.parse("eventually(x >= 0, 2, 5)").rho(sig(x=x), 1.0, {})
    padded = np.concatenate([x, np.full(5, x[-1])])
    brute = np.array([np.max(padded[k + 2 : k + 6]) for k in range(40)])
    assert np.allclose(r, brute)


def test_first_violation_index():
    s = sig(x=[0, 0, 3, 0])
    assert stl.first_violation(stl.parse("always(x <= 1)"), s, 1.0) == 2


@pytest.mark.parametrize("bad", ["__import__('os').system('x')", "x == 1", "always(x <= y)", "always(1 <= 2)", "x <="])
def test_parser_rejects_anything_outside_the_grammar(bad):
    with pytest.raises(stl.STLSyntaxError):
        stl.parse(bad)
