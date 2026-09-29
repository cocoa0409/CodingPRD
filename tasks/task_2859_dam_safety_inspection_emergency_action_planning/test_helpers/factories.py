"""Request-payload factories.

Every builder emits the field names and JSON types the PRD declares: money as
integer cents, counts as integers, elevations and flows as JSON numbers, and
every temporal field as a full ISO-8601 instant.
"""

from __future__ import annotations

from typing import Any, Optional

from .constants import (
    CATEGORY_STRUCTURAL,
    CLOCK_ORIGIN,
    DECISION_ISSUE,
    ENTRY_CIVIL_PENALTY,
    EXERCISE_TABLETOP,
    INSPECTION_TYPE_PERIODIC,
    ORDER_TYPE_COMPLIANCE,
    OWNER_TYPE_PRIVATE,
    PERMIT_TYPE_REPAIR,
    REVIEW_APPROVE,
    SAFETY_SATISFACTORY,
    SEVERITY_MODERATE,
    VERIFY_SATISFIED,
)


def _merge(payload: dict[str, Any], overrides: Optional[dict[str, Any]]) -> dict:
    if overrides:
        payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Clock
# ---------------------------------------------------------------------------
def clock_payload(to_iso8601: str = CLOCK_ORIGIN) -> dict:
    return {"to_iso8601": to_iso8601}


# ---------------------------------------------------------------------------
# Owners / engineers / reaches
# ---------------------------------------------------------------------------
def owner_payload(
    legal_name: str = "Cascade Hydro LLC",
    owner_type: str = OWNER_TYPE_PRIVATE,
    contact_email: str = "ops@cascadehydro.example",
    financial_assurance_bond_cents: int = 50_000_000,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "legal_name": legal_name,
            "owner_type": owner_type,
            "contact_email": contact_email,
            "financial_assurance_bond_cents": int(financial_assurance_bond_cents),
        },
        overrides,
    )


def engineer_payload(
    full_name: str = "Dana Reyes",
    license_number: str = "PE-44120",
    license_expires_at: str = "2029-12-31T00:00:00Z",
    certified_hazard_classes: Optional[list[str]] = None,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "full_name": full_name,
            "license_number": license_number,
            "license_expires_at": license_expires_at,
            "certified_hazard_classes": list(
                certified_hazard_classes or ["LOW", "SIGNIFICANT", "HIGH"]
            ),
        },
        overrides,
    )


def river_reach_payload(
    name: str = "Little Bear Creek Reach 3",
    channel_capacity_cfs: float = 1200,
    downstream_community: str = "Elk Hollow",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "name": name,
            "channel_capacity_cfs": channel_capacity_cfs,
            "downstream_community": downstream_community,
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Dams
# ---------------------------------------------------------------------------
def dam_payload(
    owner_id: str,
    river_reach_id: str,
    name: str = "Elk Hollow Dam",
    nid_code: str = "ST00123",
    height_ft: float = 62,
    gross_storage_acre_ft: float = 1500,
    crest_elevation_ft: float = 1042.5,
    normal_pool_elevation_ft: float = 1038.0,
    year_completed: int = 1968,
    registered_at: str = "2019-04-15T00:00:00Z",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "owner_id": owner_id,
            "river_reach_id": river_reach_id,
            "name": name,
            "nid_code": nid_code,
            "height_ft": height_ft,
            "gross_storage_acre_ft": gross_storage_acre_ft,
            "crest_elevation_ft": crest_elevation_ft,
            "normal_pool_elevation_ft": normal_pool_elevation_ft,
            "year_completed": int(year_completed),
            "registered_at": registered_at,
        },
        overrides,
    )


def state_intervention_payload(
    intervention_type: str,
    justification: str = "State action recorded by the dam safety program.",
    **overrides: Any,
) -> dict:
    return _merge(
        {"intervention_type": intervention_type, "justification": justification},
        overrides,
    )


# ---------------------------------------------------------------------------
# Consequence assessments
# ---------------------------------------------------------------------------
def assessment_payload(
    dam_id: str,
    population_at_risk: int = 3,
    habitable_structures: int = 2,
    critical_facilities: int = 0,
    breach_peak_outflow_cfs: float = 9000,
    breach_travel_time_minutes: float = 200,
    inundation_area_acres: float = 50,
    inundation_map_ref: str = "IM-2019-A",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "population_at_risk": int(population_at_risk),
            "habitable_structures": int(habitable_structures),
            "critical_facilities": int(critical_facilities),
            "breach_peak_outflow_cfs": breach_peak_outflow_cfs,
            "breach_travel_time_minutes": breach_travel_time_minutes,
            "inundation_area_acres": inundation_area_acres,
            "inundation_map_ref": inundation_map_ref,
        },
        overrides,
    )


