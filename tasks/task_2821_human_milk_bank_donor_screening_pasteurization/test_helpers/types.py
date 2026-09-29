"""Entity shapes, status vocabularies and role names for the milk bank API.

The TypedDicts describe what a read of each resource is expected to return, so a
test can name a field once and the type checker (and the reader) can see whether
that field belongs to the entity at all. The six immutable-by-design records
carry no `updated_at` and no `version`, which is modelled here by keeping them
out of those TypedDicts entirely.
"""

from typing import Any, Dict, List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class Role:
    DONOR = "Donor"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    MEDICAL_DIRECTOR = "MedicalDirector"
    PROCESSING_TECHNICIAN = "ProcessingTechnician"
    QUALITY_ASSURANCE_OFFICER = "QualityAssuranceOfficer"
    DISPENSING_PHARMACIST = "DispensingPharmacist"
    PRESCRIBER = "Prescriber"
    MILK_BANK_ADMIN = "MilkBankAdmin"


ALL_ROLES = [
    Role.DONOR,
    Role.INTAKE_COORDINATOR,
    Role.MEDICAL_DIRECTOR,
    Role.PROCESSING_TECHNICIAN,
    Role.QUALITY_ASSURANCE_OFFICER,
    Role.DISPENSING_PHARMACIST,
    Role.PRESCRIBER,
    Role.MILK_BANK_ADMIN,
]

# ---------------------------------------------------------------------------
# Status vocabularies
# ---------------------------------------------------------------------------


class DonorStatus:
    APPLICANT = "APPLICANT"
    SCREENING = "SCREENING"
    INFO_REQUESTED = "INFO_REQUESTED"
    QUALIFIED = "QUALIFIED"
    TEMPORARILY_DEFERRED = "TEMPORARILY_DEFERRED"
    PERMANENTLY_DEFERRED = "PERMANENTLY_DEFERRED"


class ZoneCode:
    Z1 = "Z1"
    Z2 = "Z2"
    Z3 = "Z3"


class QuestionnaireStatus:
    ACCEPTED = "ACCEPTED"
    INFO_REQUESTED = "INFO_REQUESTED"
    AUTO_DEFERRED = "AUTO_DEFERRED"
    SUPERSEDED = "SUPERSEDED"


class SerologyResult:
    NON_REACTIVE = "NON_REACTIVE"
    REACTIVE = "REACTIVE"
    INDETERMINATE = "INDETERMINATE"


class ApprovalStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    WITHDRAWN = "WITHDRAWN"


class DeferralReason:
    MEDICATION = "MEDICATION"
    ILLNESS = "ILLNESS"
    TRAVEL = "TRAVEL"
    DONOR_REQUEST = "DONOR_REQUEST"
    PHYSICIAN_WITHDRAWAL = "PHYSICIAN_WITHDRAWAL"
    REACTIVE_SEROLOGY = "REACTIVE_SEROLOGY"
    AUTO_HIGH_RISK = "AUTO_HIGH_RISK"


HUMAN_DEFERRAL_REASONS = [
    DeferralReason.MEDICATION,
    DeferralReason.ILLNESS,
    DeferralReason.TRAVEL,
    DeferralReason.DONOR_REQUEST,
    DeferralReason.PHYSICIAN_WITHDRAWAL,
]

SYSTEM_DEFERRAL_REASONS = [
    DeferralReason.REACTIVE_SEROLOGY,
    DeferralReason.AUTO_HIGH_RISK,
]


class DeferralType:
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class DeferralStatus:
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"


class RecallScope:
    NONE = "NONE"
    DONATIONS_ONLY = "DONATIONS_ONLY"
    FULL_CHAIN = "FULL_CHAIN"


class ShipmentStatus:
    IN_TRANSIT = "IN_TRANSIT"
    ACCEPTED = "ACCEPTED"
    QUARANTINED = "QUARANTINED"
    REJECTED = "REJECTED"
    CLOSED = "CLOSED"


class Disposition:
    ACCEPT = "ACCEPT"
    REJECT = "REJECT"


class DonationStatus:
    ELIGIBLE = "ELIGIBLE"
    ALLOCATED = "ALLOCATED"
    PASTEURIZED = "PASTEURIZED"
    RECALLED = "RECALLED"
    DISCARDED = "DISCARDED"


class MilkClass:
    PRETERM = "PRETERM"
    TERM = "TERM"


class TargetMilkClass:
    PRETERM = "PRETERM"
    TERM = "TERM"
    MIXED = "MIXED"


