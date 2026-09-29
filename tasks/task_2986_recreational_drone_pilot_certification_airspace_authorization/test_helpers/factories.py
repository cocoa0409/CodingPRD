"""Request payload factories.

Every factory returns a plain dict that satisfies the PRD's shape rules, and every
factory merges `**overrides` last so a caller can replace or remove any field
without the factory also passing that key positionally.

Conventions honoured throughout:
  * monetary amounts are JSON integers of whole cents, never strings;
  * datetimes are whole-second ISO 8601 UTC instants with a literal `Z` suffix;
  * string literals respect the length and charset bounds the PRD declares;
  * default instants all sit at or after the clock's startup value.
"""

import itertools
from typing import Any, Dict, List, Optional

from .api_client import OMIT
from .constants import CLOCK_STARTUP_UTC

_counter = itertools.count(1)


def unique_suffix() -> str:
    """A short, collision-free suffix for unique-constrained string fields."""
    return f"{next(_counter):06d}"


def unique_email(prefix: str = "pilot") -> str:
    return f"{prefix}.{unique_suffix()}@drone-ops.test"


def unique_serial(prefix: str = "SN") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_designator(prefix: str = "ZONE") -> str:
    return f"{prefix}-{unique_suffix()}"


def unique_policy_number(prefix: str = "POL") -> str:
    return f"{prefix}-{unique_suffix()}"


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    merged = dict(base)
    merged.update(overrides)
    return merged


# ---------------------------------------------------------------------------
# Pilots
# ---------------------------------------------------------------------------


def pilot_payload(operator_category: str = "RECREATIONAL", **overrides: Any) -> Dict[str, Any]:
    base = {
        "full_name": f"Test Pilot {unique_suffix()}",
        "email": unique_email(),
        "operator_category": operator_category,
    }
    return _merge(base, overrides)


def recreational_pilot_payload(**overrides: Any) -> Dict[str, Any]:
    return pilot_payload("RECREATIONAL", **overrides)


def commercial_pilot_payload(**overrides: Any) -> Dict[str, Any]:
    return pilot_payload("COMMERCIAL", **overrides)


def suspension_payload(
    suspension_reason: str = "Manual enforcement action", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"suspension_reason": suspension_reason}, overrides)


def revocation_payload(
    suspension_reason: str = "Permanent revocation of privileges", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"suspension_reason": suspension_reason}, overrides)


# ---------------------------------------------------------------------------
# Knowledge tests
# ---------------------------------------------------------------------------


def knowledge_test_payload(
    test_code: str = "TRUST_RECREATIONAL",
    scheduled_at: str = CLOCK_STARTUP_UTC,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {"test_code": test_code, "scheduled_at": scheduled_at}
    return _merge(base, overrides)


def grade_payload(raw_score: int = 100, **overrides: Any) -> Dict[str, Any]:
    return _merge({"raw_score": raw_score}, overrides)


# ---------------------------------------------------------------------------
# Airframes and broadcast modules
# ---------------------------------------------------------------------------


def aircraft_payload(
    owner_pilot_id: str,
    takeoff_weight_g: int = 1200,
    max_altitude_ft: int = 1500,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "owner_pilot_id": owner_pilot_id,
        "model": f"Testwing {unique_suffix()}",
        "serial_number": unique_serial("AF"),
        "takeoff_weight_g": takeoff_weight_g,
        "max_altitude_ft": max_altitude_ft,
    }
    return _merge(base, overrides)


def grounding_payload(
    grounding_reason: str = "Scheduled maintenance", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"grounding_reason": grounding_reason}, overrides)


def module_payload(**overrides: Any) -> Dict[str, Any]:
    base = {
        "module_serial": unique_serial("RID"),
        "broadcast_protocol": "WIFI_NAN",
        "firmware_version": "1.4.2",
        "broadcast_sample_ref": f"sample-{unique_suffix()}",
    }
    return _merge(base, overrides)


def module_submission_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"broadcast_sample_ref": f"sample-{unique_suffix()}"}, overrides)


def module_verify_payload(
    outcome: str = "VERIFIED",
    verified_until: Any = OMIT,
    failure_reason: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"outcome": outcome}
    if verified_until is not OMIT:
        base["verified_until"] = verified_until
    if failure_reason is not OMIT:
        base["failure_reason"] = failure_reason
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Airspace zones and temporary flight restrictions
# ---------------------------------------------------------------------------