def assessment_a1(dam_id: str, **overrides: Any) -> dict:
    """Screening 9.00 / certified 6.60 -- both SIGNIFICANT."""
    return assessment_payload(dam_id, **overrides)


def assessment_a2(dam_id: str, **overrides: Any) -> dict:
    """Screening 30.00 (SIGNIFICANT) / certified 45.00 (HIGH)."""
    base = assessment_payload(
        dam_id,
        population_at_risk=12,
        habitable_structures=4,
        critical_facilities=0,
        breach_peak_outflow_cfs=18500,
        breach_travel_time_minutes=20,
        inundation_area_acres=300,
        inundation_map_ref="IM-2026-B",
    )
    return _merge(base, overrides)


def assessment_a3(dam_id: str, **overrides: Any) -> dict:
    """All consequence inputs zero -- score 0.00, LOW under either variant."""
    base = assessment_payload(
        dam_id,
        population_at_risk=0,
        habitable_structures=0,
        critical_facilities=0,
        breach_peak_outflow_cfs=4000,
        breach_travel_time_minutes=200,
        inundation_area_acres=50,
        inundation_map_ref="IM-2019-C",
    )
    return _merge(base, overrides)


def assessment_a4(dam_id: str, **overrides: Any) -> dict:
    """Every component at its cap -- certified 100.00, HIGH."""
    base = assessment_payload(
        dam_id,
        population_at_risk=100,
        habitable_structures=40,
        critical_facilities=10,
        breach_peak_outflow_cfs=42000,
        breach_travel_time_minutes=10,
        inundation_area_acres=900,
        inundation_map_ref="IM-2026-D",
    )
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Inspections
# ---------------------------------------------------------------------------
def inspection_payload(
    dam_id: str,
    engineer_id: str,
    inspection_type: str = INSPECTION_TYPE_PERIODIC,
    window_start: str = "2026-08-04T00:00:00Z",
    window_end: str = "2026-08-06T00:00:00Z",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "engineer_id": engineer_id,
            "inspection_type": inspection_type,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def deficiency_item(
    category: str = CATEGORY_STRUCTURAL,
    severity: str = SEVERITY_MODERATE,
    description: str = "Crest settlement observed along the left abutment.",
    **overrides: Any,
) -> dict:
    return _merge(
        {"category": category, "severity": severity, "description": description},
        overrides,
    )


def inspection_submission_payload(
    performed_at: str = "2026-08-05T12:00:00Z",
    condition_rating: str = SAFETY_SATISFACTORY,
    narrative: str = "Walked the crest, spillway and outlet works; no seepage observed.",
    deficiencies: Optional[list[dict]] = None,
    **overrides: Any,
) -> dict:
    payload: dict[str, Any] = {
        "performed_at": performed_at,
        "condition_rating": condition_rating,
        "narrative": narrative,
    }
    if deficiencies is not None:
        payload["deficiencies"] = deficiencies
    return _merge(payload, overrides)


def inspection_return_payload(
    reason: str = "Narrative omits the outlet works inspection.", **overrides: Any
) -> dict:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Remediation orders
# ---------------------------------------------------------------------------
def remediation_order_payload(
    order_type: str = ORDER_TYPE_COMPLIANCE,
    requested_response_days: int = 60,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "order_type": order_type,
            "requested_response_days": int(requested_response_days),
        },
        overrides,
    )


def order_response_payload(
    corrective_action_summary: str = "Toe drain cleaned and relief wells installed.",
    completed_at: str = "2026-08-05T12:00:00Z",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "corrective_action_summary": corrective_action_summary,
            "completed_at": completed_at,
        },
        overrides,
    )


def order_verify_payload(
    outcome: str = VERIFY_SATISFIED,
    notes: str = "Corrective work inspected in the field and accepted.",
    **overrides: Any,
) -> dict:
    return _merge({"outcome": outcome, "notes": notes}, overrides)


# ---------------------------------------------------------------------------
# Emergency action plans
# ---------------------------------------------------------------------------
def eap_payload(
    dam_id: str,
    expected_dam_version: int,
    version_label: str = "2026 Rev A",
    inundation_map_ref: str = "IM-2019-A",
    notification_flowchart_ref: str = "FC-2026-1",
    notification_contact_count: int = 4,
    drawdown_procedure_ref: str = "DP-2026-1",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "version_label": version_label,
            "inundation_map_ref": inundation_map_ref,
            "notification_flowchart_ref": notification_flowchart_ref,
            "notification_contact_count": int(notification_contact_count),
            "drawdown_procedure_ref": drawdown_procedure_ref,
            "expected_dam_version": int(expected_dam_version),
        },
        overrides,
    )


