"""Domain thresholds and pinned instants, read from the PRD's own numbers."""

# --------------------------------------------------------------------------
# Logical clock and the ordering calendar
# --------------------------------------------------------------------------
DEFAULT_CLOCK_UTC = "2026-09-01T00:00:00Z"
NOT_OPEN_LAST_INSTANT_UTC = "2026-10-31T23:59:59Z"
REGULAR_WINDOW_OPENS_UTC = "2026-11-01T00:00:00Z"
REGULAR_WINDOW_CLOSES_UTC = "2027-01-31T23:59:59Z"
LATE_WINDOW_OPENS_UTC = "2027-02-01T00:00:00Z"
LATE_WINDOW_CLOSES_UTC = "2027-03-15T23:59:59Z"
MID_REGULAR_CLOCK_UTC = "2026-12-01T00:00:00Z"
MID_LATE_CLOCK_UTC = "2027-02-10T00:00:00Z"
LATE_WINDOW_CLOCK_UTC = "2027-02-15T00:00:00Z"

# Other pinned program instants
APPROVAL_TERM_END_UTC = "2027-06-30T23:59:59Z"
REGULAR_RELEASE_UTC = "2027-07-05T00:00:00Z"
RELEASE_READY_CLOCK_UTC = "2027-07-06T00:00:00Z"
CANCELLATION_DEADLINE_UTC = "2027-07-31T23:59:59Z"
SCORE_RELEASE_WINDOW_CLOSES_UTC = "2027-09-15T23:59:59Z"
APPEAL_DEADLINE_FLOOR_UTC = "2027-08-15T23:59:59Z"
APPEAL_CYCLE_CLOCK_UTC = "2027-08-01T00:00:00Z"
PRE_RELEASE_CLOCK_UTC = "2027-06-01T00:00:00Z"
# Registration acceptance requires the ordering window at the logical clock to
# be REGULAR or LATE (PRD §3.3), so alternate-exam setup cannot run at an
# instant past the LATE window's close of 2027-03-15T23:59:59Z.
ALTERNATE_PLANNING_CLOCK_UTC = "2027-02-10T00:00:00Z"
POST_RELEASE_CLOCK_UTC = "2027-07-10T00:00:00Z"

# --------------------------------------------------------------------------
# Order fee, late fee and unused-exam charge
# --------------------------------------------------------------------------
BASE_EXAM_FEE_CENTS = 18000
LATE_SURCHARGE_PER_EXAM_CENTS = 4000
EMERGENCY_SURCHARGE_PER_EXAM_CENTS = 9000
CONSOLIDATION_BREAKS = [0, 2, 5, 10]
CONSOLIDATION_RATES = [1.00, 0.97, 0.94, 0.90]
CLOSED_WINDOW_ADDITIONAL_CENTS = 5500
LATE_FEE_CAP_COUNT = 25
UNUSED_EXAM_GRACE_COUNT = 1
UNUSED_EXAM_CHARGE_PER_EXAM_CENTS = 27000

# --------------------------------------------------------------------------
# Order / registration / send budgets
# --------------------------------------------------------------------------
MIN_ORDER_SIZE = 1
MAX_EXAMINEES_PER_ORDER = 500
MAX_EXAMS_PER_STUDENT = 9
MAX_SYLLABUS_REVISIONS = 5
DESIGNATION_SLOT_BUDGET = 8
FREE_SEND_ALLOWANCE = 2
SEND_FEE_CENTS = 2500

# --------------------------------------------------------------------------
# Scoring and reader calibration
# --------------------------------------------------------------------------
AP5_MIN = 96.0
AP4_MIN = 76.0
AP3_MIN = 52.0
AP2_MIN = 30.0
READER_LOAD_CAP = 120
READER_RELIABILITY_FLOOR = 0.75
CALIBRATION_PASS_THRESHOLD = 0.85
MIN_CALIBRATION_SAMPLES = 10
SAMPLE_FULL_CREDIT_COUNT = 20
DEVIATION_SCALE = 0.08
AGREEMENT_WEIGHT = 0.90
SAMPLE_WEIGHT = 0.10

