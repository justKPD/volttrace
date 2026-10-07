import pytest

from volttrace.plant import InitialState, Plant, PlantParams


def make(**kw):
    return Plant(PlantParams.default(), InitialState(**kw))


def test_coasting_slows_down_and_draws_only_aux():
    p = make(v_kph=100)
    for _ in range(100):
        p.step(0.0, 0.0, 0.01)
    assert p.v * 3.6 < 100
    assert p.p_bat == pytest.approx(3000.0)


def test_discharge_sags_voltage_and_drains_soc():
    p = make(v_kph=80, soc=0.5)
    ocv = p.ocv()
    for _ in range(100):
        p.step(500.0, 0.0, 0.01)
    assert p.v_bus < ocv
    assert p.soc < 0.5
    assert p.i_bat > 0


def test_regen_raises_voltage_and_charges():
    p = make(v_kph=150, soc=0.5)
    ocv = p.ocv()
    p.step(-400.0, 0.0, 0.01)
    assert p.i_bat < 0 and p.v_bus > ocv


def test_cold_and_aged_pack_has_higher_resistance():
    assert make(t_bat_c=-10).r_int() > make(t_bat_c=25).r_int()
    assert make(r_aging_factor=2.0).r_int() == pytest.approx(2 * make().r_int())


def test_friction_brake_never_reverses_the_car():
    p = make(v_kph=1)
    for _ in range(100):
        p.step(0.0, 20000.0, 0.01)
    assert p.v == 0.0
