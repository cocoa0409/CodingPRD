"""Numeric limits, the logical calendar, and the canonical worked issue.

Every figure here is transcribed from PRD.md. Monetary amounts are held as
Python ``int``/``float`` so that they serialise as JSON *numbers*, never as JSON
strings -- the API contract of section 2.6 is numeric.
"""

from datetime import datetime, timedelta, timezone

# --- Routing ----------------------------------------------------------------
# PRD section 4: every endpoint is namespaced under this prefix.
API_PREFIX = "/bond-offerings"

# --- Pagination (PRD section 2.3) -------------------------------------------
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# --- Money and denomination (PRD section 2.6) -------------------------------
BOND_PAR_USD = 1000
MIN_DENOMINATION_USD = 5000
PRICE_DECIMALS = 3
MONEY_DECIMALS = 2
YIELD_DECIMALS = 4
SEMIANNUAL_PERIODS_PER_YEAR = 2

# --- Continuing-disclosure risk scoring (PRD section 3.1) -------------------
LATE_ANNUAL_FILING_POINTS = 12
LATE_EVENT_NOTICE_POINTS = 8
MATERIAL_EVENT_POINTS = 25
ENTITY_TYPE_SURCHARGE = {
    "STATE": 0,
    "CITY": 5,
    "COUNTY": 5,
    "SCHOOL_DISTRICT": 10,
    "AUTHORITY": 15,
}
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100
# PRD section 3.1: "A score at or above forty puts the issuer inside the
# high-risk gate"; the boundary is inclusive on the gate side.
DISCLOSURE_RISK_GATE = 40

# --- Field bounds -----------------------------------------------------------
ISSUER_NAME_MAX = 160
FIRM_NAME_MAX = 160
MSRB_REGISTRATION_LENGTH = 6
PRIOR_COUNT_MIN = 0
PRIOR_COUNT_MAX = 20
SERIES_DESIGNATION_MAX = 40
VERSION_LABEL_MAX = 40
SECTION_CODE_MAX = 16
SECTION_TITLE_MAX = 160
SECTION_BODY_MAX = 8000
PROVIDER_NAME_MAX = 120
ENHANCED_RATING_MAX = 6
DISSEMINATION_AGENT_MAX = 120
SEQUENCE_NUMBER_MIN = 1
SEQUENCE_NUMBER_MAX = 40
COUPON_RATE_MIN = 0.0
COUPON_RATE_MAX = 12.0
YIELD_PCT_MAX = 12.0
CALL_PRICE_MIN = 100.000
CALL_PRICE_MAX = 103.000
PREMIUM_BPS_MIN = 0.0
PREMIUM_BPS_MAX = 200.0
INSURED_TRANCHE_IDS_MIN = 1
INSURED_TRANCHE_IDS_MAX = 40
ANNUAL_REPORT_DUE_DAYS_MIN = 120
ANNUAL_REPORT_DUE_DAYS_MAX = 270
MATERIAL_EVENT_NOTICE_DAYS_MIN = 1
MATERIAL_EVENT_NOTICE_DAYS_MAX = 10
ATTENDEE_COUNT_MIN = 1
ATTENDEE_COUNT_MAX = 25
PRIORITY_RANK_MIN = 1
PRIORITY_RANK_MAX = 40
PCT_SHARE_MAX = 100.0
LIABILITY_PCT_TOTAL = 100.0000
PRICE_OR_YIELD_MAX = 130.0
MIN_RECORD_RETENTION_YEARS = 6

# --- Temporal rules ---------------------------------------------------------
# PRD section 3.5: window may run no longer than three hours.
PRESENTATION_MAX_MINUTES = 180
# PRD section 3.5: "a buffer of one clear hour guards each agency's schedule".
PRESENTATION_BUFFER_MINUTES = 60
# PRD section 3.4: "permitted only while draft_round is strictly less than four".
REVISION_ROUND_CAP = 4

