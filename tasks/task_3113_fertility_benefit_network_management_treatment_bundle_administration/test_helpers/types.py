"""Domain types for the Fertility Benefit Network API: status enums, role enum,
and one TypedDict per top-level resource.

Every resource in this API is created with the full set of common fields
(`id`, `created_at`, `updated_at`, `version`); none is immutable after creation.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --- Role enum -----------------------------------------------------------------

class UserRole(str, Enum):
    MEMBER = "Member"
    CARE_ADVOCATE = "CareAdvocate"
    CLINICAL_REVIEWER = "ClinicalReviewer"
    CLINIC_COORDINATOR = "ClinicCoordinator"
    SPECIALTY_PHARMACIST = "SpecialtyPharmacist"
    CLAIMS_PROCESSOR = "ClaimsProcessor"
    CLAIMS_REVIEWER = "ClaimsReviewer"
    NETWORK_MANAGER = "NetworkManager"
    PLAN_ADMINISTRATOR = "PlanAdministrator"


# --- Status enums --------------------------------------------------------------

class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundingType(str, Enum):
    SELF_FUNDED = "SELF_FUNDED"
    FULLY_INSURED = "FULLY_INSURED"


class AllocationMethod(str, Enum):
    SEQUENTIAL_BUNDLE = "SEQUENTIAL_BUNDLE"
    CONCURRENT_BUNDLE = "CONCURRENT_BUNDLE"


class BundleType(str, Enum):
    DIAGNOSTIC_IUI = "DIAGNOSTIC_IUI"
    IVF_RETRIEVAL_TRANSFER = "IVF_RETRIEVAL_TRANSFER"
    PRESERVATION = "PRESERVATION"
    DONOR_EGG = "DONOR_EGG"
    DONOR_SPERM = "DONOR_SPERM"
    SURROGACY = "SURROGACY"
    MEDICATION = "MEDICATION"


class BundleStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXHAUSTED = "EXHAUSTED"


class AdvocateStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AT_CAPACITY = "AT_CAPACITY"
    INACTIVE = "INACTIVE"


class MemberStatus(str, Enum):
    INTAKE = "INTAKE"
    CARE_ACTIVE = "CARE_ACTIVE"
    CARE_COMPLETE = "CARE_COMPLETE"


class RequiredTrack(str, Enum):
    STANDARD_IVF = "STANDARD_IVF"
    DIAGNOSTIC_IUI = "DIAGNOSTIC_IUI"
    PRESERVATION = "PRESERVATION"
    DONOR_EGG = "DONOR_EGG"
    DONOR_SPERM = "DONOR_SPERM"
    SURROGACY = "SURROGACY"


class PathwayType(str, Enum):
    STANDARD_IVF = "STANDARD_IVF"
    DIAGNOSTIC_IUI = "DIAGNOSTIC_IUI"
    PRESERVATION = "PRESERVATION"
    DONOR_EGG = "DONOR_EGG"
    DONOR_SPERM = "DONOR_SPERM"
    SURROGACY = "SURROGACY"


class PathwaySelected(str, Enum):
    NONE = "NONE"
    PRESERVATION = "PRESERVATION"
    DONOR_EGG = "DONOR_EGG"
    DONOR_SPERM = "DONOR_SPERM"
    SURROGACY = "SURROGACY"


class NetworkTier(str, Enum):
    PREFERRED = "PREFERRED"
    STANDARD = "STANDARD"
    OUT_OF_NETWORK = "OUT_OF_NETWORK"


class ClinicStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    CONTRACTED = "CONTRACTED"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ContractingStatus(str, Enum):
    IN_REVIEW = "IN_REVIEW"
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    TERMINATED = "TERMINATED"


class PlanStatus(str, Enum):
    PLAN_DRAFT = "PLAN_DRAFT"
    CLINIC_SELECTED = "CLINIC_SELECTED"
    AUTHORIZATION_PENDING = "AUTHORIZATION_PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    PLANNING_REVISION = "PLANNING_REVISION"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class ReviewStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"


class ConsumptionStatus(str, Enum):
    UNCONSUMED = "UNCONSUMED"
    PARTIALLY_CONSUMED = "PARTIALLY_CONSUMED"
    EXHAUSTED = "EXHAUSTED"


class CycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    STIMULATION = "STIMULATION"
    RETRIEVAL = "RETRIEVAL"
    FERTILIZATION = "FERTILIZATION"
    TRANSFER = "TRANSFER"
    OUTCOME_PENDING = "OUTCOME_PENDING"
    OUTCOME_RECORDED = "OUTCOME_RECORDED"
    CANCELLED = "CANCELLED"


class ConsumptionMarker(str, Enum):
    UNCONSUMED = "UNCONSUMED"
    CONSUMED = "CONSUMED"


class PharmacyStatus(str, Enum):
    PRESCRIBED = "PRESCRIBED"
    DISPENSING = "DISPENSING"
    DISPENSED = "DISPENSED"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class PathwayStatus(str, Enum):
    DRAFT = "DRAFT"
    CLINICAL_REVIEW = "CLINICAL_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class CarrierKind(str, Enum):
    MEMBER = "MEMBER"
    GESTATIONAL_CARRIER = "GESTATIONAL_CARRIER"
    CUSTODIAN = "CUSTODIAN"


class RouteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ROUTED = "ROUTED"
    RETIRED = "RETIRED"
    WITHDRAWN = "WITHDRAWN"


class ServiceCategory(str, Enum):
    CLINIC_BUNDLE = "CLINIC_BUNDLE"
    MEDICATION = "MEDICATION"
    LAB = "LAB"
    STORAGE = "STORAGE"
    DONOR_MATERIAL = "DONOR_MATERIAL"
    SURROGACY_FEE = "SURROGACY_FEE"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PENDED = "PENDED"
    ADJUDICATED = "ADJUDICATED"
    DENIED = "DENIED"
    APPEALED = "APPEALED"
    PAID = "PAID"
    REVERSED = "REVERSED"


class OutcomeStatus(str, Enum):
    RECORDED = "RECORDED"
    AMENDED = "AMENDED"
    VOIDED = "VOIDED"


# --- Entity TypedDicts ---------------------------------------------------------

class EmployerAccount(TypedDict):
    id: str
    employer_name: str
    plan_year: int
    funding_type: str
    allocation_method: str
    enrollment_limit: int
    account_status: str
    active_member_count: int
    entitlement_count: int
    created_at: str
    updated_at: str
    version: int


class BundleEntitlement(TypedDict):
    id: str
    employer_account_id: str
    bundle_type: str
    lifetime_max_cycles: int
    max_cycles_per_year: int
    max_transfers_per_cycle: int
    pharmacy_pool_cents: int
    copay_max: bool
    effective_from: str
    effective_to: str
    cycles_consumed: int
    cycles_committed: int
    cycles_remaining: int
    pharmacy_consumed_cents: int
    pharmacy_remaining_cents: int
    bundle_status: str
    created_at: str
    updated_at: str
    version: int


class CareAdvocate(TypedDict):
    id: str
    full_name: str
    states_licensed: List[str]
    specializations: List[str]
    caseload_limit: int
    credentials_expire_on: str
    current_caseload: int
    assignments_completed: int
    advocate_status: str
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    employer_account_id: str
    external_ref: str
    full_name: str
    state_code: str
    required_track: str
    member_status: str
    care_advocate_id: Optional[str]
    clinic_id: Optional[str]
    pathway_selected: str
    completed_cycles: int
    live_births_recorded: int
    intake_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Clinic(TypedDict):
    id: str
    legal_name: str
    npi: str
    state_code: str
    network_tier: str
    min_live_birth_rate_bps: int
    max_multiple_birth_rate_bps: int
    required_quality_report_count: int
    maturity_report_threshold: int
    bundles_offered: List[str]
    live_birth_rate_bps: int
    multiple_birth_rate_bps: int
    composite_quality_bps: int
    cycles_reported: int
    clinic_status: str
    created_at: str
    updated_at: str
    version: int


class ClinicContract(TypedDict):
    id: str
    clinic_id: str
    effective_from: str
    effective_to: str
    bundle_rates: dict
    contracting_status: str
    frozen_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentPlan(TypedDict, total=False):
    id: str
    member_id: str
    care_advocate_id: str
    bundle_entitlement_id: str
    clinic_id: Optional[str]
    pathway_type: str
    plan_status: str
    planned_cycles: int
    min_inter_cycle_days: int
    selected_bundle_price_cents: int
    cycles_completed: int
    plan_blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Preauthorization(TypedDict, total=False):
    id: str
    treatment_plan_id: str
    cycle_sequence_index: int
    criteria_inputs: dict
    member_cost_share_pct: int
    review_status: str
    consumption_status: str
    clinical_criteria_score: int
    approved_cycles: int
    consumed_cycles: int
    bundle_price_snapshot_cents: int
    effective_from: Optional[str]
    effective_to: Optional[str]
    denial_reason_code: Optional[str]
    decision_actor: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TreatmentCycle(TypedDict, total=False):
    id: str
    treatment_plan_id: str
    preauthorization_id: str
    member_id: str
    cycle_index: int
    cycle_status: str
    retrieval_date: str
    transfer_date: str
    embryos_transferred: int
    consumption_marker: str
    created_at: str
    updated_at: str
    version: int


class MedicationOrder(TypedDict, total=False):
    id: str
    member_id: str
    care_advocate_id: Optional[str]
    preauthorization_id: str
    medication_code: str
    specialty_drug: bool
    quantity: int
    days_supply: int
    acquisition_cost_cents: int
    dispensing_pharmacy: str
    pharmacy_status: str
    plan_paid_cents: int
    member_cost_cents: int
    dispensed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PathwayRequest(TypedDict, total=False):
    id: str
    member_id: str
    care_advocate_id: str
    pathway_type: str
    pathway_status: str
    consent_signed: bool
    consent_signed_on: Optional[str]
    gestational_carrier_ref: Optional[str]
    donor_agency_ref: Optional[str]
    coverage_pct: int
    pathway_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    preauthorization_id: str
    treatment_cycle_id: Optional[str]
    service_category: str
    billed_cents: int
    service_date_iso: str
    claim_status: str
    allowed_cents: int
    member_cost_share_cents: int
    plan_paid_cents: int
    member_accumulator_before_cents: int
    member_accumulator_after_cents: int
    adjudication_basis: Optional[str]
    pended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class OutcomeRecord(TypedDict, total=False):
    id: str
    clinic_id: str
    treatment_cycle_id: str
    member_id: str
    live_birth: bool
    births_count: int
    multiple_birth: bool
    gestational_weeks: int
    outcome_recorded_on: str
    outcome_status: str
    amendment_reason: Optional[str]
    void_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SurrenderRoute(TypedDict, total=False):
    id: str
    member_id: str
    pathway_type: str
    carrier_kind: str
    route_from: str
    route_to: str
    route_status: str
    surrender_cost_cents: int
    raw_cost_cents: int
    created_at: str
    updated_at: str
    version: int