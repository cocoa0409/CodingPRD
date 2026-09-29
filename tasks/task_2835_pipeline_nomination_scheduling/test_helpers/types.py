"""Domain types for the Refined Products Pipeline Nomination & Scheduling API.

Status enums, entity TypedDicts and the role enum, all named exactly as the PRD
names them.
"""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    """The four roles that may appear in X-User-Role (PRD 2.1)."""

    SHIPPER = "Shipper"
    PIPELINE_SCHEDULER = "PipelineScheduler"
    TERMINAL_OPERATOR = "TerminalOperator"
    TARIFF_ADMINISTRATOR = "TariffAdministrator"


class TerminalRoleKind(str, Enum):
    ORIGIN = "ORIGIN"
    DESTINATION = "DESTINATION"
    BOTH = "BOTH"


class AdjustmentKind(str, Enum):
    INVENTORY = "INVENTORY"
    LINEFILL = "LINEFILL"


class SegmentOperationalStatus(str, Enum):
    OPERATIONAL = "OPERATIONAL"
    DERATED = "DERATED"
    SHUT = "SHUT"


class ProrationPolicy(str, Enum):
    HISTORY_WEIGHTED = "HISTORY_WEIGHTED"
    VOLUME_WEIGHTED = "VOLUME_WEIGHTED"


class ShipperStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RecordStatus(str, Enum):
    FINAL = "FINAL"
    PROVISIONAL = "PROVISIONAL"


class TariffStatus(str, Enum):
    DRAFT = "DRAFT"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    PRORATED = "PRORATED"
    SCHEDULED = "SCHEDULED"
    PUBLISHED = "PUBLISHED"
    RESEQUENCING = "RESEQUENCING"
    SETTLED = "SETTLED"


class NominationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    PRORATED = "PRORATED"
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    WITHDRAWN = "WITHDRAWN"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class AllocationClass(str, Enum):
    HISTORICAL = "HISTORICAL"
    NEW_SHIPPER = "NEW_SHIPPER"


class RejectionReason(str, Enum):
    BELOW_TENDER_MINIMUM = "BELOW_TENDER_MINIMUM"
    BELOW_TENDER_AFTER_PRORATION = "BELOW_TENDER_AFTER_PRORATION"


class MovementStatus(str, Enum):
    PLANNED = "PLANNED"
    INJECTED = "INJECTED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class QualityStatus(str, Enum):
    PENDING = "PENDING"
    PASSED = "PASSED"
    REJECTED = "REJECTED"


class CancelReason(str, Enum):
    """The two cancel reasons the service itself records (PRD 3.7, 3.8)."""

    QUALITY_RETEST_LIMIT = "QUALITY_RETEST_LIMIT"
    RESEQUENCING = "RESEQUENCING"


class MaintenanceKind(str, Enum):
    PIGGING = "PIGGING"
    INTEGRITY_DIG = "INTEGRITY_DIG"
    HYDROTEST = "HYDROTEST"
    VALVE_REPAIR = "VALVE_REPAIR"


class MaintenanceStatus(str, Enum):
    PLANNED = "PLANNED"
    NOTIFIED = "NOTIFIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"


class SettlementStatus(str, Enum):
    DRAFT = "DRAFT"
    CERTIFIED = "CERTIFIED"
    INVOICED = "INVOICED"


