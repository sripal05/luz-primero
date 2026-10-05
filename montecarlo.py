"""
montecarlo.py: stress-test one design against 1,000 possible futures.

Each run randomly picks:
  - a real weather year from the NASA record (bad years included)
  - how old the system is (panels degrade, batteries fade)
  - how dusty the panels get in the dry season
  - whether the inverter breaks, and how many weeks a repair takes
  - how much household demand has grown
Then it runs the grid for that year in BOTH modes and records reliability.
"""
import numpy as np
import pandas as pd
import config
import loads as loads_mod
import dispatch


def run(weather, pv_per_kw, batt_temp, pv_kw, batt_kwh, n=None, seed=42):
    rng = np.random.default_rng(seed)
    n = n or config.N_MONTE_CARLO
    years = weather["local_time"].dt.year.values
    unique_years = [y for y in np.unique(years) if (years == y).sum() >= 8000]
    month_all = weather["local_time"].dt.month.values
    rows = []
    for i in range(n):
        yr = rng.choice(unique_years)
        m = years == yr
        w = weather[m]
        age = rng.uniform(*config.SYSTEM_AGE_YR)
        deg = rng.uniform(*config.PV_DEGRADATION_PER_YR)
        soil = rng.uniform(*config.DRY_SEASON_SOILING)
        dry = (month_all[m] >= 5) & (month_all[m] <= 10)
        pv_derate = (1 - deg * age) * np.where(dry, 1 - soil, 1 - soil / 3)
        batt_fade = 1 - config.BATTERY_FADE_PER_YR * (age % config.BATTERY_LIFE_YR)
        growth = rng.uniform(*config.HOUSEHOLD_DEMAND_GROWTH)
        outage = np.zeros(m.sum(), bool)
        broke = rng.random() < config.INVERTER_FAILURE_PROB_PER_YR
        if broke:
            days = int(rng.uniform(*config.REPAIR_DAYS))
            start = rng.integers(0, max(1, m.sum() - days * 24))
            outage[start:start + days * 24] = True
        L = loads_mod.build_loads(w, household_growth=growth)
        row = {"run": i, "year": yr, "age": age, "soiling": soil, "growth": growth,
               "inverter_failed": broke}
        for label, mode, backup in (("priority", "priority", False), ("equal", "equal", False),
                                    ("backup", "priority", True)):
            rel, _, _ = dispatch.simulate(pv_per_kw[m], L, pv_kw, batt_kwh, batt_temp[m],
                                          mode=mode, outage=outage, pv_derate=pv_derate,
                                          batt_fade=batt_fade, critical_backup=backup)
            for k, v in rel.items():
                row[f"{label}|{k}"] = v
        rows.append(row)
    return pd.DataFrame(rows)
