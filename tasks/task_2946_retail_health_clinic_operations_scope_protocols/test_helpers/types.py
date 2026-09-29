"""TypedDict shapes for every resource the PRD declares.

All thirteen resource types carry the four common fields `id`, `created_at`,
`updated_at` and `version`, so every entity dict below extends CommonFields.
Money is always an integer count of cents; instants are ISO 8601 UTC strings.
"""
from typing import Any, Dict, List, Optional, TypedDict


class CommonFields(TypedDict):
    id: str
    created_at: str
    updated_at: str
    version: int


class StateRule(CommonFields):
    state_code: str
    chart_review_sample_pct: int
    review_deadline_hours: int
    collaborating_physician_required: bool
    min_independent_practice_age_months: int
    controlled_rx_allowed: bool
    max_supervised_clinicians_per_physician: int


class Protocol(CommonFields):
    complaint_code: str
    min_age_months: int
    max_age_months: int
    base_price_cents: int
    acuity_tier: int
    red_flag_codes: List[str]
    max_temp_c: float
    max_heart_rate_bpm: int
    min_spo2_pct: int
    requires_cosign: bool
    allowed_state_codes: List[str]


class Clinic(CommonFields):
    name: str
    state_code: str
    min_clinicians_required: int
    appointment_slots_per_hour: int
    walk_in_queue_capacity: int
    on_duty_clinician_count: int
    open_status: str
    waiting_count: int
    posted_wait_minutes: int
    last_realized_wait_minutes: Optional[int]


class Physician(CommonFields):
    full_name: str
    licensed_state_codes: List[str]
    max_supervised_clinicians: int
    status: str
    current_supervised_count: int


class Clinician(CommonFields):
    full_name: str
    credential: str
    license_state_code: str
    home_clinic_id: str
    supervising_physician_id: str
    float_eligible: bool
    scope_hold: bool
    active_assignment_count: int


class Patient(CommonFields):
    full_name: str
    date_of_birth: str
    payer_name: Optional[str]
    member_id: Optional[str]
    pcp_name: Optional[str]
    pcp_direct_address: Optional[str]
    pcp_accepts_electronic_summary: bool
    pcp_consent_on_file: bool
    active_therapy_classes: List[str]
    active_therapy_class_count: int
    outstanding_balance_cents: int


class StaffingAssignment(CommonFields):
    clinic_id: str
    clinician_id: str
    covers_assignment_id: Optional[str]
    pinned_supervising_physician_id: Optional[str]
    role_kind: str
    starts_at: str
    ends_at: str
    status: str


class QueueEntry(CommonFields):
    clinic_id: str
    patient_id: str
    kind: str
    complaint_code: str
    acuity_tier: int
    scheduled_at: Optional[str]
    arrived_at: Optional[str]
    called_at: Optional[str]
    priority_score: int
    realized_wait_minutes: Optional[int]
    status: str


class Visit(CommonFields):
    clinic_id: str
    patient_id: str
    queue_entry_id: str
    protocol_id: str
    clinician_id: Optional[str]
    complaint_code: str
    patient_age_months_at_visit: int
    clinical_status: str
    billing_status: str
    self_pay: bool
    coverage_status: str
    copay_cents: Optional[int]
    coinsurance_pct: Optional[float]
    quoted_price_cents: Optional[int]
    final_price_cents: Optional[int]
    patient_responsibility_cents: Optional[int]
    payer_responsibility_cents: Optional[int]
    services_rendered: List[str]
    referral_required: bool


class Assessment(CommonFields):
    visit_id: str
    protocol_id: str
    cosigned_by_physician_id: Optional[str]
    temp_c: float
    heart_rate_bpm: int
    spo2_pct: int
    red_flag_codes: List[str]
    referral_destination: Optional[str]
    referral_reason_code: Optional[str]
    cosigned_at: Optional[str]
    status: str


class Prescription(CommonFields):
    visit_id: str
    patient_id: str
    prescriber_clinician_id: str
    supersedes_prescription_id: Optional[str]
    drug_name: str
    therapy_class: str
    days_supply: int
    pharmacy_npi: str
    routed_at: Optional[str]
    status: str


class ChartReview(CommonFields):
    visit_id: str
    assessment_id: str
    reviewer_physician_id: str
    sampled_reason: str
    due_at: str
    changes_requested_count: int
    outcome: Optional[str]
    status: str


class VisitSummary(CommonFields):
    visit_id: str
    destination_kind: str
    destination_address: Optional[str]
    includes_referral: bool
    attempt_count: int
    last_error_code: Optional[str]
    sent_at: Optional[str]
    status: str


# ---------------------------------------------------------------------------
# Non-entity response payloads
# ---------------------------------------------------------------------------

class ClockAdvanceResult(TypedDict):
    current_utc: str
    activated_assignment_ids: List[str]
    completed_assignment_ids: List[str]
    abandoned_queue_entry_ids: List[str]
    affected_clinic_ids: List[str]


class SamplingRunResult(TypedDict):
    sampled_count: int
    mandatory_count: int
    random_count: int
    chart_review_ids: List[str]


Payload = Dict[str, Any]
Headers = Dict[str, str]
