"""Domain thresholds and numeric constants, each traceable to PRD prose.

Every value here is stated in PRD.md; see the inline section references.
Test-construction fixture defaults (cycle codes, window dates used by the
common setup chains) live in factories.py, not here.
"""

# --- PRD §2.4: logical clock -------------------------------------------------
# "At startup the clock reads exactly 2026-09-01T00:00:00Z."
CLOCK_STARTUP_DEFAULT_ISO = "2026-09-01T00:00:00Z"

# --- PRD §2.6: score scale / grid -------------------------------------------
# "a valid score is at least 0.00, at most 4.00, and an exact multiple of 0.25"
SCORE_MIN = 0.00
SCORE_MAX = 4.00
SCORE_STEP = 0.25

# --- PRD §3.3: artifact technical limits -------------------------------------
# "Videos accept only the mp4 or mov containers and at most 500 MB"
# "the three document types ... accept only pdf or docx and at most 50 MB"
# "a video longer than 15 minutes is rejected"
VIDEO_MAX_MB = 500
DOC_MAX_MB = 50
VIDEO_MAX_MINUTES = 15
VIDEO_FORMATS = ("mp4", "mov")
DOCUMENT_FORMATS = ("pdf", "docx")

# --- PRD §3.2: eligibility ---------------------------------------------------
# "years_experience must be at least 3, the minimum teaching-experience
#  requirement"
MIN_TEACHING_YEARS = 3
# fte_fraction "defaults to 1.0 and must lie between 0.5 and 1.0 inclusive"
DEFAULT_FTE_FRACTION = 1.0
FTE_FRACTION_MIN = 0.5
FTE_FRACTION_MAX = 1.0

# --- PRD §3.1: cycle rules ---------------------------------------------------
# "the component weights must sum to exactly 1.000"
REQUIRED_WEIGHT_SUM = 1.000
# "max_attempts_per_component ... defaults to 2 when omitted"
DEFAULT_MAX_ATTEMPTS_PER_COMPONENT = 2

# --- PRD §3.4: assessment-center sessions ------------------------------------
# "its slot_end_at is computed as slot_start_at plus 120 minutes"
SESSION_DURATION_MINUTES = 120

# --- PRD §3.5: calibration / reliability -------------------------------------
# "when that counter reaches 2 the assessor auto-transitions from CALIBRATING
#  to CALIBRATED"
REQUIRED_CALIBRATION_PASSES = 2
# "when that counter reaches 3 the assessor auto-transitions to SUSPENDED"
MAX_CALIBRATION_FAILURES = 3
# "the 10 most recent finalized live reads"
IRR_WINDOW = 10
# "the recomputed exact_agreement_rate falls below 0.70" (exactly 0.70 passes)
IRR_EXACT_FLOOR = 0.70
# "the fraction within 0.25 of it"
ADJACENT_BAND = 0.25

# --- PRD §3.6: double-blind scoring ------------------------------------------
# "the two scores are compared against a divergence tolerance of 0.50"
DIVERGENCE_TOLERANCE = 0.50
# benchmark tolerance "defaulting to 0.25"
DEFAULT_BENCHMARK_TOLERANCE = 0.25

# --- PRD §3.7: renewal / validity --------------------------------------------
# "APPROVE requires total_hours of at least 45 hours"
MIN_RENEWAL_HOURS = 45
# "computing valid_until as certified_at plus 1825 days"
VALIDITY_DAYS = 1825
# "from 90 days before valid_until through 30 days after it"
RENEWAL_LOOKBACK_DAYS = 90
RENEWAL_GRACE_DAYS = 30

# --- PRD §3.8: incentive programs --------------------------------------------
# "an early_bird_multiplier — defaulting to 1.10"
DEFAULT_EARLY_BIRD_MULTIPLIER = 1.10
NO_EARLY_BIRD_MULTIPLIER = 1.0  # applies when the deadline is null or missed

# --- PRD §2.3: pagination ----------------------------------------------------
# "limit ... defaults to 10, accepts a minimum of 1, and is capped at a
#  maximum of 100. offset ... defaults to 0."
PAGINATION_DEFAULT_LIMIT = 10
PAGINATION_MIN_LIMIT = 1
PAGINATION_MAX_LIMIT = 100
PAGINATION_DEFAULT_OFFSET = 0

# Grouped views for tests that iterate thresholds.
SCORING = {
    "SCORE_MIN": SCORE_MIN,
    "SCORE_MAX": SCORE_MAX,
    "SCORE_STEP": SCORE_STEP,
    "DIVERGENCE_TOLERANCE": DIVERGENCE_TOLERANCE,
}
CALIBRATION = {
    "REQUIRED_CALIBRATION_PASSES": REQUIRED_CALIBRATION_PASSES,
    "MAX_CALIBRATION_FAILURES": MAX_CALIBRATION_FAILURES,
    "DEFAULT_BENCHMARK_TOLERANCE": DEFAULT_BENCHMARK_TOLERANCE,
}
RELIABILITY = {
    "IRR_WINDOW": IRR_WINDOW,
    "IRR_EXACT_FLOOR": IRR_EXACT_FLOOR,
    "ADJACENT_BAND": ADJACENT_BAND,
}
RENEWAL = {
    "MIN_RENEWAL_HOURS": MIN_RENEWAL_HOURS,
    "VALIDITY_DAYS": VALIDITY_DAYS,
    "RENEWAL_LOOKBACK_DAYS": RENEWAL_LOOKBACK_DAYS,
    "RENEWAL_GRACE_DAYS": RENEWAL_GRACE_DAYS,
}
ARTIFACT_LIMITS = {
    "VIDEO_MAX_MB": VIDEO_MAX_MB,
    "DOC_MAX_MB": DOC_MAX_MB,
    "VIDEO_MAX_MINUTES": VIDEO_MAX_MINUTES,
}
