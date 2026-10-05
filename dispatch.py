"""
dispatch.py: the heart of the model. Runs the microgrid hour by hour.

Each hour:
  1. Solar power goes to loads first, in priority order.
  2. If solar isn't enough, a load may draw from the battery, but only
     down to its RESERVE FLOOR. Homes get cut at 45% charge, the school at 35%,
     so the last part of the battery is saved for the water pump and health post.
  3. Leftover solar charges the battery (unless the battery is below 0 C).

Two modes:
  "priority": the community-ranked design above (needs one smart relay per load).
  "equal":    a normal shared grid. If the total demand can't be met, the whole
              grid browns out and EVERYONE loses power. This is the baseline.

Result: for each load, the % of hours it needed power and got it.
"""
import numpy as np
import config
from battery_temp import capacity_factor


def simulate(pv_per_kw, loads, pv_kw, batt_kwh, batt_temp, mode="priority",
             outage=None, pv_derate=None, batt_fade=1.0, return_soc=False,
             critical_backup=False):
    """critical_backup=True: a small second inverter wired only to the water pump and
    health post, so they keep running if the main inverter breaks."""
    n = len(pv_per_kw)
    names = sorted(loads, key=lambda k: config.LOADS[k]["rank"])
    L = np.column_stack([loads[k] for k in names])
    floors = np.array([config.RESERVE_FLOORS[k] if mode == "priority" else config.BATTERY_MIN_SOC
                       for k in names])
    pv = pv_per_kw * pv_kw * (pv_derate if pv_derate is not None else 1.0)
    cap = batt_kwh * batt_fade
    tf = capacity_factor(batt_temp)
    can_charge = batt_temp > config.NO_CHARGE_BELOW_C
    out_eff = config.INVERTER_EFF * np.sqrt(config.ROUND_TRIP_EFF)  # battery -> load
    in_eff = np.sqrt(config.ROUND_TRIP_EFF)                         # solar -> battery
    pmax = config.MAX_C_RATE * cap
    outage = outage if outage is not None else np.zeros(n, bool)
    crit_mask = np.array([config.LOADS[k]["rank"] <= 2 for k in names])

    served = np.zeros_like(L, dtype=bool)
    soc_log = np.empty(n) if return_soc else None
    E = 0.6 * cap
    lost_cold = 0.0
    curtailed = 0.0
    for t in range(n):
        need = L[t]
        if outage[t]:
            # Main inverter broken. Panels still charge the battery through the separate
            # MPPT charge controller (DC-coupled design); only the backup feeder can deliver.
            if critical_backup and mode == "priority":
                need = np.where(crit_mask, need, 0.0)  # only pump + clinic stay wired
            else:
                need = np.zeros_like(need)
        sol = pv[t] * config.INVERTER_EFF
        drawn = 0.0
        if mode == "priority":
            for j in range(len(names)):
                d = need[j]
                if d <= 0:
                    continue
                use = min(d, sol)
                sol -= use
                rest = d - use
                if rest <= 1e-9:
                    served[t, j] = True
                    continue
                dc = rest / out_eff
                avail = (E - floors[j] * cap) * tf[t]
                if dc <= avail and drawn + dc <= pmax:
                    E -= dc
                    drawn += dc
                    served[t, j] = True
        else:
            total = need.sum()
            use = min(total, sol)
            rest = total - use
            dc = rest / out_eff
            if rest <= 1e-9 or (dc <= (E - floors[0] * cap) * tf[t] and dc <= pmax):
                sol -= use
                E -= dc if rest > 1e-9 else 0
                served[t] = need > 0
            # else: blackout, solar left over goes to charging below
        surplus_dc = sol / config.INVERTER_EFF
        if surplus_dc > 0:
            if can_charge[t]:
                add = min(surplus_dc * in_eff, cap - E, pmax)
                E += add
                curtailed += surplus_dc - add / in_eff
            else:
                lost_cold += surplus_dc
        if return_soc:
            soc_log[t] = E / cap if cap else 0

    demand_hours = L > 0
    reliability = {k: served[:, j][demand_hours[:, j]].mean() for j, k in enumerate(names)}
    energy_served = {k: (L[:, j] * served[:, j]).sum() / max(L[:, j].sum(), 1e-9)
                     for j, k in enumerate(names)}
    extra = {"lost_cold_kwh": lost_cold, "curtailed_kwh": curtailed,
             "served": served, "names": names}
    if return_soc:
        extra["soc"] = soc_log
    return reliability, energy_served, extra
