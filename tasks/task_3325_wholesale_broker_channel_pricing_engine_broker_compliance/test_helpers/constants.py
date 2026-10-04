"""Domain thresholds and pinned reference values for the pricing / QC engine.

Every numeric literal here is re-derived from the PRD prose, not copied from
any design artifact. Where a design artifact's worked example disagreed with
the PRD arithmetic, the PRD arithmetic wins.
"""

# --- Turn-time commitments (§2.6) -------------------------------------------
UNDERWRITING_TURN_DAYS = 10
CLOSING_TURN_DAYS = 7
UNDERWRITING_EXTENSION_DAYS = 5
OPEN_DEFECT_DEADLINE_DAYS = 3
REPURCHASE_WINDOW_DAYS = 30

# --- Financial strength / tier (§3.2) ---------------------------------------
NET_WORTH_TARGET_CENTS = 100_000_000
LIQUIDITY_TARGET_CENTS = 40_000_000
LEVERAGE_CAP_RATIO = 3.0
EXPERIENCE_TARGET_YEARS = 5
NET_WORTH_FLOOR_CENTS = 25_000_000
ATTAINMENT_MEETS_RATIO = 1.0
ATTAINMENT_NEAR_RATIO = 0.75

TIER_1_MIN_SCORE = 85.00
TIER_2_MIN_SCORE = 60.00
TIER_3_MIN_SCORE = 40.00

# --- Broker standing (§2.4) --------------------------------------------------
QUALITY_SUSPENSION_THRESHOLD = 40.00
DEFECT_SUSPENSION_TIER = 5
FINANCIAL_SUSPENSION_THRESHOLD = 40.00
REINSTATEMENT_QUALITY_THRESHOLD = 60.00
REINSTATEMENT_DEFECT_TIER = 2

# --- Pricing dimensions (§3.5) ----------------------------------------------
CREDIT_BUCKETS = {
    "760-plus": -0.125,
    "740-759": -0.050,
    "720-739": 0.000,
    "700-719": 0.125,
    "680-699": 0.250,
    "under-680": 0.500,
}
LTV_BUCKETS = {
    "up-to-60": 0.000,
    "60-70": 0.050,
    "70-80": 0.125,
    "80-90": 0.250,
    "90-95": 0.375,
    "over-95": 0.500,
}
OCCUPANCY_BUCKETS = {
    "PRIMARY_RESIDENCE": 0.000,
    "SECOND_HOME": 0.250,
    "INVESTMENT": 0.500,
}
PRODUCT_BUCKETS = {
    "CONVENTIONAL": 0.000,
    "FHA": 0.125,
    "VA": -0.125,
    "JUMBO": 0.375,
    "USDA": 0.250,
}

LOCK_SURCHARGE_15D = 0.125
LOCK_SURCHARGE_30D = 0.000
LOCK_SURCHARGE_60D = -0.125
LOCK_BOUNDARY_SHORT_DAYS = 30
LOCK_BOUNDARY_LONG_DAYS = 60

# Base price grid: rows are the rounded credit buckets, columns the six LTV
# bands ascending.  Derived verbatim from the PRD's seven-step price_points rule.
PRICE_GRID_ROWS = ["760-plus", "740", "720", "700", "680", "660", "under-660"]
PRICE_GRID_COLS = ["up-to-60", "60-70", "70-80", "80-90", "90-95", "over-95"]
PRICE_TABLE = {
    "760-plus": [-1.00, -0.75, -0.50, -0.25, 0.00, 0.25],
    "740": [-0.75, -0.50, -0.25, 0.00, 0.25, 0.50],
    "720": [-0.50, -0.25, 0.00, 0.25, 0.50, 0.75],
    "700": [-0.25, 0.00, 0.25, 0.50, 0.75, 1.00],
    "680": [0.00, 0.25, 0.50, 0.75, 1.00, 1.25],
    "660": [0.25, 0.50, 0.75, 1.00, 1.25, 1.50],
    "under-660": [0.50, 0.75, 1.00, 1.25, 1.50, 1.75],
}
PLATINUM_MAX_POINTS = -0.50
GOLD_MAX_POINTS = 0.00
SILVER_MAX_POINTS = 0.50
TIER_DISCOUNT = {
    "PLATINUM": -0.25,
    "GOLD": -0.10,
    "SILVER": 0.000,
    "BRONZE": 0.25,
}

# --- Compensation (§3.6) -----------------------------------------------------
LENDER_PAID_RATE_IMPACT = 0.250
BORROWER_PAID_RATE_IMPACT = -0.250

# --- Quality control (§3.9) --------------------------------------------------
DEFECT_WEIGHTS = {
    "INCOME_DISCREPANCY": 8.00,
    "UNDISCLOSED_LIABILITY": 5.00,
    "APPRAISAL_DEVIATION": 6.00,
    "TITLE_DEFECT": 7.00,
    "LICENSE_DEFECT": 10.00,
    "NON_DEFECT": 0.00,
}
SEVERITY_MULTIPLIERS = {"MINOR": 0.50, "MAJOR": 1.00, "CRITICAL": 1.50}
REPURCHASE_POINTS_THRESHOLD = 12.00
ORIGINATION_FEE_SHARE = 0.5
DEFECT_TIER_MULTIPLIERS = {0: 1.00, 1: 1.25, 2: 1.50, 3: 2.00}
DEFECT_TIER_MULTIPLIER_MAX = 2.50

# --- Exclusivity (§3.4) ------------------------------------------------------
WARNED_AT_BREACHED_POLICIES = 1
RESTRICTED_AT_BREACHED_POLICIES = 2
BLOCKED_AT_BREACHED_POLICIES = 3

