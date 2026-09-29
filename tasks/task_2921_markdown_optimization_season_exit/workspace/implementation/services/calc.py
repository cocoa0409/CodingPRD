"""Deterministic calculations (PRD 2.8, 3.2, 3.3, 3.4, 3.5, 3.7, 3.8, 3.9)."""

import math
from decimal import Decimal

from common import (clamp, days_between, dec, r2, r4, rc, round_half_up,
                    whole_weeks)

# --- global constants -----------------------------------------------------
MIN_CADENCE_DAYS = 14
MAX_LADDER_STEPS = 4
EXIT_BUFFER_DAYS = 7
MAX_REVISION_ROUNDS = 3
MAX_NEGOTIATION_ROUNDS = 4
EXIT_WINDOW_TRIGGER_PCT = Decimal("60.00")
EXIT_DEPTH_PCT = Decimal("50.00")

SIGNAGE_LEAD_DEFAULT_DAYS = {"CHAIN": 10, "REGION": 7, "STORE": 3}

PROTECTION_DAYS = {
    "APPAREL": 42,
    "FOOTWEAR": 56,
    "ACCESSORIES": 28,
    "SEASONAL_DECOR": 21,
}

BASE_DEPTH_BY_STAGE = {
    "NEW_ARRIVAL": Decimal("0.00"),
    "CORE": Decimal("5.00"),
    "AGING": Decimal("15.00"),
    "CLEARANCE": Decimal("30.00"),
    "EXIT_PENDING": Decimal("50.00"),
    "DISPOSED": Decimal("0.00"),
}

ELASTICITY_FLOOR = Decimal("-4.0000")
ELASTICITY_CAP = Decimal("-0.2000")

SLOW_SELLER_SELL_THROUGH_PCT = Decimal("45.00")
SLOW_SELLER_MIN_WEEKS = 6
AGING_WEEKS_ON_HAND = 10
CLEARANCE_WEEKS_TO_EXIT = 6
EXIT_PENDING_WEEKS_TO_EXIT = 2
WEEKS_OF_SUPPLY_SENTINEL = Decimal("999.99")

JOBBER_RECOVERY_PCT = Decimal("92")
DONATION_RECOVERY_PCT = Decimal("21")

CATEGORIES = ("APPAREL", "FOOTWEAR", "ACCESSORIES", "SEASONAL_DECOR")


# --------------------------------------------------------------------------
# Item metrics (PRD 3.2)
# --------------------------------------------------------------------------

def protection_days(category):
    return PROTECTION_DAYS[category]


def sell_through_pct(units_sold_total, units_received_total):
    if not units_received_total:
        return r2(0)
    return r2(dec(units_sold_total) / dec(units_received_total) * dec(100))


def weeks_of_supply(on_hand_units, units_sold_total, sample_weeks):
    if not sample_weeks or not units_sold_total:
        return float(WEEKS_OF_SUPPLY_SENTINEL)
    average = round_half_up(dec(units_sold_total) / dec(sample_weeks), 4)
    if average <= 0:
        return float(WEEKS_OF_SUPPLY_SENTINEL)
    return r2(dec(on_hand_units) / average)


def price_relative_pct(ticket_price_cents, original_retail_cents):
    if not original_retail_cents:
        return r2(0)
    return r2(dec(ticket_price_cents) / dec(original_retail_cents) * dec(100))


# --------------------------------------------------------------------------
# Elasticity (PRD 3.4)
# --------------------------------------------------------------------------

def own_history_ok(weeks):
    """weeks must already be ordered week_ending_date ASC, created_at ASC."""
    if len(weeks) < 4:
        return False
    prices = set(w["ticket_price_cents"] for w in weeks)
    if len(prices) < 2:
        return False
    first, last = weeks[0], weeks[-1]
    if first["ticket_price_cents"] == last["ticket_price_cents"]:
        return False
    if first["units_sold"] < 1 or last["units_sold"] < 1:
        return False
    return True


