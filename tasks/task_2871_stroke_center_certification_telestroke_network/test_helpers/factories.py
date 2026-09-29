"""Payload factories - one per write endpoint, caller-supplied input fields only.

Numeric fields are emitted as JSON numbers and every datetime as a full ISO 8601
UTC instant, per PRD 2.4 and PRD 2.6.
"""
import itertools
from typing import Optional

_SEQ = itertools.count(1)


def _next() -> int:
    return next(_SEQ)


DEFAULTS = {
    "HUB_NAME": "Metro Hub Primary Stroke Center",
    "SPOKE_NAME": "Riverside Community Spoke",
    "THROMBECTOMY_NAME": "Harbor Thrombectomy Center",
    "STATE_CODE": "CA",
    "EMS_REGION_CODE": "CA-R1",
    "NEUROLOGIST_NAME": "Dr Alice Marchetti",
    "PATIENT_REF": "P-TEST-001",
    "IMAGING_MODALITY": "CT_NON_CONTRAST",
    "MAX_CONCURRENT_CONSULTS": 3,
    "EFFECTIVE_FROM": "2026-08-01T00:00:00Z",
    "EFFECTIVE_UNTIL": "2027-08-01T00:00:00Z",
    "CREDENTIAL_EXPIRES_AT": "2027-08-01T00:00:00Z",
    "NIHSS_SCORE": 12,
    "THROMBOLYTIC_DOSE_MG": 65.0,
    "TRANSPORT_ETA_MINUTES": 35,
}


# ---------------------------------------------------------------------------
# Stroke centers (PRD 3.1)
# ---------------------------------------------------------------------------
def register_center_payload(**overrides) -> dict:
    payload = {
        "name": f"{DEFAULTS['SPOKE_NAME']} {_next()}",
        "facility_type": "SPOKE",
        "state_code": DEFAULTS["STATE_CODE"],
        "ems_region_code": DEFAULTS["EMS_REGION_CODE"],
    }
    payload.update(overrides)
    return payload


def hub_center_payload(**overrides) -> dict:
    return register_center_payload(
        name=f"{DEFAULTS['HUB_NAME']} {_next()}", facility_type="HUB_PRIMARY", **overrides
    )


def spoke_center_payload(**overrides) -> dict:
    return register_center_payload(
        name=f"{DEFAULTS['SPOKE_NAME']} {_next()}", facility_type="SPOKE", **overrides
    )


def thrombectomy_center_payload(**overrides) -> dict:
    return register_center_payload(
        name=f"{DEFAULTS['THROMBECTOMY_NAME']} {_next()}",
        facility_type="THROMBECTOMY_CAPABLE",
        **overrides,
    )


def update_center_payload(**overrides) -> dict:
    payload = {"name": f"Renamed Facility {_next()}"}
    payload.update(overrides)
    return payload


def readiness_attestation_payload(component: str = "CT_SCANNER", result: str = "PASS", **overrides) -> dict:
    payload = {"component": component, "result": result}
    payload.update(overrides)
    return payload


