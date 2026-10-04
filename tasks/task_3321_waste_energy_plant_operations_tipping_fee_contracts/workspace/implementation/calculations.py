"""Calculations per scaffold §calculations and PRD §3."""

import calendar
import math
from datetime import timedelta

from decimal import Decimal

from helpers import round3, round6, round_cents

DAILY_CAPACITY_TONNES = Decimal("1000")
STEAM_EFFICIENCY_TPH_PER_MW = Decimal("0.32")
ASH_FRACTION = Decimal("0.25")
MONTHS_PER_YEAR = 12


def compute_tipping_fee(tonnes, rate_cents):
    return round_cents(Decimal(str(tonnes)) * Decimal(rate_cents))


def effective_capacity(boiler):
    if boiler["status"] == "DERATED":
        return Decimal(str(boiler["derated_capacity_mw"]))
    if boiler["status"] == "ONLINE":
        return Decimal(str(boiler["max_thermal_capacity_mw"]))
    return Decimal("0")


def compute_thermal_input(waste_tonnes, hv, hours):
    return (Decimal(str(waste_tonnes)) * Decimal(str(hv)) * Decimal(1000)
            / Decimal(3600) / Decimal(str(hours)))


def compute_report_fields(report, boilers):
    """Pinned order: thermal input, capacity check, steam output, ash."""
    thermal = round3(compute_thermal_input(
        report["waste_processed_tonnes"], report["avg_heating_value_mj_per_kg"],
        report["operating_hours"]))
    cap_sum = sum((effective_capacity(b) for b in boilers), Decimal("0"))
    capacity_check = "OK" if thermal <= cap_sum else "EXCEEDS"
    raw_steam = thermal * STEAM_EFFICIENCY_TPH_PER_MW
    steam_cap = sum(
        (Decimal(str(b["max_steam_tph"])) for b in boilers
         if b["status"] in ("ONLINE", "DERATED")), Decimal("0"))
    steam = min(raw_steam, steam_cap)
    ash = Decimal(str(report["waste_processed_tonnes"])) * ASH_FRACTION
    report["thermal_input_mw"] = float(thermal)
    report["capacity_check"] = capacity_check
    report["steam_output_tph"] = float(round3(steam))
    report["ash_generated_tonnes"] = float(round3(ash))


def compute_energy_billing(ppa, delivered_mwh, merchant_price):
    if ppa["kind"] == "PPA":
        return round_cents(Decimal(str(delivered_mwh)) * Decimal(ppa["energy_rate_cents_per_mwh"]))
    return round_cents(Decimal(str(delivered_mwh)) * Decimal(merchant_price))


def seconds_in_month(dt):
    days = calendar.monthrange(dt.year, dt.month)[1]
    return days * 86400


def compute_capacity_payment(ppa, period_start, period_end, boilers):
    if ppa["kind"] == "MERCHANT":
        return 0
    available = sum((effective_capacity(b) for b in boilers), Decimal("0"))
    mw = min(Decimal(str(ppa["contracted_mw"])), available)
    period_secs = Decimal(str((period_end - period_start).total_seconds()))
    month_secs = Decimal(seconds_in_month(period_start))
    fraction = round6(period_secs / month_secs)
    if fraction > 1:
        fraction = Decimal("1")
    return round_cents(mw * Decimal(ppa["capacity_payment_cents_per_mw_month"]) * fraction)


def compute_metals_settlement(batch, contract):
    ash = Decimal(str(batch["ash_input_tonnes"]))
    ferrous_t = round3(ash * Decimal(str(contract["ferrous_recovery_pct"])))
    nonferrous_t = round3(ash * Decimal(str(contract["nonferrous_recovery_pct"])))
    ferrous_rev = round_cents(ferrous_t * Decimal(batch["ferrous_price_cents_per_tonne"]))
    nonferrous_rev = round_cents(nonferrous_t * Decimal(batch["nonferrous_price_cents_per_tonne"]))
    gross = ferrous_rev + nonferrous_rev
    fee = round_cents(ash * Decimal(contract["processing_fee_cents_per_tonne"]))
    batch["ferrous_tonnes"] = float(ferrous_t)
    batch["nonferrous_tonnes"] = float(nonferrous_t)
    batch["gross_revenue_cents"] = gross
    batch["processing_fee_cents"] = fee
    batch["net_settlement_cents"] = gross - fee


def outage_length_days(outage):
    secs = (outage["ends_at"] - outage["starts_at"]).total_seconds()
    return math.ceil(secs / 86400)


def month_period(now):
    from datetime import datetime, timezone
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    if now.month == 12:
        end = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc)
    else:
        end = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc)
    return start, end


def annual_period(agreement, now):
    """Contract year containing now, anchored at term_start anniversaries."""
    ts = agreement["term_start"]
    start = ts
    while True:
        try:
            nxt = start.replace(year=start.year + 1)
        except ValueError:
            # Feb 29 -> Feb 28 of following year
            nxt = start.replace(year=start.year + 1, day=28)
        if now < nxt or nxt >= agreement["term_end"]:
            return start, min(nxt, agreement["term_end"])
        start = nxt
