"""
Request-payload builders and the small arithmetic helpers the suite shares.

Conventions enforced here so no individual test has to remember them:

* Money is always a JSON integer count of whole cents, never a string and never a
  decimal fraction.
* Every datetime is a full ISO-8601 UTC instant with exactly three fractional digits
  and a trailing ``Z`` -- never a date-only literal.
* ``hemodilution_pct`` and ``temperature_c`` are JSON numbers.
* Optional fields are omitted entirely rather than sent as null, unless a test
  explicitly asks for an explicit null via the ``*_raw`` escape hatch of the builder.
"""

import itertools
import math

from .constants import (
    AGE_ADJUSTMENT_MIDDLE,
    AGE_ADJUSTMENT_OLD,
    AGE_ADJUSTMENT_YOUNG,
    BASE_WINDOW_ASYSTOLE_MINUTES,
    BASE_WINDOW_PRONOUNCED_MINUTES,
    CERTIFICATION_EXPIRES_AT,
    CLARITY_BASE_POINTS,
    CLARITY_POINTS_PER_GRADE,
    COOLING_CREDIT_FAST_MINUTES,
    COOLING_CREDIT_NONE_MINUTES,
    COOLING_CREDIT_SLOW_MINUTES,
    COOLING_DELAY_FAST_BOUND_MINUTES,
    COOLING_DELAY_SLOW_BOUND_MINUTES,
    ENDOTHELIAL_BASELINE,
    ENDOTHELIAL_DIVISOR,
    ENDOTHELIAL_POINTS_CAP,
    EPITHELIUM_BASE_POINTS,
    EPITHELIUM_POINTS_PER_GRADE,
    FEE_BASE_CENTS,
    FOLDS_BASE_POINTS,
    FOLDS_POINTS_PER_GRADE,
    GUTTATA_BASE_POINTS,
    GUTTATA_POINTS_PER_GRADE,
    PROXIMITY_POINTS_FAR,
    PROXIMITY_POINTS_IMMINENT,
    PROXIMITY_POINTS_MID,
    PROXIMITY_POINTS_NEAR,
    QUALITY_SCORE_MAX,
    QUALITY_SCORE_MIN,
    RECOVERY_WINDOW_FLOOR_MINUTES,
    SHELF_LIFE_BASE_HOURS,
    SHELF_LIFE_EXTENDED_PENALTY_HOURS,
    SHELF_LIFE_FLOOR_HOURS,
    SHELF_LIFE_LOW_ENDOTHELIUM_PENALTY_HOURS,
    SHELF_LIFE_LOW_ENDOTHELIUM_THRESHOLD,
    SHORT_NOTICE_DAY_BOUND,
    SURCHARGE_PROCEDURE_PCT,
    SURCHARGE_PROCEDURES,
    SURCHARGE_SHORT_NOTICE_PCT,
    SURCHARGE_URGENCY_PCT,
    TIER_BONUS,
    TIER_GOLD_FLOOR,
    TIER_PLATINUM_FLOOR,
    T_COOLED,
    T_DEATH,
    URGENCY_WEIGHT_ROUTINE,
    URGENCY_WEIGHT_URGENT,
)

_counter = itertools.count(1)


def unique_suffix():
    """A short monotonically increasing suffix for globally unique codes."""
    return f"{next(_counter):04d}"


def unique_donor_code(prefix="D-2846"):
    """A donor_code guaranteed not to collide inside one test."""
    return f"{prefix}-{unique_suffix()}"


def _omit_none(payload):
    return {k: v for k, v in payload.items() if v is not None}


# ---------------------------------------------------------------------------
# Donors and screening
# ---------------------------------------------------------------------------
def donor_payload(
    donor_code=None,
    referral_source="HOSPITAL",
    death_at=T_DEATH,
    death_time_basis="ASYSTOLE",
    body_cooled_at=T_COOLED,
    age_years=52,
    cause_of_death_category="CARDIAC",
):
    """A donor referral body. Pass ``body_cooled_at=None`` for a body never cooled."""
    return _omit_none(
        {
            "donor_code": donor_code or unique_donor_code(),
            "referral_source": referral_source,
            "death_at": death_at,
            "death_time_basis": death_time_basis,
            "body_cooled_at": body_cooled_at,
            "age_years": age_years,
            "cause_of_death_category": cause_of_death_category,
        }
    )


def screening_payload(
    question_code="TATTOO_12M", response="NO", historian_relationship="SPOUSE"
):
    return {
        "question_code": question_code,
        "response": response,
        "historian_relationship": historian_relationship,
    }


