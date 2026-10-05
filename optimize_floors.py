"""
optimize_floors.py: answers the question "why cut homes off at 15%?"

The cut-off levels (reserve floors) set the tradeoff:
  higher floor for homes -> more energy saved for pump + clinic, but homes lose more hours.

We test EVERY combination of school and home floors from 10% to 60% (66 combinations)
on the full 20-year weather record, in two scenarios:

  Typical year : new system, today's demand
  Stress year  : 15-year-old panels (1%/yr loss), heavy dry-season dust (8%),
                 battery faded to 82%, household demand +50%

Selection rule (decided before looking at results):
  Pick the combination that gives homes the MOST uptime in the stress year,
  among those that keep pump + clinic on at least 99.99% of hours in the stress year.

Finding: the ranking (serving loads in priority order) does most of the protecting.
A small 5-point buffer above the critical floor is enough; bigger reserves only
take power away from homes.

Usage:  python optimize_floors.py data/nasa_power_ancotanga.csv
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import battery_temp
import config
import dispatch
import loads as loads_mod
import plots
import pv_model
import weather

OUT = Path("results")
OUT.mkdir(exist_ok=True)
PV_KW, BATT_KWH = 10, 40          # the design chosen by run_all.py
FLOORS = np.round(np.arange(0.10, 0.61, 0.05), 2)
CRITICAL_TARGET = 0.9999


def scenarios(w):
    month = w["local_time"].dt.month.values
    dry = (month >= 5) & (month <= 10)
    stress_derate = (1 - 0.01 * 15) * np.where(dry, 0.92, 1 - 0.08 / 3)
    return {
        "Typical year": {"growth": 1.0, "pv_derate": None, "batt_fade": 1.0},
        "Stress year": {"growth": 1.5, "pv_derate": stress_derate, "batt_fade": 0.82},
    }


def pareto(df, x, y):
    """Rows that no other row beats on both x and y."""
    keep = []
    for _, r in df.iterrows():
        better = df[(df[x] >= r[x]) & (df[y] >= r[y]) & ((df[x] > r[x]) | (df[y] > r[y]))]
        keep.append(len(better) == 0)
    return df[keep].sort_values(x)


def main():
    w = weather.load(sys.argv[1]) if len(sys.argv) > 1 else weather.synthetic()
    if len(sys.argv) == 1:
        plots.TEST_WATERMARK = True
    pv, _, _ = pv_model.pv_output_per_kw(w)
    bt = battery_temp.battery_temperature(w["temp_air"].values, "Earth vault (1 m deep)")
    chosen = dict(config.RESERVE_FLOORS)
    rows, shared = [], {}
    for name, sc in scenarios(w).items():
        L = loads_mod.build_loads(w, household_growth=sc["growth"])
        kw = {"pv_derate": sc["pv_derate"], "batt_fade": sc["batt_fade"]}
        rel, _, _ = dispatch.simulate(pv, L, PV_KW, BATT_KWH, bt, "equal", **kw)
        shared[name] = {"critical": round(min(rel["Water pump"], rel["Health post"]), 4),
                        "homes": round(rel["Homes"], 4)}
        for school in FLOORS:
            for homes in FLOORS:
                if homes < school:      # homes are ranked below school, so never protected more
                    continue
                config.RESERVE_FLOORS.update({"School": school, "Homes": homes})
                rel, _, _ = dispatch.simulate(pv, L, PV_KW, BATT_KWH, bt, "priority", **kw)
                rows.append({"scenario": name, "school_floor": school, "homes_floor": homes,
                             "critical": min(rel["Water pump"], rel["Health post"]),
                             "school": rel["School"], "homes": rel["Homes"]})
        print(f"  {name} done")
    config.RESERVE_FLOORS.clear()
    config.RESERVE_FLOORS.update(chosen)
    df = pd.DataFrame(rows)
    df.to_csv(OUT / "floor_search.csv", index=False)

    stress = df[df.scenario == "Stress year"]
    ok = stress[stress.critical >= CRITICAL_TARGET]
    best = ok.sort_values(["homes", "school_floor"], ascending=[False, False]).iloc[0]
    summary = {"combinations_per_scenario": int(len(stress)),
               "selection_rule": f"max homes uptime in stress year s.t. pump+clinic >= {CRITICAL_TARGET}",
               "optimizer_pick": {"school_floor": float(best.school_floor),
                                  "homes_floor": float(best.homes_floor)},
               "config_matches_pick": bool(np.isclose(chosen["School"], best.school_floor)
                                           and np.isclose(chosen["Homes"], best.homes_floor)),
               "shared_grid": shared, "by_homes_floor": {}}
    for name in df.scenario.unique():
        d = df[(df.scenario == name) & (np.isclose(df.school_floor, chosen["School"]) |
                                        np.isclose(df.school_floor, df.homes_floor))]
        for hf in (0.15, 0.30, 0.45):
            r = df[(df.scenario == name) & np.isclose(df.homes_floor, hf) &
                   np.isclose(df.school_floor, min(chosen["School"], hf))].iloc[0]
            summary["by_homes_floor"].setdefault(name, {})[f"{hf:.0%}"] = {
                "critical": round(float(r.critical), 4), "homes": round(float(r.homes), 4)}
    fronts = {n: pareto(df[df.scenario == n], "homes", "critical") for n in df.scenario.unique()}
    plots.floor_frontier(df, fronts, chosen, shared, OUT / "fig9_floor_optimization.png")
    json.dump(summary, open(OUT / "floor_search.json", "w"), indent=2)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