def zone_payload(
    class_code: str = "G",
    class_ceiling_ft: int = 1500,
    requires_authorization: bool = False,
    max_concurrent_authorizations: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "designator": unique_designator(),
        "class_code": class_code,
        "class_ceiling_ft": class_ceiling_ft,
        "requires_authorization": requires_authorization,
        "max_concurrent_authorizations": max_concurrent_authorizations,
    }
    return _merge(base, overrides)


def controlled_zone_payload(**overrides: Any) -> Dict[str, Any]:
    """A zone whose `requires_authorization` is true."""
    merged = dict(overrides)
    merged.setdefault("class_code", "D")
    merged.setdefault("requires_authorization", True)
    return zone_payload(**merged)


def tfr_payload(
    zone_id: str,
    effective_from: str,
    effective_until: str,
    max_permitted_altitude_ft: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "zone_id": zone_id,
        "reason": f"Test restriction {unique_suffix()}",
        "effective_from": effective_from,
        "effective_until": effective_until,
    }
    if max_permitted_altitude_ft is not OMIT:
        base["max_permitted_altitude_ft"] = max_permitted_altitude_ft
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Airspace authorizations
# ---------------------------------------------------------------------------


def authorization_payload(
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    expected_zone_version: int,
    window_start: str,
    window_end: str,
    requested_ceiling_ft: int = 400,
    waiver_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "pilot_id": pilot_id,
        "aircraft_id": aircraft_id,
        "zone_id": zone_id,
        "requested_ceiling_ft": requested_ceiling_ft,
        "window_start": window_start,
        "window_end": window_end,
        "expected_zone_version": expected_zone_version,
    }
    if waiver_id is not OMIT:
        base["waiver_id"] = waiver_id
    return _merge(base, overrides)


def approve_authorization_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": "APPROVE"}, overrides)


def deny_authorization_payload(
    denial_reason: str = "Insufficient separation from arrivals", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": "DENY", "denial_reason": denial_reason}, overrides)


def revoke_authorization_payload(
    denial_reason: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if denial_reason is not OMIT:
        base["denial_reason"] = denial_reason
    return _merge(base, overrides)


# ---------------------------------------------------------------------------
# Waivers and safety cases
# ---------------------------------------------------------------------------


def waiver_payload(
    pilot_id: str,
    aircraft_id: str,
    expected_pilot_version: int,
    waiver_type: str = "OVER_PEOPLE",
    requested_ceiling_ft: int = 700,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "pilot_id": pilot_id,
        "aircraft_id": aircraft_id,
        "waiver_type": waiver_type,
        "requested_ceiling_ft": requested_ceiling_ft,
        "operation_description": f"Test special operation {unique_suffix()}",
        "expected_pilot_version": expected_pilot_version,
    }
    return _merge(base, overrides)


def safety_case_payload(
    ground_risk_class: int = 1,
    air_risk_class: str = "ARC_A",
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "mitigation_summary": f"Mitigations {unique_suffix()}",
        "ground_risk_class": ground_risk_class,
        "air_risk_class": air_risk_class,
        "contingency_procedures": f"Contingency procedures {unique_suffix()}",
    }
    return _merge(base, overrides)


def revision_request_payload(
    reviewer_findings: str = "Expand the ground-risk mitigation section", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"reviewer_findings": reviewer_findings}, overrides)


def clear_safety_case_payload(
    reviewer_findings: Any = OMIT, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if reviewer_findings is not OMIT:
        base["reviewer_findings"] = reviewer_findings
    return _merge(base, overrides)


def approve_waiver_payload(granted_ceiling_ft: int = 700, **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": "APPROVE", "granted_ceiling_ft": granted_ceiling_ft}, overrides)


def deny_waiver_payload(
    denial_reason: str = "Residual risk not adequately mitigated", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"decision": "DENY", "denial_reason": denial_reason}, overrides)


# ---------------------------------------------------------------------------
# Insurance policies
# ---------------------------------------------------------------------------


def policy_payload(
    pilot_id: str,
    effective_from: str,
    effective_until: str,
    coverage_limit_cents: int = 5000000,
    deductible_cents: int = 100000,
    indemnification_clause_accepted: bool = True,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "pilot_id": pilot_id,
        "insurer_name": f"Test Underwriters {unique_suffix()}",
        "policy_number": unique_policy_number(),
        "coverage_limit_cents": coverage_limit_cents,
        "deductible_cents": deductible_cents,
        "effective_from": effective_from,
        "effective_until": effective_until,
        "indemnification_clause_accepted": indemnification_clause_accepted,
    }
    return _merge(base, overrides)


def activate_policy_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": "ACTIVE"}, overrides)


def reject_policy_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"outcome": "REJECTED"}, overrides)


