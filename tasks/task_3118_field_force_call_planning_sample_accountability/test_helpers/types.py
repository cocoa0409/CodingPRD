"""Domain types: status enums and entity shapes for the Field Force Sample
Accountability API.

All entities in this API carry the uniform system-managed fields ``id``,
``created_at``, ``updated_at``, and ``version`` (PRD section 2.4), so every
TypedDict below lists them alongside the entity-specific fields.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The five roles spelled exactly as the PRD requires (section 2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    DISTRICT_MANAGER = "DistrictManager"
    FIELD_REP = "FieldRep"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    QUALITY_ASSURANCE = "QualityAssurance"


class RegionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class TerritoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REALIGNING = "REALIGNING"
    RETIRED = "RETIRED"


class AlignmentPosture(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"


class RepresentativeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ON_LEAVE = "ON_LEAVE"
    TERMINATED = "TERMINATED"


class ComplianceStanding(str, Enum):
    GOOD = "GOOD"
    WATCH = "WATCH"
    SUSPENDED = "SUSPENDED"


class EligibilityStatus(str, Enum):
    ELIGIBLE = "ELIGIBLE"
    PENDING_REVIEW = "PENDING_REVIEW"
    INELIGIBLE = "INELIGIBLE"
    EXPIRED_LICENSE = "EXPIRED_LICENSE"


class ProductStatus(str, Enum):
    MARKETED = "MARKETED"
    DISCONTINUED = "DISCONTINUED"


class Tier(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class TargetEntryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CAP_EXHAUSTED = "CAP_EXHAUSTED"
    REMOVED = "REMOVED"


class CallPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"


class CallStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class SignatureStatus(str, Enum):
    NONE = "NONE"
    CAPTURED = "CAPTURED"
    REJECTED = "REJECTED"


class SampleLotStatus(str, Enum):
    RELEASED = "RELEASED"
    QUARANTINED = "QUARANTINED"
    EXPIRED = "EXPIRED"
    DEPLETED = "DEPLETED"
    DESTROYED = "DESTROYED"


class QuarantineReason(str, Enum):
    NONE = "NONE"
    TEMPERATURE_EXCURSION = "TEMPERATURE_EXCURSION"
    RECALL = "RECALL"
    DAMAGE = "DAMAGE"


class ReconciliationStatus(str, Enum):
    PENDING_SIGNATURE = "PENDING_SIGNATURE"
    SIGNED = "SIGNED"
    REJECTED = "REJECTED"
    VOIDED = "VOIDED"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


class TransferReasonCode(str, Enum):
    REBALANCE = "REBALANCE"
    TERRITORY_REALIGN = "TERRITORY_REALIGN"
    SHORTAGE_COVER = "SHORTAGE_COVER"
    REP_DEPARTURE = "REP_DEPARTURE"


class CountSessionStatus(str, Enum):
    OPEN = "OPEN"
    COUNTED = "COUNTED"
    RECONCILED = "RECONCILED"
    CLOSED = "CLOSED"
    VOIDED = "VOIDED"


class DisciplinaryTier(str, Enum):
    NONE = "NONE"
    COUNSELING = "COUNSELING"
    WRITTEN_WARNING = "WRITTEN_WARNING"
    SUSPENSION_REVIEW = "SUSPENSION_REVIEW"


class LocationType(str, Enum):
    VEHICLE = "VEHICLE"
    HOME_OFFICE = "HOME_OFFICE"


class ExcursionSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class ExcursionStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    RESOLVED = "RESOLVED"


class ReturnReason(str, Enum):
    EXPIRED = "EXPIRED"
    DAMAGED = "DAMAGED"
    RECALLED = "RECALLED"


class DestructionMethod(str, Enum):
    INCINERATION = "INCINERATION"
    CHEMICAL_NEUTRALIZATION = "CHEMICAL_NEUTRALIZATION"
    RETURN_TO_MANUFACTURER = "RETURN_TO_MANUFACTURER"


class SampleReturnStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    DESTRUCTION_CONFIRMED = "DESTRUCTION_CONFIRMED"


class Region(TypedDict, total=False):
    id: str
    region_code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict, total=False):
    id: str
    region_id: str
    territory_code: str
    name: str
    cycle_start_date: str
    cycle_end_date: str
    cycle_sample_budget_units: int
    alignment_posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Representative(TypedDict, total=False):
    id: str
    territory_id: str
    employee_id: str
    full_name: str
    manager_rep_id: Optional[str]
    hire_date: str
    compliance_standing: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Prescriber(TypedDict, total=False):
    id: str
    npi_number: str
    full_name: str
    state_license_number: str
    dea_number: Optional[str]
    specialty_code: str
    eligibility_status: str
    eligibility_checked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    ndc_code: str
    brand_name: str
    controlled: bool
    per_visit_max_units: int
    annual_max_units_per_prescriber: int
    storage_temp_min_c: float
    storage_temp_max_c: float
    status: str
    created_at: str
    updated_at: str
    version: int


class TargetListEntry(TypedDict, total=False):
    id: str
    territory_id: str
    prescriber_id: str
    product_id: str
    tier: str
    planned_calls_per_cycle: int
    delivered_calls: int
    planned_sample_units: int
    delivered_sample_units: int
    call_attainment_pct_planned_basis: float
    call_attainment_pct_delivered_basis: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CallPlan(TypedDict, total=False):
    id: str
    territory_id: str
    cycle_label: str
    status: str
    published_at: Optional[str]
    total_planned_calls: int
    created_at: str
    updated_at: str
    version: int


class CallVisit(TypedDict, total=False):
    id: str
    call_plan_id: str
    representative_id: str
    target_list_entry_id: str
    prescriber_id: str
    scheduled_start: str
    scheduled_end: str
    call_status: str
    signature_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SampleLot(TypedDict, total=False):
    id: str
    product_id: str
    lot_number: str
    expiration_date: str
    quantity_received: int
    quantity_available: int
    status: str
    quarantine_reason: str
    created_at: str
    updated_at: str
    version: int


class RepLotBalance(TypedDict, total=False):
    id: str
    representative_id: str
    lot_id: str
    product_id: str
    qty_issued: int
    qty_dispensed: int
    qty_returned: int
    qty_transferred_out: int
    qty_transferred_in: int
    qty_in_transit_out: int
    qty_available_forward: int
    qty_available_confirmed: int
    created_at: str
    updated_at: str
    version: int


class SampleDisbursement(TypedDict, total=False):
    id: str
    call_visit_id: str
    representative_id: str
    prescriber_id: str
    lot_id: str
    quantity: int
    signed_at: Optional[str]
    reconciliation_status: str
    created_at: str
    updated_at: str
    version: int


class SampleTransfer(TypedDict, total=False):
    id: str
    from_rep_id: str
    to_rep_id: str
    lot_id: str
    quantity: int
    reason_code: str
    documentation_note: str
    expected_lot_version: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InventoryCountSession(TypedDict, total=False):
    id: str
    representative_id: str
    counter_rep_id: str
    window_start: str
    window_end: str
    status: str
    variance_pct: Optional[float]
    disciplinary_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CountLine(TypedDict, total=False):
    id: str
    session_id: str
    lot_id: str
    expected_qty: int
    counted_qty: Optional[int]
    variance_qty: Optional[int]
    created_at: str
    updated_at: str
    version: int


class TemperatureExcursion(TypedDict, total=False):
    id: str
    representative_id: str
    product_id: str
    location_type: str
    observed_temp_c: float
    excursion_minutes: int
    severity: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SampleReturn(TypedDict, total=False):
    id: str
    representative_id: str
    lot_id: str
    quantity: int
    return_reason: str
    destruction_method: str
    destruction_report_ref: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
