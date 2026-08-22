"""Every calculation in the specification, with the pinned rounding discipline.

All money is integer cents; every non-integral cent value is rounded half up
(PRD §2.6). Decimal is used throughout — never binary floating point.
"""
import math
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING

# ---------------------------------------------------------------- constants
ADVANCE_MULT = Decimal("1.00")
STANDARD_MULT = Decimal("1.30")
ONSITE_MULT = Decimal("1.65")

VOLUME_TIERS = (
    (100000, Decimal("0.00")),
    (500000, Decimal("0.04")),
    (1500000, Decimal("0.07")),
    (None, Decimal("0.10")),
)
FEE_TIERS = (
    (50000, Decimal("0.09")),
    (200000, Decimal("0.07")),
    (None, Decimal("0.05")),
)

MIN_BILLABLE_CWT = 2
ADVANCE_RATE_CENTS_PER_CWT = 9800
DIRECT_RATE_CENTS_PER_CWT = 11500
LOOSE_SURCHARGE = Decimal("0.30")
OT_SURCHARGE = Decimal("0.25")
LATE_SURCHARGE = Decimal("0.35")

RENT_SQFT_CENTS = 2400
RENT_LF_CENTS = 15000
SIGN_RENT_CENTS = 85000
REFURB_LOAD_PCT = Decimal("0.12")
BUILD_SQFT_CENTS = 7800
BUILD_LF_CENTS = 38000
SIGN_BUILD_CENTS = 210000
DESIGN_FEE_PCT = Decimal("0.15")
RESIDUAL_PCT = Decimal("0.20")
PER_SHOW_CARRY_CENTS = 45000
BREAKEVEN_HORIZON = 20

TARIFF_CENTS_PER_LB = 30
TARIFF_MAX_PER_CLAIM_CENTS = 5000000
DECLARED_VALUE_DEDUCTIBLE_CENTS = 25000
DEPRECIATION_BY_GRADE = {
    "A": Decimal("0.00"),
    "B": Decimal("0.10"),
    "C": Decimal("0.25"),
    "D": Decimal("0.40"),
}

DAYS_PER_BILLABLE_MONTH = 30
CWT_DIVISOR = 100

DEVICE_FEE_CENTS = 32500
LEAD_OVERAGE_CENTS = 150

MAX_DESIGN_REVISIONS = 3
MAX_CLAIM_APPEALS = 2
REFURB_OVERRUN_TOLERANCE = Decimal("1.20")
ASSET_LBS_PER_SQFT = 12

CONDITION_GRADES = ("A", "B", "C", "D")


