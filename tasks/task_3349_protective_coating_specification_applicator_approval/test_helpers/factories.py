"""Payload factories — one per resource, input fields only.

Optional fields are omitted from the payload unless the caller supplies them,
so a test can always tell whether it exercised a server-side default or an
explicit value. ``_UNSET`` marks "leave the key out entirely".
"""

from typing import Any, Dict, List, Optional

_UNSET = object()

# ── Default values for the reference world most tests build ────────────────

DEFAULT_JURISDICTION = "US-FED"
DEFAULT_APPLICATION_METHOD = "SPRAY_AIRLESS"
DEFAULT_VOC_LIMIT_GPL = 340
DEFAULT_REGULATION_FROM = "2026-01-01T00:00:00Z"
DEFAULT_REGULATION_TO = "2027-01-01T00:00:00Z"

DEFAULT_PREP_STANDARD = "SSPC_SP10_NEAR_WHITE"
DEFAULT_PROFILE_MIN = 2.0
DEFAULT_PROFILE_MAX = 4.0
DEFAULT_DFT_MIN = 8.0
DEFAULT_DFT_MAX = 16.0
DEFAULT_BASE_VOC = 300
DEFAULT_THINNER_VOC = 250
DEFAULT_MAX_THINNER_PCT = 0.10
DEFAULT_ADHESION_MIN_PSI = 500

DEFAULT_WINDOW_START = "2026-09-05T00:00:00Z"
DEFAULT_WINDOW_END = "2026-09-15T00:00:00Z"
DEFAULT_APPLIED_AT = "2026-09-06T09:00:00Z"

PASSING_DFT_READINGS = [10.0, 11.0, 12.0]
PASSING_ADHESION_READINGS = [600]


def clock_payload(current_utc: str) -> Dict[str, Any]:
    return {"current_utc": current_utc}


def coating_system_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "system_code": "SW-TEST-100",
        "manufacturer_name": "Sherwin-Williams",
        "surface_prep_standard": DEFAULT_PREP_STANDARD,
        "min_surface_profile_mils": DEFAULT_PROFILE_MIN,
        "max_surface_profile_mils": DEFAULT_PROFILE_MAX,
        "coat_count": 1,
        "total_dft_min_mils": DEFAULT_DFT_MIN,
        "total_dft_max_mils": DEFAULT_DFT_MAX,
        "base_voc_gpl": DEFAULT_BASE_VOC,
        "thinner_voc_gpl": DEFAULT_THINNER_VOC,
        "adhesion_min_psi": DEFAULT_ADHESION_MIN_PSI,
        "max_thinner_pct": DEFAULT_MAX_THINNER_PCT,
    }
    payload.update(overrides)
    return payload


def voc_regulation_payload(
    jurisdiction_code: str = DEFAULT_JURISDICTION,
    application_method: str = DEFAULT_APPLICATION_METHOD,
    voc_limit_gpl: int = DEFAULT_VOC_LIMIT_GPL,
    effective_from: str = DEFAULT_REGULATION_FROM,
    effective_to: str = DEFAULT_REGULATION_TO,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "jurisdiction_code": jurisdiction_code,
        "application_method": application_method,
        "voc_limit_gpl": voc_limit_gpl,
        "effective_from": effective_from,
        "effective_to": effective_to,
    }
    payload.update(overrides)
    return payload


def regulation_supersede_payload(
    new_voc_limit_gpl: int,
    new_effective_from: str,
    new_effective_to: str,
) -> Dict[str, Any]:
    return {
        "new_voc_limit_gpl": new_voc_limit_gpl,
        "new_effective_from": new_effective_from,
        "new_effective_to": new_effective_to,
    }


def applicator_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "company_name": "Acme Coatings",
        "contact_email": "ops@acme.example",
    }
    payload.update(overrides)
    return payload


def qualification_program_payload(
    coating_system_id: str,
    program_code: str = "QP-TEST-100",
    min_quality_history_score: int = 300,
    min_consecutive_passed_inspections: Any = 0,
    requires_training: Any = False,
    requires_equipment_audit: Any = False,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "program_code": program_code,
        "coating_system_id": coating_system_id,
        "min_quality_history_score": min_quality_history_score,
    }
    if min_consecutive_passed_inspections is not _UNSET:
        payload["min_consecutive_passed_inspections"] = min_consecutive_passed_inspections
    if requires_training is not _UNSET:
        payload["requires_training"] = requires_training
    if requires_equipment_audit is not _UNSET:
        payload["requires_equipment_audit"] = requires_equipment_audit
    payload.update(overrides)
    return payload