# ---------------------------------------------------------------------------
# Flights
# ---------------------------------------------------------------------------


def flight_payload(
    pilot_id: str,
    aircraft_id: str,
    zone_id: str,
    planned_start: str,
    planned_end: str,
    operation_category: str = "RECREATIONAL",
    planned_max_altitude_ft: int = 400,
    authorization_id: Any = OMIT,
    waiver_id: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "pilot_id": pilot_id,
        "aircraft_id": aircraft_id,
        "zone_id": zone_id,
        "operation_category": operation_category,
        "planned_start": planned_start,
        "planned_end": planned_end,
        "planned_max_altitude_ft": planned_max_altitude_ft,
        "launch_latitude": 40.7128,
        "launch_longitude": -74.006,
    }
    if authorization_id is not OMIT:
        base["authorization_id"] = authorization_id
    if waiver_id is not OMIT:
        base["waiver_id"] = waiver_id
    return _merge(base, overrides)


def preflight_check_payload(
    acknowledged_tfr_ids: Optional[List[str]] = None, **overrides: Any
) -> Dict[str, Any]:
    base: Dict[str, Any] = {"acknowledged_tfr_ids": list(acknowledged_tfr_ids or [])}
    return _merge(base, overrides)


def completion_payload(
    actual_end: str,
    max_altitude_reached_ft: int = 300,
    incident_occurred: bool = False,
    incident_summary: Any = OMIT,
    **overrides: Any,
) -> Dict[str, Any]:
    base: Dict[str, Any] = {
        "actual_end": actual_end,
        "max_altitude_reached_ft": max_altitude_reached_ft,
        "incident_occurred": incident_occurred,
    }
    if incident_summary is not OMIT:
        base["incident_summary"] = incident_summary
    elif incident_occurred:
        base["incident_summary"] = f"Incident report {unique_suffix()}"
    return _merge(base, overrides)


def cancellation_payload(
    cancellation_reason: str = "Pilot stood the mission down", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"cancellation_reason": cancellation_reason}, overrides)


# ---------------------------------------------------------------------------
# Accident reports
# ---------------------------------------------------------------------------


def accident_report_payload(
    flight_id: str,
    occurred_at: str,
    injury_level: str = "NONE",
    reported_property_damage_cents: int = 400000,
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "flight_id": flight_id,
        "occurred_at": occurred_at,
        "injury_level": injury_level,
        "reported_property_damage_cents": reported_property_damage_cents,
        "narrative": f"Accident narrative {unique_suffix()}",
    }
    return _merge(base, overrides)


def damage_line(label: str, amount_cents: int) -> Dict[str, Any]:
    """One entry of `damage_line_items`; `amount_cents` is a whole-cent integer."""
    return {"label": label, "amount_cents": amount_cents}


def close_report_payload(
    damage_line_items: List[Dict[str, Any]],
    probable_cause: str = "Loss of link during descent",
    **overrides: Any,
) -> Dict[str, Any]:
    base = {
        "damage_line_items": list(damage_line_items),
        "probable_cause": probable_cause,
    }
    return _merge(base, overrides)


def remediation_payload(
    remediation_findings: str = "Revise the pre-flight checklist", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"remediation_findings": remediation_findings}, overrides)


def withdraw_report_payload(probable_cause: Any = OMIT, **overrides: Any) -> Dict[str, Any]:
    base: Dict[str, Any] = {}
    if probable_cause is not OMIT:
        base["probable_cause"] = probable_cause
    return _merge(base, overrides)
