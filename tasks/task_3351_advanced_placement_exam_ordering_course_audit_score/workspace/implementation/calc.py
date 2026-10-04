"""The eleven program calculations, with their pinned rounding and ordering."""

from decimal import Decimal, ROUND_HALF_UP

import clock
import core
from constants import (
    ACCOMMODATION_QUANTITY_PARAMETERS,
    ACCOMMODATION_REVIEW_PENALTY,
    ACCOMMODATION_TYPE_WEIGHTS,
    ACTIVE_REGISTRATION_STATUSES,
    AGREEMENT_WEIGHT,
    ALT_CONCURRENT_CAP,
    AP2_MIN,
    AP3_MIN,
    AP4_MIN,
    AP5_MIN,
    BASE_EXAM_FEE_CENTS,
    BUFFER_AFTER_MINUTES,
    BUFFER_BEFORE_MINUTES,
    CLOSED_WINDOW_ADDITIONAL_CENTS,
    CONSOLIDATION_BREAKS,
    CONSOLIDATION_RATES,
    DEVIATION_SCALE,
    DELIVERED_REGISTRATION_STATUSES,
    DOC_COMPLETENESS_THRESHOLD,
    EMERGENCY_SURCHARGE_PER_EXAM_CENTS,
    EXAM_BASE_MINUTES,
    EXAM_DURATION_MINUTES,
    FREE_SEND_ALLOWANCE,
    LATE_FEE_CAP_COUNT,
    LATE_SURCHARGE_PER_EXAM_CENTS,
    LATE_WINDOW_CLOSES_UTC,
    READER_LOAD_CAP,
    REGULAR_RELEASE_UTC,
    REGULAR_WINDOW_CLOSES_UTC,
    REGULAR_WINDOW_OPENS_UTC,
    SAMPLE_FULL_CREDIT_COUNT,
    SAMPLE_WEIGHT,
    SEND_FEE_CENTS,
    UNUSED_EXAM_CHARGE_PER_EXAM_CENTS,
    UNUSED_EXAM_GRACE_COUNT,
)


def round_half_up(value, places=0):
    quantum = Decimal(1).scaleb(-places)
    return Decimal(str(value)).quantize(quantum, rounding=ROUND_HALF_UP)


# --- ordering window --------------------------------------------------------

def ordering_window(at=None):
    at = at or clock.now()
    if at < clock.parse_instant(REGULAR_WINDOW_OPENS_UTC):
        return "NOT_OPEN"
    if at <= clock.parse_instant(REGULAR_WINDOW_CLOSES_UTC):
        return "REGULAR"
    if at <= clock.parse_instant(LATE_WINDOW_CLOSES_UTC):
        return "LATE"
    return "CLOSED"


# --- order fees -------------------------------------------------------------

def _tier_counts(order_id):
    late = 0
    emergency = 0
    for reg in core.rows("exam_registrations"):
        if reg["exam_order_id"] != order_id:
            continue
        if reg["status"] not in ACTIVE_REGISTRATION_STATUSES:
            continue
        if reg["registration_tier"] == "LATE":
            late += 1
        elif reg["registration_tier"] == "EMERGENCY":
            emergency += 1
    return late, emergency


def order_fee_provisional(order):
    late, emergency = _tier_counts(order["id"])
    return (BASE_EXAM_FEE_CENTS * order["registration_count"]
            + LATE_SURCHARGE_PER_EXAM_CENTS * late
            + EMERGENCY_SURCHARGE_PER_EXAM_CENTS * emergency)


def order_fee_consolidated(order):
    delivered = 0
    for reg in core.rows("exam_registrations"):
        if reg["exam_order_id"] == order["id"] and reg["status"] in DELIVERED_REGISTRATION_STATUSES:
            delivered += 1
    marginal = Decimal(0)
    for index, rate in enumerate(CONSOLIDATION_RATES):
        lo = CONSOLIDATION_BREAKS[index]
        hi = CONSOLIDATION_BREAKS[index + 1] if index + 1 <= 3 else None
        upper = delivered if hi is None else min(delivered, hi)
        slice_count = max(0, upper - lo)
        marginal += round_half_up(slice_count * BASE_EXAM_FEE_CENTS * rate, 0)
    if delivered >= CONSOLIDATION_BREAKS[3]:
        rate_applied = CONSOLIDATION_RATES[3]
    elif delivered >= CONSOLIDATION_BREAKS[2]:
        rate_applied = CONSOLIDATION_RATES[2]
    elif delivered >= CONSOLIDATION_BREAKS[1]:
        rate_applied = CONSOLIDATION_RATES[1]
    else:
        rate_applied = CONSOLIDATION_RATES[0]
    single_rate_base = round_half_up(delivered * BASE_EXAM_FEE_CENTS * rate_applied, 0)
    late, emergency = _tier_counts(order["id"])
    return int(single_rate_base) + LATE_SURCHARGE_PER_EXAM_CENTS * late \
        + EMERGENCY_SURCHARGE_PER_EXAM_CENTS * emergency, int(marginal), delivered


