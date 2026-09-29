"""Request-body builders.

Each builder produces a valid payload for one write endpoint and lets a test override
whatever the case under test needs to vary. Hours, credits and distances are emitted as
JSON numbers because the specification declares them as two-decimal numeric quantities;
calendar-date fields are emitted as ``YYYY-MM-DD`` strings, which is the only width the
specification declares for them.
"""

from .constants import (
    COVERAGE_ROLE_PRIMARY,
    CREDENTIAL_BASIC,
    DELIVERY_MODE_IN_PERSON,
    INFORMANT_PARENT,
    INTERVIEW_KIND_INITIAL,
    OUTCOME_SUPPORTS,
    PLAN_TYPE_SUMMER,
    PURPOSE_SEEK_OR_OBTAIN,
    RECRUITER_STATUS_ACTIVE,
    SCHOOLING_ENROLLED,
    SERVICE_CATEGORY_INSTRUCTION,
    WORKER_RELATIONSHIP_PARENT,
    WORK_TYPE_AGRICULTURAL,
)
from .types import JsonObject


def _merge(base: JsonObject, overrides: JsonObject) -> JsonObject:
    """Overlay overrides onto a base payload; an override of ``None`` drops the key."""
    payload = dict(base)
    for key, value in overrides.items():
        if value is _DROP:
            payload.pop(key, None)
        else:
            payload[key] = value
    return payload


class _Drop(object):
    """Sentinel meaning "omit this key entirely"."""

    def __repr__(self):
        return "<omit>"


_DROP = _Drop()
DROP = _DROP


# ---------------------------------------------------------------------- geography
def area_payload(**overrides) -> JsonObject:
    """An OPEN agricultural area whose peak season runs 2026-06-01..2026-09-30."""
    return _merge(
        {
            "name": "Yakima Valley",
            "state_code": "WA",
            "primary_activity": "AGRICULTURE",
            "peak_season_start_date": "2026-06-01",
            "peak_season_end_date": "2026-09-30",
            "recruiter_capacity": 3,
        },
        overrides,
    )


def recruiter_payload(**overrides) -> JsonObject:
    """An ACTIVE recruiter holding the BASIC credential."""
    return _merge(
        {
            "full_name": "Rosa Aguilar",
            "state_code": "WA",
            "credential_level": CREDENTIAL_BASIC,
            "status": RECRUITER_STATUS_ACTIVE,
        },
        overrides,
    )


def assignment_payload(recruiter_id, area_id, expected_area_version, **overrides) -> JsonObject:
    """A PRIMARY assignment whose interval contains the default peak season."""
    return _merge(
        {
            "recruiter_id": recruiter_id,
            "area_id": area_id,
            "coverage_role": COVERAGE_ROLE_PRIMARY,
            "starts_on": "2026-05-01",
            "ends_on": "2026-10-31",
            "expected_area_version": expected_area_version,
        },
        overrides,
    )


def assignment_close_payload(outcome, **overrides) -> JsonObject:
    return _merge({"outcome": outcome}, overrides)


# ------------------------------------------------------------------------ children
def student_payload(area_id, **overrides) -> JsonObject:
    """An ENROLLED child with both placement flags set and a credit deficit of 2."""
    return _merge(
        {
            "full_name": "Mateo Reyes",
            "birth_date": "2010-03-20",
            "current_state_code": "WA",
            "area_id": area_id,
            "schooling_status": SCHOOLING_ENROLLED,
            "grade_level": 9,
            "school_days_interrupted": 10,
            "math_below_grade": True,
            "reading_below_grade": True,
            "credit_deficit": 2,
        },
        overrides,
    )


def osy_student_payload(area_id, **overrides) -> JsonObject:
    """An OUT_OF_SCHOOL child, which is the profile the OSY pathway scores."""
    return _merge(
        {
            "full_name": "Ines Delgado",
            "birth_date": "2007-05-20",
            "current_state_code": "WA",
            "area_id": area_id,
            "schooling_status": "OUT_OF_SCHOOL",
            "grade_level": None,
            "school_days_interrupted": 5,
            "math_below_grade": True,
            "reading_below_grade": True,
            "credit_deficit": 4,
            "has_hs_credential": False,
            "primary_language_not_english": True,
        },
        overrides,
    )


# ------------------------------------------------------------------ qualifying moves
def move_payload(student_id, **overrides) -> JsonObject:
    """A verified-eligible agricultural move dated inside the recency window."""
    return _merge(
        {
            "student_id": student_id,
            "from_state_code": "CA",
            "to_state_code": "WA",
            "move_date": "2026-06-15",
            "work_type": WORK_TYPE_AGRICULTURAL,
            "worker_relationship": WORKER_RELATIONSHIP_PARENT,
            "purpose": PURPOSE_SEEK_OR_OBTAIN,
            "distance_miles": 820.50,
        },
        overrides,
    )


