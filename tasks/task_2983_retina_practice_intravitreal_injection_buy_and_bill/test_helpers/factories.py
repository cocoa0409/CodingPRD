"""
Request-payload factories.

Each factory returns a plain dict carrying exactly the fields the contract
declares for that request, with sane defaults, and merges ``**overrides`` last so
a test can vary one field without restating the rest.  Every required field is a
named keyword argument, so no factory ever supplies the same key twice.

Money is always an integer count of cents.  Instants are always full ISO-8601 UTC
instants; the only date-shaped inputs in this contract are the authorization
``effective_date`` and the assistance-enrollment window, which the narrative also
describes as instants, so those too are sent as instants.
"""

from typing import Any, Dict, List, Optional


def _merge(payload: Dict[str, Any], overrides: Dict[str, Any]) -> Dict[str, Any]:
    """Apply overrides, dropping any key whose override value is ``None``-by-request."""
    payload.update(overrides)
    return payload


# --------------------------------------------------------------------------
# Logical clock
# --------------------------------------------------------------------------


def clock_payload(current_utc: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"current_utc": current_utc}, overrides)


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


def payer_payload(
    *,
    name: str,
    payer_type: str = "COMMERCIAL",
    coinsurance_rate: float = 0.2,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Payer registration.  ``pa_required``, ``biosimilar_preference`` and
    ``appeal_window_days`` are omitted so their declared defaults apply unless a
    test overrides them; ``federal_program`` is never sent because it is derived.
    """
    return _merge(
        {"name": name, "payer_type": payer_type, "coinsurance_rate": coinsurance_rate},
        overrides,
    )


def drug_payload(
    *,
    brand_name: str,
    hcpcs_code: str,
    vial_fill_ml: float,
    label_dose_ml: float,
    mg_per_ml: float,
    billing_unit_mg: float,
    asp_cents_per_billing_unit: int,
    min_interval_days: int,
    max_interval_days: int,
    vial_type: str = "SINGLE_DOSE",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "brand_name": brand_name,
            "hcpcs_code": hcpcs_code,
            "vial_type": vial_type,
            "vial_fill_ml": vial_fill_ml,
            "label_dose_ml": label_dose_ml,
            "mg_per_ml": mg_per_ml,
            "billing_unit_mg": billing_unit_mg,
            "asp_cents_per_billing_unit": asp_cents_per_billing_unit,
            "min_interval_days": min_interval_days,
            "max_interval_days": max_interval_days,
        },
        overrides,
    )


def biosimilar_payload(
    *, reference_drug_id: str, **kwargs: Any
) -> Dict[str, Any]:
    """A biosimilar is a drug payload declaring its lineage; no key is passed twice."""
    payload = drug_payload(**kwargs)
    payload["is_biosimilar"] = True
    payload["reference_drug_id"] = reference_drug_id
    return payload


def policy_payload(
    *,
    payer_id: str,
    drug_id: str,
    drug_allowed_cents_per_billing_unit: int,
    admin_allowed_cents: int,
    coverage_tier: str = "PREFERRED",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Coverage policy.  ``wastage_reimbursed``, ``pa_required``, ``pa_validity_days``,
    ``pa_max_injections``, ``step_therapy_prerequisite_drug_id`` and
    ``required_prior_failures`` are left to their declared defaults unless given.
    """
    return _merge(
        {
            "payer_id": payer_id,
            "drug_id": drug_id,
            "coverage_tier": coverage_tier,
            "drug_allowed_cents_per_billing_unit": drug_allowed_cents_per_billing_unit,
            "admin_allowed_cents": admin_allowed_cents,
        },
        overrides,
    )


def patient_payload(
    *,
    mrn: str,
    full_name: str,
    payer_id: str,
    member_id: str,
    contact_point: str = "patient@example.test",
    **overrides: Any,
) -> Dict[str, Any]:
    """Patient registration; ``notification_channel`` defaults to ``PHONE``."""
    return _merge(
        {
            "mrn": mrn,
            "full_name": full_name,
            "payer_id": payer_id,
            "member_id": member_id,
            "contact_point": contact_point,
        },
        overrides,
    )


def clinician_payload(
    *,
    full_name: str,
    npi: str,
    credential: str = "MD",
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Clinician registration; ``injection_privilege`` defaults to true and
    ``max_injections_per_day`` to 12.
    """
    return _merge({"full_name": full_name, "npi": npi, "credential": credential}, overrides)


def clinician_suspend_payload(
    *, suspension_reason: str = "Credentialing lapse", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"suspension_reason": suspension_reason}, overrides)


# --------------------------------------------------------------------------
# Imaging
# --------------------------------------------------------------------------


def imaging_payload(
    *,
    patient_id: str,
    eye: str,
    study_datetime: str,
    central_subfield_thickness_um: int,
    intraretinal_fluid: bool = False,
    subretinal_fluid: bool = False,
    new_hemorrhage: bool = False,
    va_letter_score: int = 65,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "eye": eye,
            "study_datetime": study_datetime,
            "central_subfield_thickness_um": central_subfield_thickness_um,
            "intraretinal_fluid": intraretinal_fluid,
            "subretinal_fluid": subretinal_fluid,
            "new_hemorrhage": new_hemorrhage,
            "va_letter_score": va_letter_score,
        },
        overrides,
    )


# --------------------------------------------------------------------------
# Treatment plans
# --------------------------------------------------------------------------


def plan_payload(
    *, patient_id: str, drug_id: str, eye: str, **overrides: Any
) -> Dict[str, Any]:
    """Plan creation; ``loading_doses_required`` defaults to 3."""
    return _merge({"patient_id": patient_id, "drug_id": drug_id, "eye": eye}, overrides)


def plan_activate_payload(*, baseline_imaging_study_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"baseline_imaging_study_id": baseline_imaging_study_id}, overrides)


def plan_suspend_payload(
    *, suspension_reason: str = "PATIENT_REQUEST", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"suspension_reason": suspension_reason}, overrides)


def plan_discontinue_payload(
    *, discontinuation_reason: str = "Patient moved out of area", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"discontinuation_reason": discontinuation_reason}, overrides)


# --------------------------------------------------------------------------
# Inventory
# --------------------------------------------------------------------------


def lot_payload(
    *,
    drug_id: str,
    lot_number: str,
    expiration_date: str,
    received_date: str,
    unit_acquisition_cost_cents: int,
    vials_received: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "drug_id": drug_id,
            "lot_number": lot_number,
            "expiration_date": expiration_date,
            "received_date": received_date,
            "unit_acquisition_cost_cents": unit_acquisition_cost_cents,
            "vials_received": vials_received,
        },
        overrides,
    )


def quarantine_payload(
    *, quarantine_reason: str = "Suspected cold-chain excursion", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"quarantine_reason": quarantine_reason}, overrides)


def exposure_params(*, basis: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"basis": basis}, overrides)


# --------------------------------------------------------------------------
# Prior authorizations
# --------------------------------------------------------------------------


def authorization_payload(
    *, treatment_plan_id: str, expected_treatment_plan_version: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "treatment_plan_id": treatment_plan_id,
            "expected_treatment_plan_version": expected_treatment_plan_version,
        },
        overrides,
    )


def authorization_submit_payload(
    *, clinical_justification: str = "Persistent exudative activity on OCT", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"clinical_justification": clinical_justification}, overrides)


def approval_decision_payload(
    *,
    auth_number: str,
    approved_injections: int,
    effective_date: str,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "decision": "APPROVED",
            "auth_number": auth_number,
            "approved_injections": approved_injections,
            "effective_date": effective_date,
        },
        overrides,
    )


def denial_decision_payload(*, denial_reason: str = "STEP_THERAPY", **overrides: Any) -> Dict[str, Any]:
    return _merge({"decision": "DENIED", "denial_reason": denial_reason}, overrides)


def info_requested_decision_payload(
    *, information_requested: str = "Send the prior OCT series", **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {"decision": "INFO_REQUESTED", "information_requested": information_requested},
        overrides,
    )


def authorization_appeal_payload(
    *, appeal_basis: str = "Two documented prerequisite failures on file", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"appeal_basis": appeal_basis}, overrides)


# --------------------------------------------------------------------------
# Injection encounters
# --------------------------------------------------------------------------


def encounter_payload(
    *,
    treatment_plan_id: str,
    imaging_study_id: str,
    encounter_datetime: str,
    expected_treatment_plan_version: int,
    **overrides: Any,
) -> Dict[str, Any]:
    """
    Encounter creation.  ``medical_necessity_override`` and ``override_reason``
    are omitted unless a test supplies them, so the declared default of false
    applies.
    """
    return _merge(
        {
            "treatment_plan_id": treatment_plan_id,
            "imaging_study_id": imaging_study_id,
            "encounter_datetime": encounter_datetime,
            "expected_treatment_plan_version": expected_treatment_plan_version,
        },
        overrides,
    )


def document_payload(
    *,
    administered_dose_ml: float,
    injection_site_prep_confirmed: bool = True,
    post_injection_iop_mmhg: int = 16,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "administered_dose_ml": administered_dose_ml,
            "injection_site_prep_confirmed": injection_site_prep_confirmed,
            "post_injection_iop_mmhg": post_injection_iop_mmhg,
        },
        overrides,
    )


def attest_payload(*, attested_wasted_ml: float, **overrides: Any) -> Dict[str, Any]:
    return _merge({"attested_wasted_ml": attested_wasted_ml}, overrides)


def void_payload(*, void_reason: str = "Booking made in error", **overrides: Any) -> Dict[str, Any]:
    return _merge({"void_reason": void_reason}, overrides)


# --------------------------------------------------------------------------
# Claims
# --------------------------------------------------------------------------


def claim_payload(*, injection_encounter_id: str, **overrides: Any) -> Dict[str, Any]:
    return _merge({"injection_encounter_id": injection_encounter_id}, overrides)


def drug_line_paid_payload(
    *,
    drug_allowed_cents: int,
    drug_paid_cents: int,
    wastage_allowed_cents: int,
    wastage_paid_cents: int,
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "drug_line_outcome": "PAID",
            "drug_allowed_cents": drug_allowed_cents,
            "drug_paid_cents": drug_paid_cents,
            "wastage_allowed_cents": wastage_allowed_cents,
            "wastage_paid_cents": wastage_paid_cents,
        },
        overrides,
    )


def drug_line_denied_payload(*, denial_code: str = "NOT_COVERED", **overrides: Any) -> Dict[str, Any]:
    return _merge({"drug_line_outcome": "DENIED", "denial_code": denial_code}, overrides)


def drug_line_written_off_payload(**overrides: Any) -> Dict[str, Any]:
    return _merge({"drug_line_outcome": "WRITTEN_OFF"}, overrides)


def admin_line_paid_payload(
    *, admin_allowed_cents: int, admin_paid_cents: int, **overrides: Any
) -> Dict[str, Any]:
    return _merge(
        {
            "admin_line_outcome": "PAID",
            "admin_allowed_cents": admin_allowed_cents,
            "admin_paid_cents": admin_paid_cents,
        },
        overrides,
    )


def admin_line_denied_payload(
    *, denial_code: str = "NOT_COVERED", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"admin_line_outcome": "DENIED", "denial_code": denial_code}, overrides)


def claim_appeal_payload(
    *, appeal_basis: str = "Wastage is payable under the JW policy", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"appeal_basis": appeal_basis}, overrides)


# --------------------------------------------------------------------------
# Assistance enrollments
# --------------------------------------------------------------------------


def enrollment_payload(
    *,
    patient_id: str,
    annual_benefit_cents: int,
    per_encounter_cap_cents: int,
    effective_date: str,
    expiration_date: str,
    program_type: str = "INDEPENDENT_FOUNDATION",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {
            "patient_id": patient_id,
            "program_type": program_type,
            "annual_benefit_cents": annual_benefit_cents,
            "per_encounter_cap_cents": per_encounter_cap_cents,
            "effective_date": effective_date,
            "expiration_date": expiration_date,
        },
        overrides,
    )


def enrollment_terminate_payload(
    *, termination_reason: str = "Patient withdrew from the programme", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"termination_reason": termination_reason}, overrides)


# --------------------------------------------------------------------------
# Adverse events
# --------------------------------------------------------------------------


def adverse_event_payload(
    *,
    injection_encounter_id: str,
    event_type: str,
    onset_datetime: str,
    severity: str,
    **overrides: Any,
) -> Dict[str, Any]:
    """``culture_result`` is omitted so its declared default of ``PENDING`` applies."""
    return _merge(
        {
            "injection_encounter_id": injection_encounter_id,
            "event_type": event_type,
            "onset_datetime": onset_datetime,
            "severity": severity,
        },
        overrides,
    )


def adjudication_payload(
    *, outcome: str, adjudication_note: str = "Reviewed against the operative record", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"outcome": outcome, "adjudication_note": adjudication_note}, overrides)


# --------------------------------------------------------------------------
# Lot recalls and notifications
# --------------------------------------------------------------------------


def recall_payload(
    *,
    drug_lot_id: str,
    recall_class: str,
    reason: str = "Manufacturer sterility deviation",
    **overrides: Any,
) -> Dict[str, Any]:
    return _merge(
        {"drug_lot_id": drug_lot_id, "recall_class": recall_class, "reason": reason}, overrides
    )


def ship_return_payload(*, carrier_reference: str = "CARRIER-REF-0001", **overrides: Any) -> Dict[str, Any]:
    return _merge({"carrier_reference": carrier_reference}, overrides)


def reconcile_credit_payload(*, credit_received_cents: int, **overrides: Any) -> Dict[str, Any]:
    return _merge({"credit_received_cents": credit_received_cents}, overrides)


def recall_close_payload(
    *, closure_note: str = "All exposed patients resolved", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"closure_note": closure_note}, overrides)


def mark_unreachable_payload(
    *, attempt_note: str = "Three calls and a letter, no reply", **overrides: Any
) -> Dict[str, Any]:
    return _merge({"attempt_note": attempt_note}, overrides)


# --------------------------------------------------------------------------
# Pagination helpers
# --------------------------------------------------------------------------


def page_params(
    limit: Optional[int] = None, offset: Optional[int] = None, **filters: Any
) -> Dict[str, Any]:
    """Build a list-endpoint query string, omitting anything not supplied."""
    params: Dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if offset is not None:
        params["offset"] = offset
    params.update({key: value for key, value in filters.items() if value is not None})
    return params


def modifiers(*values: str) -> List[str]:
    """Readability shim for an expected modifier array."""
    return list(values)
