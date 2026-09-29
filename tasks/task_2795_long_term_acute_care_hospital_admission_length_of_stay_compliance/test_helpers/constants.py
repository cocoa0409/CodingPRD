"""
Domain constants: the named thresholds, windows and multipliers of the specification.

Every value here is quoted from the specification. Tests import these names rather than
restating literals, so that the provenance of each figure is visible in one place and a
misremembered threshold fails once, here, instead of silently in thirty places.
"""

# ── The logical clock ────────────────────────────────
# "Before any operator sets it, the logical clock reads exactly 2026-08-01T00:00:00Z".
CLOCK_EPOCH = "2026-08-01T00:00:00Z"

# ── Pagination (§2.3) ────────────────────────────────
DEFAULT_LIMIT = 10
MIN_LIMIT = 1
MAX_LIMIT = 100
DEFAULT_OFFSET = 0

# ── Precision (§2.5) ─────────────────────────────────
PERCENT_DECIMALS = 2
VENT_HOUR_DECIMALS = 1
RISK_SCORE_MIN = 0
RISK_SCORE_MAX = 100

# ── Referral-mix monitoring (§3.1, §3.3) ─────────────
BASE_REFERRAL_THRESHOLD_PCT = 25.00
EXPANDED_REFERRAL_THRESHOLD_PCT = 50.00
WARNING_MARGIN_PCT = 5.00
MIN_ADMISSIONS_FOR_MONITORING = 4

# ── Short-stay outlier and payment (§3.6, §3.7) ──────
# "sso_threshold_days is floor(0.8333333333333334 x alos_days)".
SSO_ALOS_FRACTION = 0.8333333333333334
SSO_IPPS_PER_DIEM_FACTOR = 1.20
FIXED_LOSS_AMOUNT_CENTS = 3000000
OUTLIER_MARGINAL_COST_FACTOR = 0.80
PCT_SCALE = 100

# ── Payment variant selection (§3.7) ─────────────────
ICU_DAYS_SITE_NEUTRAL_MIN = 3
VENT_HOURS_SITE_NEUTRAL_MIN = 96

# ── Denial risk scoring (§3.8) ───────────────────────
MISSING_DISCIPLINE_WEIGHT = 8
WEANING_GAP_WEIGHT = 15
SSO_WEIGHT = 20
SITE_NEUTRAL_WEIGHT = 10
LOS_EXCESS_WEIGHT = 0.5
ANSWERED_QUERY_CREDIT = 12
HIGH_BAND_MIN = 70
MODERATE_BAND_MIN = 40
# The four disciplines whose absence the score counts.
REQUIRED_DISCIPLINES = ("PHYSICIAN", "NURSING", "RESPIRATORY_THERAPY", "CASE_MANAGEMENT")

# ── Documentation queries (§3.8) ─────────────────────
QUERY_RESPONSE_WINDOW_HOURS = 72

# ── Interruptions (§3.5) ─────────────────────────────
INTERRUPTION_WINDOW_DAYS = {"ACUTE_CARE": 9, "IRF": 27, "SNF": 27, "HOME": 3}
INTERRUPTION_BUFFER_HOURS = 24
MAX_INTERRUPTIONS_PER_STAY = 3

# ── Recombination (§3.5) ─────────────────────────────
RECOMBINATION_WINDOW_DAYS = 3

# ── Weaning protocol (§3.4) ──────────────────────────
PROGRESSION_STEPS_REQUIRED = 2
MIN_SBT_ATTEMPTS_FOR_VENT_DEPENDENT = 3
CONSECUTIVE_FAILURES_TO_REGRESS = 2
DEFAULT_PROTOCOL_LABEL = "STANDARD_SBT"
IDT_NOTE_DAYS_PER_WEEK = 7

# ── Field length and range limits (§3.1 – §3.8) ──────
MAX_HOSPITAL_NAME_LENGTH = 120
NPI_DIGITS = 10
MAX_MRN_LENGTH = 24
MAX_FULL_NAME_LENGTH = 120
MAX_PERIOD_LABEL_LENGTH = 40
MAX_CRITERIA_LABEL_LENGTH = 40
MIN_DRG_CODE_LENGTH = 3
MAX_DRG_CODE_LENGTH = 5
MAX_NOTE_TEXT_LENGTH = 2000
MAX_PROMPT_TEXT_LENGTH = 1000
MAX_RESPONSE_TEXT_LENGTH = 2000


# ── Shared reference data used across the suite ──────
# One DRG with a long average stay, whose full standard amount is 6,000,000 cents
# (4,800,000 x 1.25) and whose short-stay threshold is floor(0.8333... x 30) = 25 days.
DRG_207 = {
    "drg_code": "207",
    "relative_weight": 1.25,
    "alos_days": 30,
    "standard_federal_rate_cents": 4800000,
    "ipps_comparable_per_diem_cents": 90000,
    "ipps_comparable_full_cents": 2400000,
}
DRG_207_FULL_STANDARD_CENTS = 6000000
DRG_207_SSO_THRESHOLD_DAYS = 25

# A shorter DRG whose full standard amount is 3,600,000 cents (4,800,000 x 0.75) and
# whose short-stay threshold is floor(0.8333... x 13) = 10 days.
DRG_573 = {
    "drg_code": "573",
    "relative_weight": 0.75,
    "alos_days": 13,
    "standard_federal_rate_cents": 4800000,
    "ipps_comparable_per_diem_cents": 400000,
    "ipps_comparable_full_cents": 3400000,
}
DRG_573_FULL_STANDARD_CENTS = 3600000
DRG_573_SSO_THRESHOLD_DAYS = 10

# The criteria set the suite screens against unless a test publishes its own.
CRITERIA_SET_A = {
    "label": "CS-2026A",
    "effective_from": "2026-01-01",
    "pmv_min_vent_hours": 96,
    "pmv_min_icu_days": 3,
    "wound_min_stage": 3,
    "wound_min_count": 2,
}

# The period every scenario admits into: it brackets both the clock epoch and the
# backdated July admission dates the arithmetic scenarios rely on.
PERIOD_FY2027 = {
    "period_label": "FY2027",
    "start_date": "2026-07-01",
    "end_date": "2027-06-30",
}
