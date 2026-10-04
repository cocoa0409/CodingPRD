"""Domain types for the Pediatric Research Hospital API.

Status enums, the role enum, and entity TypedDicts. Every entity in this program
declares common fields enabled, so every TypedDict carries id, created_at,
updated_at and version.
"""
from enum import Enum
from typing import TypedDict, Optional, List, Any


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    PROTOCOL_COORDINATOR = "ProtocolCoordinator"
    IRB_REVIEWER = "IRBReviewer"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    HOUSING_COORDINATOR = "HousingCoordinator"
    PATIENT_SUPPORT_OFFICER = "PatientSupportOfficer"
    AFFILIATE_CLINIC_COORDINATOR = "AffiliateClinicCoordinator"
    SURVIVORSHIP_COORDINATOR = "SurvivorshipCoordinator"
    ANY = "Any"


class ProtocolStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    HELD = "HELD"
    CLOSED = "CLOSED"


class ReferralStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"
    ARRIVED = "ARRIVED"


class EnrollmentStatus(str, Enum):
    PENDING_CONSENT = "PENDING_CONSENT"
    ENROLLED = "ENROLLED"
    ACTIVE_TREATMENT = "ACTIVE_TREATMENT"
    ON_HIATUS = "ON_HIATUS"
    SURVIVORSHIP = "SURVIVORSHIP"
    WITHDRAWN = "WITHDRAWN"
    COMPLETED = "COMPLETED"


class HousingAssignmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"
    CANCELLED = "CANCELLED"


class PledgeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SETTLED_FINAL = "SETTLED_FINAL"
    VOIDED = "VOIDED"


class TravelStatus(str, Enum):
    REQUESTED = "REQUESTED"
    CONFIRMED = "CONFIRMED"
    DISBURSED = "DISBURSED"
    CANCELLED = "CANCELLED"


class MilestoneStatus(str, Enum):
    PENDING = "PENDING"
    DUE = "DUE"
    EXECUTED = "EXECUTED"
    MISSED = "MISSED"


class HoldStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    ESCALATED = "ESCALATED"


class HousingTier(str, Enum):
    ON_CAMPUS = "ON_CAMPUS"
    PARTNER_CLASS_A = "PARTNER_CLASS_A"
    PARTNER_CLASS_B = "PARTNER_CLASS_B"
    PARTNER_CLASS_C = "PARTNER_CLASS_C"


class AppliedTier(str, Enum):
    PENDING = "PENDING"
    ON_CAMPUS = "ON_CAMPUS"
    PARTNER_CLASS_A = "PARTNER_CLASS_A"
    PARTNER_CLASS_B = "PARTNER_CLASS_B"
    PARTNER_CLASS_C = "PARTNER_CLASS_C"
    DECLINED = "DECLINED"


class Turnaround(str, Enum):
    """Named ticks for the logical clock. Every computation is measured against it."""

    STARTUP_DEFAULT = "2026-09-01T00:00:00Z"


# ─── Entity TypedDicts (every entity declares common fields enabled) ──────────


class ResearchFund(TypedDict):
    id: str
    fund_code: str
    fiscal_year: int
    fundraising_raised_cents: int
    research_allocation_pct: float
    federal_grant_cents: int
    patient_support_balance_cents: int
    research_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class ClinicalProtocol(TypedDict):
    id: str
    fund_id: str
    protocol_code: str
    disease_group: str
    age_min_years: int
    age_max_years: int
    required_stage: str
    protocol_budget_cents: int
    reserved_cents: int
    committed_cents: int
    available_cents: int
    capacity: int
    enrolled_count: int
    age_tier: str
    mental_capacity_floor: int
    is_protocol_held: bool
    is_budget_saturated: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict):
    id: str
    protocol_id: str
    child_name: str
    child_date_of_birth: str
    disease_group: str
    disease_stage: str
    household_state_code: str
    traveling_family_member_count: int
    expected_treatment_days: int
    is_immunosuppressed: bool
    has_febrile_neutropenia_risk: bool
    is_self_pay: bool
    insurance_coverage_cents: int
    one_to_one_care_capability_codes: List[str]
    traveling_one_to_one_codes: List[str]
    eligibility_alias: str
    computed_age_years: int
    screening_fee_cents: int
    selector_window_days: int
    reservation_basis_cents: int
    applied_tier: str
    status: str
    enrollment_id: Optional[str]
    decline_reason: Optional[str]
    decline_occurred_at: Optional[str]
    reopened_referral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict):
    id: str
    referral_id: str
    protocol_id: str
    consent_signer: str
    assent_state: str
    is_assent_required: bool
    guardian_consent_signed_at: Optional[str]
    child_assent_signed_at: Optional[str]
    status: str
    protocol_enrolled_count: int
    active_family_count: int
    created_at: str
    updated_at: str
    version: int


