"""Request payload factories.

Every factory returns a fresh dict of PRD field names and accepts `**overrides`
so a test can vary one literal without restating the rest. Passing the `OMIT`
sentinel as an override drops the field from the payload entirely, which is how
optional-field and required-field-missing cases are expressed.

Numeric values are emitted as JSON numbers: percentages, point values, scores
and rates as floats; money as an integer count of cents. Instants are always
full ISO-8601 UTC instants, never date-only literals.
"""

from typing import Any, Dict, List, Optional

from . import constants as K
from .types import Payload


class _Omit:
    """Sentinel meaning "leave this field out of the payload"."""

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "OMIT"


OMIT = _Omit()


def _build(base: Dict[str, Any], overrides: Dict[str, Any]) -> Payload:
    payload = dict(base)
    payload.update(overrides)
    return {
        key: value
        for key, value in payload.items()
        if not isinstance(value, _Omit)
    }


# ---------------------------------------------------------------------------
# Inspection standards and defect definitions
# ---------------------------------------------------------------------------
def standard_payload(**overrides: Any) -> Payload:
    """A DRAFT standard whose three area weights sum to exactly 100.00."""
    return _build(
        {
            "code": K.STANDARD_CODE,
            "name": K.STANDARD_NAME,
            "effective_date": K.EFFECTIVE_DATE,
            "unit_weight_pct": K.UNIT_WEIGHT_PCT,
            "inside_weight_pct": K.INSIDE_WEIGHT_PCT,
            "outside_weight_pct": K.OUTSIDE_WEIGHT_PCT,
        },
        overrides,
    )


def adopt_payload(**overrides: Any) -> Payload:
    return _build({"adopted_at": K.ADOPTED_AT}, overrides)


