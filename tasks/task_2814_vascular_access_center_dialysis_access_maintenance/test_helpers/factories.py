"""Payload factories: request bodies only, one per write endpoint.

Every factory returns a dict carrying exactly the fields the PRD declares as
client input for that operation, with valid defaults, and accepts keyword
overrides.  Monetary fields are emitted as integer cents and the three
measurement fields as JSON numbers with one decimal place, matching the declared
wire types.  Scalars the PRD requires to be unique (facility_code, mrn, npi,
room_code, lot_number) are drawn from a process-local counter so that
independent factory calls never collide.
"""

import itertools
from typing import Any, Dict, Optional

_SEQ = itertools.count(1)


def next_seq() -> int:
    return next(_SEQ)


def unique_facility_code(prefix: str = "FAC") -> str:
    return f"{prefix}{next_seq():04d}"


def unique_mrn(prefix: str = "MRN") -> str:
    return f"{prefix}{next_seq():06d}"


def unique_npi() -> str:
    """Ten digits, unique per process."""
    return f"{9000000000 + next_seq()}"


def unique_room_code(prefix: str = "RM") -> str:
    return f"{prefix}{next_seq():04d}"


def unique_lot_number(prefix: str = "LOT") -> str:
    return f"{prefix}{next_seq():06d}"


# ─── Reference data ───────────────────────────────────────────────────────────

def dialysis_facility_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": f"Riverside Dialysis Center {next_seq()}",
        "facility_code": unique_facility_code(),
    }
    payload.update(overrides)
    return payload


def patient_payload(dialysis_facility_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "mrn": unique_mrn(),
        "full_name": f"Patient {next_seq()}",
        "dialysis_facility_id": dialysis_facility_id,
        "dialysis_modality": "IN_CENTER_HD",
        "payer_program": "FEE_FOR_SERVICE",
    }
    payload.update(overrides)
    return payload


def clinician_payload(clinician_role: str = "INTERVENTIONALIST", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": f"Dr Clinician {next_seq()}",
        "clinician_role": clinician_role,
        "npi": unique_npi(),
    }
    payload.update(overrides)
    return payload


def sedation_rn_payload(**overrides: Any) -> Dict[str, Any]:
    """A sedation nurse credentialed for moderate sedation well past the clock."""
    payload = clinician_payload(
        clinician_role="SEDATION_RN",
        moderate_sedation_credentialed=True,
        credential_expires_on="2027-12-31",
        max_concurrent_sedation_cases=2,
    )
    payload.update(overrides)
    return payload


def procedure_room_payload(**overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "room_code": unique_room_code(),
        "room_type": "ANGIO_SUITE",
    }
    payload.update(overrides)
    return payload


def device_lot_payload(device_type: str = "BALLOON", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "device_type": device_type,
        "catalog_code": f"CAT-{device_type}-{next_seq():04d}",
        "lot_number": unique_lot_number(),
        "expires_on": "2027-06-30",
        "received_quantity": 10,
        "unit_cost_cents": 12500,
    }
    payload.update(overrides)
    return payload


def quarantine_payload(quarantine_reason: str = "Manufacturer recall notice", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"quarantine_reason": quarantine_reason}
    payload.update(overrides)
    return payload


# ─── Accesses and surveillance ────────────────────────────────────────────────

def vascular_access_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "access_type": "AVF",
        "laterality": "LEFT",
        "site": "FOREARM",
        "placed_on": "2026-06-20",
    }
    payload.update(overrides)
    return payload


def catheter_access_payload(patient_id: str, **overrides: Any) -> Dict[str, Any]:
    payload = vascular_access_payload(
        patient_id,
        access_type="TUNNELED_CATHETER",
        site="INTERNAL_JUGULAR",
        laterality="RIGHT",
    )
    payload.update(overrides)
    return payload


def access_status_payload(to_status: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"to_status": to_status}
    payload.update(overrides)
    return payload


def surveillance_reading_payload(
    access_id: str,
    reported_by_facility_id: str,
    reading_at: str,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "access_id": access_id,
        "reported_by_facility_id": reported_by_facility_id,
        "reading_at": reading_at,
        "access_flow_ml_min": 900,
        "venous_pressure_mmhg": 120,
        "recirculation_pct": 5.0,
        "kind": "ROUTINE",
    }
    payload.update(overrides)
    return payload


# ─── Referrals ────────────────────────────────────────────────────────────────

def referral_payload(access_id: str, referring_facility_id: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "access_id": access_id,
        "referring_facility_id": referring_facility_id,
        "suspected_problem": "STENOSIS",
        "clinical_narrative": "Rising venous pressures and prolonged bleeding after needle removal.",
    }
    payload.update(overrides)
    return payload


def request_info_payload(info_request_note: str = "Please attach the most recent flow trend.", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"info_request_note": info_request_note}
    payload.update(overrides)
    return payload