# --- Arbitrage (PRD section 3.8) --------------------------------------------
ARBITRAGE_ALLOWANCE_PCT = 0.125
ARBITRAGE_DAY_BASIS = 360

# --- Logical clock (PRD section 2.4) ----------------------------------------
# "The logical clock starts at exactly 2026-08-01T00:00:00Z."
CLOCK_EPOCH = "2026-08-01T00:00:00.000Z"


def parse_iso(value):
    """Parse an ISO 8601 UTC instant, with or without fractional digits."""
    text = value.replace("Z", "+00:00")
    return datetime.fromisoformat(text).astimezone(timezone.utc)


def iso_utc(moment):
    """Render a datetime as an ISO 8601 UTC instant with three fractional digits.

    PRD section 2.2 fixes this shape for every timestamp the API emits, so the
    same shape is what tests send.
    """
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.") + (
        "%03dZ" % (moment.microsecond // 1000)
    )


def plus_minutes(instant, minutes):
    """Return ``instant`` shifted by ``minutes``, as an ISO 8601 UTC string."""
    return iso_utc(parse_iso(instant) + timedelta(minutes=minutes))


def plus_hours(instant, hours):
    """Return ``instant`` shifted by ``hours``, as an ISO 8601 UTC string."""
    return plus_minutes(instant, hours * 60)


def plus_days(instant, days):
    """Return ``instant`` shifted by ``days``, as an ISO 8601 UTC string."""
    return iso_utc(parse_iso(instant) + timedelta(days=days))


def plus_semiannual(instant, periods):
    """Return the instant exactly ``periods`` six-month periods after ``instant``.

    PRD section 3.2 requires ``maturity_date`` to "land exactly on a semiannual
    anniversary" of the deal's ``dated_date`` -- a whole number of six-month
    periods after the dated date, never a fraction of one.
    """
    base = parse_iso(instant)
    total_months = (base.year * 12 + (base.month - 1)) + periods * 6
    year, month = divmod(total_months, 12)
    return iso_utc(base.replace(year=year, month=month + 1))


# --- The canonical worked issue (PRD sections 3.2, 3.3, 3.8) ----------------
# Two tranches of 5,000,000 each; the numbers below are the PRD's own worked
# figures, so any fixture built from them can assert them without re-deriving.
DATED_DATE = "2026-08-01T00:00:00.000Z"
CANONICAL_EXPECTED_PAR_USD = 10000000
CANONICAL_TRANCHE_PRINCIPAL_USD = 5000000

# Tranche 1: 5.000 coupon reoffered at 4.250 over twenty semiannual periods,
# not callable -> prices at 106.058 to maturity (PRD section 3.2).
TRANCHE_1_COUPON_PCT = 5.000
TRANCHE_1_YIELD_PCT = 4.250
TRANCHE_1_PERIODS = 20
TRANCHE_1_MATURITY_DATE = plus_semiannual(DATED_DATE, TRANCHE_1_PERIODS)
TRANCHE_1_PRICE_TO_MATURITY_PCT = 106.058
TRANCHE_1_REOFFERING_PRICE_PCT = 106.058

# Tranche 2: the same coupon at 4.000 over forty periods, callable at par after
# twenty -> 113.678 to maturity, 108.176 to the call, marketed at 108.176 with
# is_priced_to_call true (PRD section 3.2).
TRANCHE_2_COUPON_PCT = 5.000
TRANCHE_2_YIELD_PCT = 4.000
TRANCHE_2_PERIODS = 40
TRANCHE_2_CALL_PERIODS = 20
TRANCHE_2_MATURITY_DATE = plus_semiannual(DATED_DATE, TRANCHE_2_PERIODS)
TRANCHE_2_FIRST_CALL_DATE = plus_semiannual(DATED_DATE, TRANCHE_2_CALL_PERIODS)
TRANCHE_2_CALL_PRICE_PCT = 100.000
TRANCHE_2_PRICE_TO_MATURITY_PCT = 113.678
TRANCHE_2_PRICE_TO_CALL_PCT = 108.176
TRANCHE_2_REOFFERING_PRICE_PCT = 108.176

