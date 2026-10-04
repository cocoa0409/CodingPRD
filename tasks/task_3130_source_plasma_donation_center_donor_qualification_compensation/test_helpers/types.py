"""Domain types: entity TypedDicts, status enums, role enum.

All structures mirror the PRD's entity model for the plasma donation center API.
"""
from enum import Enum
from typing import Optional, TypedDict


class CenterStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    INSPECTION_HOLD = "INSPECTION_HOLD"
    DECOMMISSIONED = "DECOMMISSIONED"


class DonorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    QUALIFIED = "QUALIFIED"
    DEFERRED_TEMP = "DEFERRED_TEMP"
    DEFERRED_PERM = "DEFERRED_PERM"


class ScreeningVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    CLEARED = "CLEARED"
    FAILED = "FAILED"
    EXPIRED = "EXPIRED"


class RecordType(str, Enum):
    IDENTITY = "IDENTITY"
    HEALTH_HISTORY = "HEALTH_HISTORY"
    PHYSICAL_EXAM = "PHYSICAL_EXAM"
    VIRAL_MARKER = "VIRAL_MARKER"


class SubRecordOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class DonationVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    OBSERVATION = "OBSERVATION"
    COMPLETED = "COMPLETED"
    ABORTED_REACTION = "ABORTED_REACTION"
    NO_SHOW = "NO_SHOW"


class UnitStatus(str, Enum):
    QUARANTINED = "QUARANTINED"
    RELEASED = "RELEASED"
    DESTROYED = "DESTROYED"
    LOOKBACK_HOLD = "LOOKBACK_HOLD"


class ScheduleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class PaymentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    CLAWED_BACK = "CLAWED_BACK"


class PaymentVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DeferralType(str, Enum):
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class RegistryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLEARED = "CLEARED"
    OVERRIDDEN = "OVERRIDDEN"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    UNITS_QUARANTINED = "UNITS_QUARANTINED"
    RESOLVED_DESTROYED = "RESOLVED_DESTROYED"
    RESOLVED_RELEASED = "RESOLVED_RELEASED"


class Severity(str, Enum):
    MILD = "MILD"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RECORDER = "Recorder"
    MEDICAL_SCREENER = "MedicalScreener"
    PHLEBOTOMIST = "Phlebotomist"


class PlasmaCenter(TypedDict, total=False):
    id: str
    center_code: str
    legal_name: str
    state_code: str
    screening_lanes: int
    donor_floor_beds: int
    observation_chairs: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Donor(TypedDict, total=False):
    id: str
    external_donor_ref: str
    legal_first_name: str
    legal_last_name: str
    date_of_birth: str
    weight_kg: float
    home_center_id: str
    donor_status: str
    applicant_window_started_on: Optional[str]
    deferral_ends_on: Optional[str]
    deferred_reason_code: Optional[str]
    lifetime_donation_count: int
    ytd_compensation_cents: int
    requires_1099: bool
    active_deferral_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScreeningVisit(TypedDict, total=False):
    id: str
    donor_id: str
    center_id: str
    scheduled_for: str
    screening_lane_index: int
    identity_verified: bool
    health_history_recorded: bool
    physical_exam_recorded: bool
    viral_marker_recorded: bool
    visit_status: str
    created_at: str
    updated_at: str
    version: int


class ScreeningSubRecord(TypedDict, total=False):
    id: str
    screening_visit_id: str
    record_type: str
    payload: dict
    recorded_by_user_id: str
    outcome: str
    created_at: str
    updated_at: str
    version: int


class DonationVisit(TypedDict, total=False):
    id: str
    donor_id: str
    center_id: str
    screening_visit_id: str
    scheduled_for: str
    bed_index: Optional[int]
    observation_chair_index: Optional[int]
    programmed_volume_ml: int
    actual_volume_ml: Optional[int]
    visit_status: str
    compensation_payment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AdverseReaction(TypedDict, total=False):
    id: str
    donation_visit_id: str
    severity: str
    reaction_code: str
    observed_at: str
    notes: str
    created_at: str
    updated_at: str
    version: int


class DonationUnit(TypedDict, total=False):
    id: str
    donation_visit_id: str
    donor_id: str
    center_id: str
    volume_ml: int
    collected_at: str
    unit_status: str
    released_at: Optional[str]
    destroyed_at: Optional[str]
    destruction_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CompensationSchedule(TypedDict, total=False):
    id: str
    center_id: str
    effective_from: str
    effective_to: str
    base_cents_first_donation: int
    base_cents_second_donation: int
    base_cents_subsequent_donation: int
    promo_code: Optional[str]
    promo_bonus_cents: int
    promo_qualifying_donation_count: int
    schedule_status: str
    created_at: str
    updated_at: str
    version: int


class CompensationPayment(TypedDict, total=False):
    id: str
    donation_visit_id: str
    donor_id: str
    center_id: str
    schedule_id: str
    base_cents: int
    promo_cents: int
    net_cents: int
    payment_status: str
    variant: str
    variant_switched_at: Optional[str]
    payment_issued_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeferralRegistryEntry(TypedDict, total=False):
    id: str
    donor_id: str
    reason_code: str
    deferral_type: str
    deferral_ends_on: Optional[str]
    source_center_id: str
    filed_by_user_id: str
    registry_status: str
    override_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LookBackCase(TypedDict, total=False):
    id: str
    donor_id: str
    triggering_screening_sub_record_id: str
    triggering_donation_visit_id: str
    lookback_window_days: int
    case_status: str
    opened_at: str
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CenterCapacitySnapshot(TypedDict, total=False):
    id: str
    center_id: str
    snapshot_at: str
    screening_lanes_in_use: int
    donor_floor_beds_in_use: int
    observation_chairs_in_use: int
    pending_releases_count: int
    trigger_event: str
    created_at: str
    updated_at: str
    version: int
