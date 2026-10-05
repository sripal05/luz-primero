"""
battery_temp.py: how cold does the battery get in each housing design?

Why it matters: lithium batteries must NOT be charged below 0 C, and they
deliver less energy when cold. Altiplano nights regularly drop below freezing.

Two physics models:
 - "air" housings (cabinet, insulated room): the inside temperature slowly
   follows the outside air. tau (hours) sets how slowly. Bigger tau = better insulation.
 - "ground" (earth vault): soil acts like a huge thermal buffer. Daily
   temperature swings die out within ~15 cm of soil, and the yearly swing is
   shrunk and delayed with depth. Classic heat-diffusion result:
       amplitude at depth z = surface amplitude * exp(-z / d),  d = sqrt(2 * alpha / omega)
   We use AIR temperature as the surface temperature, which is conservative:
   real Altiplano soil surfaces are warmer than the air because of strong sun.
"""
import numpy as np
import config


def air_enclosure(temp_air, tau_h):
    k = 1 - np.exp(-1.0 / tau_h)
    out = np.empty_like(temp_air)
    t = float(np.mean(temp_air[:24]))
    for i, ta in enumerate(temp_air):
        t += (ta - t) * k
        out[i] = t
    return out


def earth_vault(temp_air, depth_m):
    hours = np.arange(len(temp_air))
    w = 2 * np.pi / (365.25 * 24)  # yearly cycle, radians per hour
    # Fit the yearly cycle of the air temperature: T = mean + a*cos + b*sin
    X = np.column_stack([np.ones_like(hours), np.cos(w * hours), np.sin(w * hours)])
    coef, *_ = np.linalg.lstsq(X, temp_air, rcond=None)
    mean, a, b = coef
    damping_depth = np.sqrt(2 * config.SOIL_DIFFUSIVITY / (w / 3600))  # meters
    shrink = np.exp(-depth_m / damping_depth)
    lag = depth_m / damping_depth
    amp, phase = np.hypot(a, b), np.arctan2(b, a)
    return mean + amp * shrink * np.cos(w * hours - phase - lag), damping_depth


def battery_temperature(temp_air, enclosure):
    spec = config.ENCLOSURES[enclosure]
    if spec["type"] == "air":
        return air_enclosure(np.asarray(temp_air, float), spec["tau_h"])
    return earth_vault(np.asarray(temp_air, float), spec["depth_m"])[0]


def capacity_factor(batt_temp):
    """Usable fraction of stored energy vs battery temperature (linear between datasheet points)."""
    lo, hi = config.CAPACITY_AT_MINUS10C, config.CAPACITY_AT_25C
    return np.clip(lo + (hi - lo) * (batt_temp + 10) / 35, lo, hi)
