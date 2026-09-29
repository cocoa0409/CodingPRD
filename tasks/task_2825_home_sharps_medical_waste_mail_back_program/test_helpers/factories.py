"""Payload factories: PRD-exact field names, sensible defaults, `**overrides`
for whatever a test needs to control.

Monetary values are always integer counts of cents (PRD 2.7) and are emitted as
JSON numbers. Calendar-date fields are `YYYY-MM-DD` strings and instant fields
are full ISO 8601 UTC instants (PRD 2.4).
"""

from typing import Any, Dict, List, Optional


def _merge(base: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides; a value of `None` in overrides is preserved (it is a
    meaningful payload value in this domain), while the sentinel string
    ``"__OMIT__"`` removes the key entirely."""
    merged = dict(base)
    merged.update(overrides)
    return {k: v for k, v in merged.items() if v != "__OMIT__"}


OMIT = "__OMIT__"


# --------------------------------------------------------------------------
# Program foundations (PRD 3.1)
# --------------------------------------------------------------------------
def state_rule_payload(
    state_code: str = "CA",
    household_sharps_classification: str = "CONDITIONALLY_EXEMPT",
    mail_back_permitted: bool = True,
    max_container_volume_liters: float = 30.3,
    certificate_retention_years: int = 3,
    requires_state_manifest: bool = False,
    notification_deadline_hours: int = 72,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "state_code": state_code,
            "household_sharps_classification": household_sharps_classification,
            "mail_back_permitted": mail_back_permitted,
            "max_container_volume_liters": max_container_volume_liters,
            "certificate_retention_years": certificate_retention_years,
            "requires_state_manifest": requires_state_manifest,
            "notification_deadline_hours": notification_deadline_hours,
        },
        overrides,
    )


def packaging_spec_payload(
    spec_code: str = "PS-A",
    un_specification_code: str = "UN 4G/X7.5/S/26",
    postal_service: str = "USPS_PARCEL_SELECT_MAILBACK",
    hazard_class: str = "UN3291_SHARPS_ONLY",
    max_gross_weight_grams: int = 6800,
    allowed_container_sizes: Optional[List[str]] = None,
    requires_absorbent: bool = False,
    status: str = "ACTIVE",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "spec_code": spec_code,
            "un_specification_code": un_specification_code,
            "postal_service": postal_service,
            "hazard_class": hazard_class,
            "max_gross_weight_grams": max_gross_weight_grams,
            "allowed_container_sizes": (
                allowed_container_sizes
                if allowed_container_sizes is not None
                else ["ONE_QUART", "TWO_GALLON", "THREE_GALLON"]
            ),
            "requires_absorbent": requires_absorbent,
            "status": status,
        },
        overrides,
    )


def treatment_facility_payload(
    state_rule_id: str,
    name: str = "Bay Area Sharps Treatment",
    permit_number: str = "CA-TF-0001",
    accepted_hazard_classes: Optional[List[str]] = None,
    daily_intake_capacity_units: int = 1000,
    status: str = "ACTIVE",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "name": name,
            "state_rule_id": state_rule_id,
            "permit_number": permit_number,
            "accepted_hazard_classes": (
                accepted_hazard_classes
                if accepted_hazard_classes is not None
                else ["UN3291_SHARPS_ONLY", "UN3291_REGULATED_MEDICAL_WASTE"]
            ),
            "daily_intake_capacity_units": daily_intake_capacity_units,
            "status": status,
        },
        overrides,
    )


def status_action_payload(action: str, reason: Optional[str] = None, **overrides: Any):
    payload: Dict[str, Any] = {"action": action}
    if reason is not None:
        payload["reason"] = reason
    return _merge(payload, overrides)


# --------------------------------------------------------------------------
# Sponsorship and funding (PRD 3.2)
# --------------------------------------------------------------------------
def sponsor_payload(
    legal_name: str = "NovaPen Devices Inc",
    sponsor_type: str = "MANUFACTURER",
    contact_email: str = "programs@novapen.example",
    status: str = "ACTIVE",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "legal_name": legal_name,
            "sponsor_type": sponsor_type,
            "contact_email": contact_email,
            "status": status,
        },
        overrides,
    )


def sponsorship_program_payload(
    program_code: str = "NPD-2026",
    funding_ceiling_cents: int = 500000,
    per_kit_allowance_cents: int = 6000,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "program_code": program_code,
            "funding_ceiling_cents": funding_ceiling_cents,
            "per_kit_allowance_cents": per_kit_allowance_cents,
        },
        overrides,
    )


def funding_adjustment_payload(
    delta_cents: int,
    expected_program_version: int,
    memo: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "delta_cents": delta_cents,
        "expected_program_version": expected_program_version,
    }
    if memo is not None:
        payload["memo"] = memo
    return _merge(payload, overrides)


# --------------------------------------------------------------------------
# Patients and enrollments (PRD 3.3)
# --------------------------------------------------------------------------
def patient_payload(
    state_rule_id: str,
    full_name: str = "Dana Reyes",
    therapy_type: str = "INSULIN_PEN_NEEDLES",
    weekly_sharps_count: int = 14,
    contact_email: str = "dana@example.com",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "full_name": full_name,
            "state_rule_id": state_rule_id,
            "therapy_type": therapy_type,
            "weekly_sharps_count": weekly_sharps_count,
            "contact_email": contact_email,
        },
        overrides,
    )


def eligibility_review_payload(
    decision: str = "APPROVE", note: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if note is not None:
        payload["note"] = note
    return _merge(payload, overrides)


def enrollment_payload(
    patient_id: str,
    sponsorship_program_id: str,
    cadence_days: int = 30,
    kits_authorized: int = 5,
    requested_container_size: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "patient_id": patient_id,
        "sponsorship_program_id": sponsorship_program_id,
        "cadence_days": cadence_days,
        "kits_authorized": kits_authorized,
    }
    if requested_container_size is not None:
        payload["requested_container_size"] = requested_container_size
    return _merge(payload, overrides)


def sponsor_decision_payload(
    decision: str = "APPROVE",
    sponsor_decision_note: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"decision": decision}
    if sponsor_decision_note is not None:
        payload["sponsor_decision_note"] = sponsor_decision_note
    return _merge(payload, overrides)


# --------------------------------------------------------------------------
# Kits and custody (PRD 3.4, 3.5)
# --------------------------------------------------------------------------
def kit_issuance_payload(
    expected_enrollment_version: int,
    container_size: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "expected_enrollment_version": expected_enrollment_version
    }
    if container_size is not None:
        payload["container_size"] = container_size
    return _merge(payload, overrides)


def seal_payload(
    fill_units: int = 69, sealed_gross_weight_grams: int = 1400, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "fill_units": fill_units,
            "sealed_gross_weight_grams": sealed_gross_weight_grams,
        },
        overrides,
    )


def kit_void_payload(
    void_reason: str = "patient changed therapy", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"void_reason": void_reason}, overrides)


# --------------------------------------------------------------------------
# Labels, shipments, screening (PRD 3.6, 3.7)
# --------------------------------------------------------------------------
def return_label_payload(packaging_spec_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"packaging_spec_id": packaging_spec_id}, overrides)


def label_void_payload(
    void_reason: Optional[str] = "carrier rate change", **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if void_reason is not None:
        payload["void_reason"] = void_reason
    return _merge(payload, overrides)


def label_activation_payload(
    treatment_facility_id: str,
    scheduled_intake_date: str = "2026-08-10",
    declared_gross_weight_grams: int = 1400,
    state_manifest_number: Optional[str] = None,
    absorbent_declared: Optional[bool] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "treatment_facility_id": treatment_facility_id,
        "scheduled_intake_date": scheduled_intake_date,
        "declared_gross_weight_grams": declared_gross_weight_grams,
    }
    if state_manifest_number is not None:
        payload["state_manifest_number"] = state_manifest_number
    if absorbent_declared is not None:
        payload["absorbent_declared"] = absorbent_declared
    return _merge(payload, overrides)


def transport_event_payload(event_type: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"event_type": event_type}, overrides)


def conformance_screening_payload(
    outcome: str = "CONFORMING",
    observed_gross_weight_grams: int = 1520,
    reason_code: Optional[str] = None,
    **overrides: Any,
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "outcome": outcome,
        "observed_gross_weight_grams": observed_gross_weight_grams,
    }
    if reason_code is not None:
        payload["reason_code"] = reason_code
    return _merge(payload, overrides)


def notify_customer_payload(
    notification_channel: str = "EMAIL", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"notification_channel": notification_channel}, overrides)


def remediation_payload(remediation_action: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"remediation_action": remediation_action}, overrides)


# --------------------------------------------------------------------------
# Certification and auto-ship (PRD 3.8, 3.9)
# --------------------------------------------------------------------------
def destruction_certificate_payload(
    destroyed_units: int = 69, **overrides: Any
) -> Dict[str, Any]:
    return _merge({"destroyed_units": destroyed_units}, overrides)


def certificate_void_payload(
    void_reason: str = "wrong unit count recorded", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"void_reason": void_reason}, overrides)


def auto_ship_run_payload(
    as_of_date: Optional[str] = None, **overrides: Any
) -> Dict[str, Any]:
    payload: Dict[str, Any] = {}
    if as_of_date is not None:
        payload["as_of_date"] = as_of_date
    return _merge(payload, overrides)