def enrollment_payload(
    program_id: str,
    training_completed_at: Any = _UNSET,
    equipment_audit_passed: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"program_id": program_id}
    if training_completed_at is not _UNSET:
        payload["training_completed_at"] = training_completed_at
    if equipment_audit_passed is not _UNSET:
        payload["equipment_audit_passed"] = equipment_audit_passed
    payload.update(overrides)
    return payload


def certify_payload(expected_applicator_version: int) -> Dict[str, Any]:
    return {"expected_applicator_version": expected_applicator_version}


def project_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "project_name": "Harbor Bridge Recoat",
        "owner_name": "Port Authority",
        "jurisdiction_code": DEFAULT_JURISDICTION,
        "asset_type": "BRIDGE",
        "warranty_budget_cents": 1_000_000,
    }
    payload.update(overrides)
    return payload


def specification_payload(
    coating_system_id: str,
    application_method: str = DEFAULT_APPLICATION_METHOD,
    supersedes_specification_id: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "coating_system_id": coating_system_id,
        "application_method": application_method,
    }
    if supersedes_specification_id is not _UNSET:
        payload["supersedes_specification_id"] = supersedes_specification_id
    payload.update(overrides)
    return payload


def issue_payload(expected_project_version: int) -> Dict[str, Any]:
    return {"expected_project_version": expected_project_version}


def substitution_request_payload(
    proposed_coating_system_id: str,
    rationale: str = "lead-time advantage",
    max_review_rounds: Any = _UNSET,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "proposed_coating_system_id": proposed_coating_system_id,
        "rationale": rationale,
    }
    if max_review_rounds is not _UNSET:
        payload["max_review_rounds"] = max_review_rounds
    payload.update(overrides)
    return payload


def resubmit_payload(rationale: str = "added freight quote") -> Dict[str, Any]:
    return {"rationale": rationale}


def decide_payload(decision: str, decision_reason: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if decision_reason is not _UNSET:
        payload["decision_reason"] = decision_reason
    return payload


def work_order_payload(
    specification_id: str,
    applicator_id: str,
    asset_zone: str = "ZONE-1",
    window_start: str = DEFAULT_WINDOW_START,
    window_end: str = DEFAULT_WINDOW_END,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "specification_id": specification_id,
        "applicator_id": applicator_id,
        "asset_zone": asset_zone,
        "window_start": window_start,
        "window_end": window_end,
    }
    payload.update(overrides)
    return payload


def prep_inspection_payload(
    observed_prep_standard: str = DEFAULT_PREP_STANDARD,
    measured_profile_mils: float = 3.0,
    soluble_salt_ug_cm2: float = 5.0,
    ambient_dew_point_spread_c: float = 5.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observed_prep_standard": observed_prep_standard,
        "measured_profile_mils": measured_profile_mils,
        "soluble_salt_ug_cm2": soluble_salt_ug_cm2,
        "ambient_dew_point_spread_c": ambient_dew_point_spread_c,
    }
    payload.update(overrides)
    return payload


def application_payload(
    coat_number: int = 1,
    applied_at: str = DEFAULT_APPLIED_AT,
    thinner_pct_used: float = 0.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "coat_number": coat_number,
        "applied_at": applied_at,
        "thinner_pct_used": thinner_pct_used,
    }
    payload.update(overrides)
    return payload


def inspection_report_payload(
    spot_dft_readings_mils: Optional[List[float]] = None,
    adhesion_readings_psi: Optional[List[float]] = None,
    holiday_count: int = 0,
    tested_area_m2: float = 10.0,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "spot_dft_readings_mils": (
            list(spot_dft_readings_mils) if spot_dft_readings_mils is not None else list(PASSING_DFT_READINGS)
        ),
        "adhesion_readings_psi": (
            list(adhesion_readings_psi) if adhesion_readings_psi is not None else list(PASSING_ADHESION_READINGS)
        ),
        "holiday_count": holiday_count,
        "tested_area_m2": tested_area_m2,
    }
    payload.update(overrides)
    return payload


def warranty_payload(
    work_order_id: str,
    term_years: int = 5,
    exposure_cents: int = 80_000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "work_order_id": work_order_id,
        "term_years": term_years,
        "exposure_cents": exposure_cents,
    }
    payload.update(overrides)
    return payload


def claim_payload(
    defect_mode: str = "ADHESION_LOSS",
    evidence_notes: str = "blistering at weld seams",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "defect_mode": defect_mode,
        "evidence_notes": evidence_notes,
    }
    payload.update(overrides)
    return payload


def void_payload(void_reason: str = "applicator fraud documented in audit") -> Dict[str, Any]:
    return {"void_reason": void_reason}


def adjudicate_payload(outcome: str, adjudicated_fault_pct: Any = _UNSET) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"outcome": outcome}
    if adjudicated_fault_pct is not _UNSET:
        payload["adjudicated_fault_pct"] = adjudicated_fault_pct
    return payload
