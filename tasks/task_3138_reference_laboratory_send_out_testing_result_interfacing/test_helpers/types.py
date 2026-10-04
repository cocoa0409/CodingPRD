"""Domain types: entity TypedDicts, status enums and the role enum.

Every entity in this API declares the common field set (PRD 2.4): each resource
carries ``id``, ``created_at``, ``updated_at`` and ``version``. No entity in this
domain is an append-only log, so every TypedDict below carries all four.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# =============================================================================
# Role enum (PRD 2.1)
# =============================================================================

class UserRole(str, Enum):
    REFERENCE_LAB_OPERATIONS = "ReferenceLabOperations"
    LAB_CLIENT_ADMIN = "LabClientAdmin"
    COURIER_COORDINATOR = "CourierCoordinator"
    ACCESSIONING_TECHNOLOGIST = "AccessioningTechnologist"
    MEDICAL_TECHNOLOGIST = "MedicalTechnologist"
    INTERFACE_ANALYST = "InterfaceAnalyst"
    PATHOLOGIST = "Pathologist"
    MEDICAL_DIRECTOR = "MedicalDirector"
    LAB_BILLING_SPECIALIST = "LabBillingSpecialist"
    UTILIZATION_REVIEWER = "UtilizationReviewer"


# =============================================================================
# Status enums
# =============================================================================

class ClientLaboratoryStatus(str, Enum):
    PENDING_ONBOARDING = "PENDING_ONBOARDING"
    ACTIVE = "ACTIVE"
    CREDIT_HOLD = "CREDIT_HOLD"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class OnboardingStatus(str, Enum):
    DOCUMENTS_PENDING = "DOCUMENTS_PENDING"
    REQUIREMENTS_PUBLISHED = "REQUIREMENTS_PUBLISHED"
    COURIER_CONFIGURED = "COURIER_CONFIGURED"
    COMPLETE = "COMPLETE"


class InterfaceStatus(str, Enum):
    NOT_BUILT = "NOT_BUILT"
    IN_BUILD = "IN_BUILD"
    CERTIFIED = "CERTIFIED"
    RETIRED = "RETIRED"


class CourierRunStatus(str, Enum):
    PLANNED = "PLANNED"
    DISPATCHED = "DISPATCHED"
    IN_TRANSIT = "IN_TRANSIT"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class CatalogEntryStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    DEPRECATED = "DEPRECATED"
    WITHDRAWN = "WITHDRAWN"


class SpecimenStatus(str, Enum):
    RECEIVED = "RECEIVED"
    ACCESSIONED = "ACCESSIONED"
    IN_TESTING = "IN_TESTING"
    RESULT_PENDING_REVIEW = "RESULT_PENDING_REVIEW"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"


class SendOutOrderStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCESSIONED = "ACCESSIONED"
    IN_TESTING = "IN_TESTING"
    INTERIM_REPORTED = "INTERIM_REPORTED"
    RESULT_RELEASED = "RESULT_RELEASED"
    REFLEX_PENDING = "REFLEX_PENDING"
    ON_HOLD = "ON_HOLD"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    PROVISIONAL = "PROVISIONAL"
    BILLED = "BILLED"
    VOIDED = "VOIDED"


class OrderTestLineStatus(str, Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    INTERIM = "INTERIM"
    FINAL = "FINAL"
    REPEAT_REQUIRED = "REPEAT_REQUIRED"
    CANCELLED = "CANCELLED"


class ResultFlag(str, Enum):
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    LOW = "LOW"
    CRITICAL_HIGH = "CRITICAL_HIGH"
    CRITICAL_LOW = "CRITICAL_LOW"


class InstrumentRunStatus(str, Enum):
    RESERVED = "RESERVED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"


class InterfaceBuildStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_BUILD = "IN_BUILD"
    CERTIFIED = "CERTIFIED"
    SUPERSEDED = "SUPERSEDED"
    RETIRED = "RETIRED"


class InterfaceMessageStatus(str, Enum):
    QUEUED = "QUEUED"
    VALIDATED = "VALIDATED"
    HELD = "HELD"
    TRANSMITTED = "TRANSMITTED"
    FAILED = "FAILED"
    ACKNOWLEDGED = "ACKNOWLEDGED"


class BillingLedgerStatus(str, Enum):
    OPEN = "OPEN"
    HELD = "HELD"
    CLOSED = "CLOSED"


class UtilizationAdvisoryStatus(str, Enum):
    OPEN = "OPEN"
    SENT = "SENT"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISMISSED = "DISMISSED"
    ESCALATED = "ESCALATED"


class RushTier(str, Enum):
    STANDARD = "STANDARD"
    RUSH = "RUSH"
    CRITICAL = "CRITICAL"


# =============================================================================
# Entity TypedDicts — every entity declares common_fields (PRD 2.4)
# =============================================================================

class ClientLaboratory(TypedDict, total=False):
    id: str
    name: str
    clia_number: str
    client_type: str
    state_code: str
    billing_arrangement: str
    credit_limit_cents: int
    status: str
    onboarding_status: str
    interface_status: str
    requirement_notes_published_at: Optional[str]
    outstanding_balance_cents: float
    billable_line_count: int
    forward_utilization_score: int
    settled_utilization_score: int
    utilization_flag: bool
    created_at: str
    updated_at: str
    version: int


class CourierRun(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    route_code: str
    origin_city: str
    destination_city: str
    vehicle_id: str
    scheduled_departure_at: str
    scheduled_arrival_at: str
    scheduled_pickup_at: str
    scheduled_delivery_at: str
    temperature_control_mode: str
    specimen_count: int
    transit_allowance_minutes: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TestCatalogEntry(TypedDict, total=False):
    id: str
    test_code: str
    test_name: str
    test_category: str
    method: str
    required_specimen_type: str
    container_type: str
    min_volume_ml: float
    transport_temperature: str
    stability_hours_ambient: float
    stability_hours_refrigerated: float
    stability_hours_frozen: float
    base_tat_hours: float
    list_price_cents: int
    client_price_cents: Optional[int]
    floor_price_cents: int
    reference_low: Optional[float]
    reference_high: Optional[float]
    critical_value_low: Optional[float]
    critical_value_high: Optional[float]
    reflex_test_code: Optional[str]
    reflex_condition: str
    reflex_within_hours: float
    reflex_min_remaining_hours: float
    is_utilization_managed: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Specimen(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    courier_run_id: Optional[str]
    aliquot_parent_id: Optional[str]
    accession_number: str
    patient_mrn: str
    specimen_type: str
    container_type: str
    volume_ml: float
    aliquot_volume_ml: Optional[float]
    collection_at: str
    received_at: str
    transport_temperature: str
    condition: str
    condition_reason_code: Optional[str]
    rejection_reason_code: Optional[str]
    remaining_stability_hours: float
    total_aliquot_volume_ml: float
    status: str
    created_at: str
    updated_at: str
    version: int


class SendOutOrder(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    specimen_id: str
    reflex_source_order_id: Optional[str]
    order_number: str
    patient_mrn: str
    client_requested_at: str
    priority: str
    rush_tier: str
    base_tat_hours: float
    effective_tat_hours: float
    expected_result_at: str
    stability_deadline_at: str
    provisional_charge_cents: float
    order_final_charge_cents: float
    charge_variance_cents: float
    tat_credit_cents: float
    interpretive_comment: Optional[str]
    override_utilization_guard: bool
    order_status: str
    billing_status: str
    test_lines: List[dict]
    created_at: str
    updated_at: str
    version: int


class OrderTestLine(TypedDict, total=False):
    id: str
    send_out_order_id: str
    test_catalog_entry_id: str
    line_sequence: int
    is_add_on: bool
    add_on_at: Optional[str]
    result_value: Optional[float]
    result_units: Optional[str]
    result_flag: Optional[str]
    critical_value_notified_to: Optional[str]
    critical_value_notified_at: Optional[str]
    entered_by_user_id: Optional[str]
    billed_cents: float
    tat_credit_cents: float
    result_released_at: Optional[str]
    line_status: str
    created_at: str
    updated_at: str
    version: int


class InstrumentRun(TypedDict, total=False):
    id: str
    test_catalog_entry_id: str
    instrument_code: str
    section: str
    decontamination_buffer_minutes: int
    reserved_start_at: str
    reserved_end_at: str
    occupied_until_at: str
    run_status: str
    created_at: str
    updated_at: str
    version: int


class InterfaceBuild(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    build_version_label: str
    format: str
    order_interface_enabled: bool
    result_interface_enabled: bool
    certified_at: Optional[str]
    superseded_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ResultInterfaceMessage(TypedDict, total=False):
    id: str
    send_out_order_id: str
    interface_build_id: str
    message_type: str
    control_id: str
    interpreted_comment_included: bool
    discrete_field_count: int
    queued_at: str
    transmitted_at: Optional[str]
    retry_count: int
    next_retry_offset_minutes: float
    status: str
    created_at: str
    updated_at: str
    version: int


class BillingLedger(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    billed_cents: float
    voided_cents: float
    net_billed_cents: float
    charge_entry_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UtilizationAdvisory(TypedDict, total=False):
    id: str
    client_laboratory_id: str
    test_catalog_entry_id: str
    source_order_id: Optional[str]
    advisory_type: str
    message: str
    send_count: int
    status: str
    created_at: str
    updated_at: str
    version: int