def unused_exam_charge(confirmed_count):
    if confirmed_count <= UNUSED_EXAM_GRACE_COUNT:
        return 0
    return (confirmed_count - UNUSED_EXAM_GRACE_COUNT) * UNUSED_EXAM_CHARGE_PER_EXAM_CENTS


# --- late fees --------------------------------------------------------------

def late_fee_per_registration(registration_tier, window):
    if registration_tier == "LATE":
        if window == "LATE":
            return LATE_SURCHARGE_PER_EXAM_CENTS
        if window == "CLOSED":
            return LATE_SURCHARGE_PER_EXAM_CENTS + CLOSED_WINDOW_ADDITIONAL_CENTS
        return 0
    if registration_tier == "EMERGENCY":
        return EMERGENCY_SURCHARGE_PER_EXAM_CENTS
    return 0


def late_fee_order_level(order_id):
    late = 0
    for reg in core.rows("exam_registrations"):
        if reg["exam_order_id"] == order_id and reg["registration_tier"] == "LATE":
            late += 1
    return min(late, LATE_FEE_CAP_COUNT) * LATE_SURCHARGE_PER_EXAM_CENTS


# --- readers ----------------------------------------------------------------

def calibration_index_weighted(sample_count, agreement_rate):
    sample_factor = min(1.0, (sample_count or 0) / float(SAMPLE_FULL_CREDIT_COUNT))
    penalty = round_half_up(DEVIATION_SCALE * (1.0 - sample_factor), 4)
    index = agreement_rate * AGREEMENT_WEIGHT + sample_factor * SAMPLE_WEIGHT - float(penalty)
    return float(round_half_up(index, 4))


def eligible_readers(subject, exclude_reader_ids=None):
    exclude = set(exclude_reader_ids or [])
    pool = []
    for reader in core.rows("readers"):
        if reader["id"] in exclude:
            continue
        if reader["subject_expertise"] != subject:
            continue
        if reader["calibration_status"] != "CALIBRATED":
            continue
        if reader["load_status"] != "AVAILABLE":
            continue
        if reader["assigned_score_count"] >= READER_LOAD_CAP:
            continue
        pool.append(reader)
    pool.sort(key=lambda r: (
        r["assigned_score_count"],
        r["created_at"],
        -r["reliability_index"],
        r["full_name"],
    ))
    return pool


def select_reader(subject, exclude_reader_ids=None):
    pool = eligible_readers(subject, exclude_reader_ids)
    return pool[0] if pool else None


# --- score mapping ----------------------------------------------------------

def ap_score_cross_total(raw_composite):
    if raw_composite >= AP5_MIN:
        return 5
    if raw_composite >= AP4_MIN:
        return 4
    if raw_composite >= AP3_MIN:
        return 3
    if raw_composite >= AP2_MIN:
        return 2
    return 1


def ap_score_section_band_sum(sum_of_bands):
    if sum_of_bands >= 21:
        return 5
    if sum_of_bands >= 17:
        return 4
    if sum_of_bands >= 13:
        return 3
    if sum_of_bands >= 9:
        return 2
    return 1


_BAND_EDGES = {
    5: (AP5_MIN, 120.0),
    4: (AP4_MIN, AP5_MIN),
    3: (AP3_MIN, AP4_MIN),
    2: (AP2_MIN, AP3_MIN),
    1: (0.0, AP2_MIN),
}


def section_band_sum(raw_composite):
    """Sum of the five per-section bands for a composite.

    The five sections sit at the composite's own band; a composite resting on
    the top 5% of its band straddles the cross-total edge and promotes one
    section, which is what makes the two variants diverge.
    """
    band = ap_score_cross_total(raw_composite)
    lo, hi = _BAND_EDGES[band]
    span = hi - lo
    bonus = 1 if span > 0 and raw_composite >= hi - span * 0.05 else 0
    return 5 * band + bonus


