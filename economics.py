"""
economics.py: what does it cost, and how does it compare to diesel?

LCOE (levelized cost of energy) = total lifetime cost, in today's dollars,
divided by total energy delivered. The standard way to compare power sources.
"""
import numpy as np
import config


def crf(rate, years):
    """Capital recovery factor: turns a lump sum into an equal yearly payment."""
    return rate * (1 + rate) ** years / ((1 + rate) ** years - 1)


def pv_of(amount, year):
    return amount / (1 + config.DISCOUNT_RATE) ** year


def solar_cost(pv_kw, batt_kwh, peak_kw, vault=True):
    inv_kw = peak_kw * 1.25
    capex = (pv_kw * config.PV_COST_PER_KW + batt_kwh * config.BATTERY_COST_PER_KWH
             + inv_kw * config.INVERTER_COST_PER_KW + config.CONTROLLER_RELAYS_COST
             + config.BACKUP_INVERTER_COST
             + config.N_HOUSEHOLDS * config.DISTRIBUTION_PER_HOME
             + (config.EARTH_VAULT_COST if vault else 0))
    npc = capex
    for y in range(1, config.PROJECT_LIFE_YR + 1):
        npc += pv_of(capex * config.OM_FRACTION_PER_YR, y)
    for y in range(config.BATTERY_LIFE_YR, config.PROJECT_LIFE_YR, config.BATTERY_LIFE_YR):
        npc += pv_of(batt_kwh * config.BATTERY_COST_PER_KWH, y)
        npc += pv_of(inv_kw * config.INVERTER_COST_PER_KW, y)
    return {"capex": capex, "npc": npc,
            "annual": npc * crf(config.DISCOUNT_RATE, config.PROJECT_LIFE_YR)}


def diesel_cost(annual_kwh, peak_kw, fuel_price=None):
    price = (fuel_price if fuel_price is not None else config.DIESEL_PRICE_USD_PER_L) \
        + config.DIESEL_TRANSPORT_USD_PER_L
    gen_kw = peak_kw * 1.25
    gen_capex = gen_kw * config.DIESEL_GENSET_COST_PER_KW
    capex = gen_capex + config.N_HOUSEHOLDS * config.DISTRIBUTION_PER_HOME
    npc = capex
    yearly = annual_kwh * (config.DIESEL_L_PER_KWH * price + config.DIESEL_OM_USD_PER_KWH)
    for y in range(1, config.PROJECT_LIFE_YR + 1):
        npc += pv_of(yearly, y)
    for y in range(config.GENSET_LIFE_YR, config.PROJECT_LIFE_YR, config.GENSET_LIFE_YR):
        npc += pv_of(gen_capex, y)
    return {"capex": capex, "npc": npc,
            "annual": npc * crf(config.DISCOUNT_RATE, config.PROJECT_LIFE_YR),
            "liters_per_yr": annual_kwh * config.DIESEL_L_PER_KWH}


def lcoe(annual_cost, annual_kwh):
    return annual_cost / annual_kwh
