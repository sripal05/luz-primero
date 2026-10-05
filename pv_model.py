"""
pv_model.py: turn sunlight + temperature into panel output.

Steps (all standard physics, done by the pvlib library from Sandia National Labs):
 1. Where is the sun each hour?               (solar position)
 2. Split sunlight into direct beam + diffuse  (Erbs model)
 3. How much hits a tilted panel?              (Hay-Davies transposition)
 4. How hot is the panel?                      (Faiman cell temperature model)
 5. Hot panels make less power, cold ones more (temperature coefficient)

Output: kW produced per 1 kW of installed panels, every hour.
The Altiplano is cold and very sunny, so panels run cooler than in most
places and produce MORE than their rating suggests. Step 5 captures that.
"""
import numpy as np
import pvlib
import config


def pv_output_per_kw(weather):
    times = weather.index + np.timedelta64(30, "m")  # middle of each hour
    sun = pvlib.solarposition.get_solarposition(times, config.LATITUDE, config.LONGITUDE,
                                                altitude=config.ELEVATION_M)
    ghi = weather["ghi"].values
    split = pvlib.irradiance.erbs(ghi, sun["zenith"].values, times.dayofyear)
    dni_extra = pvlib.irradiance.get_extra_radiation(times).values
    poa = pvlib.irradiance.get_total_irradiance(
        surface_tilt=config.PANEL_TILT_DEG, surface_azimuth=config.PANEL_AZIMUTH_DEG,
        solar_zenith=sun["apparent_zenith"].values, solar_azimuth=sun["azimuth"].values,
        dni=split["dni"], ghi=ghi, dhi=split["dhi"], dni_extra=dni_extra,
        model="haydavies", albedo=0.25)
    poa_global = np.nan_to_num(np.asarray(poa["poa_global"]), nan=0.0).clip(min=0)
    cell_temp = pvlib.temperature.faiman(poa_global, weather["temp_air"].values,
                                         np.asarray(weather["wind"], dtype=float))
    power = poa_global / 1000 * (1 + config.TEMP_COEFF_PER_C * (cell_temp - 25))
    power = power * (1 - config.SYSTEM_LOSSES)
    return np.clip(power, 0, None), np.asarray(cell_temp), poa_global