# ------------------------------------------------------------ money helpers
def dec(value):
    """Exact Decimal from an int / float / str without binary drift."""
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def round_half_up(value):
    """Round a Decimal quantity half up to a whole cent (or whole unit)."""
    return int(dec(value).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def hours_2dp(value):
    """Hours are carried to two decimal places, rounded half up."""
    return dec(value).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def cwt_of(weight_lbs):
    """Hundredweight for one crate: pounds over 100 rounded UP, per crate."""
    pounds = int(weight_lbs)
    return -(-pounds // CWT_DIVISOR)


# ------------------------------------------------------- deadline tiering
def deadline_tier(now_dt, show_deadlines):
    """(tier, multiplier) from the logical clock alone; boundaries inclusive."""
    discount_deadline, move_in_start = show_deadlines
    if now_dt <= discount_deadline:
        return "ADVANCE", ADVANCE_MULT
    if now_dt <= move_in_start:
        return "STANDARD", STANDARD_MULT
    return "ONSITE", ONSITE_MULT


# ------------------------------------------------------ service order money
def price_lines(lines, tier_multiplier):
    """Round EACH line to whole cents first, then sum the rounded values."""
    subtotal = 0
    for line in sorted(lines, key=lambda row: row["line_seq"]):
        gross = dec(line["unit_qty"]) * dec(line["unit_rate_cents"])
        after_discount = gross * (Decimal(1) - dec(line.get("discount_pct") or 0))
        line_total = round_half_up(after_discount * dec(tier_multiplier))
        line["line_total_cents"] = line_total
        subtotal += line_total
    return subtotal


def _tier_rate(tiers, amount):
    for threshold, rate in tiers:
        if threshold is None or amount < threshold:
            return rate
    return tiers[-1][1]


def order_waterfall(subtotal_cents):
    """Pinned evaluation order: subtotal -> volume -> base -> fee -> total."""
    volume_pct = _tier_rate(VOLUME_TIERS, subtotal_cents)
    volume_discount_cents = round_half_up(dec(subtotal_cents) * volume_pct)
    discounted_base_cents = subtotal_cents - volume_discount_cents
    fee_pct = _tier_rate(FEE_TIERS, discounted_base_cents)
    service_fee_cents = round_half_up(dec(discounted_base_cents) * fee_pct)
    total_cents = discounted_base_cents + service_fee_cents
    return {
        "subtotal_cents": subtotal_cents,
        "volume_discount_cents": volume_discount_cents,
        "discounted_base_cents": discounted_base_cents,
        "service_fee_cents": service_fee_cents,
        "total_cents": total_cents,
    }


# ------------------------------------------------------------------ drayage
def drayage_charge(crates, channel, received_at_dt, advance_deadline_dt):
    gross_weight_lbs = sum(int(crate["weight_lbs"]) for crate in crates)
    billable_cwt = max(MIN_BILLABLE_CWT, cwt_of(gross_weight_lbs))
    base_rate = (ADVANCE_RATE_CENTS_PER_CWT if channel == "ADVANCE_WAREHOUSE"
                 else DIRECT_RATE_CENTS_PER_CWT)
    surcharge = Decimal("0")
    if any(crate.get("crate_type") == "LOOSE_UNCRATED" for crate in crates):
        surcharge += LOOSE_SURCHARGE
    hour = received_at_dt.hour
    if hour < 8 or hour >= 16:
        surcharge += OT_SURCHARGE
    if channel == "ADVANCE_WAREHOUSE" and advance_deadline_dt is not None \
            and received_at_dt > advance_deadline_dt:
        surcharge += LATE_SURCHARGE
    charge = round_half_up(dec(billable_cwt) * dec(base_rate) * (Decimal(1) + surcharge))
    return gross_weight_lbs, billable_cwt, charge


# ------------------------------------------------------------ exhibit quote
def acquisition_quote(sqft, linear_feet, has_hanging_sign, expected_show_count,
                      selected_acquisition_mode):
    rental_base = (dec(sqft) * RENT_SQFT_CENTS + dec(linear_feet) * RENT_LF_CENTS
                   + (SIGN_RENT_CENTS if has_hanging_sign else 0))
    rental_quote = round_half_up(rental_base * (Decimal(1) + REFURB_LOAD_PCT))
    rental_per_show = rental_quote

    build_cost = (dec(sqft) * BUILD_SQFT_CENTS + dec(linear_feet) * BUILD_LF_CENTS
                  + (SIGN_BUILD_CENTS if has_hanging_sign else 0))
    purchase_quote = round_half_up(build_cost * (Decimal(1) + DESIGN_FEE_PCT))
    residual = round_half_up(dec(purchase_quote) * RESIDUAL_PCT)
    amortizable = dec(purchase_quote - residual)
    purchase_per_show = round_half_up(amortizable / dec(expected_show_count)) \
        + PER_SHOW_CARRY_CENTS

    breakeven = 0
    for candidate in range(1, BREAKEVEN_HORIZON + 1):
        per_show = round_half_up(amortizable / dec(candidate)) + PER_SHOW_CARRY_CENTS
        if per_show <= rental_per_show:
            breakeven = candidate
            break

    quoted = rental_quote if selected_acquisition_mode == "RENTAL" else purchase_quote
    return {
        "rental_quote_cents": rental_quote,
        "purchase_quote_cents": purchase_quote,
        "rental_per_show_cents": rental_per_show,
        "purchase_per_show_cents": purchase_per_show,
        "breakeven_show_count": breakeven,
        "quoted_price_cents": quoted,
    }


# --------------------------------------------------------------- claim money
def tariff_settlement(declared_value_cents, weight_basis_lbs):
    weight_cap = round_half_up(dec(weight_basis_lbs) * TARIFF_CENTS_PER_LB)
    return min(int(declared_value_cents), weight_cap, TARIFF_MAX_PER_CLAIM_CENTS)


def declared_value_settlement(declared_value_cents, list_value_cents, condition_grade):
    depreciation = DEPRECIATION_BY_GRADE.get(condition_grade, Decimal("0.00"))
    basis = min(int(declared_value_cents), int(list_value_cents))
    depreciated = round_half_up(dec(basis) * (Decimal(1) - depreciation))
    return max(0, depreciated - DECLARED_VALUE_DEDUCTIBLE_CENTS)


# ------------------------------------------------------------------ storage
def storage_charge(weight_lbs, rate_cents_per_cwt_per_month, stored_since_dt, as_of_dt,
                   free_days):
    elapsed = as_of_dt - stored_since_dt
    days_stored = int(math.floor(elapsed.total_seconds() / 86400.0))
    if days_stored < 0:
        days_stored = 0
    billable_days = max(0, days_stored - int(free_days))
    billable_months = int(math.ceil(billable_days / float(DAYS_PER_BILLABLE_MONTH)))
    return round_half_up(dec(cwt_of(weight_lbs)) * dec(rate_cents_per_cwt_per_month)
                         * dec(billable_months))


# ------------------------------------------------------------- lead capture
def license_billing(license_row):
    count = len(license_row["ingested_badge_ids"])
    overage = max(0, count - int(license_row["included_leads"]))
    overage_cents = overage * LEAD_OVERAGE_CENTS
    license_row["leads_ingested_count"] = count
    license_row["billable_overage_leads"] = overage
    license_row["lead_overage_cents"] = overage_cents
    license_row["license_total_cents"] = \
        int(license_row["device_count"]) * DEVICE_FEE_CENTS + overage_cents
    return license_row


# --------------------------------------------------------------------- labor
def labor_billing(actual_start_dt, actual_end_dt, min_call_hours, crew_size,
                  straight_rate, overtime_multiplier, doubletime_multiplier,
                  st_start_hhmm, st_end_hhmm):
    """Elapsed minutes -> half-hour ceiling -> minimum call -> band split."""
    elapsed_minutes = int((actual_end_dt - actual_start_dt).total_seconds() // 60)
    half_hours = dec(elapsed_minutes) / Decimal(60) * Decimal(2)
    elapsed_hours = half_hours.quantize(Decimal("1"), rounding=ROUND_CEILING) / Decimal(2)
    billed_hours = max(dec(min_call_hours), elapsed_hours)

    if actual_start_dt.weekday() == 6:  # Sunday in UTC — the whole call is double time
        st_hours = Decimal("0.00")
        ot_hours = Decimal("0.00")
        dt_hours = hours_2dp(billed_hours)
    else:
        st_start = _minute_of_day(st_start_hhmm, 0)
        st_end = _minute_of_day(st_end_hhmm, 16 * 60 + 30)
        st_minutes = 0
        ot_minutes = 0
        for offset in range(elapsed_minutes):
            minute = actual_start_dt + _minutes(offset)
            mod = minute.hour * 60 + minute.minute
            if st_start <= mod < st_end:
                st_minutes += 1
            else:
                ot_minutes += 1
        padding_minutes = int(billed_hours * Decimal(60)) - elapsed_minutes
        if padding_minutes > 0:
            last_minute = actual_end_dt - _minutes(1)
            mod = last_minute.hour * 60 + last_minute.minute
            if st_start <= mod < st_end:
                st_minutes += padding_minutes
            else:
                ot_minutes += padding_minutes
        st_hours = hours_2dp(dec(st_minutes) / Decimal(60))
        ot_hours = hours_2dp(dec(ot_minutes) / Decimal(60))
        dt_hours = Decimal("0.00")

    rate = dec(straight_rate)
    charge = round_half_up(dec(crew_size) * (
        st_hours * rate
        + ot_hours * rate * dec(overtime_multiplier)
        + dt_hours * rate * dec(doubletime_multiplier)))
    return {
        "billed_hours": hours_2dp(billed_hours),
        "st_hours": st_hours,
        "ot_hours": ot_hours,
        "dt_hours": dt_hours,
        "labor_charge_cents": charge,
    }


def no_show_charge(crew_size, min_call_hours, straight_rate):
    return round_half_up(dec(crew_size) * dec(min_call_hours) * dec(straight_rate))


def _minutes(count):
    from datetime import timedelta
    return timedelta(minutes=count)


def _minute_of_day(hhmm, fallback):
    if not isinstance(hhmm, str) or ":" not in hhmm:
        return fallback
    hours, _, minutes = hhmm.partition(":")
    try:
        return int(hours) * 60 + int(minutes)
    except ValueError:
        return fallback
