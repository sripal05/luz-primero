"""
loads.py: how much electricity each community load needs, every hour.
Returns a dict {load name: array of kW for each hour}.
"""
import numpy as np
import config


def _spread(kwh_day, hours, hour_of_day):
    """Spread a daily total evenly across the given hours."""
    on = np.isin(hour_of_day, hours)
    return np.where(on, kwh_day / len(hours), 0.0)


def build_loads(weather, household_growth=1.0):
    local = weather["local_time"]
    hr = local.dt.hour.values if hasattr(local, "dt") else local.hour.values
    month = local.dt.month.values
    day = local.dt.day.values
    weekday = local.dt.weekday.values < 5
    loads = {}

    p = config.LOADS["Water pump"]
    loads["Water pump"] = _spread(p["kwh_day"], p["hours"], hr)

    h = config.LOADS["Health post"]
    fridge = 1.0  # kWh/day vaccine fridge, runs around the clock
    loads["Health post"] = fridge / 24 + _spread(h["kwh_day"] - fridge, list(range(8, 18)), hr)

    s = config.LOADS["School"]
    in_session = weekday & (month >= 2) & (month <= 11) & ~((month == 7) & (day <= 21))
    loads["School"] = np.where(in_session, _spread(s["kwh_day"], s["hours"], hr), 0.0)

    homes = config.LOADS["Homes"]["kwh_day"] * household_growth
    shape = np.zeros(24)
    shape[[18, 19, 20, 21, 22]] = 0.70 / 5   # evening peak: lights, TV, radio
    shape[[6, 7]] = 0.15 / 2                 # morning
    shape[list(range(8, 18))] = 0.15 / 10    # daytime phone charging etc.
    loads["Homes"] = homes * shape[hr]
    return loads
