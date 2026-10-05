"""
run_all.py: runs the whole study and writes every figure + number to results/.

Usage:
    python run_all.py path/to/nasa_power.csv     (real data, for the deck)
    python run_all.py                              (fake test data, watermarked)
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

import battery_temp
import config
import dispatch
import economics as econ
import loads as loads_mod
import montecarlo
import plots
import pv_model
import weather

OUT = Path("results")
OUT.mkdir(exist_ok=True)
CRIT_TARGET = 0.995  # water pump + health post must be on 99.5% of the hours they need power
HOMES_TARGET = 0.95  # fairness rule: homes must still get power 95% of the hours they need it


def main():
    if len(sys.argv) > 1:
        w = weather.load(sys.argv[1])
        print(f"Loaded REAL data: {len(w):,} hours")
    else:
        w = weather.synthetic()
        plots.TEST_WATERMARK = True
        print("WARNING: using fake test weather. Results are NOT for the deck.")
    lt = w["local_time"]
    years = lt.dt.year.values
    n_years = len(w) / 8766
    res = {"site": config.SITE_NAME, "hours": len(w), "years": round(n_years, 1),
           "real_data": len(sys.argv) > 1}

    # 1. Solar resource ------------------------------------------------------
    pv, cell_t, poa = pv_model.pv_output_per_kw(w)
    df = pd.DataFrame({"pv": pv, "t": w["temp_air"].values, "m": lt.dt.month.values,
                       "d": lt.dt.normalize().values})
    daily = df.groupby("d").agg(pv=("pv", "sum"), tmin=("t", "min"), m=("m", "first"))
    monthly = daily.groupby("m").agg(**{"yield": ("pv", "mean"), "tmin": ("tmin", "mean")})
    plots.resource(monthly, OUT / "fig1_resource.png")
    res["specific_yield_kwh_per_kwp_yr"] = round(pv.sum() / n_years)
    res["ghi_kwh_m2_day"] = round(w["ghi"].sum() / 1000 / (len(w) / 24), 2)
    res["hours_below_0C_air_per_yr"] = round((w["temp_air"] < 0).sum() / n_years)
    res["coldest_air_C"] = round(float(w["temp_air"].min()), 1)
    print("Specific yield:", res["specific_yield_kwh_per_kwp_yr"], "kWh/kWp/yr")

    # 2. Battery housing -----------------------------------------------------
    temps = {k: battery_temp.battery_temperature(w["temp_air"].values, k) for k in config.ENCLOSURES}
    below = {k: (v < 0).sum() / n_years for k, v in temps.items()}
    daily_mean = pd.Series(w["temp_air"].values).rolling(24 * 7).mean()
    i_cold = int(daily_mean.idxmin())
    sl = slice(max(0, i_cold - 24 * 7), i_cold)
    plots.battery_temps(lt.values[sl], w["temp_air"].values[sl],
                        {k: v[sl] for k, v in temps.items()}, below, OUT / "fig2_battery_temp.png")
    res["battery_hours_below_0C_per_yr"] = {k: round(v) for k, v in below.items()}
    _, damping = battery_temp.earth_vault(w["temp_air"].values, 1.0)
    res["soil_annual_damping_depth_m"] = round(float(damping), 2)
    bt = temps["Earth vault (1 m deep)"]

    # 3. Loads ---------------------------------------------------------------
    L = loads_mod.build_loads(w)
    total = sum(L.values())
    peak = float(total.max())
    annual_kwh = total.sum() / n_years
    res["annual_demand_kwh"] = round(annual_kwh)
    res["peak_kw"] = round(peak, 2)

    # 4. Sizing sweep --------------------------------------------------------
    rows = []
    for pv_kw in np.arange(4, 32, 3):
        for b in np.arange(10, 130, 10):
            cost = econ.solar_cost(pv_kw, b, peak)["annual"]
            for mode in ("priority", "equal"):
                rel, en, _ = dispatch.simulate(pv, L, pv_kw, b, bt, mode)
                rows.append({"pv_kw": pv_kw, "batt_kwh": b, "mode": mode, "annual_cost": cost,
                             "critical_rel": min(rel["Water pump"], rel["Health post"]),
                             **{f"rel_{k}": v for k, v in rel.items()},
                             **{f"energy_{k}": v for k, v in en.items()}})
        print(f"  sweep: PV {pv_kw} kW done")
    sweep = pd.DataFrame(rows)
    sweep.to_csv(OUT / "sizing_sweep.csv", index=False)
    picks = {}
    for mode in ("priority", "equal"):
        ok = sweep[(sweep["mode"] == mode) & (sweep["critical_rel"] >= CRIT_TARGET)
                   & (sweep["rel_Homes"] >= HOMES_TARGET)]
        picks[mode] = ok.sort_values("annual_cost").iloc[0].to_dict() if len(ok) else None
    plots.frontier(sweep, picks, OUT / "fig3_frontier.png")
    res["picks"] = {m: ({k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}
                        if p else None) for m, p in picks.items()}
    if picks["priority"] and picks["equal"]:
        res["cost_saving_pct"] = round(100 * (1 - picks["priority"]["annual_cost"] / picks["equal"]["annual_cost"]), 1)
    p = picks["priority"]
    print("Priority pick:", p and (p["pv_kw"], p["batt_kwh"], round(p["annual_cost"])))
    print("Equal pick:", picks["equal"] and (picks["equal"]["pv_kw"], picks["equal"]["batt_kwh"]))
    if p is None:
        print("No design met the target. Widen the sweep.")
        json.dump(res, open(OUT / "results.json", "w"), indent=2, default=str)
        return

    # Housing matters? rerun the chosen design with each enclosure
    res["housing_effect"] = {}
    for k, v in temps.items():
        rel, _, x = dispatch.simulate(pv, L, p["pv_kw"], p["batt_kwh"], v, "priority")
        res["housing_effect"][k] = {"critical_rel": round(min(rel["Water pump"], rel["Health post"]), 4),
                                    "homes_rel": round(rel["Homes"], 4),
                                    "solar_wasted_cold_kwh_yr": round(x["lost_cold_kwh"] / n_years)}

    # 5. Monte Carlo ---------------------------------------------------------
    mc = montecarlo.run(w, pv, bt, p["pv_kw"], p["batt_kwh"])
    mc.to_csv(OUT / "monte_carlo.csv", index=False)
    plots.mc_hist(mc, OUT / "fig4_monte_carlo.png")
    res["monte_carlo"] = {}
    for mode in ("priority", "equal", "backup"):
        crit = np.minimum(mc[f"{mode}|Water pump"], mc[f"{mode}|Health post"])
        nf = ~mc["inverter_failed"]
        res["monte_carlo"][mode] = {"median": round(float(crit.median()), 4),
                                    "p5": round(float(np.percentile(crit, 5)), 4),
                                    "min": round(float(crit.min()), 4),
                                    "no_failure_min": round(float(crit[nf].min()), 4),
                                    "no_failure_median": round(float(crit[nf].median()), 4),
                                    "school_median": round(float(mc[f"{mode}|School"].median()), 4),
                                    "homes_median": round(float(mc[f"{mode}|Homes"].median()), 4)}
    res["monte_carlo"]["runs_with_inverter_failure"] = int(mc["inverter_failed"].sum())
    nf = mc[~mc["inverter_failed"]]
    eq = np.minimum(nf["equal|Water pump"], nf["equal|Health post"])
    res["monte_carlo"]["corr_equal_crit_vs_growth"] = round(float(np.corrcoef(eq, nf["growth"])[0, 1]), 3)

    # 5b. Demand growth stress test (full 20-year record) ---------------------
    growth = np.round(np.arange(1.0, 1.61, 0.1), 2)
    crit_g, homes_g = {"priority": [], "equal": []}, {"priority": [], "equal": []}
    for g in growth:
        Lg = loads_mod.build_loads(w, household_growth=g)
        for mode in ("priority", "equal"):
            rel, _, _ = dispatch.simulate(pv, Lg, p["pv_kw"], p["batt_kwh"], bt, mode)
            crit_g[mode].append(min(rel["Water pump"], rel["Health post"]))
            homes_g[mode].append(rel["Homes"])
    plots.growth_curve(growth, crit_g, homes_g, OUT / "fig8_demand_growth.png")
    res["demand_growth"] = {"growth": growth.tolist(),
                            "critical": {m: [round(v, 4) for v in crit_g[m]] for m in crit_g},
                            "homes": {m: [round(v, 4) for v in homes_g[m]] for m in homes_g}}

    # 6. Worst week ----------------------------------------------------------
    rel, en, x = dispatch.simulate(pv, L, p["pv_kw"], p["batt_kwh"], bt, "priority", return_soc=True)
    pv_week = pd.Series(pv).rolling(24 * 7).sum()
    j = int(pv_week.idxmin())
    s = slice(j - 24 * 7 + 1, j + 1)
    dem = np.column_stack([L[k] for k in x["names"]])
    plots.worst_week(lt.values[s], x["soc"][s], x["served"][s], x["names"],
                     pv[s] * p["pv_kw"], total[s], dem[s], OUT / "fig5_worst_week.png")
    res["worst_week_ending"] = str(lt.values[j])[:10]
    res["worst_week_served_pct"] = {n: round(float(x["served"][s][:, i][
        np.column_stack([L[k] for k in x["names"]])[s][:, i] > 0].mean()) * 100, 1)
        for i, n in enumerate(x["names"])}

    # 7. Economics -----------------------------------------------------------
    served_kwh = sum(L[k].sum() * en[k] for k in L) / n_years
    sc = econ.solar_cost(p["pv_kw"], p["batt_kwh"], peak)
    solar_lcoe = econ.lcoe(sc["annual"], served_kwh)
    prices = np.linspace(0.4, 2.0, 33)
    d_lcoe = [econ.lcoe(econ.diesel_cost(annual_kwh, peak, fp)["annual"], annual_kwh) for fp in prices]
    plots.cost_vs_diesel(prices, solar_lcoe, d_lcoe, config.DIESEL_PRICE_USD_PER_L, OUT / "fig6_vs_diesel.png")
    dc = econ.diesel_cost(annual_kwh, peak)
    res["economics"] = {"solar_capex": round(sc["capex"]), "solar_lcoe": round(solar_lcoe, 3),
                        "diesel_lcoe": round(econ.lcoe(dc["annual"], annual_kwh), 3),
                        "diesel_liters_avoided_per_yr": round(dc["liters_per_yr"]),
                        "co2_avoided_t_per_yr": round(dc["liters_per_yr"] * 2.68 / 1000, 1),
                        "capex_per_household": round(sc["capex"] / config.N_HOUSEHOLDS)}
    breakeven = next((fp for fp, dl in zip(prices, d_lcoe) if dl >= solar_lcoe), None)
    res["economics"]["breakeven_diesel_price"] = breakeven and round(float(breakeven), 2)

    # 8. Sensitivity (tornado) ----------------------------------------------
    def lcoe_with(**over):
        old = {k: getattr(config, k) for k in over}
        for k, v in over.items():
            setattr(config, k, v)
        val = econ.lcoe(econ.solar_cost(p["pv_kw"], p["batt_kwh"], peak)["annual"], served_kwh)
        for k, v in old.items():
            setattr(config, k, v)
        return val
    tests = [("Battery price +/-30%", "BATTERY_COST_PER_KWH", 0.7, 1.3),
             ("Panel price +/-30%", "PV_COST_PER_KW", 0.7, 1.3),
             ("Discount rate 5% / 12%", "DISCOUNT_RATE", 5 / 8, 12 / 8),
             ("Battery life 14 / 7 yr", "BATTERY_LIFE_YR", 14 / 10, 7 / 10),
             ("Wiring per home +/-30%", "DISTRIBUTION_PER_HOME", 0.7, 1.3)]
    tor = []
    for lab, key, lo, hi in tests:
        base_v = getattr(config, key)
        conv = (lambda v: int(round(v))) if isinstance(base_v, int) else float
        tor.append((lab, lcoe_with(**{key: conv(base_v * lo)}), lcoe_with(**{key: conv(base_v * hi)})))
    plots.tornado(tor, solar_lcoe, OUT / "fig7_sensitivity.png")
    res["sensitivity"] = {t[0]: [round(t[1], 3), round(t[2], 3)] for t in tor}

    json.dump(res, open(OUT / "results.json", "w"), indent=2, default=str)
    print(json.dumps(res, indent=2, default=str))


if __name__ == "__main__":
    main()
