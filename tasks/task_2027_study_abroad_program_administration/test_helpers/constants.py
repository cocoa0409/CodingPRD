"""Domain thresholds — numeric constants from PRD §2.6, §3.3, §3.4, §3.8."""

# Billing pipeline constants (PRD §3.4).
HOME_TUITION_PER_TERM_CENTS = 2400000      # $24,000 per term home-tuition base
INSURANCE_PREMIUM_CENTS = 35000            # $350 premium when agreement requires insurance
APPLICATION_FEE_CENTS = 5000               # $50 application fee, always applied
AID_CAP_HOME_TUITION = 1.00                # aid portable up to 100% of base
AID_CAP_PROGRAM_FEE = 0.60                 # aid portable up to 60% of base

# Credit conversion constants (PRD §2.6, §3.8).
TRANSFER_GRADE_MIN = 2.0                   # lines below this grade contribute 0 to final_credits
CREDIT_ROUNDING_STEP = 0.5                 # per-course round-half-up step

# Temporal rules (PRD §3.1).
PROGRAM_SCHEDULE_BUFFER_DAYS = 7           # same-host programs must be >= 7 days apart

# Logical clock initial reading (PRD §2.5).
INITIAL_CLOCK_UTC = "2026-08-01T00:00:00Z"

THRESHOLDS = {
    "HOME_TUITION_PER_TERM_CENTS": HOME_TUITION_PER_TERM_CENTS,
    "INSURANCE_PREMIUM_CENTS": INSURANCE_PREMIUM_CENTS,
    "APPLICATION_FEE_CENTS": APPLICATION_FEE_CENTS,
    "AID_CAP_HOME_TUITION": AID_CAP_HOME_TUITION,
    "AID_CAP_PROGRAM_FEE": AID_CAP_PROGRAM_FEE,
    "TRANSFER_GRADE_MIN": TRANSFER_GRADE_MIN,
    "CREDIT_ROUNDING_STEP": CREDIT_ROUNDING_STEP,
    "PROGRAM_SCHEDULE_BUFFER_DAYS": PROGRAM_SCHEDULE_BUFFER_DAYS,
}

TEST_DEFAULTS = {
    "PROGRAM_FEE_CENTS": 1800000,
    "CAPACITY": 30,
    "MIN_GPA": 2.75,
    "STUDENT_GPA": 3.00,
    "CREDIT_CONVERSION_FACTOR": 0.75,
}
