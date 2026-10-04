"""Instant pricing engine (PRD 3.3, 3.7; SCAFFOLD Table 3)."""

from decimal import Decimal

from constants import (
    COMMODITY_MULTIPLE, LATE_BOOKING_SURCHARGE_PCT, LOCK_WINDOW_MINUTES,
    MARKET_LEVEL_CENTS_PER_MILE, MIN_MILES, MIN_RATE_FLOOR_CENTS,
    MIN_RATE_FLOOR_MULTIPLE, LANE_INDEX_MODULUS, LANE_INDEX_STEP,
    WEIGHT_ADJUSTMENT, d, round4, round_half_up, minutes_between, utc,
)
from db import clock_now
from errors import ApiError


def a1z26(code):
    """Each character to its alphabet position: A is one, Z is twenty-six."""
    total = 0
    for char in code:
        upper = char.upper()
        if "A" <= upper <= "Z":
            total += ord(upper) - ord("A") + 1
    return total


def lane_index_for(lane_key):
    """PRD 3.3 — 1 + ((raw mod 11) / 20), four decimals, round half up."""
    origin, _, destination = lane_key.partition(">")
    raw = a1z26(origin) + a1z26(destination)
    value = Decimal(1) + (Decimal(raw % LANE_INDEX_MODULUS) / LANE_INDEX_STEP)
    return round4(value)


def effective_miles(distance_miles):
    """Any figure below 50 miles is raised to 50 (PRD 3.3)."""
    return max(float(distance_miles), float(MIN_MILES))


def timing_band_multiple(pickup_window_start):
    """Half-open timing bands covering the whole day (PRD 3.3)."""
    hour = utc(pickup_window_start).hour
    if hour < 6:
        return Decimal("0.95")
    if hour < 15:
        return Decimal("1.10")
    if hour < 22:
        return Decimal("1.00")
    return Decimal("1.05")


def weight_adjustment_multiple(equipment_type, weight_lbs):
    """A dry van adds two hundredths to its multiple for every load above
   40,000 lb, a reefer three hundredths; a flatbed never adjusts (PRD 3.3)."""
    threshold, step = WEIGHT_ADJUSTMENT[equipment_type]
    if threshold is None:
        return Decimal("1.00")
    if weight_lbs > threshold:
        return Decimal("1.00") + step
    return Decimal("1.00")


def commodity_multiple(commodity):
    return COMMODITY_MULTIPLE[commodity]


def market_level(equipment_type, market_band):
    return MARKET_LEVEL_CENTS_PER_MILE[equipment_type][market_band]


def implied_cents_per_mile(load, market_band=None):
    band = market_band if market_band is not None else load["market_band"]
    level = market_level(load["equipment_type"], band)
    index = lane_index_for(load["lane_key"])
    timing = timing_band_multiple(load["pickup_window_start"])
    weight = weight_adjustment_multiple(load["equipment_type"], load["weight_lbs"])
    commodity = commodity_multiple(load["commodity"])
    return (d(level) * d(index) * timing * weight * commodity)


def quote_price(load, contract=None):
    """Spot vs contract base rate, floored at 50,000 cents (PRD 3.3).

    Returns (base_rate_cents, market_level_cents_per_mile).
    """
    if load["pricing_mode"] == "CONTRACT":
        if contract is None:
            raise ApiError("ERR_CONTRACT_NOT_ACTIVE")
        base = max(int(contract["committed_rate_cents"]), MIN_RATE_FLOOR_CENTS)
        level = market_level(load["equipment_type"], load["market_band"])
        return base, level
    level = market_level(load["equipment_type"], load["market_band"])
    miles = effective_miles(load["distance_miles"])
    line_haul = round_half_up(implied_cents_per_mile(load, load["market_band"]) * d(miles))
    return max(line_haul, MIN_RATE_FLOOR_CENTS), level


def min_rate_for(base_rate_cents):
    """The floor below which the platform will never tender (0.85x, half up)."""
    return round_half_up(d(base_rate_cents) * MIN_RATE_FLOOR_MULTIPLE)


def reprice_rate(load, quote, new_market_band):
    """PRD 3.7 — recompute at the new band, clamped at the quote's floor.

    posted_rate_cents is never touched.
    """
    miles = effective_miles(load["distance_miles"])
    recomputed = round_half_up(implied_cents_per_mile(load, new_market_band) * d(miles))
    return max(recomputed, quote["min_rate_cents"])


def booked_price(quote, load):
    """PRD 3.7 — locked inside the 60-minute window, otherwise live+surcharge."""
    quote_price_cents = (quote["repriced_rate_cents"]
                         if quote["quote_kind"] == "REPRICED" and quote["repriced_rate_cents"] is not None
                         else quote["base_rate_cents"])
    age_minutes = minutes_between(clock_now(), quote["created_at"])
    if age_minutes <= LOCK_WINDOW_MINUTES:
        return quote_price_cents
    miles = effective_miles(load["distance_miles"])
    live_base = round_half_up(implied_cents_per_mile(load, load["market_band"]) * d(miles))
    surcharged = round_half_up(d(live_base) * (Decimal(1) + LATE_BOOKING_SURCHARGE_PCT))
    return max(surcharged, quote["min_rate_cents"])