def consent_payload(
    consent_type="FIRST_PERSON",
    consent_scope="TRANSPLANT_ONLY",
    authorizing_party_name="Registry Self-Consent",
):
    return {
        "consent_type": consent_type,
        "consent_scope": consent_scope,
        "authorizing_party_name": authorizing_party_name,
    }


def defer_payload(deferral_reason="AWAITING_MEDICAL_RECORDS"):
    return {"deferral_reason": deferral_reason}


# ---------------------------------------------------------------------------
# Serology
# ---------------------------------------------------------------------------
def panel_payload(
    expected_donor_version,
    specimen_type="POST_MORTEM",
    drawn_at=None,
    hemodilution_pct=0.00,
):
    from .constants import T_DRAWN

    return {
        "specimen_type": specimen_type,
        "drawn_at": drawn_at or T_DRAWN,
        "hemodilution_pct": hemodilution_pct,
        "expected_donor_version": expected_donor_version,
    }


def results_payload(
    hiv_result="NON_REACTIVE",
    hbv_result="NON_REACTIVE",
    hcv_result="NON_REACTIVE",
    syphilis_result="NON_REACTIVE",
):
    return {
        "hiv_result": hiv_result,
        "hbv_result": hbv_result,
        "hcv_result": hcv_result,
        "syphilis_result": syphilis_result,
    }


# ---------------------------------------------------------------------------
# Technicians and recoveries
# ---------------------------------------------------------------------------
def technician_payload(
    full_name="Rosa Field",
    certification_level="RECOVERY_ONLY",
    certification_expires_at=CERTIFICATION_EXPIRES_AT,
):
    return {
        "full_name": full_name,
        "certification_level": certification_level,
        "certification_expires_at": certification_expires_at,
    }


def technician_status_payload(status="INACTIVE"):
    return {"status": status}


def recovery_payload(donor_id, technician_id, dispatched_at, planned_release_at):
    return {
        "donor_id": donor_id,
        "technician_id": technician_id,
        "dispatched_at": dispatched_at,
        "planned_release_at": planned_release_at,
    }


def arrive_payload(arrival_at):
    return {"arrival_at": arrival_at}


def complete_payload(
    preservation_at, preservation_medium="OPTISOL_GS", recovered_lateralities=("OD",)
):
    return {
        "preservation_at": preservation_at,
        "preservation_medium": preservation_medium,
        "recovered_lateralities": list(recovered_lateralities),
    }


def abort_payload(abort_reason="FAMILY_WITHDREW"):
    return {"abort_reason": abort_reason}


# ---------------------------------------------------------------------------
# Grading and classification
# ---------------------------------------------------------------------------
def slit_lamp_payload(
    evaluator_technician_id,
    performed_at,
    expected_tissue_version,
    epithelium_defect_grade=0,
    stromal_clarity_grade=0,
    dm_folds_grade=0,
):
    return {
        "evaluator_technician_id": evaluator_technician_id,
        "method": "SLIT_LAMP",
        "performed_at": performed_at,
        "expected_tissue_version": expected_tissue_version,
        "epithelium_defect_grade": epithelium_defect_grade,
        "stromal_clarity_grade": stromal_clarity_grade,
        "dm_folds_grade": dm_folds_grade,
    }


def specular_payload(
    evaluator_technician_id,
    performed_at,
    expected_tissue_version,
    guttata_grade=0,
    endothelial_cell_count=3100,
):
    return {
        "evaluator_technician_id": evaluator_technician_id,
        "method": "SPECULAR",
        "performed_at": performed_at,
        "expected_tissue_version": expected_tissue_version,
        "guttata_grade": guttata_grade,
        "endothelial_cell_count": endothelial_cell_count,
    }


def classify_payload(intended_use_override=None):
    return _omit_none({"intended_use_override": intended_use_override})


def quarantine_payload(quarantine_reason="OPERATOR_HOLD"):
    return {"quarantine_reason": quarantine_reason}


def discard_payload(disposal_method="INCINERATION"):
    return {"disposal_method": disposal_method}


def return_payload(return_reason="SURGERY_POSTPONED"):
    return {"return_reason": return_reason}


# ---------------------------------------------------------------------------
# Surgeons, requests and allocations
# ---------------------------------------------------------------------------
def surgeon_payload(full_name="Dr Anwar Reed", center_code="CTR-01", specialty="PK"):
    return {
        "full_name": full_name,
        "center_code": center_code,
        "specialty": specialty,
    }


def credential_payload(credential_status="SUSPENDED"):
    return {"credential_status": credential_status}