def eap_review_payload(
    decision: str = REVIEW_APPROVE,
    findings: str = "Plan reviewed against the current inundation mapping.",
    **overrides: Any,
) -> dict:
    return _merge({"decision": decision, "findings": findings}, overrides)


def exercise_payload(
    exercise_type: str = EXERCISE_TABLETOP,
    conducted_at: str = "2026-07-01T00:00:00Z",
    participant_count: int = 4,
    notification_test_passed: bool = True,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "exercise_type": exercise_type,
            "conducted_at": conducted_at,
            "participant_count": int(participant_count),
            "notification_test_passed": bool(notification_test_passed),
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# Permits
# ---------------------------------------------------------------------------
def permit_payload(
    dam_id: str,
    permit_type: str = PERMIT_TYPE_REPAIR,
    scope_description: str = "Toe drain replacement",
    estimated_project_cost_cents: int = 8_000_000,
    proposed_start_date: str = "2026-10-01T00:00:00Z",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "permit_type": permit_type,
            "scope_description": scope_description,
            "estimated_project_cost_cents": int(estimated_project_cost_cents),
            "proposed_start_date": proposed_start_date,
        },
        overrides,
    )


def assign_review_payload(review_engineer_id: str, **overrides: Any) -> dict:
    return _merge({"review_engineer_id": review_engineer_id}, overrides)


def permit_decision_payload(
    decision: str = DECISION_ISSUE,
    findings: str = "Design drawings and stability analysis reviewed.",
    conditions: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict[str, Any] = {"decision": decision, "findings": findings}
    if conditions is not None:
        payload["conditions"] = conditions
    return _merge(payload, overrides)


def permit_resubmit_payload(
    scope_description: str = "Reduced scope: toe drain replacement only",
    estimated_project_cost_cents: int = 8_000_000,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "scope_description": scope_description,
            "estimated_project_cost_cents": int(estimated_project_cost_cents),
        },
        overrides,
    )


# ---------------------------------------------------------------------------
# High-water events / readings / drawdown orders
# ---------------------------------------------------------------------------
def event_payload(
    dam_id: str,
    declared_at: str = "2026-08-01T00:00:00Z",
    trigger_description: str = "Forecast rainfall exceeds the design storm.",
    declared_inflow_cfs: float = 2500,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "declared_at": declared_at,
            "trigger_description": trigger_description,
            "declared_inflow_cfs": declared_inflow_cfs,
        },
        overrides,
    )


def reading_payload(
    reading_at: str,
    pool_elevation_ft: float,
    observed_inflow_cfs: float = 2600,
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "reading_at": reading_at,
            "pool_elevation_ft": pool_elevation_ft,
            "observed_inflow_cfs": observed_inflow_cfs,
        },
        overrides,
    )


def stand_down_payload(
    final_pool_elevation_ft: float = 1035.0, **overrides: Any
) -> dict:
    return _merge({"final_pool_elevation_ft": final_pool_elevation_ft}, overrides)


def drawdown_payload(
    dam_id: str,
    high_water_event_id: str,
    requested_release_cfs: float = 400,
    window_start: str = "2026-08-01T06:00:00Z",
    window_end: str = "2026-08-01T12:00:00Z",
    **overrides: Any,
) -> dict:
    return _merge(
        {
            "dam_id": dam_id,
            "high_water_event_id": high_water_event_id,
            "requested_release_cfs": requested_release_cfs,
            "window_start": window_start,
            "window_end": window_end,
        },
        overrides,
    )


def coordinate_payload(expected_reach_version: int, **overrides: Any) -> dict:
    return _merge({"expected_reach_version": int(expected_reach_version)}, overrides)


def complete_drawdown_payload(actual_release_acre_ft: float, **overrides: Any) -> dict:
    return _merge({"actual_release_acre_ft": actual_release_acre_ft}, overrides)


def cancel_drawdown_payload(
    reason: str = "Release no longer required.", **overrides: Any
) -> dict:
    return _merge({"reason": reason}, overrides)


# ---------------------------------------------------------------------------
# Fee ledger
# ---------------------------------------------------------------------------
def fee_adjustment_payload(
    entry_type: str = ENTRY_CIVIL_PENALTY,
    amount_cents: int = 30_000,
    source_ref: Optional[str] = None,
    memo: Optional[str] = None,
    **overrides: Any,
) -> dict:
    payload: dict[str, Any] = {
        "entry_type": entry_type,
        "amount_cents": int(amount_cents),
    }
    if source_ref is not None:
        payload["source_ref"] = source_ref
    if memo is not None:
        payload["memo"] = memo
    return _merge(payload, overrides)
