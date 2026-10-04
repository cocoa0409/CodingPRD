"""Domain types: entity TypedDicts, status enums, role enum.

Field names mirror the PRD resource definitions exactly. Every primary
resource carries the common system fields id/created_at/updated_at/version,
with exactly one exception: ScopeItem carries only id and created_at.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    AFFILIATE_STAFF = "AffiliateStaff"
    ASSESSOR = "Assessor"
    HOMEOWNER = "Homeowner"
    VOLUNTEER = "Volunteer"
    TRADE_PARTNER = "TradePartner"
    SPONSOR_REP = "SponsorRep"
    ANONYMOUS = "Anonymous"
    ANY = "Any"  # pseudo-role: never sent on the wire


class PriorityMode(str, Enum):
    STANDARD = "STANDARD"
    HAZARD_PRIORITY = "HAZARD_PRIORITY"


class FundingCycleStatus(str, Enum):
    OPEN = "OPEN"
    SELECTION_OPEN = "SELECTION_OPEN"
    SEALED = "SEALED"
    CLOSED = "CLOSED"


class SelectionRunStatus(str, Enum):
    COMPUTED = "COMPUTED"
    APPLIED = "APPLIED"
    SUPERSEDED = "SUPERSEDED"
    DISCARDED = "DISCARDED"


class SponsorTier(str, Enum):
    COMMUNITY = "COMMUNITY"
    REGIONAL = "REGIONAL"
    NATIONAL = "NATIONAL"


class CommitmentStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    ALLOCATED = "ALLOCATED"
    WITHDRAWN = "WITHDRAWN"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_VERIFICATION = "UNDER_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    ASSESSING = "ASSESSING"
    ASSESSED = "ASSESSED"
    CANDIDATE = "CANDIDATE"
    SELECTED = "SELECTED"
    DEFERRED = "DEFERRED"
    WITHDRAWN = "WITHDRAWN"
    FULFILLED = "FULFILLED"


class AssessmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SCOPED = "SCOPED"
    CANCELLED = "CANCELLED"


class ScopeCategory(str, Enum):
    SAFETY = "SAFETY"
    ACCESSIBILITY = "ACCESSIBILITY"
    CRITICAL_SYSTEMS = "CRITICAL_SYSTEMS"
    ENERGY = "ENERGY"
    GENERAL = "GENERAL"


class Trade(str, Enum):
    NONE = "NONE"
    CARPENTRY = "CARPENTRY"
    ELECTRICAL = "ELECTRICAL"
    PLUMBING = "PLUMBING"
    ROOFING = "ROOFING"
    HVAC = "HVAC"


class ScopeItemStatus(str, Enum):
    INCLUDED = "INCLUDED"
    DROPPED = "DROPPED"
    COMPLETED = "COMPLETED"


class ProjectStatus(str, Enum):
    PLANNING = "PLANNING"
    READY = "READY"
    EVENT_SCHEDULED = "EVENT_SCHEDULED"
    IN_BUILD = "IN_BUILD"
    COMPLETED = "COMPLETED"
    WARRANTY_ACTIVE = "WARRANTY_ACTIVE"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ProjectCancellationReason(str, Enum):
    FUNDING_WITHDRAWN = "FUNDING_WITHDRAWN"
    STAFF_DECISION = "STAFF_DECISION"
    HOMEOWNER_WITHDRAWN = "HOMEOWNER_WITHDRAWN"


class ReadinessPosture(str, Enum):
    READY = "READY"
    BLOCKED = "BLOCKED"


class EventStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    EXECUTED = "EXECUTED"
    CANCELLED = "CANCELLED"


class VolunteerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    DEACTIVATED = "DEACTIVATED"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    CONFIRMED = "CONFIRMED"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    NO_SHOW = "NO_SHOW"
    WITHDRAWN = "WITHDRAWN"


class ContractorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WorkOrderStatus(str, Enum):
    QUOTE_REQUESTED = "QUOTE_REQUESTED"
    QUOTED = "QUOTED"
    APPROVED = "APPROVED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    PENDING_INSPECTION = "PENDING_INSPECTION"
    INSPECTION_FAILED = "INSPECTION_FAILED"
    INSPECTED = "INSPECTED"
    INVOICED = "INVOICED"
    PAID = "PAID"
    CANCELLED = "CANCELLED"


class InspectionOutcome(str, Enum):
    PASSED = "PASSED"
    FAILED = "FAILED"


class MaterialOrderStatus(str, Enum):
    ORDERED = "ORDERED"
    STAGED = "STAGED"
    DELIVERED = "DELIVERED"
    RETURNED = "RETURNED"


class WarrantyClaimStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    RESOLVED = "RESOLVED"


# --- Entity TypedDicts -------------------------------------------------------
# Common-field entities: id, created_at, updated_at, version.

class FundingCycle(TypedDict):
    id: str
    name: str
    fiscal_year: int
    total_budget_cents: int
    priority_mode: str
    status: str
    pool_cents: int
    reserved_cents: int
    spent_cents: int
    available_cents: int
    created_at: str
    updated_at: str
    version: int


class SelectionRun(TypedDict):
    id: str
    funding_cycle_id: str
    status: str
    priority_mode_snapshot: str
    ranked_application_ids: List[str]
    selected_application_ids: List[str]
    applied_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Sponsor(TypedDict):
    id: str
    name: str
    contact_email: str
    sponsor_tier: str
    created_at: str
    updated_at: str
    version: int


class SponsorshipCommitment(TypedDict):
    id: str
    sponsor_id: str
    funding_cycle_id: str
    amount_cents: int
    team_build_event_date: Optional[str]
    status: str
    received_at: Optional[str]
    allocated_amount_cents: int
    withdrawn_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeownerApplication(TypedDict):
    id: str
    funding_cycle_id: str
    homeowner_name: str
    date_of_birth: str
    household_size: int
    household_income_cents: int
    is_veteran: bool
    has_disability: bool
    ownership_doc_provided: bool
    occupancy_doc_provided: bool
    address: str
    status: str
    is_older_adult: bool
    priority_score: int
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HomeAssessment(TypedDict):
    id: str
    application_id: str
    scheduled_on: str
    status: str
    safety_hazard_max_severity: int
    accessibility_needs_count: int
    critical_systems_notes: Optional[str]
    completed_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScopeItem(TypedDict):
    """Append-only: carries ONLY id + created_at (no updated_at, no version)."""

    id: str
    assessment_id: str
    category: str
    required_trade: str
    volunteer_performable: bool
    requires_permit: bool
    est_low_cents: int
    est_high_cents: int
    description: str
    status: str
    midpoint_cents: int
    created_at: str


class Project(TypedDict):
    id: str
    application_id: str
    funding_cycle_id: str
    status: str
    cancellation_reason: Optional[str]
    readiness_posture: str
    provisional_estimate_cents: int
    envelope_cents: int
    reserved_balance_cents: int
    reconciled_cost_cents: int
    priority_score_snapshot: int
    completed_on: Optional[str]
    follow_up_completed_on: Optional[str]
    warranty_valid_until: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RebuildEvent(TypedDict):
    id: str
    project_id: str
    name: str
    event_date: str
    max_volunteers: int
    status: str
    open_slots: int
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    skills: List[str]
    team_leader_eligible: bool
    waiver_signed_on: Optional[str]
    safety_training_completed_on: Optional[str]
    status: str
    is_eligible: bool
    created_at: str
    updated_at: str
    version: int


class EventEnrollment(TypedDict):
    id: str
    event_id: str
    volunteer_id: str
    is_team_leader: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class TradeContractor(TypedDict):
    id: str
    legal_name: str
    trade: str
    license_number: str
    license_expires_on: str
    insurance_expires_on: str
    max_concurrent_jobs: int
    status: str
    strike_count: int
    created_at: str
    updated_at: str
    version: int


class TradeWorkOrder(TypedDict):
    id: str
    project_id: str
    contractor_id: str
    scope_item_ids: List[str]
    trade: str
    status: str
    quote_cents: Optional[int]
    invoice_cents: Optional[int]
    permit_number: Optional[str]
    visit_start: Optional[str]
    visit_end: Optional[str]
    inspected_on: Optional[str]
    cancellation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialOrderLine(TypedDict):
    item_name: str
    quantity: int
    unit_price_dollars: float


class MaterialOrder(TypedDict):
    id: str
    project_id: str
    supplier: Optional[str]
    lines: List[MaterialOrderLine]
    status: str
    subtotal_cents: int
    delivery_fee_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class WarrantyClaim(TypedDict):
    id: str
    project_id: str
    description: str
    claim_amount_cents: int
    status: str
    payout_cents: Optional[int]
    submitted_on: str
    resolution_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelectionApplyResult(TypedDict):
    """Response payload of the selection-run apply action (not an entity)."""

    applied_count: int
    project_ids: List[str]
    deferred_application_ids: List[str]