def request_payload(
    surgeon_id,
    procedure_type="PK",
    surgery_date="2026-08-08T00:00:00.000Z",
    min_ecd=2000,
    max_donor_age_years=70,
    laterality_preference="ANY",
    urgency="ROUTINE",
):
    return {
        "surgeon_id": surgeon_id,
        "procedure_type": procedure_type,
        "surgery_date": surgery_date,
        "min_ecd": min_ecd,
        "max_donor_age_years": max_donor_age_years,
        "laterality_preference": laterality_preference,
        "urgency": urgency,
    }


def cancel_request_payload(cancel_reason="SURGERY_CANCELLED"):
    return {"cancel_reason": cancel_reason}


def allocation_payload(tissue_id, request_id):
    return {"tissue_id": tissue_id, "request_id": request_id}


def cancel_allocation_payload(cancel_reason="SURGERY_CANCELLED"):
    return {"cancel_reason": cancel_reason}


# ---------------------------------------------------------------------------
# Shipping and cold chain
# ---------------------------------------------------------------------------
def shipment_payload(allocation_id, carrier="COURIER", replaces_shipment_id=None):
    return _omit_none(
        {
            "allocation_id": allocation_id,
            "carrier": carrier,
            "replaces_shipment_id": replaces_shipment_id,
        }
    )


def reading_payload(recorded_at, temperature_c=4.0):
    return {"recorded_at": recorded_at, "temperature_c": temperature_c}


def dispatch_payload(shipped_at):
    return {"shipped_at": shipped_at}


def deliver_payload(delivered_at):
    return {"delivered_at": delivered_at}


# ---------------------------------------------------------------------------
# Adverse reactions and lookback
# ---------------------------------------------------------------------------
def report_payload(
    tissue_id,
    surgeon_id,
    reaction_type="PRIMARY_GRAFT_FAILURE",
    severity="SERIOUS",
    narrative="Graft failed on post-operative day one.",
):
    return {
        "tissue_id": tissue_id,
        "surgeon_id": surgeon_id,
        "reaction_type": reaction_type,
        "severity": severity,
        "narrative": narrative,
    }


def adjudication_payload(adjudication_note="Donor-attributable failure; opening lookback."):
    return {"adjudication_note": adjudication_note}


def lookback_payload(donor_id, source_report_id=None):
    return _omit_none({"donor_id": donor_id, "source_report_id": source_report_id})


def close_payload(resolution="NO_ACTION", closure_note="Investigation closed."):
    return {"resolution": resolution, "closure_note": closure_note}


# ---------------------------------------------------------------------------
# Arithmetic helpers derived from the specification
# ---------------------------------------------------------------------------
def expected_recovery_window_minutes(
    death_time_basis, cooling_delay_minutes, age_years
):
    """Base window plus cooling credit minus age penalty, clamped up to the floor."""
    base = (
        BASE_WINDOW_ASYSTOLE_MINUTES
        if death_time_basis == "ASYSTOLE"
        else BASE_WINDOW_PRONOUNCED_MINUTES
    )
    if cooling_delay_minutes is None:
        credit = COOLING_CREDIT_NONE_MINUTES
    elif cooling_delay_minutes <= COOLING_DELAY_FAST_BOUND_MINUTES:
        credit = COOLING_CREDIT_FAST_MINUTES
    elif cooling_delay_minutes <= COOLING_DELAY_SLOW_BOUND_MINUTES:
        credit = COOLING_CREDIT_SLOW_MINUTES
    else:
        credit = COOLING_CREDIT_NONE_MINUTES
    penalty = 60 if age_years >= 71 else 0
    return max(base + credit - penalty, RECOVERY_WINDOW_FLOOR_MINUTES)


def expected_quality_score(
    endothelial_cell_count,
    stromal_clarity_grade,
    epithelium_defect_grade,
    dm_folds_grade,
    guttata_grade,
    age_years,
):
    """The composite quality score, with both clamps applied in the stated order."""
    endothelial = (endothelial_cell_count - ENDOTHELIAL_BASELINE) // ENDOTHELIAL_DIVISOR
    endothelial = min(max(endothelial, 0), ENDOTHELIAL_POINTS_CAP)
    clarity = CLARITY_BASE_POINTS - CLARITY_POINTS_PER_GRADE * stromal_clarity_grade
    epithelium = (
        EPITHELIUM_BASE_POINTS - EPITHELIUM_POINTS_PER_GRADE * epithelium_defect_grade
    )
    folds = FOLDS_BASE_POINTS - FOLDS_POINTS_PER_GRADE * dm_folds_grade
    guttata = GUTTATA_BASE_POINTS - GUTTATA_POINTS_PER_GRADE * guttata_grade
    if age_years >= 71:
        age_adjustment = AGE_ADJUSTMENT_OLD
    elif age_years >= 46:
        age_adjustment = AGE_ADJUSTMENT_MIDDLE
    else:
        age_adjustment = AGE_ADJUSTMENT_YOUNG
    total = endothelial + clarity + epithelium + folds + guttata + age_adjustment
    return min(max(total, QUALITY_SCORE_MIN), QUALITY_SCORE_MAX)


