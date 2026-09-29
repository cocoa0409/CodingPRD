"""Every derived figure PRD section 2.6 / 3 pins down."""
from decimal import Decimal

import db
from constants import (
    ABSOLUTE_CONTRAINDICATION_PENALTY,
    BOARD_CERTIFIED_CREDIT,
    CERTIFIED_SCORE_MIN,
    CONDITIONAL_SCORE_MIN,
    CONGESTION_FACTORS,
    DEVIATION_PENALTY_CAP,
    DRIP_AND_SHIP_EXTRA_MIN,
    DTN_TARGET_MIN,
    ELIGIBLE_SCORE_MIN,
    HANDOFF_PREP_MIN,
    INCLUSION_ITEM_POINTS,
    MAJOR_DEVIATION_PENALTY,
    MAX_SESSION_DISCONNECTS,
    MIN_VALID_SESSION_SEC,
    OVERRIDE_SCORE_MIN,
    RATE_WEIGHTS,
    RELATIVE_CONTRAINDICATION_PENALTY,
    SENTINEL_DEVIATION_PENALTY,
    TIER_MULTIPLIERS,
    VOLUME_CREDIT_HIGH,
    VOLUME_CREDIT_HIGH_MIN,
    VOLUME_CREDIT_LOW,
    VOLUME_CREDIT_LOW_MIN,
    WINDOW_PENALTY,
)


# --- thrombolytic window classification (PRD 3.2) ---------------------------

def window_class(case, now):
    """Re-derived from scratch against the logical clock as it stands now."""
    if case["lkw_precision"] == "UNKNOWN_WAKE_UP":
        door_elapsed = db.floor_minutes(db.parse_iso(case["door_at"]), now)
        return "EXTENDED_UNKNOWN" if door_elapsed <= 120 else "OUT_OF_WINDOW"
    lkw = case.get("last_known_well_at")
    if lkw is None:
        return "OUT_OF_WINDOW"
    raw = db.floor_minutes(db.parse_iso(lkw), now)
    effective = raw + 30 if case["lkw_precision"] == "ESTIMATED" else raw
    if effective <= 180:
        return "WITHIN_3H"
    if effective <= 270:
        return "WITHIN_4_5H"
    return "OUT_OF_WINDOW"


# --- eligibility scores (PRD 3.5) -------------------------------------------

def _core_expression(inclusion_count, relative_count, absolute_count):
    return (INCLUSION_ITEM_POINTS * Decimal(inclusion_count)
            - RELATIVE_CONTRAINDICATION_PENALTY * Decimal(relative_count)
            - ABSOLUTE_CONTRAINDICATION_PENALTY * Decimal(absolute_count))


def screening_score(inclusion_count, relative_count, absolute_count):
    raw = _core_expression(inclusion_count, relative_count, absolute_count)
    return db.q2(db.clamp_0_100(raw))


def attested_score(inclusion_count, relative_count, absolute_count,
                   window_classification, board_certified):
    raw = _core_expression(inclusion_count, relative_count, absolute_count)
    raw = raw - WINDOW_PENALTY.get(window_classification, Decimal("0.0"))
    if board_certified:
        raw = raw + BOARD_CERTIFIED_CREDIT
    return db.q2(db.clamp_0_100(raw))


def determination_outcome(absolute_count, relative_count, attested, justification):
    """First match wins (PRD 3.5)."""
    if absolute_count > 0:
        return "INELIGIBLE"
    if attested < OVERRIDE_SCORE_MIN:
        return "INELIGIBLE"
    if relative_count == 0 and attested >= ELIGIBLE_SCORE_MIN:
        return "ELIGIBLE"
    if relative_count >= 1 and attested >= OVERRIDE_SCORE_MIN and justification:
        return "ELIGIBLE_WITH_RELATIVE_OVERRIDE"
    return "INELIGIBLE"


# --- video session validity (PRD 3.4) ---------------------------------------

def session_duration_seconds(started_at, ended_at):
    return db.elapsed_seconds(db.parse_iso(started_at), db.parse_iso(ended_at))


def session_valid(duration_seconds, video_quality, disconnect_count):
    return (duration_seconds >= MIN_VALID_SESSION_SEC
            and video_quality != "AUDIO_ONLY"
            and disconnect_count <= MAX_SESSION_DISCONNECTS)


# --- transfer projection (PRD 3.7) ------------------------------------------

def congestion_factor(posture_snapshot):
    return CONGESTION_FACTORS.get(posture_snapshot, Decimal("1.00"))


def adjusted_transport_minutes(transport_eta_minutes, factor):
    return db.ceil_int(Decimal(transport_eta_minutes) * factor)


def projected_dido(adjusted_minutes, mode):
    total = adjusted_minutes + HANDOFF_PREP_MIN
    if mode == "DRIP_AND_SHIP":
        total = total + DRIP_AND_SHIP_EXTRA_MIN
    return total


# --- measure rates (PRD 3.9) -----------------------------------------------

def compliance_rate(numerator, denominator):
    if denominator == 0:
        return db.q2(Decimal("0"))
    return db.q2(Decimal(100) * Decimal(numerator) / Decimal(denominator))


def per_case_dtn_excess_percent(door_to_needle_minutes):
    excess = door_to_needle_minutes - DTN_TARGET_MIN
    if excess < 0:
        excess = 0
    return db.q0(Decimal(100) * Decimal(excess) / Decimal(DTN_TARGET_MIN))


def mean_dtn_excess(per_case_values):
    if not per_case_values:
        return None
    total = sum(Decimal(v) for v in per_case_values)
    return db.q2(total / Decimal(len(per_case_values)))


def composite_score(dtn_rate, dti_rate, response_rate, major_count,
                    sentinel_count, included_abstraction_count, facility_type):
    base = (RATE_WEIGHTS["STK_DTN_60"] * Decimal(dtn_rate)
            + RATE_WEIGHTS["STK_DTI_45"] * Decimal(dti_rate)
            + RATE_WEIGHTS["STK_TELESTROKE_RESPONSE"] * Decimal(response_rate))
    penalty = (MAJOR_DEVIATION_PENALTY * Decimal(major_count)
               + SENTINEL_DEVIATION_PENALTY * Decimal(sentinel_count))
    if penalty > DEVIATION_PENALTY_CAP:
        penalty = DEVIATION_PENALTY_CAP
    if included_abstraction_count >= VOLUME_CREDIT_HIGH_MIN:
        credit = VOLUME_CREDIT_HIGH
    elif included_abstraction_count >= VOLUME_CREDIT_LOW_MIN:
        credit = VOLUME_CREDIT_LOW
    else:
        credit = Decimal("0.0")
    multiplier = TIER_MULTIPLIERS.get(facility_type, Decimal("1.00"))
    raw = (base - penalty + credit) * multiplier
    return db.q2(db.clamp_0_100(raw))


def decision_for_score(score):
    if score >= CERTIFIED_SCORE_MIN:
        return "CERTIFIED"
    if score >= CONDITIONAL_SCORE_MIN:
        return "CONDITIONAL"
    return "DENIED"