def resubmit_payload(clinical_narrative: str = "Flow trend attached; access remains difficult to cannulate.", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"clinical_narrative": clinical_narrative}
    payload.update(overrides)
    return payload


def decline_payload(decline_reason: str = "Patient transferred to another centre.", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decline_reason": decline_reason}
    payload.update(overrides)
    return payload


def missed_treatments_payload(missed_treatment_count: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"missed_treatment_count": missed_treatment_count}
    payload.update(overrides)
    return payload


# ─── Booking and the room flow ────────────────────────────────────────────────

def procedure_payload(
    referral_id: str,
    room_id: str,
    primary_operator_id: str,
    scheduled_start: str,
    scheduled_end: str,
    expected_referral_version: int,
    sedation_level: str = "NONE",
    sedation_rn_id: Optional[str] = None,
    procedure_type: str = "ANGIOPLASTY",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "referral_id": referral_id,
        "room_id": room_id,
        "primary_operator_id": primary_operator_id,
        "procedure_type": procedure_type,
        "sedation_level": sedation_level,
        "scheduled_start": scheduled_start,
        "scheduled_end": scheduled_end,
        "expected_referral_version": expected_referral_version,
    }
    if sedation_rn_id is not None:
        payload["sedation_rn_id"] = sedation_rn_id
    payload.update(overrides)
    return payload


def cancel_payload(cancel_note: str = "Patient requested a later date.", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"cancel_note": cancel_note}
    payload.update(overrides)
    return payload


def device_usage_payload(
    device_lot_id: str, quantity: int, expected_device_lot_version: int, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "device_lot_id": device_lot_id,
        "quantity": quantity,
        "expected_device_lot_version": expected_device_lot_version,
    }
    payload.update(overrides)
    return payload


def device_allocation_payload(device_type: str, quantity: int, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"device_type": device_type, "quantity": quantity}
    payload.update(overrides)
    return payload


def recovery_payload(sedation_end_at: str, **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"sedation_end_at": sedation_end_at}
    payload.update(overrides)
    return payload


def recovery_observation_payload(
    observed_at: str, aldrete_score: int = 9, on_room_air: bool = True, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "observed_at": observed_at,
        "aldrete_score": aldrete_score,
        "on_room_air": on_room_air,
    }
    payload.update(overrides)
    return payload


def abort_payload(abort_reason: str = "Vasospasm; unable to cross the lesion safely.", **overrides: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"abort_reason": abort_reason}
    payload.update(overrides)
    return payload


# ─── Revenue cycle ────────────────────────────────────────────────────────────

def procedure_code_payload(
    hcpcs_code: str,
    code_family: str,
    base_allowed_cents: int,
    rank: int,
    modifier: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hcpcs_code": hcpcs_code,
        "code_family": code_family,
        "base_allowed_cents": base_allowed_cents,
        "rank": rank,
    }
    if modifier is not None:
        payload["modifier"] = modifier
    payload.update(overrides)
    return payload


def attest_payload(
    supporting_reading_id: str,
    medical_necessity_statement: str = "Recurrent stenosis with declining flow; angioplasty medically necessary.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "medical_necessity_statement": medical_necessity_statement,
        "supporting_reading_id": supporting_reading_id,
    }
    payload.update(overrides)
    return payload


def deny_payload(
    denial_reason: str = "DOCUMENTATION", denial_code: str = "CO-16", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"denial_reason": denial_reason, "denial_code": denial_code}
    payload.update(overrides)
    return payload


# ─── Conversion planning and infection surveillance ───────────────────────────

def conversion_plan_payload(
    patient_id: str,
    from_access_id: str,
    expected_access_version: int,
    target_access_type: str = "AVF",
    target_conversion_date: str = "2026-09-15",
    target_access_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "from_access_id": from_access_id,
        "target_access_type": target_access_type,
        "target_conversion_date": target_conversion_date,
        "expected_access_version": expected_access_version,
    }
    if target_access_id is not None:
        payload["target_access_id"] = target_access_id
    payload.update(overrides)
    return payload


def maturation_check_payload(
    diameter_mm: float = 6.0,
    flow_ml_min: int = 600,
    depth_mm: float = 6.0,
    **overrides: Any,
) -> Dict[str, Any]:
    """The three ultrasound measurements; diameter and depth carry one decimal."""
    payload: Dict[str, Any] = {
        "diameter_mm": diameter_mm,
        "flow_ml_min": flow_ml_min,
        "depth_mm": depth_mm,
    }
    payload.update(overrides)
    return payload


def infection_event_payload(
    procedure_id: str,
    onset_at: str,
    event_type: str = "ACCESS_SITE_INFECTION",
    organism: str = "Staphylococcus aureus",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "procedure_id": procedure_id,
        "event_type": event_type,
        "organism": organism,
        "onset_at": onset_at,
    }
    payload.update(overrides)
    return payload