def defect_definition_payload(
    standard_id: str, blueprint: str = "SEV_WINDOW", **overrides: Any
) -> Payload:
    """A defect definition drawn from the canonical blueprint named `blueprint`.

    `blueprint` selects which row of `DEFINITION_BLUEPRINTS` seeds the payload and
    supplies the default `code`; passing `code=` as an override changes only the
    emitted field, so a test can base a payload on one blueprint while declaring a
    distinct catalogue code.
    """
    name, area, severity, base_points, deadline_hours = K.DEFINITION_BLUEPRINTS[
        blueprint
    ]
    return _build(
        {
            "standard_id": standard_id,
            "code": blueprint,
            "name": name,
            "inspectable_area": area,
            "severity": severity,
            "base_point_value": base_points,
            "correction_deadline_hours": deadline_hours,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Properties and units
# ---------------------------------------------------------------------------
def property_payload(
    blueprint: Optional[Dict[str, Any]] = None, **overrides: Any
) -> Payload:
    """A property registration; `capital_reserve_cents` is an integer of cents."""
    return _build(dict(blueprint or K.CEDAR_WALK), overrides)


def unit_payload(property_id: str, unit_number: str = "101", **overrides: Any) -> Payload:
    return _build(
        {
            "property_id": property_id,
            "unit_number": unit_number,
            "bedroom_count": 1,
            "occupancy_status": "OCCUPIED",
        },
        overrides,
    )


def property_patch_payload(**overrides: Any) -> Payload:
    return _build({}, overrides)


def unit_patch_payload(**overrides: Any) -> Payload:
    return _build({}, overrides)


# ---------------------------------------------------------------------------
# Self-assessment sweeps and work orders
# ---------------------------------------------------------------------------
def sweep_payload(property_id: str, **overrides: Any) -> Payload:
    return _build(
        {
            "property_id": property_id,
            "window_start": K.SWEEP_WINDOW_START,
            "window_end": K.SWEEP_WINDOW_END,
            "planned_area_scope": "ALL_AREAS",
        },
        overrides,
    )


def sweep_start_payload(**overrides: Any) -> Payload:
    return _build({"started_at": K.SWEEP_STARTED_AT}, overrides)


def sweep_close_payload(**overrides: Any) -> Payload:
    return _build({"closed_at": K.SWEEP_OBSERVED_AT_1}, overrides)


def finding_payload(
    expected_sweep_version: int,
    defect_definition_id: str,
    unit_id: Optional[str] = None,
    inspectable_area: str = "UNIT",
    **overrides: Any
) -> Payload:
    """A sweep finding; `unit_id` is present exactly for UNIT-area findings."""
    base: Dict[str, Any] = {
        "expected_sweep_version": expected_sweep_version,
        "defect_definition_id": defect_definition_id,
        "inspectable_area": inspectable_area,
        "observed_at": K.SWEEP_OBSERVED_AT_1,
    }
    if unit_id is not None:
        base["unit_id"] = unit_id
    return _build(base, overrides)


def work_order_complete_payload(**overrides: Any) -> Payload:
    return _build(
        {
            "completed_at": K.WORK_ORDER_COMPLETED_AT,
            "resolution_note": "Sash mechanism replaced",
        },
        overrides,
    )


def verify_closure_payload(
    verification_result: str = "PASSED", **overrides: Any
) -> Payload:
    return _build(
        {
            "verification_result": verification_result,
            "verified_at": K.WORK_ORDER_VERIFIED_AT,
        },
        overrides,
    )


def void_payload(**overrides: Any) -> Payload:
    return _build({"void_reason": "Raised against the wrong unit"}, overrides)


# ---------------------------------------------------------------------------
# Inspections, sample slots and deficiencies
# ---------------------------------------------------------------------------
def inspection_payload(property_id: str, standard_id: str, **overrides: Any) -> Payload:
    return _build(
        {
            "property_id": property_id,
            "standard_id": standard_id,
            "scheduled_start": K.INSPECTION_SCHEDULED_START,
            "scheduled_end": K.INSPECTION_SCHEDULED_END,
            "inspection_kind": "INITIAL",
        },
        overrides,
    )


def draw_sample_payload(**overrides: Any) -> Payload:
    return _build({"drawn_at": K.DRAWN_AT}, overrides)


def notice_payload(**overrides: Any) -> Payload:
    """A tenant notice with the agreed half-open entry window."""
    return _build(
        {
            "notice_method": "MAILED",
            "notified_at": K.NOTIFIED_AT,
            "access_window_start": K.ACCESS_WINDOW_START,
            "access_window_end": K.ACCESS_WINDOW_END,
        },
        overrides,
    )


def start_inspection_payload(**overrides: Any) -> Payload:
    return _build({"started_at": K.INSPECTION_STARTED_AT}, overrides)


def access_payload(access_result: str = "GRANTED", **overrides: Any) -> Payload:
    base: Dict[str, Any] = {
        "access_result": access_result,
        "recorded_at": K.ACCESS_RECORDED_AT,
    }
    if access_result == "REFUSED":
        base["refusal_reason"] = "Household declined entry"
    return _build(base, overrides)


def deficiency_payload(
    expected_inspection_version: int,
    defect_definition_id: str,
    unit_id: Optional[str] = None,
    inspectable_area: str = "UNIT",
    **overrides: Any
) -> Payload:
    base: Dict[str, Any] = {
        "expected_inspection_version": expected_inspection_version,
        "defect_definition_id": defect_definition_id,
        "inspectable_area": inspectable_area,
        "observed_at": K.OBSERVED_AT_1,
    }
    if unit_id is not None:
        base["unit_id"] = unit_id
    return _build(base, overrides)


def score_payload(**overrides: Any) -> Payload:
    return _build({"scored_at": K.SCORED_AT}, overrides)


def finalize_payload(**overrides: Any) -> Payload:
    return _build({"finalized_at": K.FINALIZED_AT}, overrides)


def cancel_payload(**overrides: Any) -> Payload:
    return _build({"cancelled_at": K.DRAWN_AT}, overrides)


def correction_payload(**overrides: Any) -> Payload:
    return _build(
        {"corrected_at": K.LT_CORRECTION_DUE_AT, "note": "Sash replaced"}, overrides
    )


def deficiency_verification_payload(
    verification_result: str = "PASSED", **overrides: Any
) -> Payload:
    return _build(
        {
            "verification_result": verification_result,
            "verified_at": K.WORK_ORDER_VERIFIED_AT,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Appeals
# ---------------------------------------------------------------------------
def appeal_payload(
    inspection_id: str,
    contested_deficiency_id: str,
    appeal_type: str = "TECHNICAL_ERROR",
    **overrides: Any
) -> Payload:
    """An appeal; `requested_point_adjustment` is present iff SCORE_CORRECTION."""
    base: Dict[str, Any] = {
        "inspection_id": inspection_id,
        "appeal_type": appeal_type,
        "rationale": "Window was boarded by the fire marshal",
        "filed_at": K.APPEAL_FILED_AT,
        "contested_deficiency_id": contested_deficiency_id,
    }
    if appeal_type == "SCORE_CORRECTION":
        base["rationale"] = "Only the lower sash is inoperable"
        base["requested_point_adjustment"] = 10.0
    return _build(base, overrides)


def appeal_review_payload(decision: str = "GRANTED", **overrides: Any) -> Payload:
    return _build(
        {
            "decision": decision,
            "decided_at": K.APPEAL_DECIDED_AT,
            "reviewer_note": "Reviewed against the submitted evidence",
        },
        overrides,
    )


def appeal_resubmit_payload(**overrides: Any) -> Payload:
    return _build(
        {"additional_evidence": "Fire marshal order attached"}, overrides
    )


# ---------------------------------------------------------------------------
# Corrective action plans
# ---------------------------------------------------------------------------
def cap_payload(inspection_id: str, **overrides: Any) -> Payload:
    """A plan whose cost is an integer count of cents."""
    return _build(
        {
            "inspection_id": inspection_id,
            "narrative": K.CAP_NARRATIVE,
            "total_estimated_cost_cents": K.CAP_COST_CENTS,
            "milestone_count": K.CAP_MILESTONE_COUNT,
            "target_completion_at": K.CAP_TARGET_COMPLETION_AT,
            "submitted_at": K.CAP_SUBMITTED_AT,
        },
        overrides,
    )


def cap_review_payload(decision: str = "APPROVED", **overrides: Any) -> Payload:
    return _build(
        {
            "decision": decision,
            "decided_at": K.CAP_DECIDED_AT,
            "reviewer_note": "Scope and schedule acceptable",
        },
        overrides,
    )


def cap_resubmit_payload(**overrides: Any) -> Payload:
    return _build(
        {
            "narrative": "Revised scope with staged window replacement",
            "total_estimated_cost_cents": K.CAP_COST_CENTS,
            "milestone_count": K.CAP_MILESTONE_COUNT,
            "target_completion_at": K.CAP_TARGET_COMPLETION_AT,
        },
        overrides,
    )


def follow_up_payload(**overrides: Any) -> Payload:
    return _build(
        {
            "scheduled_start": K.FOLLOW_UP_START,
            "scheduled_end": K.FOLLOW_UP_END,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Capital needs and operator endpoints
# ---------------------------------------------------------------------------
def capital_recompute_payload(
    property_id: str, expected_property_version: int, **overrides: Any
) -> Payload:
    return _build(
        {
            "property_id": property_id,
            "expected_property_version": expected_property_version,
            "recurrence_basis": "CALENDAR_SCOPED",
        },
        overrides,
    )


def clock_payload(current_utc: str, **overrides: Any) -> Payload:
    return _build({"current_utc": current_utc}, overrides)


def history_payload(
    property_id: str,
    standard_id: str,
    finalized_at: str,
    defect_definition_ids: List[str],
    unit_id: Optional[str] = None,
    **overrides: Any
) -> Payload:
    base: Dict[str, Any] = {
        "property_id": property_id,
        "standard_id": standard_id,
        "finalized_at": finalized_at,
        "defect_definition_ids": list(defect_definition_ids),
    }
    if unit_id is not None:
        base["unit_id"] = unit_id
    return _build(base, overrides)
