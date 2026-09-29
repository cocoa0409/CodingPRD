"""Calculation rules (SCAFFOLD section 1.3, PRD section 2.6).

All monetary arithmetic is exact decimal arithmetic on integer cents with
ROUND_HALF_UP applied exactly where each rule pins it.
"""
from decimal import Decimal, ROUND_HALF_UP

import db as store

# --- asset_fair_market_value ------------------------------------------------
DEPRECIATION_RATE_PER_YEAR = Decimal("0.10")
FLOOR_AGE_FACTOR = Decimal("0.20")
NON_FUNCTIONAL_FACTOR = Decimal("0.60")
DAYS_PER_YEAR = 365
CONDITION_FACTOR = {
    "C1": Decimal("1.00"),
    "C2": Decimal("0.85"),
    "C3": Decimal("0.70"),
    "C4": Decimal("0.50"),
    "C5": Decimal("0.30"),
    "C6": Decimal("0.15"),
    "C7": Decimal("0.05"),
}
AUCTION_RESERVE_PCT = Decimal("0.60")
MIN_RESERVE_CENTS = 2500

# --- transfer_order_price ---------------------------------------------------
TIER_DISCOUNT = {
    "STATE_AGENCY": Decimal("0.25"),
    "LOCAL_GOVERNMENT": Decimal("0.50"),
    "ELIGIBLE_NONPROFIT": Decimal("0.10"),
}
HANDLING_TIER_1_CENTS = 100000
HANDLING_TIER_2_CENTS = 1000000
HANDLING_FEE_SMALL_CENTS = 5000
HANDLING_FEE_MEDIUM_CENTS = 12500
HANDLING_FEE_LARGE_CENTS = 30000

# --- auction_invoice_total --------------------------------------------------
PAYMENT_TERM_DAYS = 7

# --- proceeds_distribution_net ---------------------------------------------
SERVICE_TIER_1_CENTS = 500000
SERVICE_TIER_2_CENTS = 5000000
SERVICE_RATE_1 = Decimal("0.125")
SERVICE_RATE_2 = Decimal("0.0875")
SERVICE_RATE_3 = Decimal("0.0525")
SANITIZATION_FEE_CENTS = 7500
DEMIL_FEE_CENTS = 22500

# --- bidder_deposit_requirement -------------------------------------------
DEPOSIT_THRESHOLD_CENTS = 500000
DEPOSIT_PCT = Decimal("0.10")
MIN_DEPOSIT_CENTS = 50000

# --- federal_use_period_end ------------------------------------------------
USE_PERIOD_MONTHS = {
    "VEHICLE": 18,
    "HEAVY_EQUIPMENT": 18,
    "RESTRICTED_MILITARY": 18,
    "IT_EQUIPMENT": 12,
    "FURNITURE": 12,
}

# --- misc ------------------------------------------------------------------
RELIST_COOLDOWN_HOURS = 24
DE_MINIMIS_SCREENING_THRESHOLD_CENTS = 25000
MIN_BID_INCREMENT_CENTS = 2500
ONE = Decimal(1)


def round_half_up(value):
    return int(Decimal(value).quantize(ONE, rounding=ROUND_HALF_UP))


# ---------------------------------------------------------------------------
# asset_fair_market_value
# ---------------------------------------------------------------------------

def assessment_rank_key(row):
    """assessed_on DESC then created_at DESC (ties broken by insert order)."""
    return (row["assessed_on"], row["created_at"], row["_seq"])


def governing_assessment(asset_id):
    pool = [a for a in store.db.assessments.values() if a["asset_id"] == asset_id]
    if not pool:
        return None, []
    ordered = sorted(pool, key=assessment_rank_key, reverse=True)
    return ordered[0], ordered


