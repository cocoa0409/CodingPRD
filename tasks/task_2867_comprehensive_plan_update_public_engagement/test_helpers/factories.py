"""Request-payload builders.

Conventions honoured throughout:
- Every acreage, density, index, weight and score is a JSON **number**, never a
  string, because the PRD declares them numeric and a quoted decimal is a schema
  violation rather than a rounding question.
- Every datetime literal is a full ISO-8601 UTC instant with a `Z`; the client
  widens the fractional part to three digits.
- No derived field is ever supplied: PRD section 2.10, "Callers never write a
  derived field."
"""

from typing import Any, Dict, Optional

from .constants import (
    ACTIVITY_WORKSHOP,
    ACTION_ZONING_CODE_UPDATE,
    BODY_COMMISSION,
    DEPENDENCY_POLICY_ALIGNMENT,
    DIRECTION_INCREASE,
    DOC_EIR,
    ELEMENT_LAND_USE,
    GROUP_GENERAL,
    INVENTORY_DEMOGRAPHIC,
    INVENTORY_LAND_USE,
    METHOD_TREND,
    TIER_VERY_LOW,
)

# ------------------------------------------------------------------ reference plan
# The reference cycle used throughout: base_year 2025, horizon_year 2045, a full
# statutory 20-year horizon.
REF_BASE_YEAR = 2025
REF_HORIZON_YEAR = 2045
REF_JURISDICTION = "CA0451"