class BasisMode(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"


class ImbalanceTier(str, Enum):
    TOLERANCE = "TOLERANCE"
    STANDARD = "STANDARD"
    PENALTY = "PENALTY"


# --------------------------------------------------------------------------
# Entity shapes. Every entity below carries id + created_at + updated_at +
# version, with the single exception of ShippingHistoryRecord: PRD 2.4 states
# that the historical movement record "carries only `id` and `created_at`".
# --------------------------------------------------------------------------


class Terminal(TypedDict):
    id: str
    terminal_code: str
    name: str
    role_kind: str
    shell_capacity_bbl: float
    min_operating_inventory_bbl: float
    injection_bays: int
    inventory_bbl: float
    created_at: str
    updated_at: str
    version: int


class ProductGrade(TypedDict):
    id: str
    grade_code: str
    name: str
    sequence_rank: int
    max_sulfur_ppm: float
    max_rvp_psi: float
    is_transmix_grade: bool
    created_at: str
    updated_at: str
    version: int


class PipelineSegment(TypedDict):
    id: str
    segment_code: str
    name: str
    origin_terminal_id: str
    destination_terminal_id: str
    linefill_grade_id: str
    capacity_bbl_per_cycle: float
    transmix_reserve_bbl: float
    transmix_cut_bbl: float
    min_tender_bbl: float
    linefill_requirement_bbl: float
    linefill_bbl: float
    proration_policy: str
    operational_status: str
    derate_pct: float
    in_transit_bbl: float
    transmix_inventory_bbl: float
    system_loss_bbl: float
    created_at: str
    updated_at: str
    version: int


class Shipper(TypedDict):
    id: str
    shipper_code: str
    name: str
    credit_limit_usd: float
    exposure_usd: float
    status: str
    suspended_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ShippingHistoryRecord(TypedDict):
    """Immutable audit row: PRD 2.4 gives it only `id` and `created_at`."""

    id: str
    shipper_id: str
    segment_id: str
    cycle_code: str
    actual_shipped_bbl: float
    cycle_end_at: str
    record_status: str
    created_at: str


class Tariff(TypedDict):
    id: str
    segment_id: str
    grade_id: str
    base_rate_usd_per_bbl: float
    tier1_min_bbl: float
    tier1_rate_usd_per_bbl: float
    tier2_min_bbl: float
    tier2_rate_usd_per_bbl: float
    tender_minimum_bbl: float
    imbalance_penalty_rate_usd_per_bbl: float
    effective_from: str
    effective_to: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class NominationCycle(TypedDict):
    id: str
    cycle_code: str
    segment_id: str
    window_open_at: str
    window_close_at: str
    ship_start_at: str
    ship_end_at: str
    status: str
    effective_capacity_bbl: int
    derate_pct_applied: float
    nominated_total_bbl: float
    allocated_total_bbl: int
    unallocated_capacity_bbl: int
    total_transmix_bbl: int
    proration_factor: Optional[float]
    schedule_version: int
    schedule_published_at: Optional[str]
    schedule_published_by_user_id: Optional[str]
    settled_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Nomination(TypedDict):
    id: str
    cycle_id: str
    shipper_id: str
    grade_id: str
    origin_terminal_id: str
    destination_terminal_id: str
    nominated_bbl: float
    allocated_bbl: int
    history_base_bbl: float
    allocation_class: str
    pinned_tariff_id: Optional[str]
    supersedes_nomination_id: Optional[str]
    status: str
    rejection_reason: Optional[str]
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class BatchTicket(TypedDict):
    id: str
    cycle_id: str
    nomination_id: str
    sequence_position: int
    predecessor_batch_id: Optional[str]
    volume_bbl: float
    transmix_bbl: int
    requires_flush: bool
    injection_window_start: str
    injection_window_end: str
    movement_status: str
    quality_status: str
    measured_sulfur_ppm: Optional[float]
    measured_rvp_psi: Optional[float]
    injected_bbl: Optional[float]
    delivered_bbl: Optional[float]
    retest_count: int
    cancel_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaintenanceEvent(TypedDict):
    id: str
    segment_id: str
    kind: str
    window_start: str
    window_end: str
    capacity_derate_pct: float
    notes: Optional[str]
    status: str
    notified_at: Optional[str]
    notified_shipper_count: int
    created_at: str
    updated_at: str
    version: int


class ImbalanceSettlement(TypedDict):
    id: str
    cycle_id: str
    shipper_id: str
    basis_mode: str
    scheduled_bbl: float
    delivered_bbl: float
    loss_allocation_bbl: float
    imbalance_bbl: float
    imbalance_pct: float
    imbalance_tier: str
    tariff_charge_usd: float
    alt_basis_charge_usd: float
    basis_delta_usd: float
    imbalance_charge_usd: float
    total_billed_usd: float
    status: str
    certified_by_user_id: Optional[str]
    invoice_number: Optional[str]
    created_at: str
    updated_at: str
    version: int
