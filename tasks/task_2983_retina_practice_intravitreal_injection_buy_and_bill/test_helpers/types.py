"""
Structural type aliases for the entities of the contract under test.

These are documentation-grade TypedDicts: they name the fields the tests read so
that a typo in a field name is visible at the call site.  ``total=False`` is used
throughout because a representation only carries the fields declared for it, and
several fields are nullable.
"""

from typing import Any, Dict, List, Optional, TypedDict

# A decoded response ``data`` payload of unknown shape.
Json = Dict[str, Any]
JsonList = List[Dict[str, Any]]

# Request headers as sent on the wire.
Headers = Dict[str, str]


class Payer(TypedDict, total=False):
    id: str
    name: str
    payer_type: str
    coinsurance_rate: float
    pa_required: bool
    biosimilar_preference: str
    appeal_window_days: int
    federal_program: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Drug(TypedDict, total=False):
    id: str
    brand_name: str
    hcpcs_code: str
    vial_type: str
    vial_fill_ml: float
    label_dose_ml: float
    mg_per_ml: float
    billing_unit_mg: float
    asp_cents_per_billing_unit: int
    min_interval_days: int
    max_interval_days: int
    is_biosimilar: bool
    reference_drug_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PayerDrugPolicy(TypedDict, total=False):
    id: str
    payer_id: str
    drug_id: str
    coverage_tier: str
    drug_allowed_cents_per_billing_unit: int
    admin_allowed_cents: int
    wastage_reimbursed: bool
    pa_required: bool
    pa_validity_days: int
    pa_max_injections: int
    step_therapy_prerequisite_drug_id: Optional[str]
    required_prior_failures: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict, total=False):
    id: str
    mrn: str
    full_name: str
    payer_id: str
    member_id: str
    notification_channel: str
    contact_point: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Clinician(TypedDict, total=False):
    id: str
    full_name: str
    npi: str
    credential: str
    injection_privilege: bool
    max_injections_per_day: int
    status: str
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ImagingStudy(TypedDict, total=False):
    """Immutable observation: carries only ``id`` and ``created_at`` as system fields."""

    id: str
    patient_id: str
    eye: str
    study_datetime: str
    central_subfield_thickness_um: int
    intraretinal_fluid: bool
    subretinal_fluid: bool
    new_hemorrhage: bool
    va_letter_score: int
    disease_activity: str
    interpreted_by_clinician_id: str
    created_at: str


class TreatmentPlan(TypedDict, total=False):
    id: str
    patient_id: str
    drug_id: str
    eye: str
    loading_doses_required: int
    status: str
    baseline_imaging_study_id: Optional[str]
    current_interval_days: Optional[int]
    next_due_date: Optional[str]
    injections_administered: int
    consecutive_quiescent_visits: int
    last_encounter_id: Optional[str]
    suspension_reason: Optional[str]
    discontinuation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DrugLot(TypedDict, total=False):
    id: str
    drug_id: str
    lot_number: str
    expiration_date: str
    received_date: str
    unit_acquisition_cost_cents: int
    vials_received: int
    status: str
    quarantine_reason: Optional[str]
    vials_on_hand: int
    vials_reserved: int
    vials_administered: int
    vials_quarantined: int
    vials_returned: int
    vials_expired: int
    carrying_cost_accrued_cents: int
    last_swept_at: Optional[str]
    related_endophthalmitis_count: int
    created_at: str
    updated_at: str
    version: int


class Vial(TypedDict, total=False):
    id: str
    drug_lot_id: str
    serial_number: str
    status: str
    reserved_for_encounter_id: Optional[str]
    reserved_at: Optional[str]
    administered_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotExposure(TypedDict, total=False):
    drug_lot_id: str
    basis: str
    days_held: int
    unconsumed_vials: int
    unconsumed_value_cents: int
    exposure_cents: int
    projected_burn_vials: int
    at_risk_vials: int


class SweepSummary(TypedDict, total=False):
    lots_swept: int
    lots_expired: int
    vials_expired: int
    carrying_cost_accrued_cents_total: int
    swept_at: str