def age_factor(acquisition_date):
    elapsed_days = (store.today() - acquisition_date).days
    full_years = elapsed_days // DAYS_PER_YEAR
    if elapsed_days < 0:
        full_years = -((-elapsed_days + DAYS_PER_YEAR - 1) // DAYS_PER_YEAR)
    factor = ONE - DEPRECIATION_RATE_PER_YEAR * full_years
    return factor if factor > FLOOR_AGE_FACTOR else FLOOR_AGE_FACTOR


def fair_market_value(asset, governing):
    cond = CONDITION_FACTOR[governing["condition_code"]]
    age = age_factor(store.parse_date(asset["acquisition_date"]))
    func = ONE if governing["functional"] else NON_FUNCTIONAL_FACTOR
    base_cents = round_half_up(
        Decimal(asset["acquisition_cost_cents"]) * cond * age * func)
    value = base_cents - governing["repair_cost_estimate_cents"]
    return value if value > 0 else 0


def auction_reserve(fmv_cents):
    computed = round_half_up(Decimal(fmv_cents) * AUCTION_RESERVE_PCT)
    return computed if computed > MIN_RESERVE_CENTS else MIN_RESERVE_CENTS


def deposit_requirement(reserve_price_cents):
    if reserve_price_cents < DEPOSIT_THRESHOLD_CENTS:
        return 0
    computed = round_half_up(Decimal(reserve_price_cents) * DEPOSIT_PCT)
    return computed if computed > MIN_DEPOSIT_CENTS else MIN_DEPOSIT_CENTS


# ---------------------------------------------------------------------------
# transfer_order_price
# ---------------------------------------------------------------------------

def transfer_price(fmv_cents, agency_type, federal_source):
    tier_factor = TIER_DISCOUNT[agency_type]
    base = round_half_up(Decimal(fmv_cents) * tier_factor)
    if base < HANDLING_TIER_1_CENTS:
        fee = HANDLING_FEE_SMALL_CENTS
    elif base < HANDLING_TIER_2_CENTS:
        fee = HANDLING_FEE_MEDIUM_CENTS
    else:
        fee = HANDLING_FEE_LARGE_CENTS
    price = (0 if federal_source else base) + fee
    return base, fee, price


# ---------------------------------------------------------------------------
# auction_invoice_total
# ---------------------------------------------------------------------------

def invoice_lines(hammer_price_cents, buyer_premium_pct, sales_tax_pct):
    premium = round_half_up(Decimal(hammer_price_cents) * buyer_premium_pct)
    tax = round_half_up(Decimal(hammer_price_cents + premium) * sales_tax_pct)
    total = hammer_price_cents + premium + tax
    return premium, tax, total


# ---------------------------------------------------------------------------
# proceeds_distribution_net
# ---------------------------------------------------------------------------

def service_fee(base_cents):
    slice_1 = base_cents if base_cents < SERVICE_TIER_1_CENTS else SERVICE_TIER_1_CENTS
    capped_2 = base_cents if base_cents < SERVICE_TIER_2_CENTS else SERVICE_TIER_2_CENTS
    slice_2 = capped_2 - SERVICE_TIER_1_CENTS
    if slice_2 < 0:
        slice_2 = 0
    slice_3 = base_cents - SERVICE_TIER_2_CENTS
    if slice_3 < 0:
        slice_3 = 0
    return (round_half_up(Decimal(slice_1) * SERVICE_RATE_1)
            + round_half_up(Decimal(slice_2) * SERVICE_RATE_2)
            + round_half_up(Decimal(slice_3) * SERVICE_RATE_3))


def cost_recovery(asset_id):
    sanitization = 0
    demil = 0
    for cert in store.db.certificates.values():
        if cert["asset_id"] != asset_id or not cert["serials_verified"]:
            continue
        if cert["cert_type"] == "DATA_SANITIZATION":
            sanitization += 1
        elif cert["cert_type"] == "DEMILITARIZATION":
            demil += 1
    return SANITIZATION_FEE_CENTS * sanitization + DEMIL_FEE_CENTS * demil


def distribution_net(base_cents, fee_cents, recovery_cents):
    net = base_cents - fee_cents - recovery_cents
    return net if net > 0 else 0


# ---------------------------------------------------------------------------
# federal_use_period_end
# ---------------------------------------------------------------------------

def use_period_end(start_date, category):
    return store.add_months(start_date, USE_PERIOD_MONTHS[category])


def federal_use_period_active(asset):
    if not asset["federal_source"]:
        return False
    end_on = asset["federal_use_period_end_on"]
    if end_on is None:
        return False
    return store.today() < store.parse_date(end_on)


def screening_exempt(asset):
    fmv = asset["fair_market_value_cents"]
    return fmv is not None and fmv < DE_MINIMIS_SCREENING_THRESHOLD_CENTS