def own_history_coefficient(weeks):
    first, last = weeks[0], weeks[-1]
    numerator = math.log(float(last["units_sold"]) / float(first["units_sold"]))
    denominator = math.log(float(last["ticket_price_cents"]) /
                           float(first["ticket_price_cents"]))
    raw = Decimal(repr(numerator / denominator))
    return clamp_coefficient(raw)


def pooled_coefficient(peers):
    weight_total = sum(dec(p["units_sold_total"]) for p in peers)
    if weight_total == 0:
        return clamp_coefficient(Decimal(0))
    weighted = sum(dec(p["elasticity_coefficient"]) * dec(p["units_sold_total"])
                   for p in peers)
    return clamp_coefficient(weighted / weight_total)


def clamp_coefficient(raw):
    bounded = min(ELASTICITY_CAP, max(ELASTICITY_FLOOR, dec(raw)))
    return r4(bounded)


# --------------------------------------------------------------------------
# Recommended depth (PRD 3.5)
# --------------------------------------------------------------------------

def urgency_component(weeks_to_exit):
    if weeks_to_exit > 12:
        return Decimal("0.00")
    if weeks_to_exit >= 8:
        return Decimal("5.00")
    if weeks_to_exit >= 4:
        return Decimal("10.00")
    return Decimal("20.00")


def pressure_component(weeks_of_supply_value):
    surplus = dec(weeks_of_supply_value) - Decimal("4.00")
    if surplus < 0:
        surplus = Decimal("0.00")
    scaled = round_half_up(surplus * Decimal("1.50"), 2)
    return min(Decimal("15.00"), scaled)


def elasticity_factor(coefficient):
    magnitude = abs(dec(coefficient)) / Decimal("1.50")
    return round_half_up(clamp(magnitude, Decimal("0.60"), Decimal("1.40")), 4)


def recommended_depth_pct(lifecycle_stage, weeks_to_exit,
                          weeks_of_supply_value, coefficient):
    base = BASE_DEPTH_BY_STAGE.get(lifecycle_stage, Decimal("0.00"))
    urgency = urgency_component(weeks_to_exit)
    pressure = pressure_component(weeks_of_supply_value)
    factor = elasticity_factor(coefficient)
    raw = (base + urgency + pressure) * factor
    return r2(clamp(raw, Decimal("10.00"), Decimal("70.00")))


# --------------------------------------------------------------------------
# Ladder rung price (PRD 2.8 pinned order (a))
# --------------------------------------------------------------------------

def rung_price_cents(original_retail_cents, depth_pct):
    discount = rc(dec(original_retail_cents) * dec(depth_pct) / dec(100))
    return original_retail_cents - discount


# --------------------------------------------------------------------------
# Clearance and allowance (PRD 3.7, 3.8)
# --------------------------------------------------------------------------

def exit_window_trigger_units(exit_units_target):
    return rc(dec(exit_units_target) * EXIT_WINDOW_TRIGGER_PCT / dec(100))


def eligible_funding_total(agreed_share_pct, gross_markdown_cents):
    return rc(dec(agreed_share_pct) / dec(100) * dec(gross_markdown_cents))


# --------------------------------------------------------------------------
# Disposition recovery (PRD 3.9)
# --------------------------------------------------------------------------

def disposition_recovery_cents(channel, units, unit_recovery_cents,
                               fmv_cents, item_unit_cost_cents):
    units = dec(units)
    if channel == "SALVAGE":
        return int(units * dec(unit_recovery_cents or 0))
    if channel == "JOBBER":
        return rc(units * dec(unit_recovery_cents or 0) *
                  JOBBER_RECOVERY_PCT / dec(100))
    basis = min(dec(fmv_cents or 0), dec(item_unit_cost_cents))
    return rc(units * basis * DONATION_RECOVERY_PCT / dec(100))