def suspend_center_payload(**overrides) -> dict:
    payload = {"suspension_reason": "certification body onsite findings"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Spoke agreements (PRD 3.1)
# ---------------------------------------------------------------------------
def spoke_agreement_payload(hub_center_id: str, spoke_center_id: str, **overrides) -> dict:
    payload = {
        "hub_center_id": hub_center_id,
        "spoke_center_id": spoke_center_id,
        "coverage_tier": "TIER_1_FULL",
        "max_concurrent_consults": DEFAULTS["MAX_CONCURRENT_CONSULTS"],
        "effective_from": DEFAULTS["EFFECTIVE_FROM"],
        "effective_until": DEFAULTS["EFFECTIVE_UNTIL"],
    }
    payload.update(overrides)
    return payload


def suspend_agreement_payload(**overrides) -> dict:
    payload = {"suspension_reason": "hub staffing shortfall"}
    payload.update(overrides)
    return payload


def proxy_credential_payload(neurologist_id: str, **overrides) -> dict:
    payload = {
        "neurologist_id": neurologist_id,
        "privilege_scope": "CONSULT_AND_THROMBOLYSIS",
        "expires_at": DEFAULTS["CREDENTIAL_EXPIRES_AT"],
    }
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Neurologists (PRD 3.1)
# ---------------------------------------------------------------------------
def neurologist_payload(home_center_id: str, **overrides) -> dict:
    payload = {
        "full_name": f"{DEFAULTS['NEUROLOGIST_NAME']} {_next()}",
        "home_center_id": home_center_id,
        "licensed_state_codes": [DEFAULTS["STATE_CODE"]],
        "board_certified": True,
        "roster_rank": 10,
        "concurrent_consult_limit": 2,
    }
    payload.update(overrides)
    return payload


def on_call_state_payload(on_call_state: str, **overrides) -> dict:
    payload = {"on_call_state": on_call_state}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Code stroke cases (PRD 3.2)
# ---------------------------------------------------------------------------
def code_stroke_payload(
    center_id: str,
    door_at: str,
    lkw_precision: str = "EXACT",
    last_known_well_at: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {
        "center_id": center_id,
        "patient_ref": f"P-TEST-{_next():04d}",
        "door_at": door_at,
        "lkw_precision": lkw_precision,
        "arrival_mode": "EMS",
    }
    if last_known_well_at is not None:
        payload["last_known_well_at"] = last_known_well_at
    payload.update(overrides)
    return payload


def imaging_complete_payload(**overrides) -> dict:
    payload = {"imaging_modality": DEFAULTS["IMAGING_MODALITY"]}
    payload.update(overrides)
    return payload


def administer_thrombolytic_payload(**overrides) -> dict:
    payload = {
        "thrombolytic_agent": "ALTEPLASE",
        "thrombolytic_dose_mg": DEFAULTS["THROMBOLYTIC_DOSE_MG"],
    }
    payload.update(overrides)
    return payload


def abort_case_payload(**overrides) -> dict:
    payload = {"abort_reason": "stroke mimic identified at bedside"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Telestroke consults (PRD 3.3, 3.4)
# ---------------------------------------------------------------------------
def consult_request_payload(
    case_id: str,
    agreement_id: str,
    expected_case_version: int,
    requested_privilege_scope: str = "CONSULT_AND_THROMBOLYSIS",
    **overrides,
) -> dict:
    payload = {
        "case_id": case_id,
        "agreement_id": agreement_id,
        "requested_privilege_scope": requested_privilege_scope,
        "expected_case_version": expected_case_version,
    }
    payload.update(overrides)
    return payload


def decline_consult_payload(**overrides) -> dict:
    payload = {"last_decline_reason": "already covering another facility"}
    payload.update(overrides)
    return payload


def video_session_payload(
    started_at: str,
    ended_at: str,
    video_quality: str = "HD",
    disconnect_count: int = 0,
    **overrides,
) -> dict:
    payload = {
        "started_at": started_at,
        "ended_at": ended_at,
        "video_quality": video_quality,
        "disconnect_count": disconnect_count,
    }
    payload.update(overrides)
    return payload


def complete_consult_payload(**overrides) -> dict:
    payload = {"recommendation": "THROMBOLYSIS", "nihss_score": DEFAULTS["NIHSS_SCORE"]}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Thrombolytic checklists (PRD 3.5)
# ---------------------------------------------------------------------------
def checklist_payload(case_id: str, **overrides) -> dict:
    payload = {"case_id": case_id}
    payload.update(overrides)
    return payload


def inclusion_item_payload(item_code: str, **overrides) -> dict:
    payload = {"item_code": item_code}
    payload.update(overrides)
    return payload


def contraindication_payload(
    code: str = "CI_RECENT_SURGERY",
    severity: str = "RELATIVE",
    documented_evidence: Optional[str] = None,
    **overrides,
) -> dict:
    payload = {"code": code, "severity": severity}
    if documented_evidence is not None:
        payload["documented_evidence"] = documented_evidence
    payload.update(overrides)
    return payload


def determine_payload(**overrides) -> dict:
    payload = {}
    payload.update(overrides)
    return payload


def amend_checklist_payload(**overrides) -> dict:
    payload = {"last_amendment_note": "blood pressure record corrected on review"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Transfer decisions (PRD 3.7)
# ---------------------------------------------------------------------------
def transfer_payload(
    case_id: str,
    destination_center_id: str,
    mode: str = "TRANSFER_ONLY",
    transport_eta_minutes: int = DEFAULTS["TRANSPORT_ETA_MINUTES"],
    **overrides,
) -> dict:
    payload = {
        "case_id": case_id,
        "destination_center_id": destination_center_id,
        "mode": mode,
        "transport_eta_minutes": transport_eta_minutes,
    }
    payload.update(overrides)
    return payload


def decline_transfer_payload(**overrides) -> dict:
    payload = {"decline_reason": "no interventional suite available"}
    payload.update(overrides)
    return payload


def handoff_payload(handoff_packet_items, **overrides) -> dict:
    payload = {"handoff_packet_items": list(handoff_packet_items)}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Protocol deviations (PRD 3.8)
# ---------------------------------------------------------------------------
def deviation_payload(
    case_id: str,
    deviation_type: str = "DTN_EXCEEDED",
    severity: str = "MAJOR",
    narrative: str = "needle time missed the sixty minute target",
    **overrides,
) -> dict:
    payload = {
        "case_id": case_id,
        "deviation_type": deviation_type,
        "severity": severity,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def return_for_info_payload(**overrides) -> dict:
    payload = {"info_request": "supply the medication administration record"}
    payload.update(overrides)
    return payload


def resubmit_deviation_payload(**overrides) -> dict:
    payload = {"additional_info": "medication administration record attached"}
    payload.update(overrides)
    return payload


def debrief_payload(**overrides) -> dict:
    payload = {"debrief_summary": "multidisciplinary debrief held with the ED team"}
    payload.update(overrides)
    return payload


def decide_deviation_payload(outcome: str = "SUBSTANTIATE", **overrides) -> dict:
    payload = {"outcome": outcome}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Quality measure abstractions (PRD 3.9)
# ---------------------------------------------------------------------------
def abstraction_payload(case_id: str, measure_code: str = "STK_DTN_60", **overrides) -> dict:
    payload = {"case_id": case_id, "measure_code": measure_code}
    payload.update(overrides)
    return payload


def finalize_abstraction_payload(**overrides) -> dict:
    payload = {"attestation_note": "chart abstracted and attested against the record"}
    payload.update(overrides)
    return payload


def retract_abstraction_payload(**overrides) -> dict:
    payload = {"retraction_reason": "wrong case abstracted"}
    payload.update(overrides)
    return payload


# ---------------------------------------------------------------------------
# Certification reports (PRD 3.9)
# ---------------------------------------------------------------------------
def certification_report_payload(
    center_id: str,
    period_start: str,
    period_end: str,
    expected_center_version: int,
    **overrides,
) -> dict:
    payload = {
        "center_id": center_id,
        "period_start": period_start,
        "period_end": period_end,
        "expected_center_version": expected_center_version,
    }
    payload.update(overrides)
    return payload


def decide_report_payload(**overrides) -> dict:
    payload = {"reviewer_note": "reviewed against the submitted composite"}
    payload.update(overrides)
    return payload
