"""
tests/test_model.py: checks that the model obeys physics and its own rules.

Run with:  python -m pytest -q

Each test is a claim a judge could ask about. If any fails, the model is wrong.
Uses small synthetic weather so the whole suite runs in seconds.
"""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import battery_temp  # noqa: E402
import config  # noqa: E402
import dispatch  # noqa: E402
import economics as econ  # noqa: E402
import loads as loads_mod  # noqa: E402
import pv_model  # noqa: E402
import weather  # noqa: E402


@pytest.fixture(scope="module")
def setup():
    w = weather.synthetic(years=(2015,), seed=1)
    pv, cell_t, poa = pv_model.pv_output_per_kw(w)
    L = loads_mod.build_loads(w)
    bt = np.full(len(w), 15.0)      # warm battery unless a test says otherwise
    return w, pv, cell_t, poa, L, bt


# ---------------- Solar physics ----------------

def test_no_solar_at_night(setup):
    w, pv, *_ = setup
    night = w["local_time"].dt.hour.isin([0, 1, 2, 3, 22, 23]).values
    assert pv[night].max() == 0


def test_panel_output_physically_bounded(setup):
    _, pv, _, poa, *_ = setup
    # 1 kW of panels can't exceed ~1.25 kW even in cold, bright, high-altitude sun
    assert pv.min() >= 0 and pv.max() < 1.25
    # tilted-panel sunlight can't exceed ~1.5x the solar constant
    assert poa.max() < 1.5 * 1361


def test_cold_panels_produce_more():
    """Same sunlight, colder air -> cooler cells -> more power (negative temp coefficient)."""
    w = weather.synthetic(years=(2015,), seed=1)
    cold, warm = w.copy(), w.copy()
    cold["temp_air"], warm["temp_air"] = -5.0, 25.0
    assert pv_model.pv_output_per_kw(cold)[0].sum() > pv_model.pv_output_per_kw(warm)[0].sum()


# ---------------- Battery rules ----------------

@pytest.mark.parametrize("mode", ["priority", "equal"])
def test_battery_stays_within_limits(setup, mode):
    _, pv, _, _, L, bt = setup
    _, _, x = dispatch.simulate(pv, L, 10, 40, bt, mode, return_soc=True)
    assert x["soc"].min() >= config.BATTERY_MIN_SOC - 1e-9
    assert x["soc"].max() <= 1 + 1e-9


def test_no_charging_below_freezing(setup):
    """Lithium plating rule: below 0 C the battery may discharge but never charge."""
    _, pv, _, _, L, _ = setup
    frozen = np.full(len(pv), -5.0)
    _, _, x = dispatch.simulate(pv, L, 10, 40, frozen, "priority", return_soc=True)
    assert np.all(np.diff(x["soc"]) <= 1e-12)
    assert x["lost_cold_kwh"] > 0


def test_cold_reduces_usable_capacity():
    assert battery_temp.capacity_factor(np.array([-10.0]))[0] == pytest.approx(config.CAPACITY_AT_MINUS10C)
    assert battery_temp.capacity_factor(np.array([25.0]))[0] == pytest.approx(config.CAPACITY_AT_25C)


# ---------------- Priority dispatch ----------------

def test_priority_order_respected(setup):
    """If a lower-ranked load got power in an hour, every higher-ranked load that
    needed power that hour got it too (tested on a stressed, undersized system)."""
    _, pv, _, _, L, bt = setup
    _, _, x = dispatch.simulate(pv, L, 4, 15, bt, "priority")
    served = x["served"]
    need = np.column_stack([L[k] for k in x["names"]]) > 0
    violations = 0
    for j in range(1, served.shape[1]):
        for i in range(j):
            violations += np.sum(served[:, j] & need[:, i] & ~served[:, i])
    assert violations == 0


def test_ranking_protects_critical_loads(setup):
    """On an undersized system, ranking must beat a shared grid for pump + clinic."""
    _, pv, _, _, L, bt = setup
    p, _, _ = dispatch.simulate(pv, L, 4, 15, bt, "priority")
    e, _, _ = dispatch.simulate(pv, L, 4, 15, bt, "equal")
    assert min(p["Water pump"], p["Health post"]) > min(e["Water pump"], e["Health post"])


def test_bigger_battery_never_hurts(setup):
    _, pv, _, _, L, bt = setup
    crit = []
    for b in (10, 20, 40, 80):
        r, _, _ = dispatch.simulate(pv, L, 6, b, bt, "priority")
        crit.append(min(r["Water pump"], r["Health post"]))
    assert all(a <= b + 1e-9 for a, b in zip(crit, crit[1:]))


def test_backup_inverter_keeps_critical_loads_on(setup):
    _, pv, _, _, L, bt = setup
    outage = np.zeros(len(pv), bool)
    outage[3000:3000 + 24 * 21] = True          # main inverter down for 3 weeks
    no_bk, _, x0 = dispatch.simulate(pv, L, 10, 40, bt, "priority", outage=outage, return_soc=True)
    bk, _, x1 = dispatch.simulate(pv, L, 10, 40, bt, "priority", outage=outage, critical_backup=True)
    assert min(bk["Water pump"], bk["Health post"]) > min(no_bk["Water pump"], no_bk["Health post"])
    homes = x1["names"].index("Homes")
    assert not x0["served"][outage].any()          # no backup: nobody has power
    assert not x1["served"][outage, homes].any()   # backup: homes still off
    # DC-coupled: panels keep charging the battery during the repair
    assert x0["soc"][outage].max() > x0["soc"][outage][0]


# ---------------- Loads ----------------

def test_daily_load_totals_match_config(setup):
    w, *_, L, _ = setup
    days = len(w) / 24
    assert L["Water pump"].sum() / days == pytest.approx(config.LOADS["Water pump"]["kwh_day"], rel=1e-6)
    assert L["Health post"].sum() / days == pytest.approx(config.LOADS["Health post"]["kwh_day"], rel=1e-6)
    assert L["Homes"].sum() / days == pytest.approx(config.LOADS["Homes"]["kwh_day"], rel=1e-6)


def test_pump_energy_matches_physics():
    """E = rho * g * V * h / efficiency, for 60 homes x 5 people x 30 L lifted 40 m."""
    volume_m3 = config.N_HOUSEHOLDS * 5 * 30 / 1000
    kwh = 1000 * 9.81 * volume_m3 * 40 / 0.40 / 3.6e6
    assert kwh == pytest.approx(config.LOADS["Water pump"]["kwh_day"], rel=0.01)


# ---------------- Heat flow in soil ----------------

def test_earth_vault_damps_temperature_swings(setup):
    w, *_ = setup
    air = w["temp_air"].values
    vault, d = battery_temp.earth_vault(air, 1.0)
    assert np.ptp(vault) < 0.5 * np.ptp(air)
    # damping depth d = sqrt(2 * alpha / omega) for the yearly cycle
    omega = 2 * np.pi / (365.25 * 24 * 3600)
    assert d == pytest.approx(np.sqrt(2 * config.SOIL_DIFFUSIVITY / omega), rel=1e-6)


# ---------------- Economics ----------------

def test_capital_recovery_factor_known_value():
    # standard table value: 8% over 20 years -> 0.10185
    assert econ.crf(0.08, 20) == pytest.approx(0.10185, abs=1e-5)


def test_diesel_cost_rises_with_fuel_price():
    lo = econ.diesel_cost(10000, 4, fuel_price=0.8)["annual"]
    hi = econ.diesel_cost(10000, 4, fuel_price=1.6)["annual"]
    assert hi > lo