class FamilySupportPledge(TypedDict):
    id: str
    enrollment_id: str
    patient_support_budget_cents: int
    covered_days: int
    provisional_settled_cents: int
    final_settled_cents: int
    billing_permitted_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingAssignment(TypedDict):
    id: str
    enrollment_id: str
    housing_facility_id: str
    start_at: str
    end_at: str
    assigned_tier: str
    nightly_rate_cents: int
    billed_nights: int
    housing_cost_cents: int
    is_active_occupancy: bool
    vacated_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class HousingFacility(TypedDict):
    id: str
    facility_code: str
    name: str
    tier: str
    is_on_campus: bool
    is_partner_site: bool
    immunosuppression_capable: bool
    is_step_down_capable: bool
    total_beds: int
    buffer_beds: int
    active_beds_committed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TravelArrangement(TypedDict):
    id: str
    enrollment_id: str
    mode: str
    traveler_count: int
    departure_at: str
    return_at: Optional[str]
    is_required_travel: bool
    trip_reason: str
    placed_coverages: List[dict]
    family_day_units: int
    transport_cost_cents: int
    fund_patient_support_balance_cents: int
    fund_research_balance_cents: int
    eligibility_confirmed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AffiliateClinic(TypedDict):
    id: str
    clinic_code: str
    name: str
    state_code: str
    is_active: bool
    created_at: str
    updated_at: str
    version: int


class AffiliationAgreement(TypedDict):
    id: str
    clinic_id: str
    protocol_id: str
    protocol_version: str
    effective_start_at: str
    is_cross_state: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtocolMilestone(TypedDict):
    id: str
    enrollment_id: str
    milestone_sequence: int
    description: str
    requires_main_campus: bool
    target_at: str
    executed_at: Optional[str]
    deferred_from_milestone_id: Optional[str]
    affiliate_clinic_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SurvivorshipStudy(TypedDict):
    id: str
    protocol_id: str
    study_code: str
    follow_up_interval_months: int
    min_years_after_completion: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SurvivorshipEnrollment(TypedDict):
    id: str
    study_id: str
    enrollment_id: str
    completed_treatment_at: str
    adult_transition_age_years: int
    next_due_at: str
    is_adult_follow_up: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SurvivorshipFollowUp(TypedDict):
    id: str
    survivorship_enrollment_id: str
    completed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FamilySupportService(TypedDict):
    id: str
    fund_id: str
    service_code: str
    display_name: str
    base_allowance_cents: int
    is_stimulation_eligible: bool
    stimulation_rate: float
    stimulation_cap_cents: int
    created_at: str
    updated_at: str
    version: int


class FamilyServiceLedger(TypedDict):
    id: str
    family_support_service_id: str
    ledger_epoch: int
    accumulated_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SiblingSupportService(TypedDict):
    id: str
    enrollment_id: str
    sibling_alias: str
    service_type: str
    delivery_window_start_at: str
    delivery_window_end_at: str
    sessions_delivered: int
    has_reached_monthly_limit: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProtocolHold(TypedDict):
    id: str
    protocol_id: str
    protocol_version: int
    hold_reason: str
    initiated_at: str
    released_at: Optional[str]
    status: str
    is_review_lock: bool
    created_at: str
    updated_at: str
    version: int


class AnyDict(TypedDict, total=False):
    """Loose shape for responses whose full field set is not asserted."""

    id: str
    status: str
    created_at: str
    updated_at: str
    version: int
    data: Any