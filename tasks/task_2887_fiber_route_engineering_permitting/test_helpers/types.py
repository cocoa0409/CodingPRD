"""Typed vocabulary for the Fiber Route Engineering & Permitting API.

Every enum member and every TypedDict key below is spelled exactly as the PRD
spells it.  Two resource types -- PoleObservation and MakeReadyItem -- are
append-only observations that carry only ``id`` and ``created_at``; their
TypedDicts deliberately omit ``updated_at`` and ``version`` because the PRD
states those two fields are "absent from their response payloads entirely
rather than present-and-null".
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


class UserRole(str, Enum):
    ROUTE_ENGINEER = "RouteEngineer"
    FIELD_SURVEYOR = "FieldSurveyor"
    PERMIT_COORDINATOR = "PermitCoordinator"
    AUTHORITY_REVIEWER = "AuthorityReviewer"
    POLE_OWNER = "PoleOwner"
    NETWORK_RECORDS_ADMIN = "NetworkRecordsAdmin"


ALL_ROLES: List[str] = [role.value for role in UserRole]


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


class RouteStatus(str, Enum):
    PLANNING = "PLANNING"
    SCOPE_LOCKED = "SCOPE_LOCKED"
    PERMITTING = "PERMITTING"
    CONSTRUCTION_READY = "CONSTRUCTION_READY"
    RECORDS_UPDATED = "RECORDS_UPDATED"


class TopologyObjective(str, Enum):
    RING_CLOSURE = "RING_CLOSURE"
    SPUR = "SPUR"
    EXPRESS_BACKBONE = "EXPRESS_BACKBONE"


# ---------------------------------------------------------------------------
# RouteSegment
# ---------------------------------------------------------------------------


class TerrainClass(str, Enum):
    URBAN_PAVED = "URBAN_PAVED"
    URBAN_UNPAVED = "URBAN_UNPAVED"
    RURAL_SHOULDER = "RURAL_SHOULDER"
    RAIL_CROSSING = "RAIL_CROSSING"
    HIGHWAY_CROSSING = "HIGHWAY_CROSSING"
    WATER_CROSSING = "WATER_CROSSING"


class AuthorityType(str, Enum):
    MUNICIPAL_ROW = "MUNICIPAL_ROW"
    STATE_HIGHWAY = "STATE_HIGHWAY"
    RAILROAD = "RAILROAD"
    WATERWAY = "WATERWAY"


class EngineeringStatus(str, Enum):
    DRAFT = "DRAFT"
    WALKED = "WALKED"
    METHOD_SELECTED = "METHOD_SELECTED"
    DESIGN_LOCKED = "DESIGN_LOCKED"


class PermitStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ConstructionMethod(str, Enum):
    AERIAL = "AERIAL"
    DIRECTIONAL_BORE = "DIRECTIONAL_BORE"
    TRENCH = "TRENCH"


class MoratoriumClass(str, Enum):
    NONE = "NONE"
    NO_OPEN_CUT = "NO_OPEN_CUT"
    FULL_RESTORATION = "FULL_RESTORATION"


# ---------------------------------------------------------------------------
# FieldWalkout / PoleObservation
# ---------------------------------------------------------------------------


class WalkoutStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class WalkoutDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class PoleOwner(str, Enum):
    ELECTRIC_UTILITY = "ELECTRIC_UTILITY"
    TELCO = "TELCO"
    MUNICIPAL_LIGHT = "MUNICIPAL_LIGHT"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class WorstPoleConditionGrade(str, Enum):
    NONE = "NONE"
    A = "A"
    B = "B"
    C = "C"
    D = "D"


# ---------------------------------------------------------------------------
# PoleAttachmentApplication / MakeReadyItem
# ---------------------------------------------------------------------------


class PoleApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    MAKE_READY_ESTIMATED = "MAKE_READY_ESTIMATED"
    GRANTED = "GRANTED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class OwnerResponseOutcome(str, Enum):
    ESTIMATED = "ESTIMATED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    DENIED = "DENIED"


class WorkClass(str, Enum):
    TRANSFER = "TRANSFER"
    POLE_REPLACEMENT = "POLE_REPLACEMENT"
    GUYING = "GUYING"
    RISER = "RISER"
    CLEARANCE_TRIM = "CLEARANCE_TRIM"


# ---------------------------------------------------------------------------
# PermitApplication
# ---------------------------------------------------------------------------


class PermitApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class PermitDecision(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    REVISION_REQUESTED = "REVISION_REQUESTED"


# ---------------------------------------------------------------------------
# DesignPackage / SplicePoint
# ---------------------------------------------------------------------------


class DesignStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    STAMPED = "STAMPED"
    SUPERSEDED = "SUPERSEDED"


class SplicePointStatus(str, Enum):
    PLACED = "PLACED"
    VOIDED = "VOIDED"


class EnclosureType(str, Enum):
    HANDHOLE = "HANDHOLE"
    AERIAL_SNOWSHOE = "AERIAL_SNOWSHOE"
    CABINET = "CABINET"


# ---------------------------------------------------------------------------
# AsBuiltRecord
# ---------------------------------------------------------------------------


class AsBuiltStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class AsBuiltDecision(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity payload shapes
# ---------------------------------------------------------------------------


class Route(TypedDict):
    id: str
    name: str
    topology_objective: str
    target_in_service_date: str
    status: str
    budget_authorized_cents: int
    budget_committed_cents: int
    budget_available_cents: int
    segment_count: int
    design_total_length_feet: int
    total_preliminary_cost_cents: int
    total_bid_ready_cost_cents: int
    scope_locked_at: Optional[str]
    planned_complexity_index: Optional[int]
    live_complexity_index: Optional[int]
    created_at: str
    updated_at: str
    version: int


class RouteSegment(TypedDict):
    id: str
    route_id: str
    sequence_index: int
    street_name: str
    municipality_code: str
    length_feet: int
    terrain_class: str
    planned_work_start_on: str
    planned_work_end_on: str
    predecessor_segment_id: Optional[str]
    existing_conduit_available: bool
    required_authority_type: str
    engineering_status: str
    permit_status: str
    construction_method: Optional[str]
    moratorium_class: str
    restoration_cost_cents: int
    accepted_obstruction_count: int
    preliminary_cost_cents: Optional[int]
    bid_ready_cost_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FieldWalkout(TypedDict):
    id: str
    segment_id: str
    walked_on: str
    obstruction_count: int
    conduit_available_confirmed: bool
    surveyor_note: Optional[str]
    status: str
    review_round: int
    worst_pole_condition_grade: str
    make_ready_flagged_pole_count: int
    reviewed_by_user_id: Optional[str]
    rejection_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PoleObservation(TypedDict):
    """Append-only observation: no ``updated_at`` and no ``version``."""

    id: str
    walkout_id: str
    pole_tag: str
    pole_owner: str
    condition_grade: str
    available_vertical_clearance_in: int
    existing_attachment_count: int
    requires_make_ready: bool
    created_at: str


class PoleAttachmentApplication(TypedDict):
    id: str
    segment_id: str
    pole_owner: str
    pole_count: int
    status: str
    revision_round: int
    committed: bool
    submitted_at: Optional[str]
    owner_note: Optional[str]
    make_ready_items_subtotal_cents: Optional[int]
    make_ready_admin_fee_bp: Optional[int]
    make_ready_admin_fee_cents: Optional[int]
    make_ready_cost_cents: Optional[int]
    make_ready_days: Optional[int]
    created_at: str
    updated_at: str
    version: int


class MakeReadyItem(TypedDict):
    """Append-only line item: no ``updated_at`` and no ``version``."""

    id: str
    application_id: str
    pole_tag: str
    work_class: str
    quantity: int
    unit_cost_cents: int
    lead_days: int
    extended_cost_cents: int
    created_at: str


class PermitApplication(TypedDict):
    id: str
    segment_id: str
    authority_type: str
    authority_name: str
    work_window_start_on: str
    work_window_end_on: str
    status: str
    revision_round: int
    review_days: Optional[int]
    submitted_at: Optional[str]
    decision_due_at: Optional[str]
    decided_at: Optional[str]
    decided_by_user_id: Optional[str]
    decision_note: Optional[str]
    deemed: bool
    created_at: str
    updated_at: str
    version: int


class MoratoriumWindow(TypedDict):
    id: str
    municipality_code: str
    street_name: str
    resurfaced_on: str
    starts_on: str
    ends_on: str
    moratorium_class: str
    ordinance_reference: str
    created_at: str
    updated_at: str
    version: int


class DesignPackage(TypedDict):
    id: str
    route_id: str
    revision: int
    fiber_count_allocated: int
    express_fiber_count: int
    status: str
    assigned_drop_fiber_count: int
    reserve_fiber_count: int
    spare_ratio_bp: int
    splice_point_count: int
    handhole_count: int
    submitted_by_user_id: Optional[str]
    stamped_by_user_id: Optional[str]
    stamped_at: Optional[str]
    stamp_voided_at: Optional[str]
    return_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SplicePoint(TypedDict):
    id: str
    design_id: str
    segment_id: str
    station_feet: int
    enclosure_type: str
    fiber_count_dropped: int
    status: str
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AsBuiltRecord(TypedDict):
    id: str
    route_id: str
    design_revision: int
    as_built_length_feet: int
    splice_point_count_field_verified: int
    records_system_reference: str
    status: str
    length_variance_bp: int
    submitted_by_user_id: Optional[str]
    certified_by_user_id: Optional[str]
    certification_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


JsonDict = Dict[str, Any]
