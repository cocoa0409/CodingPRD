"""Domain types: entity TypedDicts, status enums, role enum.

All thirteen resources share the common-fields convention of the PRD
(id, created_at, updated_at, version on every resource, no exceptions).
"""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SOURCING_MANAGER = "SourcingManager"
    QUALITY_ASSURANCE = "QualityAssurance"
    FORMULATOR = "Formulator"
    SAFETY_OFFICER = "SafetyOfficer"
    LAB_TECHNICIAN = "LabTechnician"
    BRAND_MANAGER = "BrandManager"
    LICENSOR = "Licensor"
    ALLOCATION_PLANNER = "AllocationPlanner"
    BOX_OFFICE = "BoxOffice"
    CONSUMER = "Consumer"


class ColorStatus(str, Enum):
    PROPOSED = "PROPOSED"
    IN_VOTE = "IN_VOTE"
    ACTIVE = "ACTIVE"
    RETIRE_VOTE = "RETIRE_VOTE"
    RETIRED = "RETIRED"
    ARCHIVED = "ARCHIVED"


class BatchStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    CERTIFIED = "CERTIFIED"
    REJECTED = "REJECTED"


class HazardClass(str, Enum):
    STANDARD = "STANDARD"
    SENSITIVE = "SENSITIVE"
    RESTRICTED = "RESTRICTED"


class CertificationMark(str, Enum):
    ACMI_AP = "ACMI_AP"
    ACMI_CL = "ACMI_CL"
    NONE = "NONE"


class FormulaStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class IntendedUse(str, Enum):
    CRAYON = "CRAYON"
    MARKER = "MARKER"
    COLORED_PENCIL = "COLORED_PENCIL"


class CampaignKind(str, Enum):
    INTRODUCTION = "INTRODUCTION"
    RETIREMENT = "RETIREMENT"


class CampaignStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    TALLYED = "TALLYED"


class CampaignOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class VoterSegment(str, Enum):
    KIDS = "KIDS"
    PARENTS = "PARENTS"
    EDUCATORS = "EDUCATORS"
    COLLECTORS = "COLLECTORS"


class SafetyTestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"


class SpecKind(str, Enum):
    RETAIL = "RETAIL"
    CLASSROOM = "CLASSROOM"
    LICENSED = "LICENSED"


class SpecStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPRECATED = "DEPRECATED"


class RunStage(str, Enum):
    PLANNED = "PLANNED"
    MOLDING = "MOLDING"
    LABELING = "LABELING"
    PACKING = "PACKING"
    COMPLETED = "COMPLETED"
    ON_HOLD = "ON_HOLD"
    CANCELLED = "CANCELLED"
    QUARANTINED = "QUARANTINED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPLETED = "DEPLETED"
    QUARANTINED = "QUARANTINED"


class AllocationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMMITTED = "COMMITTED"
    FULFILLED = "FULFILLED"
    RELEASED = "RELEASED"
    EXPIRED = "EXPIRED"
    SHORTED = "SHORTED"


class PriorityTier(str, Enum):
    PLATINUM = "PLATINUM"
    GOLD = "GOLD"
    STANDARD = "STANDARD"


class LineStatus(str, Enum):
    DRAFT = "DRAFT"
    LICENSOR_REVIEW = "LICENSOR_REVIEW"
    BRAND_REVIEW = "BRAND_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class RoyaltyBase(str, Enum):
    GROSS = "GROSS"
    NET = "NET"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CLOSED = "CLOSED"


class TicketKind(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    GROUP = "GROUP"


class TicketStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CHECKED_IN = "CHECKED_IN"
    REFUNDED = "REFUNDED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class RecallStatus(str, Enum):
    OPEN = "OPEN"
    CONTAINED = "CONTAINED"
    CLOSED = "CLOSED"


class RecallSeverity(str, Enum):
    CLASS_I = "CLASS_I"
    CLASS_II = "CLASS_II"
    CLASS_III = "CLASS_III"


# --- Entity TypedDicts (all carry common fields: id/created_at/updated_at/version) ---

class Color(TypedDict, total=False):
    id: str
    name: str
    hex_code: str
    is_core_curriculum: bool
    status: str
    introduced_on: Optional[str]
    retired_on: Optional[str]
    archive_after_date: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PigmentBatch(TypedDict, total=False):
    id: str
    pigment_name: str
    supplier_name: str
    hazard_class: str
    received_quantity_kg: float
    certification_mark: str
    status: str
    created_by_user_id: str
    certified_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Formula(TypedDict, total=False):
    id: str
    color_id: str
    intended_use: str
    pigment_recipe: List[dict]
    status: str
    submitted_by_user_id: Optional[str]
    approved_by_user_id: Optional[str]
    licensed_use_count: int
    created_at: str
    updated_at: str
    version: int


class VoteCampaign(TypedDict, total=False):
    id: str
    color_id: str
    kind: str
    opens_on: str
    closes_on: str
    status: str
    votes_yes_weighted: float
    votes_total_weighted: float
    turnout_count: int
    outcome: Optional[str]
    tallied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyTest(TypedDict, total=False):
    id: str
    formula_id: str
    test_standard: str
    test_seq: int
    status: str
    result_notes: Optional[str]
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AssortmentSpec(TypedDict, total=False):
    id: str
    name: str
    kind: str
    partner_name: Optional[str]
    entries: List[dict]
    wholesale_price_cents: int
    box_size: int
    status: str
    boxes_available: int
    boxes_reserved: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    assortment_spec_id: str
    pigment_batch_id: str
    planned_boxes: int
    planned_start_date: str
    planned_end_date: str
    stage: str
    stage_before_hold: Optional[str]
    hold_reason: Optional[str]
    packed_counts: Optional[List[dict]]
    packing_variance_units: int
    packing_penalty_cents: int
    boxes_produced: int
    waste_units: int
    run_seq: int
    created_at: str
    updated_at: str
    version: int


class InventoryLot(TypedDict, total=False):
    id: str
    production_run_id: str
    boxes_received: int
    boxes_on_hand: int
    boxes_committed: int
    boxes_shipped: int
    lot_seq: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RetailAllocation(TypedDict, total=False):
    id: str
    assortment_spec_id: str
    retailer_name: str
    priority_tier: str
    requested_boxes: int
    requested_ship_date: str
    allocated_boxes_provisional: int
    allocated_boxes_final: Optional[int]
    status: str
    request_seq: int
    created_at: str
    updated_at: str
    version: int


class LicensedLine(TypedDict, total=False):
    id: str
    name: str
    licensor_user_id: str
    formula_id: str
    term_start: str
    term_end: str
    royalty_rate: float
    royalty_base: str
    pinned_formula_version: Optional[int]
    projected_royalty_cents: int
    status: str
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttractionSession(TypedDict, total=False):
    id: str
    venue_name: str
    session_date: str
    start_minute: int
    duration_minutes: int
    capacity_units: int
    is_charter: bool
    base_price_cents: int
    booked_units: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Ticket(TypedDict, total=False):
    id: str
    session_id: str
    kind: str
    group_size: Optional[int]
    school_name: Optional[str]
    units: int
    price_cents: int
    status: str
    checked_in_at: Optional[str]
    waitlist_seq: int
    created_at: str
    updated_at: str
    version: int


class RecallCase(TypedDict, total=False):
    id: str
    pigment_batch_id: str
    affected_run_count: int
    affected_units: int
    severity: str
    cooling_until: str
    status: str
    created_at: str
    updated_at: str
    version: int
