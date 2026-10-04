"""Calculation rules (SCAFFOLD section 1.3 / PRD sections 2.7 and 3.4-3.6).

Every constant below is verbatim from the scaffold calculation tables.
"""

from decimal import Decimal

from errors import dec, round_half_up

# --- payout grid -----------------------------------------------------------
GRID_TIER_1_BASE_BPS = 7000
GRID_TIER_2_BASE_BPS = 8000
GRID_TIER_3_BASE_BPS = 9000
GRID_TIER_1_CEILING_CENTS = 100_000_000
GRID_TIER_2_CEILING_CENTS = 250_000_000

PRODUCT_RATE_DELTA_BPS = {
    "EQUITY": 0,
    "MUTUAL_FUND": -500,
    "ANNUITY": -700,
    "BROKERAGE_TRAIL": -300,
    "ADVISORY": 500,
}
AFFILIATION_MODEL_OFFSET_BPS = {
    "IC": 0,
    "EMPLOYEE": 500,
    "HYBRID": 250,
    "INSTITUTIONAL": 6500,
}
MAX_RATE_BPS = 9000
MIN_RATE_BPS = 500

# --- expense pass-through / net settlement ---------------------------------
PASS_THROUGH_TECHNOLOGY_FLAT_CENTS = 3_000_000
PASS_THROUGH_CLEARING_FLAT_CENTS = 500_000
PASS_THROUGH_REGULATORY_FLAT_CENTS = 600_000
PASS_THROUGH_TECHNOLOGY_PCT_BPS = 200
PASS_THROUGH_CLEARING_PCT_BPS = 100
PASS_THROUGH_REGULATORY_PCT_BPS = 50

PASS_THROUGH_PCT_BPS = {
    "TECHNOLOGY": PASS_THROUGH_TECHNOLOGY_PCT_BPS,
    "CLEARING": PASS_THROUGH_CLEARING_PCT_BPS,
    "REGULATORY": PASS_THROUGH_REGULATORY_PCT_BPS,
}
PASS_THROUGH_FLAT_CENTS = {
    "TECHNOLOGY": PASS_THROUGH_TECHNOLOGY_FLAT_CENTS,
    "CLEARING": PASS_THROUGH_CLEARING_FLAT_CENTS,
    "REGULATORY": PASS_THROUGH_REGULATORY_FLAT_CENTS,
}

EO_RATE_BPS = {"STANDARD": 120, "PREMIUM": 350, "LIMITED": 900}
SUPERVISORY_OVERRIDE_BPS = {"IC": 0, "EMPLOYEE": 0, "HYBRID": 100, "INSTITUTIONAL": 250}
ANNUAL_PAYOUT_CAP_CENTS = 500_000_000

# --- loans ------------------------------------------------------------------
LPL_PARITY_PRINCIPAL_CAP_CENTS = 50_000_000
MILESTONE_WINDOW_MONTHS = 12

# --- advisory fee levelization ---------------------------------------------
FEE_LEVEL_TARGET_BPS = 85
ADVISORY_REBATE_BAND_1_BPS = 6000
ADVISORY_REBATE_BAND_2_BPS = 7000
ADVISORY_REBATE_BAND_3_BPS = 8000
LEVELIZATION_FEE_CAP_CENTS = 30_000_000

# --- retention credit -------------------------------------------------------
RETENTION_TARGET_BPS = 7000
RETENTION_CREDIT_CAP_BPS = 200

# --- transfer gates ---------------------------------------------------------
AFFILIATION_PORTABILITY_MIN_BPS = 5000
NON_PROTOCOL_PORTABILITY_MIN_BPS = 7000
BOOK_TRANSFER_PORTABILITY_MIN_BPS = 6000


def grid_tier_base_bps(basis_cents):
    """Boundaries are inclusive-lower (PRD 3.4)."""
    basis = int(basis_cents)
    if basis < GRID_TIER_1_CEILING_CENTS:
        return GRID_TIER_1_BASE_BPS
    if basis < GRID_TIER_2_CEILING_CENTS:
        return GRID_TIER_2_BASE_BPS
    return GRID_TIER_3_BASE_BPS


def rate_for(basis_cents, product_type, affiliation_model):
    """clamp(base + product delta - model offset, 500, 9000)."""
    raw = (grid_tier_base_bps(basis_cents)
           + PRODUCT_RATE_DELTA_BPS.get(product_type, 0)
           - AFFILIATION_MODEL_OFFSET_BPS.get(affiliation_model, 0))
    return min(MAX_RATE_BPS, max(MIN_RATE_BPS, raw))


def rate_was_floored(basis_cents, product_type, affiliation_model):
    raw = (grid_tier_base_bps(basis_cents)
           + PRODUCT_RATE_DELTA_BPS.get(product_type, 0)
           - AFFILIATION_MODEL_OFFSET_BPS.get(affiliation_model, 0))
    return raw < MIN_RATE_BPS


def entry_amount(gross_commission_cents, rate_bps):
    """round_half_up(gross * rate / 10000) - rounded once per entry."""
    return round_half_up(dec(gross_commission_cents) * dec(rate_bps) / dec(10000))


def sum_entry_amounts(entries, rate_of):
    """Per-entry round-half-up, then sum (PRD 2.7 / 3.4)."""
    total = 0
    for entry in entries:
        total += entry_amount(entry["gross_commission_cents"], rate_of(entry))
    return total


def book_portability_pct(ingested_book_total_cents, book_transferred_cents):
    ingested = int(ingested_book_total_cents or 0)
    if ingested == 0:
        return 0
    return int(book_transferred_cents or 0) * 10000 // ingested


def retention_credit_cap_cents(book_transferred_cents):
    return round_half_up(dec(book_transferred_cents or 0) * dec(RETENTION_CREDIT_CAP_BPS) / dec(10000))


def retention_credit_amount(balance_cents, retention_rate_bps):
    return round_half_up(dec(balance_cents or 0) * dec(retention_rate_bps) / dec(10000))


def retention_ratio_bps(accounts_retained_count, accounts_in_contest_count):
    if int(accounts_in_contest_count or 0) == 0:
        return 0
    return int(accounts_retained_count or 0) * 10000 // int(accounts_in_contest_count)


def milestone_threshold_cents(principal_cents, forgiveness_milestone_pct):
    return round_half_up(dec(principal_cents) * dec(forgiveness_milestone_pct) / dec(100))


def milestone_forgiveness_cents(principal_cents, forgiveness_milestone_pct):
    """Floor division on the percentage of principal; never rounded (PRD 2.7)."""
    return int(principal_cents) * int(forgiveness_milestone_pct) // 100


def rebate_bps_for_portability(portability_pct):
    band = int(portability_pct or 0)
    if band < 6000:
        return ADVISORY_REBATE_BAND_1_BPS
    if band < 8000:
        return ADVISORY_REBATE_BAND_2_BPS
    return ADVISORY_REBATE_BAND_3_BPS