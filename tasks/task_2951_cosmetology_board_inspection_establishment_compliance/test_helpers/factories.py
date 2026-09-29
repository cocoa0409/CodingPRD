"""Payload factories.

Every factory returns only the fields the endpoint declares as input; computed,
system and derived fields are never sent.  Monetary values are whole-cent
integers, point/hour values are floats carried to two decimals, ``*_at`` fields
are full ISO 8601 UTC instants with three fractional digits, and ``*_on`` fields
are ISO calendar dates.
"""
from typing import Any, Dict, Optional

_COUNTER = {"n": 0}


def _next(prefix: str) -> str:
    _COUNTER["n"] += 1
    return f"{prefix}-{_COUNTER['n']:05d}"


def reset_counter() -> None:
    _COUNTER["n"] = 0


# --- Reference registries ----------------------------------------------------
def violation_code_payload(
    code: Optional[str] = None,
    category: str = "SANITATION",
    severity: str = "MINOR",
    base_points: float = 1.00,
    fine_cents_base: int = 10000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "code": code if code is not None else _next("VC"),
        "category": category,
        "severity": severity,
        "base_points": base_points,
        "fine_cents_base": fine_cents_base,
    }
    payload.update(overrides)
    return payload


def school_payload(
    name: Optional[str] = None,
    county_code: str = "AAA",
    required_clock_hours: float = 1600.00,
    accreditation_status: Optional[str] = None,
    apprenticeship_program_approved: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "name": name if name is not None else _next("School"),
        "county_code": county_code,
        "required_clock_hours": required_clock_hours,
    }
    if accreditation_status is not None:
        payload["accreditation_status"] = accreditation_status
    if apprenticeship_program_approved is not None:
        payload["apprenticeship_program_approved"] = apprenticeship_program_approved
    payload.update(overrides)
    return payload


# --- Practitioners, training and licensing -----------------------------------
def practitioner_payload(
    full_name: Optional[str] = None,
    license_type: str = "COSMETOLOGIST",
    school_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "full_name": full_name if full_name is not None else _next("Candidate"),
        "license_type": license_type,
    }
    if school_id is not None:
        payload["school_id"] = school_id
    payload.update(overrides)
    return payload


def training_record_payload(
    practitioner_id: str,
    credit_type: str = "SCHOOL_CLOCK_HOUR",
    hours: float = 8.00,
    performed_on: str = "2026-07-06",
    discipline: str = "THEORY",
    school_id: Optional[str] = None,
    sponsor_practitioner_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "practitioner_id": practitioner_id,
        "credit_type": credit_type,
        "hours": hours,
        "performed_on": performed_on,
        "discipline": discipline,
    }
    # PRD 2.9 pairing: school_id belongs to SCHOOL_CLOCK_HOUR only, and
    # sponsor_practitioner_id to APPRENTICE_HOUR only.
    if credit_type == "SCHOOL_CLOCK_HOUR":
        payload["school_id"] = school_id
        payload["sponsor_practitioner_id"] = None
    else:
        payload["school_id"] = None
        payload["sponsor_practitioner_id"] = sponsor_practitioner_id
    payload.update(overrides)
    return payload


def license_action_payload(
    action: str,
    effective_at: Optional[str] = None,
    reason: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"action": action}
    if effective_at is not None:
        payload["effective_at"] = effective_at
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# --- Establishments and build-out --------------------------------------------
def establishment_payload(
    legal_name: Optional[str] = None,
    establishment_type: str = "SALON",
    county_code: str = "AAA",
    station_capacity: int = 5,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "legal_name": legal_name if legal_name is not None else _next("Salon"),
        "establishment_type": establishment_type,
        "county_code": county_code,
        "station_capacity": station_capacity,
    }
    payload.update(overrides)
    return payload


def workstation_payload(
    station_number: int = 1,
    station_type: str = "STYLING_CHAIR",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "station_number": station_number,
        "station_type": station_type,
    }
    payload.update(overrides)
    return payload


def posting_payload(
    posted_practitioner_id: Optional[str], **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"posted_practitioner_id": posted_practitioner_id}
    payload.update(overrides)
    return payload


def booth_rental_payload(
    workstation_id: str,
    practitioner_id: str,
    expected_workstation_version: int,
    rental_type: str = "BOOTH_RENTER_INDEPENDENT_CONTRACTOR",
    term_start_at: str = "2026-08-01T00:00:00.000Z",
    term_end_at: Optional[str] = None,
    monthly_rent_cents: int = 50000,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "workstation_id": workstation_id,
        "practitioner_id": practitioner_id,
        "rental_type": rental_type,
        "term_start_at": term_start_at,
        "monthly_rent_cents": monthly_rent_cents,
        "expected_workstation_version": expected_workstation_version,
    }
    if term_end_at is not None:
        payload["term_end_at"] = term_end_at
    payload.update(overrides)
    return payload