def expected_provisional_shelf_life_hours(preservation_medium, time_limit_band):
    base = SHELF_LIFE_BASE_HOURS[preservation_medium]
    if time_limit_band == "WITHIN_EXTENDED":
        base -= SHELF_LIFE_EXTENDED_PENALTY_HOURS
    return max(base, SHELF_LIFE_FLOOR_HOURS)


def expected_final_shelf_life_hours(
    preservation_medium,
    time_limit_band,
    cooling_delay_minutes,
    endothelial_cell_count,
):
    """Base less the band, cooling and low-endothelium penalties, floored at 24."""
    hours = SHELF_LIFE_BASE_HOURS[preservation_medium]
    if time_limit_band == "WITHIN_EXTENDED":
        hours -= SHELF_LIFE_EXTENDED_PENALTY_HOURS
    if cooling_delay_minutes is None or cooling_delay_minutes > COOLING_DELAY_SLOW_BOUND_MINUTES:
        hours -= 72
    if endothelial_cell_count < SHELF_LIFE_LOW_ENDOTHELIUM_THRESHOLD:
        hours -= SHELF_LIFE_LOW_ENDOTHELIUM_PENALTY_HOURS
    return max(hours, SHELF_LIFE_FLOOR_HOURS)


def expected_proximity_points(days_to_surgery):
    if days_to_surgery <= 2:
        return PROXIMITY_POINTS_IMMINENT
    if days_to_surgery <= 7:
        return PROXIMITY_POINTS_NEAR
    if days_to_surgery <= 21:
        return PROXIMITY_POINTS_MID
    return PROXIMITY_POINTS_FAR


def expected_priority(urgency, days_to_surgery):
    """Return the (base_score, priority_tier, priority_score) triple."""
    urgency_weight = (
        URGENCY_WEIGHT_URGENT if urgency == "URGENT" else URGENCY_WEIGHT_ROUTINE
    )
    base_score = urgency_weight + expected_proximity_points(days_to_surgery)
    if base_score >= TIER_PLATINUM_FLOOR:
        tier = "PLATINUM"
    elif base_score >= TIER_GOLD_FLOOR:
        tier = "GOLD"
    else:
        tier = "STANDARD"
    return base_score, tier, base_score + TIER_BONUS[tier]


def _round_half_up(value):
    return int(math.floor(value + 0.5))


def expected_surcharge_cents(base_cents, percent):
    """One surcharge component, rounded half up to the whole cent on its own."""
    return _round_half_up(base_cents * percent / 100.0)


def expected_fee_cents(classification, urgency, procedure_type, days_to_surgery):
    """Base plus each independently rounded surcharge."""
    base = FEE_BASE_CENTS[classification]
    total = base
    if urgency == "URGENT":
        total += expected_surcharge_cents(base, SURCHARGE_URGENCY_PCT)
    if procedure_type in SURCHARGE_PROCEDURES:
        total += expected_surcharge_cents(base, SURCHARGE_PROCEDURE_PCT)
    if days_to_surgery <= SHORT_NOTICE_DAY_BOUND:
        total += expected_surcharge_cents(base, SURCHARGE_SHORT_NOTICE_PCT)
    return total


__all__ = [
    "unique_suffix",
    "unique_donor_code",
    "donor_payload",
    "screening_payload",
    "consent_payload",
    "defer_payload",
    "panel_payload",
    "results_payload",
    "technician_payload",
    "technician_status_payload",
    "recovery_payload",
    "arrive_payload",
    "complete_payload",
    "abort_payload",
    "slit_lamp_payload",
    "specular_payload",
    "classify_payload",
    "quarantine_payload",
    "discard_payload",
    "return_payload",
    "surgeon_payload",
    "credential_payload",
    "request_payload",
    "cancel_request_payload",
    "allocation_payload",
    "cancel_allocation_payload",
    "shipment_payload",
    "reading_payload",
    "dispatch_payload",
    "deliver_payload",
    "report_payload",
    "adjudication_payload",
    "lookback_payload",
    "close_payload",
    "expected_recovery_window_minutes",
    "expected_quality_score",
    "expected_provisional_shelf_life_hours",
    "expected_final_shelf_life_hours",
    "expected_proximity_points",
    "expected_priority",
    "expected_surcharge_cents",
    "expected_fee_cents",
]
