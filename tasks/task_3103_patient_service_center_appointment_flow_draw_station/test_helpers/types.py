"""Domain types: entity TypedDicts, status enums and the role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PHLEBOTOMIST = "Phlebotomist"
    PATIENT = "Patient"
    LAB_LIAISON = "LabLiaison"
    CENTER_SUPERVISOR = "CenterSupervisor"
    LAB_SYSTEM = "LabSystem"


class ServiceCenterState(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class TestOrderStatus(str, Enum):
    RECEIVED = "RECEIVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COLLECTED = "COLLECTED"
    CANCELLED = "CANCELLED"


class NecessityStatus(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    PENDING = "PENDING"


class InsuranceStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    ELIGIBLE = "ELIGIBLE"
    INELIGIBLE = "INELIGIBLE"
    EXPIRED = "EXPIRED"
    NOT_COVERED = "NOT_COVERED"


class InsurancePlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class CollectionMode(str, Enum):
    SELF_SERVICE = "SELF_SERVICE"
    STANDARD = "STANDARD"
    PEDIATRIC = "PEDIATRIC"
    DIFFICULT_DRAW = "DIFFICULT_DRAW"


class DrawState(str, Enum):
    SCHEDULED = "SCHEDULED"
    CHECKED_IN = "CHECKED_IN"
    STAFF_PENDING = "STAFF_PENDING"
    IN_DRAW = "IN_DRAW"
    ATTEMPT_LIMIT_REACHED = "ATTEMPT_LIMIT_REACHED"
    DRAWN = "DRAWN"
    RESCHEDULED = "RESCHEDULED"
    NO_SHOW = "NO_SHOW"


class QueueState(str, Enum):
    NONE = "NONE"
    WAITING = "WAITING"
    CALLED = "CALLED"
    AT_STATION = "AT_STATION"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class SpecimenStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    COMPROMISED = "COMPROMISED"
    REJECTED = "REJECTED"
    RECOLLECTED = "RECOLLECTED"


class CourierRunStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class CourierDirection(str, Enum):
    OUTBOUND = "OUTBOUND"
    INBOUND = "INBOUND"


class PhlebotomistStatus(str, Enum):
    ON_DUTY = "ON_DUTY"
    OFF_DUTY = "OFF_DUTY"


class Credential(str, Enum):
    PBT = "PBT"
    PBT_PEDIATRIC = "PBT_PEDIATRIC"
    RN = "RN"


class EstimateVariant(str, Enum):
    PROVISIONAL_ELIGIBLE = "PROVISIONAL_ELIGIBLE"
    SELF_PAY_LIST = "SELF_PAY_LIST"
    ATTENDED_COLLECTED = "ATTENDED_COLLECTED"


class WaitBand(str, Enum):
    IMMEDIATE = "IMMEDIATE"
    WITHIN_WINDOW = "WITHIN_WINDOW"
    EXTENDED = "EXTENDED"


# ─── Entity shapes (common_fields: true everywhere in this API) ───────────────

class ServiceCenter(TypedDict):
    id: str
    name: str
    state_code: str
    timezone_offset_minutes: int
    station_count: int
    slot_minutes: int
    open_local_minutes: int
    close_local_minutes: int
    pediatric_capable: bool
    draw_hold_minutes: int
    ops_run_index: int
    staffed_minutes_available: int
    created_at: str
    updated_at: str
    version: int


class Patient(TypedDict):
    id: str
    full_name: str
    birth_date: str
    mrn: str
    created_at: str
    updated_at: str
    version: int


class Phlebotomist(TypedDict):
    id: str
    service_center_id: str
    full_name: str
    credential: str
    shift_start_local_minutes: int
    shift_end_local_minutes: int
    max_concurrent_attempts_referral: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TestOrder(TypedDict):
    id: str
    service_center_id: str
    patient_id: str
    ordering_provider_npi: str
    test_panel: str
    collection_mode: str
    is_fasting_required: bool
    fasting_hours_required: int
    fasting_deadline_utc: Optional[str]
    fasting_overdue: bool
    patient_last_food_utc: Optional[str]
    list_price_cents: int
    icd10_codes: List[str]
    insurance_plan_id: str
    patient_is_pediatric: bool
    necessity_status: str
    insurance_status: str
    est_copay_cents: int
    est_coinsurance_cents: int
    self_pay_rate_cents: int
    patient_responsibility_cents: int
    self_pay_discount_cents: int
    prepay_required_cents: int
    prepay_collected_cents: int
    balance_remaining_cents: int
    status: str
    resolved_tubes: List[str]
    draw_order_spec: List
    concurrence_hash: str
    created_at: str
    updated_at: str
    version: int


class MedicalNecessityRule(TypedDict):
    id: str
    test_panel: str
    icd10_code: str
    is_covered: bool
    created_at: str
    updated_at: str
    version: int


class InsurancePlan(TypedDict):
    id: str
    payer_name: str
    plan_type: str
    copay_cents: int
    coinsurance_pct: float
    deductible_remaining_cents: int
    prior_paid_pct: float
    allowed_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Appointment(TypedDict):
    id: str
    service_center_id: str
    test_order_id: str
    scheduled_start_utc: str
    slot_span: int
    source: str
    queue_state: str
    checkin_utc: Optional[str]
    fasting_deadline_utc: Optional[str]
    fasting_overdue: bool
    station_index: int
    phlebotomist_id: Optional[str]
    complexity_score: int
    resolved_tubes: List[str]
    draw_order_spec: List
    draw_state: str
    attempt_count: int
    draw_hold_expires_utc: Optional[str]
    draw_hold_expired: bool
    created_at: str
    updated_at: str
    version: int


class TubeRequirement(TypedDict):
    id: str
    test_panel: str
    tube_code: str
    required_volume_ml: float
    min_volume_ml: float
    order_of_draw: int
    max_urgency_hours: int
    stability_minutes: int
    special_handling_codes: List[str]
    is_recollection_eligible: bool
    created_at: str
    updated_at: str
    version: int


class CourierRun(TypedDict):
    id: str
    service_center_id: str
    direction: str
    dispatch_utc: str
    cutoff_utc: str
    committed_specimen_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict):
    id: str
    service_center_id: str
    test_order_id: str
    tube_code: str
    volume_ml: float
    order_of_draw: int
    special_handling_codes: List[str]
    collected_utc: str
    courier_run_id: Optional[str]
    status: str
    compromise_reason: Optional[str]
    recollection_approved_at_utc: Optional[str]
    day_rejection_index: int
    rejection_waived: bool
    tests_covered: List[str]
    created_at: str
    updated_at: str
    version: int


class ResponsibilityEstimate(TypedDict):
    id: str
    test_order_id: str
    variant: str
    supersedes_estimate_id: Optional[str]
    copay_component_cents: int
    coinsurance_component_cents: int
    deductible_component_cents: int
    gross_cents: int
    discount_cents: int
    net_patient_cents: int
    created_at: str
    updated_at: str
    version: int


class QueueStatus(TypedDict):
    estimated_wait_minutes: int
    wait_band: str
    fasting_gate: str