class PoolStatus:
    DRAFT = "DRAFT"
    BALANCED = "BALANCED"
    COMMITTED = "COMMITTED"
    PASTEURIZED = "PASTEURIZED"
    SCRAPPED = "SCRAPPED"
    SCRAPPED_CULTURE = "SCRAPPED_CULTURE"


class ComponentStatus:
    ALLOCATED = "ALLOCATED"
    VOIDED = "VOIDED"
    CONSUMED_PASTEURIZED = "CONSUMED_PASTEURIZED"
    CONSUMED_LOST = "CONSUMED_LOST"


class RunStatus:
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    BOTTLED = "BOTTLED"
    VOIDED = "VOIDED"


class ThermalStatus:
    PENDING = "PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CultureStatus:
    NOT_COLLECTED = "NOT_COLLECTED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class ReleaseEligibility:
    ELIGIBLE = "ELIGIBLE"
    BLOCKED = "BLOCKED"


class LotReleaseStatus:
    HOLD = "HOLD"
    RELEASED = "RELEASED"
    EXHAUSTED = "EXHAUSTED"
    DISCARDED = "DISCARDED"
    RECALLED = "RECALLED"
    EXPIRED = "EXPIRED"


class ProgramStatus:
    OPEN = "OPEN"
    EXHAUSTED = "EXHAUSTED"


class PatientType:
    NICU_INPATIENT = "NICU_INPATIENT"
    OUTPATIENT = "OUTPATIENT"


class ClinicalAcuity:
    CRITICAL = "CRITICAL"
    STANDARD = "STANDARD"


class PrescriptionStatus:
    QUEUED = "QUEUED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


class DispenseStatus:
    DISPENSED = "DISPENSED"
    VOIDED = "VOIDED"
    RECALLED = "RECALLED"


# ---------------------------------------------------------------------------
# Entity shapes
# ---------------------------------------------------------------------------

JsonDict = Dict[str, Any]


class Donor(TypedDict, total=False):
    id: str
    donor_code: str
    full_name: str
    email: str
    zone_code: str
    status: str
    screening_risk_score: int
    surveillance_risk_score: int
    reimbursement_balance_cents: int
    lifetime_accepted_volume_ml: int
    temporary_deferral_count: int
    active_deferral_until_date: Optional[str]
    qualified_at: Optional[str]
    qualified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HealthHistoryQuestionnaire(TypedDict, total=False):
    id: str
    donor_id: str
    medication_flag_count: int
    travel_risk_flag: bool
    tobacco_use: bool
    alcohol_units_per_week: int
    months_postpartum: int
    base_risk_points: int
    screening_risk_score: int
    status: str
    submitted_at: str
    created_at: str


class SerologyPanel(TypedDict, total=False):
    id: str
    donor_id: str
    collected_on: str
    hiv_result: str
    htlv_result: str
    hbv_result: str
    hcv_result: str
    syphilis_result: str
    panel_status: str
    expires_on: str
    recorded_by_user_id: str
    created_at: str


class PhysicianApproval(TypedDict, total=False):
    id: str
    donor_id: str
    physician_npi: str
    approved_on: str
    valid_until: str
    status: str
    recorded_by_user_id: str
    created_at: str


class DeferralEvent(TypedDict, total=False):
    id: str
    donor_id: str
    reason_code: str
    deferral_type: str
    effective_from: str
    deferral_days: int
    lookback_days: int
    recall_scope: str
    status: str
    recalled_donation_count: int
    quarantined_pool_count: int
    recalled_lot_count: int
    recalled_dispense_count: int
    reversed_subsidy_cents: int
    recorded_by_user_id: str
    created_at: str


class Shipment(TypedDict, total=False):
    id: str
    donor_id: str
    tracking_code: str
    zone_code: str
    container_count: int
    uses_dry_ice: bool
    declared_volume_ml: int
    shipped_on: str
    status: str
    estimated_reimbursement_cents: int
    final_reimbursement_cents: Optional[int]
    credited_reimbursement_cents: Optional[int]
    excursion_minutes: Optional[int]
    arrival_max_temp_celsius: Optional[float]
    verified_volume_ml: Optional[int]
    received_at: Optional[str]
    received_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Donation(TypedDict, total=False):
    id: str
    shipment_id: str
    donor_id: str
    container_label: str
    expressed_on: str
    volume_ml: int
    remaining_ml: int
    kcal_per_oz: float
    milk_class: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Pool(TypedDict, total=False):
    id: str
    pool_code: str
    target_milk_class: str
    pool_sequence: int
    status: str
    distinct_donor_count: int
    total_volume_ml: int
    projected_kcal_per_oz: Optional[float]
    bottled_volume_ml: int
    committed_at: Optional[str]
    committed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoolComponent(TypedDict, total=False):
    id: str
    pool_id: str
    donation_id: str
    allocated_volume_ml: int
    component_kcal_per_oz: float
    component_donor_id: str
    status: str
    created_at: str


