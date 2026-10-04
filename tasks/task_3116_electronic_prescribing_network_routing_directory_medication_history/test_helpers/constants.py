"""Domain constants: fee schedules, calculation thresholds, and calculation literals
from PRD §3.7, §3.8 and §3.9.
"""

# ─── Transaction fee settlement: tier schedules (PRD §3.7) ───
SENDER_SCHEDULE = {
    "default": {"FREE_UPPER": 200, "STANDARD_UPPER": 2000, "R2": 12, "R3": 7},
    "MED_HISTORY": {"FREE_UPPER": 100, "STANDARD_UPPER": 1000, "R2": 18, "R3": 9},
}
RECEIVER_SCHEDULE = {
    "default": {"FREE_UPPER": 200, "STANDARD_UPPER": 2500, "R2": 8, "R3": 4},
}

MONTHLY_CHARGEABLE_CEILING = 7500
SHORTFALL_RESERVE_RATE = 0.30
ROLLING_TRAJECTORY_FACTOR = 1.45

# The sender-schedule value at the ceiling for a non-history type.
CEILING_FEE_CENTS_SENDER_DEFAULT = 60100


def apply_tiers(n, schedule=None):
    """The pinned marginal tier schedule (PRD §3.7): n2 counts in the STANDARD band,
    n3 counts in the VOLUME band, and the amount is n2 * R2 + n3 * R3."""
    sched = schedule or SENDER_SCHEDULE["default"]
    n2 = min(max(0, n - sched["FREE_UPPER"]), sched["STANDARD_UPPER"] - sched["FREE_UPPER"])
    n3 = max(0, n - sched["STANDARD_UPPER"])
    return n2 * sched["R2"] + n3 * sched["R3"]


# ─── Medication history batch cost (PRD §3.8) ───
MED_HISTORY_QUERY_BASE_CENTS = 25
MED_HISTORY_QUERY_PER_RECORD_CENTS = 10
RECORD_FEE_CAP = 40


def batch_cost_cents(source_record_count):
    """25 + 10 * min(source_record_count, 40)."""
    return MED_HISTORY_QUERY_BASE_CENTS + MED_HISTORY_QUERY_PER_RECORD_CENTS * min(
        source_record_count, RECORD_FEE_CAP
    )


# ─── Reliability variants (PRD §2.6) ───
RELIABILITY_WINDOW_N = 20
EWMA_ALPHA = 0.0670
DEGRADE_BELOW = 0.90
REACTIVATE_AT_LEAST = 0.95

# ─── Delivery reachability (PRD §2.4) ───
AT_RISK_BELOW = 0.50

# ─── Endpoint coverage invariant (PRD §2.6) ───
ACTIVE_COVERAGE_FLOOR = 0.50

# ─── Benefit cost estimate constants ───
PRIOR_AUTH_PLAN_SHARE_CAP = 0.50

# ─── Logical clock (PRD §2.10) ───
CLOCK_STARTUP_DEFAULT = "2026-09-01T00:00:00Z"

TEST_DEFAULTS = {
    "MONTH_KEY": "2026-09",
    "BENCHMARK_PRICE_CENTS": 8000,
    "PLAN_COPAY_CENTS": 1500,
    "PLAN_COINSURANCE_PCT": 0.2,
    "PLAN_DEDUCTIBLE_CENTS": 10000,
    "PLAN_DEDUCTIBLE_MET_CENTS": 4000,
    "PLAN_BRAND_FEE_CENTS": 300,
    "FORMULARY_PREFERRED_PCT": 0.3,
    "PLAN_BENEFIT_CAP_CENTS": 50000,
}

# ─── Worked examples pinned in PRD prose ───
# 500-count sender cell of an ordinary type: charge 3600, MONTHLY final 2520,
# ROLLING_90_DAY final 1710.
WORKED_500_COUNT = {
    "charge_cents": 3600,
    "monthly_reserve_cents": 1080,
    "monthly_final_cents": 2520,
    "rolling_projection": 725,
    "rolling_reserve_cents": 1890,
    "rolling_final_cents": 1710,
    "mode_difference_cents": 630,
}

# benefit_cost_estimate worked example (PRD §3.9)
BENEFIT_WORKED_EXAMPLE = {
    "benchmark_price_cents": 8000,
    "effective_benchmark_cents": 8000,
    "patient_cost_share_cents": 3100,
    "deductible_remaining_cents": 6000,
    "brand_fee_cents": 300,
    "provisional_patient_pay_cents": 3100,
    "provisional_plan_pay_cents": 5200,
    "final_patient_pay_cents": 3400,
    "final_plan_pay_cents": 4900,
    "total_cents": 8300,
}

# medication_history_batch_cost boundary literals (PRD §3.8)
BATCH_COST_BOUNDARIES = {
    3: 55,      # 25 + 10 * 3
    25: 275,    # 25 + 10 * 25
    39: 415,    # 25 + 10 * 39
    40: 425,    # cap reached
    41: 425,
    500: 425,
}

# monthly chargeable ceiling boundary literals (PRD §3.7)
FEE_CEILING_BOUNDARIES = {
    7499: 60093,   # 5499*12 + 2000*7
    7500: 60100,   # 5500*12 + 2000*7
    7501: 60100,   # clamped to 7500 before tiering
}