# --- Logical clock (§2.10) ---------------------------------------------------
CLOCK_START = "2026-09-01T00:00:00Z"
EARLY_FUNDING_CUTOFF_UTC = "2026-09-01T00:00:00Z"
CLOCK_2026_09_20 = "2026-09-20T00:00:00Z"
CLOCK_2026_09_30 = "2026-09-30T00:00:00Z"
CLOCK_2026_10_01 = "2026-10-01T00:00:00Z"
CLOCK_2026_10_05 = "2026-10-05T00:00:00Z"
CLOCK_2026_12_01 = "2026-12-01T00:00:00Z"
FUTURE_LICENSE_EXPIRES_ON = "2027-12-31T00:00:00Z"
FUTURE_LOCK_EXPIRES_AT = "2027-01-01T00:00:00Z"

# --- Standard inputs ---------------------------------------------------------
STANDARD_VOLUME_EXPECTATION_CENTS = 100_000_000
STANDARD_LOAN_AMOUNT_CENTS = 40_000_000
STANDARD_PLAN_LENDER_PAID_CENTS = 250_000
STANDARD_PLAN_BORROWER_PAID_CENTS = 300_000
FULL_MARK_SCORE_INPUTS = {
    "net_worth_cents": NET_WORTH_TARGET_CENTS,
    "liquidity_cents": LIQUIDITY_TARGET_CENTS,
    "total_liabilities_cents": 0,
    "years_in_business": EXPERIENCE_TARGET_YEARS,
    "prior_year_funded_volume_cents": STANDARD_VOLUME_EXPECTATION_CENTS,
    "audit_attested": True,
}

# Reference scenario constants used across pricing fixtures.
REFERENCE_BASE_RATE_PCT = 6.125
REFERENCE_FICO = 780
REFERENCE_LTV = 0.5500


def ltv_band_label(ltv_ratio: float) -> str:
    """Band selection for ltv_ratio: half-open on the left, closed on the right."""
    if ltv_ratio <= 0.60:
        return "up-to-60"
    if ltv_ratio <= 0.70:
        return "60-70"
    if ltv_ratio <= 0.80:
        return "70-80"
    if ltv_ratio <= 0.90:
        return "80-90"
    if ltv_ratio <= 0.95:
        return "90-95"
    return "over-95"


def credit_bucket_label(representative_fico: int) -> str:
    """Credit band selection: closed on the left, open on the right, except the last."""
    if representative_fico >= 760:
        return "760-plus"
    if representative_fico >= 740:
        return "740-759"
    if representative_fico >= 720:
        return "720-739"
    if representative_fico >= 700:
        return "700-719"
    if representative_fico >= 680:
        return "680-699"
    return "under-680"


def price_grid_row_key(representative_fico: int) -> str:
    """Row key for the base price grid: fico rounded half up to the nearest ten."""
    rounded = int(round(representative_fico / 10.0)) * 10
    if rounded >= 760:
        return "760-plus"
    if rounded >= 660:
        return str(rounded)
    return "under-660"


def expected_price_points(representative_fico: int, ltv_ratio: float,
                          overall_adjustment_pct: float) -> float:
    """Seven-step price_points derivation, re-derived from the PRD prose."""
    row = PRICE_TABLE[price_grid_row_key(representative_fico)]
    base = row[PRICE_GRID_COLS.index(ltv_band_label(ltv_ratio))]
    provisional = base + overall_adjustment_pct
    if provisional <= PLATINUM_MAX_POINTS:
        tier = "PLATINUM"
    elif provisional <= GOLD_MAX_POINTS:
        tier = "GOLD"
    elif provisional <= SILVER_MAX_POINTS:
        tier = "SILVER"
    else:
        tier = "BRONZE"
    return round_half_up(provisional + TIER_DISCOUNT[tier], 3)


def round_half_up(value: float, places: int = 2) -> float:
    from decimal import Decimal, ROUND_HALF_UP

    quantum = Decimal(1).scaleb(-places)
    return float(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def financial_strength_score(net_worth_cents, liquidity_cents,
                             total_liabilities_cents, years_in_business) -> float:
    """Four-term weighted blend, re-derived from the PRD §3.2 formula."""
    net_worth_term = min(1.0, net_worth_cents / NET_WORTH_TARGET_CENTS) * 40
    liquidity_term = min(1.0, liquidity_cents / LIQUIDITY_TARGET_CENTS) * 30
    denom = max(1, net_worth_cents * LEVERAGE_CAP_RATIO)
    leverage_term = max(0.0, 1.0 - total_liabilities_cents / denom) * 20
    experience_term = min(1.0, years_in_business / EXPERIENCE_TARGET_YEARS) * 10
    raw = net_worth_term + liquidity_term + leverage_term + experience_term
    return round_half_up(min(100.0, max(0.0, raw)), 2)


def attainment_band(prior_year_funded_volume_cents, volume_expectation_cents) -> str:
    ratio = prior_year_funded_volume_cents / volume_expectation_cents
    if ratio >= ATTAINMENT_MEETS_RATIO:
        return "MEETS_EXPECTATION"
    if ratio >= ATTAINMENT_NEAR_RATIO:
        return "NEAR_EXPECTATION"
    return "BELOW_EXPECTATION"


def repurchase_exposure(loan_amount_cents: int, rolling_funded_volume_cents: int) -> int:
    """Pair-share reversal plus half the contribution, rounded once to whole cents."""
    pool = rolling_funded_volume_cents
    f = loan_amount_cents
    share = (pool * f) / (pool + f)
    return int(round_half_up(share + f / 2.0, 0))