def ap_score_marginal(raw_composite):
    return ap_score_section_band_sum(section_band_sum(raw_composite))


# --- alternates -------------------------------------------------------------

def _buffered_interval(alternate_date_utc):
    moment = clock.parse_instant(alternate_date_utc)
    return (moment - clock.timedelta(minutes=BUFFER_BEFORE_MINUTES),
            moment + clock.timedelta(minutes=EXAM_DURATION_MINUTES + BUFFER_AFTER_MINUTES))


def _school_alternates(school_id, exclude_id=None):
    out = []
    for req in core.rows("alternate_exam_requests"):
        if req["id"] == exclude_id:
            continue
        if req["status"] not in ("APPROVED", "SCHEDULED"):
            continue
        reg = core.get("exam_registrations", req["exam_registration_id"])
        if reg is None:
            continue
        student = core.get("students", reg["student_id"])
        if student is None or student["school_id"] != school_id:
            continue
        out.append(req)
    return out


def alternate_seat_overflow(school, request):
    """True when the requesting interval collides, overflows, or breaks the day cap."""
    own_start, own_end = _buffered_interval(request["alternate_date_utc"])
    existing = _school_alternates(school["id"], exclude_id=request["id"])
    intervals = []
    for req in existing:
        start, end = _buffered_interval(req["alternate_date_utc"])
        intervals.append((start, end))
        if own_start < end and start < own_end:
            return True
    intervals.sort()
    merged = []
    for start, end in intervals:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    total_minutes = sum((end - start).total_seconds() / 60.0 for start, end in merged)
    if total_minutes > school["seat_capacity"] * BUFFER_BEFORE_MINUTES:
        return True
    own_day = own_start.date()
    same_day = 0
    for req in existing:
        if clock.parse_instant(req["alternate_date_utc"]).date() == own_day:
            same_day += 1
    return same_day >= ALT_CONCURRENT_CAP


# --- score release / sends --------------------------------------------------

def score_release_open(registration_id):
    open_at = clock.parse_instant(REGULAR_RELEASE_UTC)
    for req in core.rows("alternate_exam_requests"):
        if req["exam_registration_id"] != registration_id or req["status"] != "SCHEDULED":
            continue
        moment = clock.parse_instant(req["alternate_date_utc"])
        if moment > open_at:
            open_at = moment
    return open_at


def _send_include_counts(exam_score_id):
    college = 0
    school = 0
    for send in core.rows("score_sends"):
        if send["exam_score_id"] != exam_score_id:
            continue
        if send["status"] not in ("PENDING", "SENT", "ACKNOWLEDGED"):
            continue
        if send["recipient_type"] == "COLLEGE":
            college += 1
        elif send["recipient_type"] == "SCHOOL":
            school += 1
    return college, school


def score_send_fee(exam_score_id, recipient_type):
    """all_include variant - the figure stored on the row."""
    college, school = _send_include_counts(exam_score_id)
    if recipient_type == "COLLEGE":
        college += 1
    elif recipient_type == "SCHOOL":
        school += 1
    return max(0, (college + school) - FREE_SEND_ALLOWANCE) * SEND_FEE_CENTS


def score_send_fee_college_only(exam_score_id, recipient_type):
    """college_only_exclude variant - the per-student college-designation view."""
    college, _school = _send_include_counts(exam_score_id)
    if recipient_type == "COLLEGE":
        college += 1
    first_college = max(0, college - 1)
    return max(0, first_college - FREE_SEND_ALLOWANCE) * SEND_FEE_CENTS


# --- accommodation ----------------------------------------------------------

def accommodation_weight_sum(documentation_completeness, accommodation_type, review_round):
    doc_score = min(DOC_COMPLETENESS_THRESHOLD, documentation_completeness or 0)
    type_weight = ACCOMMODATION_TYPE_WEIGHTS.get(accommodation_type, 0.0)
    penalty = ACCOMMODATION_REVIEW_PENALTY * (review_round or 0)
    value = doc_score * 0.6 + type_weight * 0.4 - penalty
    return float(round_half_up(value, 4))


def accommodation_provisioned_minutes(accommodation_type):
    parameter = ACCOMMODATION_QUANTITY_PARAMETERS.get(accommodation_type, 0.0)
    return int(round_half_up(EXAM_BASE_MINUTES * (1.0 + parameter), 0))