def adjudicate_payload(decision="VERIFIED") -> JsonObject:
    return {"decision": decision}


# --------------------------------------------------------------- interview records
def interview_payload(student_id, move_id, **overrides) -> JsonObject:
    """An INITIAL interview whose outcome supports eligibility."""
    return _merge(
        {
            "student_id": student_id,
            "move_id": move_id,
            "interview_kind": INTERVIEW_KIND_INITIAL,
            "conducted_on": "2026-06-20",
            "informant_relationship": INFORMANT_PARENT,
            "outcome": OUTCOME_SUPPORTS,
            "documentation_notes": "Parent confirms apple harvest work.",
            "corroboration_count": 1,
        },
        overrides,
    )


def reinterview_payload(student_id, move_id, coe_id, **overrides) -> JsonObject:
    """A QC_REINTERVIEW record, which is the kind a quality-control decision requires."""
    return _merge(
        {
            "student_id": student_id,
            "move_id": move_id,
            "coe_id": coe_id,
            "interview_kind": "QC_REINTERVIEW",
            "conducted_on": "2026-07-20",
            "informant_relationship": INFORMANT_PARENT,
            "outcome": OUTCOME_SUPPORTS,
            "documentation_notes": "Re-contact confirms the reported residency date.",
            "corroboration_count": 2,
        },
        overrides,
    )


# ------------------------------------------------------------------- certificates
def coe_payload(student_id, move_id, **overrides) -> JsonObject:
    """A certificate whose residency date falls after the move date."""
    return _merge(
        {
            "student_id": student_id,
            "move_id": move_id,
            "residency_date": "2026-07-01",
            "qc_hold_exempt": True,
        },
        overrides,
    )


def invalidate_payload(reason="Residency documentation withdrawn by the family.") -> JsonObject:
    return {"invalidation_reason": reason}


def qc_decision_payload(decision, reinterview_id, **overrides) -> JsonObject:
    return _merge({"decision": decision, "reinterview_id": reinterview_id}, overrides)


# ---------------------------------------------------------------------- terms
def reidentify_payload(new_move_id, residency_date) -> JsonObject:
    return {"new_move_id": new_move_id, "residency_date": residency_date}


# ------------------------------------------------------------- national exchange
def transfer_request_payload(student_id, **overrides) -> JsonObject:
    """A transfer request whose holding state differs from the requesting state."""
    return _merge(
        {
            "student_id": student_id,
            "requesting_state_code": "WA",
            "holding_state_code": "CA",
            "exchange_reference": "MSIX-2026-000123",
            "reported_prior_credits": 0.00,
        },
        overrides,
    )


def match_payload(matched_prior_student_id=None) -> JsonObject:
    """Supplying the identifier drives the matched branch; omitting it drives no-match."""
    if matched_prior_student_id is None:
        return {}
    return {"matched_prior_student_id": matched_prior_student_id}


def reject_payload(reason="Holding state withdrew the predecessor record.") -> JsonObject:
    return {"rejection_reason": reason}


# ----------------------------------------------------------------- service plans
def plan_payload(student_id, expected_student_version, **overrides) -> JsonObject:
    """A SUMMER_PROGRAM plan, which either schooling status may hold."""
    return _merge(
        {
            "student_id": student_id,
            "plan_type": PLAN_TYPE_SUMMER,
            "delivery_mode": DELIVERY_MODE_IN_PERSON,
            "expected_student_version": expected_student_version,
        },
        overrides,
    )


def plan_close_payload(closure_reason) -> JsonObject:
    return {"closure_reason": closure_reason}


# ------------------------------------------------------------ delivered sessions
def delivery_payload(plan_id, **overrides) -> JsonObject:
    """A 1.50-hour instructional session on the quarter-hour grid."""
    return _merge(
        {
            "plan_id": plan_id,
            "delivered_on": "2026-07-20",
            "hours": 1.50,
            "service_category": SERVICE_CATEGORY_INSTRUCTION,
        },
        overrides,
    )


def credit_delivery_payload(plan_id, hours, credits, **overrides) -> JsonObject:
    """A credit-accrual session, the only kind that may award credits."""
    return _merge(
        {
            "plan_id": plan_id,
            "delivered_on": "2026-07-20",
            "hours": hours,
            "service_category": "CREDIT_ACCRUAL_SESSION",
            "credits_awarded": credits,
        },
        overrides,
    )