# --------------------------------------------------------------------------
# Alternate administrations
# --------------------------------------------------------------------------
BUFFER_BEFORE_MINUTES = 30
EXAM_DURATION_MINUTES = 195
BUFFER_AFTER_MINUTES = 30
ALT_CONCURRENT_CAP = 2

# --------------------------------------------------------------------------
# Accommodations
# --------------------------------------------------------------------------
DOC_COMPLETENESS_THRESHOLD = 3
ACCOMMODATION_REVIEW_PENALTY = 0.05
EXAM_BASE_MINUTES = 195
MAX_DOC_REVIEW_ROUNDS = 3

# --------------------------------------------------------------------------
# Worked reference values pinned by the PRD prose
# --------------------------------------------------------------------------
# "an order with eight delivered exams yields a marginal accumulator of
#  139140 cents against a single-rate base of 135360 cents"
MARGINAL_BASE_8_DELIVERED = 139140
SINGLE_RATE_BASE_8_DELIVERED = 135360
SINGLE_RATE_DELTA_8_DELIVERED = 3780
# "the same 0.9000 agreement over a full 20-paper sample yields 0.9100"
CALIBRATION_INDEX_20_AT_0900 = 0.9100
CALIBRATION_INDEX_10_AT_0900 = 0.8200
# "an extended-time approval provisions 293 minutes rather than 292"
PROVISIONED_MINUTES_EXTENDED_TIME = 293
# "A request with full documentation, zero review rounds and the extended-time
#  type therefore scores 2.2000."
WEIGHT_SUM_FULL_DOC_EXTENDED_TIME = 2.2000


def round_half_up(value: float) -> int:
    """Round half away from zero, matching the PRD's half-up rounding rule."""
    import math

    return int(math.floor(abs(value) + 0.5)) * (1 if value >= 0 else -1)


def provisional_order_fee_cents(registration_count, late_count, emergency_count) -> int:
    """Provisional variant: every registered exam at the base fee plus surcharges."""
    return (
        BASE_EXAM_FEE_CENTS * registration_count
        + LATE_SURCHARGE_PER_EXAM_CENTS * late_count
        + EMERGENCY_SURCHARGE_PER_EXAM_CENTS * emergency_count
    )


def marginal_consolidation_base(delivered_count: int) -> int:
    """Consolidated variant, marginal form: each slice rounded before summing."""
    total = 0
    for index, rate in enumerate(CONSOLIDATION_RATES):
        low = CONSOLIDATION_BREAKS[index]
        high = CONSOLIDATION_BREAKS[index + 1] if index + 1 < len(CONSOLIDATION_BREAKS) else None
        clipped = delivered_count if high is None else min(delivered_count, high)
        slice_count = max(0, clipped - low)
        total += round_half_up(slice_count * BASE_EXAM_FEE_CENTS * rate)
    return total


def single_rate_consolidation_base(delivered_count: int) -> int:
    """Consolidated variant, single-rate form: one rate for the whole count."""
    rate = CONSOLIDATION_RATES[-1]
    for index in range(len(CONSOLIDATION_BREAKS)):
        low = CONSOLIDATION_BREAKS[index]
        high = CONSOLIDATION_BREAKS[index + 1] if index + 1 < len(CONSOLIDATION_BREAKS) else None
        if delivered_count >= low and (high is None or delivered_count < high):
            rate = CONSOLIDATION_RATES[index]
            break
    return round_half_up(delivered_count * BASE_EXAM_FEE_CENTS * rate)


def unused_exam_charge_cents(confirmed_count: int) -> int:
    """Grace count of one is free; beyond that each unused exam costs 27000."""
    if confirmed_count <= UNUSED_EXAM_GRACE_COUNT:
        return 0
    return (confirmed_count - UNUSED_EXAM_GRACE_COUNT) * UNUSED_EXAM_CHARGE_PER_EXAM_CENTS