class PriorAuthorization(TypedDict, total=False):
    id: str
    treatment_plan_id: str
    patient_id: str
    drug_id: str
    payer_id: str
    status: str
    injections_used: int
    submission_count: int
    step_therapy_failures_documented: int
    auth_number: Optional[str]
    approved_injections: Optional[int]
    effective_date: Optional[str]
    expiration_date: Optional[str]
    clinical_justification: Optional[str]
    information_requested: Optional[str]
    denial_reason: Optional[str]
    appeal_basis: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjectionEncounter(TypedDict, total=False):
    id: str
    treatment_plan_id: str
    patient_id: str
    eye: str
    imaging_study_id: str
    clinician_id: str
    encounter_datetime: str
    effective_drug_id: str
    substituted_from_drug_id: Optional[str]
    medical_necessity_override: bool
    override_reason: Optional[str]
    prior_authorization_id: Optional[str]
    vial_id: Optional[str]
    previous_encounter_id: Optional[str]
    interval_days_from_previous: Optional[int]
    administered_dose_ml: Optional[float]
    wasted_ml: Optional[float]
    administered_billing_units: Optional[int]
    wasted_billing_units: Optional[int]
    total_billed_billing_units: Optional[int]
    modifiers: Optional[List[str]]
    injection_site_prep_confirmed: Optional[bool]
    post_injection_iop_mmhg: Optional[int]
    attested_by_clinician_id: Optional[str]
    status: str
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    injection_encounter_id: str
    patient_id: str
    payer_id: str
    hcpcs_code: str
    modifiers: List[str]
    billed_billing_units: int
    administration_cpt_code: str
    drug_billed_cents: int
    wastage_billed_cents: int
    admin_billed_cents: int
    drug_allowed_cents: int
    wastage_allowed_cents: int
    admin_allowed_cents: int
    drug_paid_cents: int
    wastage_paid_cents: int
    admin_paid_cents: int
    total_allowed_cents: int
    coinsurance_cents: int
    assistance_enrollment_id: Optional[str]
    foundation_applied_cents: int
    patient_responsibility_cents: int
    practice_writeoff_cents: int
    standard_drug_cost_cents: int
    provisional_margin_cents: int
    actual_acquisition_cost_cents: Optional[int]
    realized_margin_cents: Optional[int]
    denial_code: Optional[str]
    appeal_basis: Optional[str]
    drug_line_status: str
    admin_line_status: str
    created_at: str
    updated_at: str
    version: int


class AssistanceEnrollment(TypedDict, total=False):
    id: str
    patient_id: str
    program_type: str
    annual_benefit_cents: int
    per_encounter_cap_cents: int
    benefit_used_cents: int
    effective_date: str
    expiration_date: str
    status: str
    termination_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseEvent(TypedDict, total=False):
    id: str
    injection_encounter_id: str
    patient_id: str
    source_drug_lot_id: Optional[str]
    event_type: str
    severity: str
    culture_result: str
    onset_datetime: str
    days_post_injection: int
    reportable: bool
    fda_report_due_date: Optional[str]
    status: str
    reported_by_clinician_id: str
    adjudicated_by_clinician_id: Optional[str]
    adjudication_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LotRecall(TypedDict, total=False):
    id: str
    drug_lot_id: str
    recall_class: str
    reason: str
    initiated_by_user_id: str
    notification_deadline_date: str
    status: str
    notifications_required: int
    notifications_acknowledged: int
    notifications_unreachable: int
    vials_returned_count: int
    credit_expected_cents: Optional[int]
    credit_received_cents: Optional[int]
    carrier_reference: Optional[str]
    closed_by_user_id: Optional[str]
    closure_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RecallNotification(TypedDict, total=False):
    id: str
    lot_recall_id: str
    patient_id: str
    injection_encounter_id: str
    channel: str
    status: str
    sent_at: Optional[str]
    acknowledged_at: Optional[str]
    attempt_note: Optional[str]
    created_at: str
    updated_at: str
    version: int
