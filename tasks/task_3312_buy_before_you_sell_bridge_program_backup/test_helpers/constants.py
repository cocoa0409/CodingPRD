"""Domain thresholds stated in PRD.md.

Every constant here is fixed verbatim by PRD prose. Constants the PRD names
without ever fixing a value (for example the appraisal-validity window and the
coordination-task slot length) are deliberately absent: no assertion may depend
on a value the contract leaves open.
"""

# ── Logical clock (PRD sections 2.7, 3.11) ──────────────────────
LOGICAL_CLOCK_START = "2026-09-01T00:00:00Z"

# ── Money / rate units (PRD section 2.4) ────────────────────────
BPS_DENOMINATOR = 10_000

# ── Household intake (PRD section 3.1) ──────────────────────────
CREDIT_SCORE_MIN = 300
CREDIT_SCORE_MAX = 850
MAX_DTI_BPS_DEFAULT = 4300

# ── Property record (PRD section 3.1) ───────────────────────────
MORTGAGE_PAYOFF_DEFAULT_CENTS = 0
PURCHASE_PRICE_DEFAULT_CENTS = 0
REPAIR_PROGRESS_BPS_DEFAULT = 300
SITE_VISIT_SCALE = 100

# ── Agent roster (PRD sections 3.1, 3.7) ────────────────────────
REFERRAL_RATE_BPS_DEFAULT = 250

# ── Qualification capacity (PRD section 3.2) ────────────────────
BASE_EQUITY_RATIO_BPS = 7000
MARKET_APPRECIATION_BPS = 1000
CONDITION_CREDIT_BASE_BPS = 500
CONDITION_RANK = {"A": 4, "B": 3, "C": 2, "D": 1}
PMI_MAX_MULTIPLE = 50_000
CREDIT_SCORE_MIN_FOR_APPROVAL = 620

# ── Enrolment and program fee (PRD section 3.3) ─────────────────
PROGRAM_FEE_BPS = 150
PROJECTED_CARRY_MONTHS_MIN = 1
PROJECTED_CARRY_MONTHS_MAX = 24

# ── Draw headroom and advances (PRD section 3.4) ────────────────
STAKE_HOLDER_REVIEW_CENTS = 9_000_000
REPAIR_APPROVAL_CAP_CENTS = 5_000_000

# ── Interest accrual (PRD section 3.5) ──────────────────────────
INTERIM_DAY_COUNT_BPS = 3000
INTERIM_RATE_DENOMINATOR = 10_000 * 10_000

# ── Guaranteed offer / price floor (PRD section 3.6) ────────────
OFFER_PRICE_DISCOUNT_BPS = 1200
CONDITION_MODIFIER_BPS = {"A": 0, "B": 200, "C": 450, "D": 600}
REGULATORY_MIN_RATIO_BPS = 8500
OFFER_WINDOW_DAYS_MIN = 1
OFFER_WINDOW_DAYS_MAX = 180
OFFER_EXTENSION_DAYS = 30

# ── Referral economics (PRD section 3.7) ────────────────────────
QUALIFIED_BONUS_BPS = 300
REFERRAL_CREDIT_CAP_CENTS = 20_000
REFERRAL_CREDIT_PER_TASK_CENTS = 8_000

# ── Discount waterfall (PRD section 3.8) ────────────────────────
AGENT_REFERRAL_POOL_CENTS = 25_000
COORDINATION_POOL_CENTS = 10_000

# ── Carrying-cost surcharge (PRD section 3.9) ───────────────────
NEW_CONSTRUCTION_ADJUSTMENT_BPS = 2500
PROJECTION_POOLING_THRESHOLD_MONTHS = 3

# ── Program charge disclosure (PRD section 3.9) ─────────────────
COORDINATION_FLAT_CENTS = 45_000
DISCLOSURE_MIN_CENTS = 300_000
DISCLOSURE_REVIEW_CENTS = 500_000
ESCALATOR_LOW_BPS = 250
ESCALATOR_HIGH_BPS = 500
SUBTOTAL_REFERENCE_CENTS = 400_000

# ── Loan-to-value ceiling (PRD section 3.11) ────────────────────
LTV_LIMIT_BPS = 7500

# ── Dual cost view (PRD section 3.9) ────────────────────────────
COST_VIEW_MONTH_DENOMINATOR = 10_000 * 100

# ── Fixture defaults ────────────────────────────────────────────
TEST_DEFAULTS = {
    "CREDIT_SCORE": 700,
    "HOUSEHOLD_INCOME_CENTS": 30_000_000,
    "INTEREST_RATE_BPS": 800,
    "PROJECTED_CARRY_MONTHS": 4,
    "WINDOW_DAYS": 30,
}