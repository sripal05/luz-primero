"""
plots.py: every figure for the deck. Same colors and style everywhere.
Colors come from a palette checked for colorblind readers.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

INK, INK2, GRID, BG = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
BLUE, ORANGE, AQUA, YELLOW, VIOLET = "#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#4a3aa7"
TIER_COLORS = {"Water pump": BLUE, "Health post": ORANGE, "School": AQUA, "Homes": YELLOW}
MODE_COLORS = {"priority": BLUE, "equal": ORANGE}
MODE_LABELS = {"priority": "Community-ranked (ours)", "equal": "Standard shared grid"}

plt.rcParams.update({
    "font.family": "DejaVu Sans", "font.size": 13, "axes.edgecolor": GRID,
    "axes.labelcolor": INK2, "xtick.color": INK2, "ytick.color": INK2,
    "axes.titlecolor": INK, "axes.titlesize": 15, "axes.titleweight": "bold",
    "axes.titlelocation": "left", "axes.spines.top": False, "axes.spines.right": False,
    "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.8,
    "figure.facecolor": BG, "axes.facecolor": BG, "savefig.facecolor": BG,
    "legend.frameon": False, "lines.linewidth": 2,
})

TEST_WATERMARK = False


def _save(fig, path):
    if TEST_WATERMARK:
        fig.text(0.5, 0.5, "TEST DATA - NOT REAL", fontsize=40, color="red", alpha=0.25,
                 ha="center", va="center", rotation=20)
    fig.tight_layout()
    fig.savefig(path, dpi=200)
    plt.close(fig)


def resource(monthly, path):
    """monthly: DataFrame with columns yield_kwh_per_kwp_day, tmin, indexed 1..12"""
    months = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.2))
    a.bar(range(12), monthly["yield"], color=BLUE, width=0.7)
    a.set_xticks(range(12), months)
    a.set_title("Solar output per kW of panels")
    a.set_ylabel("kWh per day")
    b.bar(range(12), monthly["tmin"], color=VIOLET, width=0.7)
    b.axhline(0, color=INK2, lw=1)
    b.set_xticks(range(12), months)
    b.set_title("Coldest hour of the month (avg)")
    b.set_ylabel("deg C")
    _save(fig, path)


def battery_temps(times, air, temps, hours_below, path):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.4), gridspec_kw={"width_ratios": [2.2, 1]})
    a.plot(times, air, color=GRID, lw=1.5, label="Outside air")
    cols = [ORANGE, YELLOW, BLUE]
    for (name, t), c in zip(temps.items(), cols):
        a.plot(times, t, color=c, label=name)
    a.axhline(0, color=INK2, lw=1, ls="--")
    a.text(times[2], 0.6, "0 C: charging blocked below", color=INK2, fontsize=11)
    a.set_title("Battery temperature, coldest week")
    a.set_ylabel("deg C")
    a.legend(loc="upper right", fontsize=10)
    a.tick_params(axis="x", rotation=30)
    names = list(hours_below)
    b.barh(names, [hours_below[n] for n in names], color=cols, height=0.6)
    for i, n in enumerate(names):
        b.text(hours_below[n], i, f"  {hours_below[n]:,.0f}", va="center", color=INK)
    b.set_title("Hours/yr below 0 C")
    b.invert_yaxis()
    b.set_xlim(0, max(hours_below.values()) * 1.35 + 1)
    _save(fig, path)


def frontier(sweep, picks, path):
    fig, ax = plt.subplots(figsize=(10, 5.6))
    for mode in ("equal", "priority"):
        s = sweep[sweep["mode"] == mode].sort_values("annual_cost")
        best = s["critical_rel"].cummax()
        front = s[s["critical_rel"] >= best - 1e-12]
        ax.scatter(s["annual_cost"] / 1000, s["critical_rel"] * 100, s=10,
                   color=MODE_COLORS[mode], alpha=0.25)
        ax.step(front["annual_cost"] / 1000, front["critical_rel"] * 100, where="post",
                color=MODE_COLORS[mode], label=MODE_LABELS[mode])
    offsets = {"priority": (-10, -60), "equal": (14, -70)}
    for mode, p in picks.items():
        if p is None:
            continue
        ax.scatter([p["annual_cost"] / 1000], [p["critical_rel"] * 100], s=90,
                   color=MODE_COLORS[mode], edgecolor=BG, linewidth=2, zorder=5)
        ax.annotate(f"${p['annual_cost']/1000:,.1f}k/yr\n{p['pv_kw']:.0f} kW solar\n{p['batt_kwh']:.0f} kWh battery",
                    (p["annual_cost"] / 1000, p["critical_rel"] * 100), xytext=offsets[mode],
                    textcoords="offset points", fontsize=11, color=INK,
                    ha="right" if mode == "priority" else "left",
                    arrowprops=dict(arrowstyle="-", color=INK2, lw=0.8))
    ax.set_ylim(90, 100.3)
    ax.set_xlabel("Annualized system cost (thousand USD per year)")
    ax.set_ylabel("Water pump + health post uptime (%)")
    ax.set_title("Cost vs. critical-load uptime across every design tested")
    ax.legend(loc="lower right")
    _save(fig, path)


def mc_hist(mc, path):
    """Two panels: critical-load uptime in bad futures, and homes uptime in a typical future."""
    designs = [("equal", "Standard shared grid", ORANGE),
               ("priority", "Community-ranked", BLUE),
               ("backup", "Ranked + backup inverter", AQUA)]
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.2))
    for i, (key, lab, c) in enumerate(designs):
        crit = np.minimum(mc[f"{key}|Water pump"], mc[f"{key}|Health post"]) * 100
        v = np.percentile(crit, 5)
        a.barh(i, v, color=c, height=0.6)
        a.text(v, i, f"  {v:.1f}%", va="center", color=INK)
        h = mc[f"{key}|Homes"].median() * 100
        b.barh(i, h, color=c, height=0.6)
        b.text(h, i, f"  {h:.1f}%", va="center", color=INK)
    for ax in (a, b):
        ax.set_yticks(range(3), [d[1] for d in designs])
        ax.invert_yaxis()
        ax.set_xlim(0, 112)
        ax.grid(axis="y", visible=False)
    b.set_yticklabels([])
    a.set_title("Pump + clinic: worst 5% of futures")
    b.set_title("Homes: typical future")
    fig.suptitle(f"{len(mc):,} simulated futures, identical solar + battery hardware",
                 x=0.01, ha="left", color=INK2, fontsize=12)
    _save(fig, path)


def growth_curve(growth, crit, homes, path):
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.4), sharex=True)
    for mode in ("equal", "priority"):
        a.plot((growth - 1) * 100, np.array(crit[mode]) * 100, color=MODE_COLORS[mode],
               marker="o", ms=7, label=MODE_LABELS[mode])
        b.plot((growth - 1) * 100, np.array(homes[mode]) * 100, color=MODE_COLORS[mode],
               marker="o", ms=7)
    a.set_title("Water pump + health post uptime")
    b.set_title("Homes uptime")
    for ax in (a, b):
        ax.set_xlabel("Household demand growth after electrification (%)")
        ax.set_ylabel("% of hours with power")
    a.legend(loc="lower left")
    _save(fig, path)


def worst_week(times, soc, served, names, pv, load_total, demand, path):
    fig, (a, b) = plt.subplots(2, 1, figsize=(11, 5.8), sharex=True,
                               gridspec_kw={"height_ratios": [1.6, 1]})
    a.fill_between(times, pv, color=YELLOW, alpha=0.5, label="Solar", lw=0)
    a.plot(times, load_total, color=INK2, lw=1.3, label="Demand")
    a.set_ylabel("kW")
    a.set_title("Worst cloudy week in the record: who keeps power?")
    a.legend(loc="upper right", fontsize=10)
    t = np.array(times)
    for j, n in enumerate(names):
        on = served[:, j]
        off = (demand[:, j] > 0) & ~on
        b.scatter(t[on], np.full(on.sum(), j), s=6, color=TIER_COLORS[n], marker="s")
        b.scatter(t[off], np.full(off.sum(), j), s=10, color="#b0afa9", marker="x", lw=1)
    b.set_yticks(range(len(names)), names)
    b.invert_yaxis()
    b.set_title("Hours with power (squares) vs. cut off (gray x)", fontsize=13)
    b.grid(False)
    b.tick_params(axis="x", rotation=30)
    _save(fig, path)


def cost_vs_diesel(prices, solar_lcoe, diesel_lcoes, current_price, path):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    ax.plot(prices, diesel_lcoes, color=ORANGE, label="Diesel generator")
    ax.axhline(solar_lcoe, color=BLUE, label="Solar microgrid (ours)")
    ax.axvline(current_price, color=INK2, lw=1, ls="--")
    ax.text(current_price, ax.get_ylim()[1] * 0.95, "  assumed price", color=INK2, fontsize=11)
    ax.set_xlabel("Diesel price at the community (USD per liter)")
    ax.set_ylabel("Cost per kWh delivered (USD)")
    ax.set_title("Lifetime cost per kWh: solar vs. diesel")
    ax.legend(loc="lower right")
    _save(fig, path)


def tornado(results, base, path):
    """results: list of (label, low_value, high_value)"""
    results = sorted(results, key=lambda r: abs(r[2] - r[1]))
    fig, ax = plt.subplots(figsize=(10, 4.8))
    for i, (lab, lo, hi) in enumerate(results):
        ax.barh(i, lo - base, left=base, color=BLUE, height=0.6)
        ax.barh(i, hi - base, left=base, color=ORANGE, height=0.6)
    ax.set_yticks(range(len(results)), [r[0] for r in results])
    ax.axvline(base, color=INK, lw=1)
    ax.set_xlabel("Solar cost per kWh (USD)")
    ax.set_title("Which assumptions matter most?")
    ax.text(0.99, 0.02, "blue = assumption lower, orange = higher", transform=ax.transAxes,
            ha="right", color=INK2, fontsize=11)
    _save(fig, path)


def floor_frontier(df, fronts, chosen, shared, path):
    """Uptime vs. the homes cut-off level, typical and stress year, vs. a shared grid."""
    fig, (a, b) = plt.subplots(1, 2, figsize=(12, 4.6))
    styles = {"Typical year": dict(ls="--", marker="o", mfc=BG), "Stress year": dict(ls="-", marker="o")}
    for name, st in styles.items():
        d = df[(df.scenario == name) &
               np.isclose(df.school_floor, np.minimum(chosen["School"], df.homes_floor))]
        d = d.sort_values("homes_floor")
        a.plot(d.homes_floor * 100, d.homes * 100, color=YELLOW, ms=6, label=name, **st)
        b.plot(d.homes_floor * 100, d.critical * 100, color=BLUE, ms=6, label=name, **st)
    s = shared["Stress year"]
    a.axhline(s["homes"] * 100, color=ORANGE, lw=1.5)
    a.text(60, s["homes"] * 100 + 0.6, "shared grid, stress year", color=INK2, fontsize=10, ha="right")
    b.axhline(s["critical"] * 100, color=ORANGE, lw=1.5)
    b.text(60, s["critical"] * 100 + 0.4, "shared grid, stress year", color=INK2, fontsize=10, ha="right")
    for ax in (a, b):
        ax.axvline(chosen["Homes"] * 100, color=INK2, lw=1, ls=":")
        ax.set_xlabel("Battery level where homes are cut off (%)")
        ax.set_ylabel("% of hours with power")
    a.text(chosen["Homes"] * 100 + 1, a.get_ylim()[0] + 0.5, "our choice", color=INK2, fontsize=11)
    a.set_title("Homes")
    b.set_title("Water pump + health post")
    b.set_ylim(85, 100.8)
    a.legend(loc="upper right", fontsize=10)
    _save(fig, path)
