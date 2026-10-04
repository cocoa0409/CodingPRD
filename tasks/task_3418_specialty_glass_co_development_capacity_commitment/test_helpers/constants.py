"""Domain thresholds and wire constants.

Every numeric value here is transcribed from the PRD prose sentence that
states it; each entry carries its PRD section and the quoted fragment in a
comment so the mapping can be audited mechanically.
"""

# ── Logical clock ────────────────────────────────────────────────────────────
# PRD section 2.4: "the logical clock reads exactly 2026-09-01T00:00:00Z
# (CONST.DEFAULT_CLOCK_ISO)"
DEFAULT_CLOCK_ISO = "2026-09-01T00:00:00Z"

# ── Tanks and campaigns ──────────────────────────────────────────────────────
# PRD section 3.5: "its `created_at` plus 540 days (CONST.TANK_CONSTRUCTION_DAYS)"
TANK_CONSTRUCTION_DAYS = 540
# PRD section 3.5: "at least 365 days (CONST.MIN_CAMPAIGN_DAYS, with exactly
# 365 allowed) and at most 1825 days (CONST.MAX_CAMPAIGN_DAYS)"
MIN_CAMPAIGN_DAYS = 365
MAX_CAMPAIGN_DAYS = 1825
# PRD section 3.5: "the gap between the adjoining window edges must be at
# least 45 days (CONST.CHANGEOVER_GAP_DAYS)"
CHANGEOVER_GAP_DAYS = 45

# ── Qualification ────────────────────────────────────────────────────────────
# PRD section 3.3: "only while `attempt_number` is below 3
# (CONST.MAX_QUAL_ATTEMPTS)"
MAX_QUAL_ATTEMPTS = 3

# ── Licensing ────────────────────────────────────────────────────────────────
# PRD section 3.7: "must span at least 180 days (CONST.LICENSE_MIN_TERM_DAYS)"
LICENSE_MIN_TERM_DAYS = 180

# ── Yield learning curve ─────────────────────────────────────────────────────
# PRD section 3.5: "below 20000 units (CONST.YIELD_STEP1_MAX_UNITS) the
# provisional yield rate is 0.62 (CONST.YIELD_STEP1_RATE)"
YIELD_STEP1_MAX_UNITS = 20000
YIELD_STEP1_RATE = 0.62
# PRD section 3.5: "at 20000 units or more but below 80000 units
# (CONST.YIELD_STEP2_MAX_UNITS) it is 0.78 (CONST.YIELD_STEP2_RATE)"
YIELD_STEP2_MAX_UNITS = 80000
YIELD_STEP2_RATE = 0.78
# PRD section 3.5: "at 80000 units or more it is 0.90 (CONST.YIELD_STEP3_RATE)"
YIELD_STEP3_RATE = 0.90

# ── Campaign unit cost ───────────────────────────────────────────────────────
# PRD section 3.5: "850 cents base melt cost per unit
# (CONST.BASE_MELT_COST_CENTS_PER_UNIT)"
BASE_MELT_COST_CENTS_PER_UNIT = 850
# PRD section 3.5: "60 cents (CONST.ENERGY_SURCHARGE_T2_CENTS) when the basis
# units are at least 50000 (CONST.ENERGY_SURCHARGE_T1_MAX_UNITS), and 120
# cents (CONST.ENERGY_SURCHARGE_T1_CENTS) below that"
ENERGY_SURCHARGE_T1_MAX_UNITS = 50000
ENERGY_SURCHARGE_T1_CENTS = 120
ENERGY_SURCHARGE_T2_CENTS = 60
# PRD section 3.5: "otherwise it is 4000 cents per campaign day
# (CONST.CHANGEOVER_AMORTIZATION_CENTS_PER_DAY) multiplied by the campaign-day
# count"
CHANGEOVER_AMORTIZATION_CENTS_PER_DAY = 4000

# ── Commitment coverage and prepayment ───────────────────────────────────────
# PRD section 3.4: "divided by 1000 cents per unit
# (CONST.PREPAYMENT_UNIT_CREDIT_CENTS), floored to a whole unit"
PREPAYMENT_UNIT_CREDIT_CENTS = 1000
# PRD section 3.4: "at least 1000000 cents — CONST.MIN_PREPAYMENT_CENTS — with
# exactly the minimum allowed"
MIN_PREPAYMENT_CENTS = 1000000
# PRD section 3.4: "`TIER_A` when base coverage is at least 1.2
# (CONST.TIER_A_COVERAGE_MIN), otherwise `TIER_B` when it is at least 1.0
# (CONST.TIER_B_COVERAGE_MIN), otherwise `TIER_C`"
TIER_A_COVERAGE_MIN = 1.2
TIER_B_COVERAGE_MIN = 1.0
# PRD section 3.4: "a bonus rate of 0.05 (CONST.TIER_A_BONUS_RATE) for
# `TIER_A`, 0.02 (CONST.TIER_B_BONUS_RATE) for `TIER_B`, and zero for
# `TIER_C`"
TIER_A_BONUS_RATE = 0.05
TIER_B_BONUS_RATE = 0.02

# ── Supply coverage and breach ───────────────────────────────────────────────
# PRD section 3.3 (retire cascade, hop three): "if it has fallen below 1.0
# (CONST.SUPPLY_COVERAGE_MIN)"; also section 3.4: "recomputes that figure
# below 1.0"
SUPPLY_COVERAGE_MIN = 1.0
# PRD section 3.3: "a `breach_deadline` set to the current logical clock plus
# 90 days (CONST.BREACH_GRACE_DAYS)"
BREACH_GRACE_DAYS = 90

# ── Royalty tiers ────────────────────────────────────────────────────────────
# PRD section 3.8: "0.03 (CONST.ROYALTY_T1_RATE) when the total is at most
# 100000 units (CONST.ROYALTY_T1_MAX_UNITS), 0.022 (CONST.ROYALTY_T2_RATE)
# when it is above 100000 and at most 500000 units
# (CONST.ROYALTY_T2_MAX_UNITS), and 0.015 (CONST.ROYALTY_T3_RATE) above
# 500000"
ROYALTY_T1_MAX_UNITS = 100000
ROYALTY_T1_RATE = 0.03
ROYALTY_T2_MAX_UNITS = 500000
ROYALTY_T2_RATE = 0.022
ROYALTY_T3_RATE = 0.015

# ── Pagination (PRD section 2.3) ─────────────────────────────────────────────
# "limit, defaulting to 10 with a minimum of 1 and a maximum of 100, and
# offset, defaulting to 0"
DEFAULT_PAGE_LIMIT = 10
MIN_PAGE_LIMIT = 1
MAX_PAGE_LIMIT = 100
DEFAULT_PAGE_OFFSET = 0

# ── Role wire strings (PRD section 2.1) ──────────────────────────────────────
ROLE_PLATFORM_ADMIN = "PlatformAdmin"
ROLE_PROGRAM_MANAGER = "ProgramManager"
ROLE_CAPACITY_PLANNER = "CapacityPlanner"
ROLE_FINANCE_CONTROLLER = "FinanceController"
ROLE_LEGAL_COUNSEL = "LegalCounsel"
ROLE_DEVICE_MAKER = "DeviceMaker"

ALL_ROLES = (
    ROLE_PLATFORM_ADMIN,
    ROLE_PROGRAM_MANAGER,
    ROLE_CAPACITY_PLANNER,
    ROLE_FINANCE_CONTROLLER,
    ROLE_LEGAL_COUNSEL,
    ROLE_DEVICE_MAKER,
)
