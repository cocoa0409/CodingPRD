"""Domain thresholds and canonical fixture data (PRD §2.3, §2.4, §3).

All monetary values are integer cents (PRD §2.6). Rates are decimals preserved
at input precision. Every constant below is pinned by a verbatim PRD sentence.
"""

# --- Logical clock (PRD §2.4) ------------------------------------------------
# "the logical clock ... starts fixed at 2026-09-01T00:00:00Z"
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"

# --- Stale credit (PRD §3.6) --------------------------------------------------
# "a stale credit rate of 0.75"
STALE_CREDIT_RATE = 0.75
# "The cap is 10% of the distributor's gross delivered charges ..."
STALE_CAP_PCT = 0.10
# pull_date >= delivery_date + shelf_life_days, else ERR_CLAIM_NOT_STALE_YET
# pull_date <= delivery_date + shelf_life_days + 7, else ERR_CLAIM_WINDOW_EXPIRED
CLAIM_PULL_GRACE_DAYS = 7
# "a claim submitted more than two days after the pull, is too late"
CLAIM_SUBMIT_AFTER_PULL_DAYS = 2
# auto-expiry: claims "created more than three days before the close date"
CLAIM_AUTO_EXPIRY_DAYS = 3

# --- Service audits and strikes (PRD §3.5) ------------------------------------
# "a violation when any single component score is strictly below 70"
VIOLATION_THRESHOLD = 70
# weighted blend: 40% shelf stocking, 30% rotation, 30% display
AUDIT_WEIGHT_SHELF = 0.40
AUDIT_WEIGHT_ROTATION = 0.30
AUDIT_WEIGHT_DISPLAY = 0.30
AUDIT_SCORE_MIN = 0
AUDIT_SCORE_MAX = 100
# "the recomputed count has reached three, the agreement auto-suspends"
STRIKE_SUSPEND_THRESHOLD = 3
# "the trailing ninety calendar days ending on ... the new audit's date"
STRIKE_WINDOW_DAYS = 90

# --- Territory transfer valuation (PRD §3.8) ----------------------------------
# "depreciation: 2% of purchase_price_cents per full year of service"
DEPRECIATION_RATE = 0.02
# "a FOR_CAUSE exit ... assesses a penalty_cents of 15% of the purchase price"
FOR_CAUSE_PENALTY_PCT = 0.15
# "a VOLUNTARY exit credits goodwill of 50,000 cents per compliant account"
GOODWILL_PER_COMPLIANT_ACCOUNT_CENTS = 50000
DAYS_PER_VALUATION_YEAR = 365

# --- Financing (PRD §3.2) -----------------------------------------------------
WEEKS_PER_YEAR = 52
DAYS_PER_YEAR = 365

# --- Account standing (PRD §2.9) ----------------------------------------------
# "PROBATION whenever the trade balance exceeds 80% of ... credit_limit_cents"
PROBATION_BALANCE_PCT = 0.80

# --- Orders (PRD §3.3) ---------------------------------------------------------
# "the delivery_date must fall at least two days after the current logical date"
ORDER_LEAD_TIME_DAYS = 2

# --- Pagination (PRD §2.3) -----------------------------------------------------
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# --- Grouped views (skill template shape) --------------------------------------
THRESHOLDS = {
    "VIOLATION_THRESHOLD": VIOLATION_THRESHOLD,
    "STRIKE_SUSPEND_THRESHOLD": STRIKE_SUSPEND_THRESHOLD,
    "STRIKE_WINDOW_DAYS": STRIKE_WINDOW_DAYS,
    "ORDER_LEAD_TIME_DAYS": ORDER_LEAD_TIME_DAYS,
    "CLAIM_PULL_GRACE_DAYS": CLAIM_PULL_GRACE_DAYS,
    "CLAIM_SUBMIT_AFTER_PULL_DAYS": CLAIM_SUBMIT_AFTER_PULL_DAYS,
    "CLAIM_AUTO_EXPIRY_DAYS": CLAIM_AUTO_EXPIRY_DAYS,
}

RATES = {
    "STALE_CREDIT_RATE": STALE_CREDIT_RATE,
    "STALE_CAP_PCT": STALE_CAP_PCT,
    "DEPRECIATION_RATE": DEPRECIATION_RATE,
    "FOR_CAUSE_PENALTY_PCT": FOR_CAUSE_PENALTY_PCT,
    "PROBATION_BALANCE_PCT": PROBATION_BALANCE_PCT,
}

# --- Canonical catalog ---------------------------------------------------------
# Four-sku product catalog used across the test plan. Prices/shelf lives are
# chosen so the PRD §3.4 worked example is reproducible: with discount 0.20,
# RYE-09 x3 and BAG-06 x3 charge 766 + 377 = 1143 per-line-then-sum.
SKU_WHT = "WHT-24"
SKU_BUN = "BUN-12"
SKU_RYE = "RYE-09"
SKU_BAG = "BAG-06"

STANDARD_PRODUCT_CATALOG = [
    {"sku": SKU_WHT, "display_name": "White 24oz", "shelf_life_days": 5, "list_price_cents": 320},
    {"sku": SKU_BUN, "display_name": "Buns 12pk", "shelf_life_days": 4, "list_price_cents": 240},
    {"sku": SKU_RYE, "display_name": "Rye 9-grain", "shelf_life_days": 7, "list_price_cents": 319},
    {"sku": SKU_BAG, "display_name": "Bagels 6pk", "shelf_life_days": 3, "list_price_cents": 157},
]

STANDARD_DISCOUNT_PCT = 0.20

# Per-unit distributor charge at the standard discount, per PRD §3.6:
# unit_charge = round_half_up(list_price_cents * (1 - discount_pct)).
# WHT-24: round(320 * 0.8) = 256; BUN-12: round(240 * 0.8) = 192;
# RYE-09: round(319 * 0.8) = round(255.2) = 255; BAG-06: round(157 * 0.8) = round(125.6) = 126.
UNIT_CHARGE_CENTS = {SKU_WHT: 256, SKU_BUN: 192, SKU_RYE: 255, SKU_BAG: 126}

# --- Canonical fixture values ---------------------------------------------------
TEST_DEFAULTS = {
    "BAKERY_NAME": "Southwest Bakery",
    "BAKERY_CAPACITY_UNITS": 100,
    "TERRITORY_AREA_CODE": "DAL-N",
    "TERRITORY_LIST_PRICE_CENTS": 25000000,
    "DISTRIBUTOR_LEGAL_NAME": "RoutePro LLC",
    "DISTRIBUTOR_CREDIT_LIMIT_CENTS": 200000,
    "PURCHASE_PRICE_CENTS": 1000000,
    "DISCOUNT_PCT": STANDARD_DISCOUNT_PCT,
    "AGREEMENT_START_DATE": "2026-09-01",
    "AGREEMENT_END_DATE": "2027-09-01",
    "STORE_NAME": "FreshMart Oak",
}

# Canonical financed purchase: principal 52,000 cents at 0.10 annual over
# 10 weeks -> weekly payment 5255 cents per the level-annuity formula of
# PRD §3.2 (r = 0.10/52; payment = 52000 * r / (1 - (1 + r) ** -10)).
FINANCED_AMOUNT_CENTS = 52000
FINANCING_ANNUAL_RATE = 0.10
FINANCING_TERM_WEEKS = 10
FINANCING_WEEKLY_PAYMENT_CENTS = 5255

# A fixed ISO week used by settlement tests: 2026-09-07 falls in week 2026-W37.
ISO_WEEK_2026_W37 = "2026-W37"
