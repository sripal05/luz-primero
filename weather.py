"""
weather.py: load NASA POWER weather data and turn it into hourly sun + temperature.

Handles both files you might download:
  - hourly CSV (preferred): used as-is
  - daily CSV (fallback): each day's sunlight is spread across the hours using
    the shape of a clear-sky day, so the daily total still matches NASA exactly.
"""
import numpy as np
import pandas as pd
import pvlib
import config


def _read_power_csv(path):
    """NASA CSVs have a text header block. Skip it and read the table."""
    with open(path) as f:
        lines = f.readlines()
    start = next(i for i, l in enumerate(lines) if "-END HEADER-" in l) + 1
    df = pd.read_csv(path, skiprows=start)
    df = df.replace(-999, np.nan)  # NASA marks missing values as -999
    return df


def _location():
    return pvlib.location.Location(config.LATITUDE, config.LONGITUDE,
                                   tz="UTC", altitude=config.ELEVATION_M)


def load_hourly(path):
    df = _read_power_csv(path)
    # NASA "LST" = local solar time. Convert to UTC: UTC = solar time - longitude/15 h
    local = pd.to_datetime(dict(year=df.YEAR, month=df.MO, day=df.DY, hour=df.HR))
    utc = local - pd.to_timedelta(config.LONGITUDE / 15, unit="h")
    out = pd.DataFrame({
        "ghi": df.ALLSKY_SFC_SW_DWN.values,   # W/m2, sunlight on flat ground
        "temp_air": df.T2M.values,            # deg C
        "wind": df.WS10M.values if "WS10M" in df else 2.0,
        "local_time": local.values,
    }, index=pd.DatetimeIndex(utc, tz="UTC"))
    out = out.interpolate(limit=6).fillna(0)
    out["ghi"] = out["ghi"].clip(lower=0)
    return out


def load_daily(path):
    df = _read_power_csv(path)
    if "DOY" in df:
        dates = pd.to_datetime(df.YEAR.astype(str), format="%Y") + pd.to_timedelta(df.DOY - 1, unit="D")
    else:
        dates = pd.to_datetime(dict(year=df.YEAR, month=df.MO, day=df.DY))
    daily = pd.DataFrame({"kwh": df.ALLSKY_SFC_SW_DWN.values, "tmean": df.T2M.values,
                          "tmin": df.T2M_MIN.values,
                          "wind": df.WS10M.values if "WS10M" in df else 2.0},
                         index=dates).interpolate(limit=5)
    # Build hourly timestamps in local solar time, then UTC
    local = pd.date_range(daily.index[0], daily.index[-1] + pd.Timedelta(hours=23), freq="h")
    utc = pd.DatetimeIndex(local - pd.to_timedelta(config.LONGITUDE / 15, unit="h"), tz="UTC")
    cs = _location().get_clearsky(utc + pd.Timedelta(minutes=30))["ghi"].values
    day_key = local.normalize()
    cs_day = pd.Series(cs, index=local).groupby(day_key).transform("sum").values
    kwh = daily["kwh"].reindex(day_key).values
    ghi = np.where(cs_day > 0, cs / cs_day * kwh * 1000, 0)
    # Temperature: coldest at ~6am, warmest at ~2pm (sine curve)
    tmean = daily["tmean"].reindex(day_key).values
    tmin = daily["tmin"].reindex(day_key).values
    amp = tmean - tmin
    hr = local.hour.values
    temp = tmean + amp * np.sin((hr - 8) / 24 * 2 * np.pi)
    return pd.DataFrame({"ghi": ghi, "temp_air": temp,
                         "wind": daily["wind"].reindex(day_key).values,
                         "local_time": local.values}, index=utc).fillna(0)


def load(path):
    df = _read_power_csv(path)
    return load_hourly(path) if "HR" in df.columns else load_daily(path)


def synthetic(years=(2015, 2016, 2017), seed=0):
    """TEST DATA ONLY. Fake Altiplano weather so the code can run before
    the real NASA file arrives. Never put these results in the deck."""
    rng = np.random.default_rng(seed)
    local = pd.date_range(f"{years[0]}-01-01", f"{years[-1]}-12-31 23:00", freq="h")
    utc = pd.DatetimeIndex(local - pd.to_timedelta(config.LONGITUDE / 15, unit="h"), tz="UTC")
    cs = _location().get_clearsky(utc + pd.Timedelta(minutes=30))["ghi"].values
    month = local.month.values
    rainy = np.isin(month, [12, 1, 2, 3])
    day_idx = (local.normalize() - local[0].normalize()).days.values
    n_days = day_idx.max() + 1
    cloud_day = np.where(rng.random(n_days) < 0.35, rng.uniform(0.2, 0.7, n_days), rng.uniform(0.85, 1.0, n_days))
    cloud = np.where(rainy, cloud_day[day_idx] * 0.85, np.minimum(1, cloud_day[day_idx] + 0.1))
    doy = local.dayofyear.values
    tmean = 7 + 4 * np.cos((doy - 15) / 365 * 2 * np.pi)          # colder in June-July
    swing = 9 - 3 * np.cos((doy - 15) / 365 * 2 * np.pi)          # bigger swing in dry winter
    temp = tmean + swing * np.sin((local.hour.values - 8) / 24 * 2 * np.pi)
    return pd.DataFrame({"ghi": cs * cloud, "temp_air": temp, "wind": 3.0,
                         "local_time": local.values}, index=utc)
