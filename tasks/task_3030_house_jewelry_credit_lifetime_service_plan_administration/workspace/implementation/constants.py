"""Every constant the calculation and compliance rules name."""

from decimal import Decimal, ROUND_HALF_UP

# --- counter credit pricing (credit_limit_registry_pricing) ---
TIER_3_REQUEST_THRESHOLD_CENTS = 1000000
TIER_2_REQUEST_THRESHOLD_CENTS = 500000
TIER_1_REQUEST_THRESHOLD_CENTS = 200000
INCOME_DOWNGRADE_THRESHOLD_CENTS = 2500000
ALL_STATES_KEY = "*"

# --- deferred-interest plan economics (promo_plan_tiering / promo_interest_accrual) ---
MONTHS_PER_QUARTER = 3
DAYS_PER_YEAR = 365
APR_PROMO_12_6M = 26.99
APR_PROMO_18_6M = 27.99
APR_PROMO_24_12M = 28.99
DEFERRAL_BPS_PROMO_12_6M = 1200
DEFERRAL_BPS_PROMO_18_6M = 1500
DEFERRAL_BPS_PROMO_24_12M = 1600

# The deferral fee is built tier by tier across the code boundaries rather than
# at the chosen code's single headline rate (MARGINAL_DEFERRAL_BPS); for
# PROMO_12_6M the two readings coincide, as the document states.
DEFERRAL_TIERS = (
    (12, DEFERRAL_BPS_PROMO_12_6M),
    (18, DEFERRAL_BPS_PROMO_18_6M),
    (24, DEFERRAL_BPS_PROMO_24_12M),
)

DECISION_VALIDITY_HOURS = 24

# --- bench liability (repair_loss_liability) ---
WARRANTY_RESERVE_PCT = 0.07
LOSS_LIABILITY_DEFAULT_CENTS = 0

# --- routing and turnaround (vendor_routing_and_turnaround) ---
ROUTE_TABLE = {
    "STONE_LOSS": "MALCA",
    "SETTING": "JEWELCRAFT",
    "PRONG": "JEWELCRAFT",
    "RESIZE": "MASTERMELT",
    "OTHER": "MASTERMELT",
}
RUSH_SHOP_CODE = "CONRUSH"
CEILING_MULTIPLIER = 1.5

# --- turnaround breach compensation (turnaround_breach_compensation) ---
PARTIAL_BREACH_PCT = 0.05
MAJOR_BREACH_PCT = 0.15
FULL_BREACH_PCT = 0.25
BREACH_COMPENSATION_PCT = 0.05

# --- trade-up (trade_up_credit_basis / balance_due_after_trade_up) ---
TRADE_UP_CREDIT_PCT = 0.85
TRADE_UP_BONUS_PCT = 0.10
TRADE_UP_CREDIT_CAP_MULTIPLIER = 2

# --- custom commissions (custom_design_deposit_and_forfeit) ---
DEPOSIT_PCT_MIN = 0.30
DEPOSIT_PCT_MAX = 0.50
CAD_REVISION_FEE_CENTS = 2500
FREE_REVISION_LIMIT = 2

# Rough recovery on an abandoned bespoke build: no material-recovery endpoint
# exists, so the recovered material value is always 0.
MATERIAL_RECOVERY_CENTS = 0

# The certified production metal list.  No custom-design input declares a metal
# field, so nothing can be submitted off the list; the request body carries no
# metal key at all.
CERTIFIED_PRODUCTION_METALS = ("14K_GOLD", "18K_GOLD", "PLATINUM", "STERLING_SILVER")

# --- inspection scheduling (inspection_reminder_scheduling) ---
REMINDER_LEAD_DAYS = 14
FIRST_CYCLE_INDEX = 1

# --- credit posture (credit_tier_from_plan_mix_and_inspection_streak) ---
UTIL_VIOLATION_BPS = 8000
UTIL_WATCH_BPS = 5000
STREAK_COMPONENT_CAP = 3

# --- statements (statement_balance_rollup / payment_allocation_waterfall) ---
TIER_FEE_PCT_HIGH = 0.03
TIER_FEE_PCT_MID = 0.02
TIER_FEE_PCT_LOW = 0.01
TIER_BOUNDARY_HIGH_CENTS = 500000
TIER_BOUNDARY_MID_CENTS = 200000
MIN_FLOOR_CENTS = 5000
MIN_BASE_PCT_LOW = 0.01
MIN_BASE_PCT_HIGH = 0.02
HIGH_BALANCE_THRESHOLD_CENTS = 200000

# --- replacement appraisal (replacement_appraised_value) ---
APPRAISAL_MULTIPLIER_UNREPAIRABLE = 1.04
APPRAISAL_MULTIPLIER_DEFAULT = 1.00
LAB_GROWN_FACTOR = 0.65
INSURANCE_REPLACEMENT_PCT = 0.75
INSURANCE_REPLACEMENT_CAP_PCT = 0.25

# --- payoff ledger (payoff_ledger_projection) ---
PROMOTIONAL_BUCKET = "PROMOTIONAL"

# --- misc product constants ---
NATURAL_ORIGIN_CARAT_THRESHOLD = 1.00


def half_up(value):
    """Round a Decimal or number half away from zero to a whole cent."""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    return int(dec.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def ceil_cents(value):
    """Round away from zero to the next whole cent (the down-payment floor)."""
    dec = value if isinstance(value, Decimal) else Decimal(str(value))
    from decimal import ROUND_CEILING
    return int(dec.quantize(Decimal("1"), rounding=ROUND_CEILING))