def plan_update_payload(**overrides) -> Dict[str, Any]:
    payload = {
        "title": "Horizon 2045",
        "jurisdiction_code": REF_JURISDICTION,
        "base_year": REF_BASE_YEAR,
        "horizon_year": REF_HORIZON_YEAR,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ inventory datasets
def tabular_inventory_payload(
    plan_update_id: str,
    inventory_type: str = INVENTORY_DEMOGRAPHIC,
    record_count: int = 1200,
    vintage_year: int = REF_BASE_YEAR,
    **overrides,
) -> Dict[str, Any]:
    """A DEMOGRAPHIC, HOUSING or EMPLOYMENT dataset: record_count, no acreage."""
    payload = {
        "plan_update_id": plan_update_id,
        "inventory_type": inventory_type,
        "record_count": record_count,
        "vintage_year": vintage_year,
    }
    payload.update(overrides)
    return payload


def land_use_inventory_payload(
    plan_update_id: str,
    vacant_acres: float = 400,
    underutilized_acres: float = 250,
    infrastructure_constrained_acres: float = 60,
    allowed_density_units_per_acre: float = 18,
    vintage_year: int = REF_BASE_YEAR,
    **overrides,
) -> Dict[str, Any]:
    """The reference acreage row: 400 vacant, 250 underutilized, 60 constrained,
    18 allowed units per acre — GROSS_CAPACITY 11700 and NET_CAPACITY 7115."""
    payload = {
        "plan_update_id": plan_update_id,
        "inventory_type": INVENTORY_LAND_USE,
        "vacant_acres": vacant_acres,
        "underutilized_acres": underutilized_acres,
        "infrastructure_constrained_acres": infrastructure_constrained_acres,
        "allowed_density_units_per_acre": allowed_density_units_per_acre,
        "vintage_year": vintage_year,
    }
    payload.update(overrides)
    return payload


# -------------------------------------------------------------- growth scenarios
def growth_scenario_payload(
    plan_update_id: str,
    land_use_inventory_id: str,
    expected_inventory_version: int,
    method: str = METHOD_TREND,
    label: str = "Baseline Trend",
    horizon_year: int = REF_HORIZON_YEAR,
    base_households: int = 60000,
    annual_household_growth_rate: float = 0.008,
    job_growth_total: int = 31000,
    demolition_replacement_units: int = 1200,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "plan_update_id": plan_update_id,
        "land_use_inventory_id": land_use_inventory_id,
        "expected_inventory_version": expected_inventory_version,
        "label": label,
        "method": method,
        "horizon_year": horizon_year,
        "base_households": base_households,
        "annual_household_growth_rate": annual_household_growth_rate,
        "job_growth_total": job_growth_total,
        "demolition_replacement_units": demolition_replacement_units,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------ housing allocations
def housing_allocation_payload(
    plan_update_id: str,
    income_tier: str = TIER_VERY_LOW,
    assigned_units: int = 900,
    cycle_deadline: str = "2033-12-31T00:00:00.000Z",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "plan_update_id": plan_update_id,
        "income_tier": income_tier,
        "assigned_units": assigned_units,
        "cycle_deadline": cycle_deadline,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------ plan elements
def plan_element_payload(
    plan_update_id: str,
    element_type: str = ELEMENT_LAND_USE,
    title: Optional[str] = None,
    draft_body: str = "Chapter narrative for the statutory element.",
    policy_count: Optional[int] = 6,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_update_id": plan_update_id,
        "element_type": element_type,
        "title": title if title is not None else f"{element_type} Element",
        "draft_body": draft_body,
    }
    if policy_count is not None:
        payload["policy_count"] = policy_count
    payload.update(overrides)
    return payload


def review_decision_payload(decision: str, review_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if review_note is not None:
        payload["review_note"] = review_note
    return payload


# ------------------------------------------------------------- consistency links
def consistency_link_payload(
    source_element_id: str,
    target_element_id: str,
    dependency_type: str = DEPENDENCY_POLICY_ALIGNMENT,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "source_element_id": source_element_id,
        "target_element_id": target_element_id,
        "dependency_type": dependency_type,
    }
    payload.update(overrides)
    return payload


def reconcile_payload(note: str = "Policies realigned across both chapters.") -> Dict[str, Any]:
    return {"reconciliation_note": note}


# -------------------------------------------------------------------- venues
def venue_payload(
    name: str = "Civic Center Hall",
    seated_capacity: int = 120,
    turnover_buffer_minutes: Optional[int] = None,
    ada_accessible: Optional[bool] = None,
    transit_served: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    """Only the two mandatory fields are sent unless a test pins a default."""
    payload: Dict[str, Any] = {"name": name, "seated_capacity": seated_capacity}
    if turnover_buffer_minutes is not None:
        payload["turnover_buffer_minutes"] = turnover_buffer_minutes
    if ada_accessible is not None:
        payload["ada_accessible"] = ada_accessible
    if transit_served is not None:
        payload["transit_served"] = transit_served
    payload.update(overrides)
    return payload


def equity_eligible_venue_payload(**overrides) -> Dict[str, Any]:
    """A venue that satisfies the targeted-outreach equity test: both
    transit_served and ada_accessible."""
    return venue_payload(
        name="Transit Plaza Community Room",
        ada_accessible=True,
        transit_served=True,
        **overrides,
    )


# ------------------------------------------------------- engagement activities
def engagement_activity_payload(
    plan_update_id: str,
    activity_type: str = ACTIVITY_WORKSHOP,
    title: str = "Community Workshop A",
    venue_id: Optional[str] = None,
    start_at: str = "2026-07-10T18:00:00.000Z",
    end_at: str = "2026-07-10T20:00:00.000Z",
    interpretation_offered: Optional[bool] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "plan_update_id": plan_update_id,
        "activity_type": activity_type,
        "title": title,
        "start_at": start_at,
        "end_at": end_at,
    }
    if venue_id is not None:
        payload["venue_id"] = venue_id
    if interpretation_offered is not None:
        payload["interpretation_offered"] = interpretation_offered
    payload.update(overrides)
    return payload


def participation_record_payload(
    activity_id: str,
    respondent_ref: str = "resp-001",
    demographic_group: str = GROUP_GENERAL,
    census_tract: str = "060014001",
    interpreter_used: Optional[bool] = None,
    comment_text: Optional[str] = None,
    **overrides,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "activity_id": activity_id,
        "respondent_ref": respondent_ref,
        "demographic_group": demographic_group,
        "census_tract": census_tract,
    }
    if interpreter_used is not None:
        payload["interpreter_used"] = interpreter_used
    if comment_text is not None:
        payload["comment_text"] = comment_text
    payload.update(overrides)
    return payload


# ------------------------------------------------------- environmental reviews
def environmental_review_payload(
    plan_update_id: str,
    document_type: str = DOC_EIR,
    title: str = "Draft Environmental Impact Report",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "plan_update_id": plan_update_id,
        "document_type": document_type,
        "title": title,
    }
    payload.update(overrides)
    return payload


def plan_alternative_payload(
    environmental_review_id: str,
    label: str = "Transit-Focused Growth",
    traffic_vmt_index: float = 40,
    ghg_index: float = 40,
    habitat_index: float = 40,
    water_index: float = 40,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "environmental_review_id": environmental_review_id,
        "label": label,
        "traffic_vmt_index": traffic_vmt_index,
        "ghg_index": ghg_index,
        "habitat_index": habitat_index,
        "water_index": water_index,
    }
    payload.update(overrides)
    return payload


# ------------------------------------------------------------------- hearings
def hearing_payload(
    plan_update_id: str,
    body_type: str = BODY_COMMISSION,
    scheduled_start: str = "2026-09-25T18:00:00.000Z",
    scheduled_end: str = "2026-09-25T21:00:00.000Z",
    notice_published_at: str = "2026-09-15T00:00:00.000Z",
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "plan_update_id": plan_update_id,
        "body_type": body_type,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "notice_published_at": notice_published_at,
    }
    payload.update(overrides)
    return payload


def outcome_payload(outcome: str, minutes_note: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if minutes_note is not None:
        payload["minutes_note"] = minutes_note
    return payload


# ------------------------------------------------------------------ amendments
def amendment_payload(
    hearing_id: str,
    target_element_id: str,
    expected_element_version: int,
    summary: str = "Add two policies on inclusionary housing.",
    policy_delta: int = 2,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "hearing_id": hearing_id,
        "target_element_id": target_element_id,
        "summary": summary,
        "policy_delta": policy_delta,
        "expected_element_version": expected_element_version,
    }
    payload.update(overrides)
    return payload


# --------------------------------------------------------- implementation actions
def implementation_action_payload(
    plan_update_id: str,
    source_element_id: str,
    action_type: str = ACTION_ZONING_CODE_UPDATE,
    title: str = "Rezone the transit corridor",
    indicator_name: str = "Permitted units per year",
    indicator_direction: str = DIRECTION_INCREASE,
    baseline_value: float = 100,
    target_value: float = 250,
    **overrides,
) -> Dict[str, Any]:
    payload = {
        "plan_update_id": plan_update_id,
        "source_element_id": source_element_id,
        "action_type": action_type,
        "title": title,
        "indicator_name": indicator_name,
        "indicator_direction": indicator_direction,
        "baseline_value": baseline_value,
        "target_value": target_value,
    }
    payload.update(overrides)
    return payload


def state_determination_payload(
    determination: str,
    findings: str = "State review findings of record.",
    deficient_element_types: Optional[list] = None,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"determination": determination, "findings": findings}
    if deficient_element_types is not None:
        payload["deficient_element_types"] = deficient_element_types
    return payload