class PasteurizationRun(TypedDict, total=False):
    id: str
    pool_id: str
    pasteurizer_id: str
    scheduled_start_at: str
    cycle_minutes: int
    run_status: str
    thermal_status: str
    culture_status: str
    release_eligibility: str
    reading_count: int
    longest_hold_seconds: Optional[int]
    peak_celsius: Optional[float]
    completed_at: Optional[str]
    completed_by_user_id: Optional[str]
    culture_cfu_per_ml: Optional[int]
    culture_organism: Optional[str]
    culture_recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemperatureReading(TypedDict, total=False):
    id: str
    run_id: str
    offset_seconds: int
    celsius: float
    qualifies: bool
    recorded_by_user_id: str
    created_at: str


class MilkLot(TypedDict, total=False):
    id: str
    run_id: str
    lot_code: str
    lot_sequence: int
    bottle_count: int
    bottle_volume_ml: int
    total_volume_ml: int
    dispensed_ml: int
    available_ml: int
    kcal_per_oz: float
    milk_class: str
    pasteurization_date: str
    expiration_date: str
    release_status: str
    released_at: Optional[str]
    released_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SubsidyProgram(TypedDict, total=False):
    id: str
    program_code: str
    name: str
    coverage_pct: float
    annual_cap_cents: int
    consumed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescription(TypedDict, total=False):
    id: str
    prescription_code: str
    subsidy_program_id: Optional[str]
    patient_reference: str
    patient_type: str
    clinical_acuity: str
    requires_preterm_milk: bool
    subsidy_required: bool
    prescribed_ml: int
    needed_by_date: str
    priority_tier: int
    waitlist_position: Optional[int]
    cumulative_dispensed_ml: int
    remaining_ml: int
    status: str
    prescriber_user_id: str
    created_at: str
    updated_at: str
    version: int


class Dispense(TypedDict, total=False):
    id: str
    prescription_id: str
    lot_id: str
    volume_ml: int
    tier_discount_pct: float
    gross_fee_cents: int
    subsidy_cents: int
    payer_due_cents: int
    allocation_cycle_sequence: Optional[int]
    status: str
    dispensed_by_user_id: str
    created_at: str
    updated_at: str
    version: int


# Resources carrying the full four-field audit set.
VERSIONED_ENTITIES = [
    "Donor",
    "Shipment",
    "Donation",
    "Pool",
    "PasteurizationRun",
    "MilkLot",
    "SubsidyProgram",
    "Prescription",
    "Dispense",
]

# Resources that are immutable-by-design event records: id and created_at only.
EVENT_RECORD_ENTITIES = [
    "HealthHistoryQuestionnaire",
    "SerologyPanel",
    "PhysicianApproval",
    "PoolComponent",
    "TemperatureReading",
    "DeferralEvent",
]

__all__ = [
    "JsonDict",
    "Role",
    "ALL_ROLES",
    "DonorStatus",
    "ZoneCode",
    "QuestionnaireStatus",
    "SerologyResult",
    "ApprovalStatus",
    "DeferralReason",
    "HUMAN_DEFERRAL_REASONS",
    "SYSTEM_DEFERRAL_REASONS",
    "DeferralType",
    "DeferralStatus",
    "RecallScope",
    "ShipmentStatus",
    "Disposition",
    "DonationStatus",
    "MilkClass",
    "TargetMilkClass",
    "PoolStatus",
    "ComponentStatus",
    "RunStatus",
    "ThermalStatus",
    "CultureStatus",
    "ReleaseEligibility",
    "LotReleaseStatus",
    "ProgramStatus",
    "PatientType",
    "ClinicalAcuity",
    "PrescriptionStatus",
    "DispenseStatus",
    "Donor",
    "HealthHistoryQuestionnaire",
    "SerologyPanel",
    "PhysicianApproval",
    "DeferralEvent",
    "Shipment",
    "Donation",
    "Pool",
    "PoolComponent",
    "PasteurizationRun",
    "TemperatureReading",
    "MilkLot",
    "SubsidyProgram",
    "Prescription",
    "Dispense",
    "VERSIONED_ENTITIES",
    "EVENT_RECORD_ENTITIES",
    "List",
    "Optional",
]
