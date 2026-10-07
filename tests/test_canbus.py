import pytest

from volttrace.canbus import CanBus, Fault, load_dbc

PHYS = {
    "VCU_Pedal": 37.3,
    "VCU_Brake": 0.0,
    "BMS_SOC": 80.04,
    "BMS_T_bat": 31.26,
    "BMS_V_bus": 745.33,
    "BMS_I_bat": -512.37,
    "INV_T_inv": 66.6,
    "INV_Speed": 812.34,
    "INV_Torque_act": -101.27,
}


def test_quantisation_matches_cantools_encode_decode():
    db = load_dbc()
    bus = CanBus()
    bus.tick(0.0, PHYS)
    rx = bus.rx()
    for name in CanBus.RX_MESSAGES:
        msg = db.get_message_by_name(name)
        decoded = db.decode_message(name, db.encode_message(name, {s.name: PHYS[s.name] for s in msg.signals}))
        for s in msg.signals:
            assert rx[s.name] == pytest.approx(decoded[s.name], abs=1e-9), s.name


def test_saturation_follows_dbc_range():
    bus = CanBus()
    bus.tick(0.0, {**PHYS, "BMS_T_bat": 400.0})
    assert bus.rx()["BMS_T_bat"] == pytest.approx(215.5)


def test_cycle_times_and_timeout_fault():
    bus = CanBus([Fault(t=0.05, kind="timeout", message="BMS_1")])
    for k in range(30):
        bus.tick(k * 0.01, PHYS)
    age = bus.age(0.29)
    assert age["INV_1"] == pytest.approx(0.0)
    assert age["BMS_1"] == pytest.approx(0.25)  # last BMS frame at t=0.04 (20 ms cycle)


def test_delay_and_stuck_faults():
    bus = CanBus(
        [
            Fault(t=0.0, kind="delay", message="BMS_1", value=0.05),
            Fault(t=0.0, kind="stuck", signal="INV_T_inv", value=120.0),
        ]
    )
    bus.tick(0.0, PHYS)
    assert "BMS_SOC" not in bus.rx()
    assert bus.rx()["INV_T_inv"] == 120.0
    for k in range(1, 6):
        bus.tick(k * 0.01, PHYS)
    assert bus.rx()["BMS_SOC"] == pytest.approx(80.0)


def test_runtime_signal_table_matches_the_dbc():
    from volttrace.canbus import export_signal_table, signal_table

    assert signal_table() == export_signal_table()