def termination_payload(
    terminated_at: Optional[str] = None, reason: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if terminated_at is not None:
        payload["terminated_at"] = terminated_at
    if reason is not None:
        payload["reason"] = reason
    payload.update(overrides)
    return payload


# --- Sanitation --------------------------------------------------------------
def sanitation_log_payload(
    workstation_id: str,
    log_type: str = "IMPLEMENT_DISINFECTION",
    performed_at: str = "2026-08-01T09:00:00.000Z",
    contact_minutes: float = 10.00,
    disinfectant_epa_reg_number: str = "EPA-1234-56",
    implement_batch_count: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "workstation_id": workstation_id,
        "log_type": log_type,
        "performed_at": performed_at,
        "contact_minutes": contact_minutes,
        "disinfectant_epa_reg_number": disinfectant_epa_reg_number,
    }
    # PRD 2.9 pairing: implement_batch_count is required for
    # IMPLEMENT_DISINFECTION and must be null for every foot-spa protocol.
    if log_type == "IMPLEMENT_DISINFECTION":
        payload["implement_batch_count"] = (
            implement_batch_count if implement_batch_count is not None else 12
        )
    else:
        payload["implement_batch_count"] = None
    payload.update(overrides)
    return payload


# --- Inspections -------------------------------------------------------------
def inspection_payload(
    establishment_id: str,
    inspector_user_id: str,
    inspection_type: str = "ROUTINE",
    window_start_at: str = "2026-08-01T09:00:00.000Z",
    window_end_at: str = "2026-08-01T17:00:00.000Z",
    complaint_reference: Optional[str] = None,
    reinspection_of_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "inspection_type": inspection_type,
        "inspector_user_id": inspector_user_id,
        "window_start_at": window_start_at,
        "window_end_at": window_end_at,
    }
    # PRD 2.9 pairing: complaint_reference only on COMPLAINT_DRIVEN,
    # reinspection_of_id only on REINSPECTION.
    if inspection_type == "COMPLAINT_DRIVEN":
        payload["complaint_reference"] = (
            complaint_reference if complaint_reference is not None else _next("DOCKET")
        )
    if inspection_type == "REINSPECTION":
        payload["reinspection_of_id"] = reinspection_of_id
    payload.update(overrides)
    return payload


def finding_payload(
    violation_code_id: str,
    observed_count: int = 1,
    corrected_on_site: bool = False,
    attributed_practitioner_id: Optional[str] = None,
    workstation_id: Optional[str] = None,
    note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "violation_code_id": violation_code_id,
        "observed_count": observed_count,
        "corrected_on_site": corrected_on_site,
    }
    if attributed_practitioner_id is not None:
        payload["attributed_practitioner_id"] = attributed_practitioner_id
    if workstation_id is not None:
        payload["workstation_id"] = workstation_id
    if note is not None:
        payload["note"] = note
    payload.update(overrides)
    return payload


def hazard_declaration_payload(
    hazard_violation_finding_id: str,
    narrative: str = "Foot spa visibly colonised; basin removed from service.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "hazard_violation_finding_id": hazard_violation_finding_id,
        "narrative": narrative,
    }
    payload.update(overrides)
    return payload


def hazard_clearance_payload(
    clearing_reinspection_id: str, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"clearing_reinspection_id": clearing_reinspection_id}
    payload.update(overrides)
    return payload


# --- Citations, hearings, payments -------------------------------------------
def citation_payload(
    inspection_id: str,
    expected_inspection_version: int,
    subject_type: str = "ESTABLISHMENT",
    subject_practitioner_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "inspection_id": inspection_id,
        "subject_type": subject_type,
        "expected_inspection_version": expected_inspection_version,
    }
    # PRD 2.9 pairing: subject_practitioner_id required for PRACTITIONER,
    # forbidden for ESTABLISHMENT.
    if subject_type == "PRACTITIONER":
        payload["subject_practitioner_id"] = subject_practitioner_id
    payload.update(overrides)
    return payload


def contest_payload(
    grounds: str = "The cited implements were disinfected before the visit.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"grounds": grounds}
    payload.update(overrides)
    return payload


def hearing_payload(
    presiding_officer_user_id: str,
    scheduled_at: str = "2026-08-10T10:00:00.000Z",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "presiding_officer_user_id": presiding_officer_user_id,
        "scheduled_at": scheduled_at,
    }
    payload.update(overrides)
    return payload


def decision_payload(
    decision: str = "AFFIRMED",
    rationale: str = "The record supports the finding as written.",
    amended_fine_cents: Optional[int] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision, "rationale": rationale}
    # PRD 2.9 pairing: amended_fine_cents required for AMENDED, forbidden
    # otherwise.
    if decision == "AMENDED":
        payload["amended_fine_cents"] = amended_fine_cents
    payload.update(overrides)
    return payload


def payment_payload(
    amount_cents: int, payer_reference: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"amount_cents": amount_cents}
    if payer_reference is not None:
        payload["payer_reference"] = payer_reference
    payload.update(overrides)
    return payload


# --- Infection incidents ------------------------------------------------------
def infection_incident_payload(
    establishment_id: str,
    case_count: int = 1,
    onset_date: str = "2026-07-28",
    narrative: str = "Three clients reported folliculitis after pedicures.",
    suspected_practitioner_id: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "establishment_id": establishment_id,
        "case_count": case_count,
        "onset_date": onset_date,
        "narrative": narrative,
    }
    if suspected_practitioner_id is not None:
        payload["suspected_practitioner_id"] = suspected_practitioner_id
    payload.update(overrides)
    return payload


def notification_payload(
    health_authority_reference: Optional[str] = None,
    notified_at: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "health_authority_reference": (
            health_authority_reference
            if health_authority_reference is not None
            else _next("HA-REF")
        )
    }
    if notified_at is not None:
        payload["notified_at"] = notified_at
    payload.update(overrides)
    return payload


def resolution_payload(
    resolution: str = "SUBSTANTIATED",
    findings_summary: str = "Implement reuse confirmed by the field investigation.",
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "resolution": resolution,
        "findings_summary": findings_summary,
    }
    payload.update(overrides)
    return payload
