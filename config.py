"""
config.py: EVERY assumption in the model lives here.

If a judge asks "where did that number come from?", the answer is in this file.
Each value has a note. Values marked VERIFY need a source before the deck goes out.
Change a number here and every result updates when you rerun run_all.py.
"""

# ---------------------------------------------------------------------------
# SITE: Ancotanga, Caracollo municipality, Oruro, Bolivia
# ---------------------------------------------------------------------------
SITE_NAME = "Ancotanga, Oruro, Bolivia"
LATITUDE = -17.7656     # from the NASA POWER file the team downloaded
LONGITUDE = -67.4383
ELEVATION_M = 3730     # reported altitude of the Oruro solar plant site

# ---------------------------------------------------------------------------
# SOLAR PANELS
# ---------------------------------------------------------------------------
# Southern hemisphere, so panels face NORTH (azimuth 0 deg).
# Tilt a bit steeper than latitude to favor winter (June-August) when sun is low.
PANEL_TILT_DEG = 25
PANEL_AZIMUTH_DEG = 0
TEMP_COEFF_PER_C = -0.0035   # power change per deg C of cell temp (typical mono-Si datasheet)
SYSTEM_LOSSES = 0.12         # wiring, mismatch, inverter clipping (PVWatts default is ~14%)

# ---------------------------------------------------------------------------
# BATTERY (lithium iron phosphate, LFP)
# ---------------------------------------------------------------------------
BATTERY_MIN_SOC = 0.10       # never drain below 10% (protects battery life)
ROUND_TRIP_EFF = 0.92        # typical LFP
INVERTER_EFF = 0.95
MAX_C_RATE = 0.5             # max charge/discharge power = 0.5 x capacity per hour
# Cold effects (LFP datasheets): capacity drops in the cold, and charging
# below 0 C causes lithium plating, so the battery management system blocks it.
NO_CHARGE_BELOW_C = 0.0
CAPACITY_AT_25C = 1.00
CAPACITY_AT_MINUS10C = 0.80  # linear in between; VERIFY against a real LFP datasheet

# ---------------------------------------------------------------------------
# BATTERY HOUSING: the three designs we compare
# tau = thermal time constant in hours (how slowly the box follows outside air)
# ---------------------------------------------------------------------------
ENCLOSURES = {
    "Outdoor metal cabinet": {"type": "air", "tau_h": 3},
    "Insulated adobe room": {"type": "air", "tau_h": 30},
    "Earth vault (1 m deep)": {"type": "ground", "depth_m": 1.0},
}
SOIL_DIFFUSIVITY = 5e-7      # m^2/s, typical dry sandy/loamy soil

# ---------------------------------------------------------------------------
# COMMUNITY LOADS: ranked by the community (1 = most important)
# kWh per day and the hours they run. VERIFY household count with census data.
# ---------------------------------------------------------------------------
N_HOUSEHOLDS = 60
LOADS = {
    # Water pump: 60 homes x 5 people x 30 L = 9 m^3/day, lifted 40 m,
    # pump efficiency 40% -> 9000 kg * 9.81 * 40 m / 0.40 / 3.6e6 = 2.45 kWh/day
    "Water pump": {"rank": 1, "kwh_day": 2.45, "hours": list(range(10, 15)), "days": "all"},
    # Health post: vaccine fridge runs 24 h, plus lights and equipment by day
    "Health post": {"rank": 2, "kwh_day": 3.0, "hours": "fridge_plus_day", "days": "all"},
    # School: morning shift, weekdays, school year Feb-Nov with July winter break
    "School": {"rank": 3, "kwh_day": 4.0, "hours": list(range(8, 13)), "days": "school"},
    # Homes: lights, phone charging, radio/TV, mostly evening
    "Homes": {"rank": 4, "kwh_day": 0.5 * N_HOUSEHOLDS, "hours": "evening", "days": "all"},
}

# Priority dispatch: each tier may only draw the battery down to this level.
# Low-priority loads get cut off early so energy is saved for the top tiers.
RESERVE_FLOORS = {"Water pump": 0.10, "Health post": 0.10, "School": 0.15, "Homes": 0.15}
# Chosen by optimize_floors.py: the lowest cut-off that keeps pump + clinic at 100% even in a
# stress year (old panels, heavy dust, worn battery, +50% household demand). Was 25%/30% by hand.

# ---------------------------------------------------------------------------
# MONTE CARLO uncertainty ranges
# ---------------------------------------------------------------------------
N_MONTE_CARLO = 1000
PV_DEGRADATION_PER_YR = (0.004, 0.010)  # 0.4%-1.0% per year
SYSTEM_AGE_YR = (0, 15)
DRY_SEASON_SOILING = (0.02, 0.08)        # dust loss May-Oct
INVERTER_FAILURE_PROB_PER_YR = 0.10
REPAIR_DAYS = (7, 42)                    # remote site: parts take weeks
HOUSEHOLD_DEMAND_GROWTH = (1.0, 1.5)     # people buy appliances once powered
BATTERY_FADE_PER_YR = 0.02

# ---------------------------------------------------------------------------
# ECONOMICS (USD). VERIFY all against ESMAP mini-grid cost reports.
# ---------------------------------------------------------------------------
PV_COST_PER_KW = 900
BATTERY_COST_PER_KWH = 350
INVERTER_COST_PER_KW = 400
CONTROLLER_RELAYS_COST = 1500   # priority controller: smart relays per feeder
BACKUP_INVERTER_COST = 600      # small 1.5 kW inverter wired only to pump + health post
DISTRIBUTION_PER_HOME = 250
EARTH_VAULT_COST = 800          # local labor + adobe/earth
OM_FRACTION_PER_YR = 0.02
BATTERY_LIFE_YR = 10
PROJECT_LIFE_YR = 20
DISCOUNT_RATE = 0.08

# Diesel baseline
DIESEL_GENSET_COST_PER_KW = 500
DIESEL_L_PER_KWH = 0.45         # small gensets at part load are inefficient
DIESEL_PRICE_USD_PER_L = 1.63   # Bs 17.95/L since Sept 19, 2026 at ~Bs 11/USD parallel rate (Rio Times)
DIESEL_TRANSPORT_USD_PER_L = 0.15
DIESEL_OM_USD_PER_KWH = 0.05
GENSET_LIFE_YR = 7