# A discount maturity that stays priced to maturity (PRD section 3.2).
DISCOUNT_COUPON_PCT = 3.000
DISCOUNT_PRICE_TO_MATURITY_PCT = 86.322
DISCOUNT_PRICE_TO_CALL_PCT = 91.824

# The exact tie that resolves to the to-maturity variant (PRD section 3.2).
TIE_COUPON_PCT = 4.000
TIE_YIELD_PCT = 4.000
TIE_PRICE_PCT = 100.000

# Issue price total for the canonical two-tranche schedule (PRD section 3.8).
CANONICAL_TRANCHE_1_PROCEEDS_USD = 5302900.00
CANONICAL_TRANCHE_2_PROCEEDS_USD = 5408800.00
CANONICAL_ISSUE_PRICE_TOTAL_USD = 10711700.00

# Negotiated compensation (PRD section 3.8).
NEGOTIATED_TAKEDOWN_PER_BOND_USD = 5.000
NEGOTIATED_MANAGEMENT_FEE_PER_BOND_USD = 2.500
NEGOTIATED_EXPENSES_PER_BOND_USD = 1.250
NEGOTIATED_COMPONENT_TOTAL_PER_BOND_USD = 8.750
NEGOTIATED_TRANCHE_SPREAD_USD = 43750.00
NEGOTIATED_GROSS_SPREAD_TOTAL_USD = 87500.00
NEGOTIATED_GROSS_SPREAD_PER_BOND_USD = 8.750

# Competitive compensation (PRD section 3.8).
COMPETITIVE_WINNING_BID_PRICE_PCT = 106.000
COMPETITIVE_BID_PROCEEDS_USD = 10600000.00
COMPETITIVE_GROSS_SPREAD_TOTAL_USD = 111700.00
COMPETITIVE_GROSS_SPREAD_PER_BOND_USD = 11.170
COMPETITIVE_NET_PROCEEDS_USD = 10600000.00

# Credit enhancement on tranche 1 (PRD sections 3.3, 3.8).
ENHANCEMENT_PREMIUM_BPS = 45.00
INSURED_DEBT_SERVICE_TRANCHE_1_USD = 7500000.00
ENHANCEMENT_PREMIUM_USD = 33750.00
NEGOTIATED_NET_PROCEEDS_INSURED_USD = 10590450.00
# PRD section 3.3: withdrawal restores net proceeds of 10,624,200.00.
NEGOTIATED_NET_PROCEEDS_UNINSURED_USD = 10624200.00

# Arbitrage projection for the canonical issue (PRD section 3.8).
CANONICAL_TRANCHE_1_BOND_YEARS = 50000
CANONICAL_TRANCHE_2_BOND_YEARS = 100000
CANONICAL_ARBITRAGE_YIELD_PCT = 4.0833
CANONICAL_PERMITTED_INVESTMENT_YIELD_PCT = 4.2083

# The worked priority-of-orders waterfall (PRD section 3.7).
WATERFALL_TRANCHE_PRINCIPAL_USD = 5000000
WATERFALL_O1_REQUESTED_USD = 2005000
WATERFALL_O2_REQUESTED_USD = 2000000
WATERFALL_O3_REQUESTED_USD = 1500000
WATERFALL_O4_REQUESTED_USD = 1000000
WATERFALL_O1_ALLOTTED_USD = 2005000
WATERFALL_O2_ALLOTTED_USD = 1715000
WATERFALL_O3_ALLOTTED_USD = 1280000
WATERFALL_O4_ALLOTTED_USD = 0
# Takedown reconciliation on those allotments at 5.000 per bond.
WATERFALL_MEMBER_A_TAKEDOWN_USD = 18600.00
WATERFALL_MEMBER_B_TAKEDOWN_USD = 6400.00
