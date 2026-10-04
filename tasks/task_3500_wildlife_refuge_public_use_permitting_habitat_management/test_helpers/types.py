"""Domain types: entity TypedDicts, status enums, role enum.

Every entity carries the standard system-managed fields (id, created_at,
updated_at, version — PRD §2.4). Domain date fields render as YYYY-MM-DD;
audit timestamps render as ISO 8601 with three fractional digits (PRD §2.4).
"""
from enum import Enum
from typing import Optional, TypedDict

__all__ = [
    "UserRole",
    "HabitatType", "AccessPosture",
    "DeterminationUseType", "PermitUseType",
    "DeterminationStatus", "DeterminationFinding",
    "CommentStatus", "CommentDisposition",
    "PermitStatus",
    "TreatmentType", "TreatmentStatus",
    "ClosureType", "ClosureScope", "ClosureStatus",
    "ProgramStatus", "BackgroundStatus", "AssignmentStatus",
    "OfferingStatus", "BidStatus",
    "AgreementStatus", "LedgerEntryType",
    "CitationSeverity", "CitationStatus",
    "ObjectiveStatus",
    "ManagementUnit", "CompatibilityDetermination", "PublicComment",
    "PermitApplication", "HabitatTreatment", "FacilityClosure",
    "InterpretiveProgram", "Volunteer", "VolunteerAssignment",
    "GrazingOffering", "CooperatorBid", "CooperativeAgreement",
    "Citation", "PopulationObjective", "UnitPostureSnapshot",
]


class UserRole(str, Enum):
    REFUGE_MANAGER = "RefugeManager"
    BIOLOGIST = "Biologist"
    PERMIT_OFFICER = "PermitOfficer"
    VOLUNTEER_COORDINATOR = "VolunteerCoordinator"
    LAW_ENFORCEMENT_OFFICER = "LawEnforcementOfficer"
    STATE_AGENCY_PARTNER = "StateAgencyPartner"
    PERMIT_APPLICANT = "PermitApplicant"
    COOPERATOR = "Cooperator"
    VOLUNTEER = "Volunteer"
    ANONYMOUS = "Anonymous"


class HabitatType(str, Enum):
    WETLAND = "WETLAND"
    GRASSLAND = "GRASSLAND"
    FOREST = "FOREST"
    MIXED = "MIXED"


class AccessPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    CLOSED = "CLOSED"


class DeterminationUseType(str, Enum):
    """Use types a compatibility determination may cover (includes GRAZING)."""
    RESEARCH = "RESEARCH"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    COMMERCIAL_FILMING = "COMMERCIAL_FILMING"
    GUIDED_ACTIVITY = "GUIDED_ACTIVITY"
    GRAZING = "GRAZING"


class PermitUseType(str, Enum):
    """Use types a permit application may request (no GRAZING)."""
    RESEARCH = "RESEARCH"
    PHOTOGRAPHY = "PHOTOGRAPHY"
    COMMERCIAL_FILMING = "COMMERCIAL_FILMING"
    GUIDED_ACTIVITY = "GUIDED_ACTIVITY"


class DeterminationStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLIC_COMMENT = "PUBLIC_COMMENT"
    ADJUDICATION = "ADJUDICATION"
    FINAL = "FINAL"


class DeterminationFinding(str, Enum):
    COMPATIBLE = "COMPATIBLE"
    NOT_COMPATIBLE = "NOT_COMPATIBLE"


class CommentStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    ADJUDICATED = "ADJUDICATED"


class CommentDisposition(str, Enum):
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    NOTED = "NOTED"


class PermitStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class TreatmentType(str, Enum):
    WATER_MANIPULATION = "WATER_MANIPULATION"
    PRESCRIBED_BURN = "PRESCRIBED_BURN"
    INVASIVE_CONTROL = "INVASIVE_CONTROL"


class TreatmentStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    WINDOW_OPEN = "WINDOW_OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    EXPIRED = "EXPIRED"


class ClosureType(str, Enum):
    NESTING = "NESTING"
    MIGRATION = "MIGRATION"
    HUNT_SAFETY = "HUNT_SAFETY"
    SPECIAL_EVENT = "SPECIAL_EVENT"


class ClosureScope(str, Enum):
    FULL = "FULL"
    TRAILS_ONLY = "TRAILS_ONLY"


class ClosureStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    ACTIVE = "ACTIVE"
    LIFTED = "LIFTED"


class ProgramStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class BackgroundStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class AssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RELEASED = "RELEASED"
    COMPLETED = "COMPLETED"


class OfferingStatus(str, Enum):
    OPEN = "OPEN"
    AWARDED = "AWARDED"
    EXPIRED = "EXPIRED"


class BidStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    WINNING = "WINNING"
    REJECTED = "REJECTED"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"


class LedgerEntryType(str, Enum):
    PAYMENT = "PAYMENT"
    REFUND = "REFUND"


class CitationSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class CitationStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ObjectiveStatus(str, Enum):
    NO_SURVEY = "NO_SURVEY"
    AT_TARGET = "AT_TARGET"
    BELOW_TARGET = "BELOW_TARGET"


# ---------------------------------------------------------------------------
# Entity TypedDicts (all entities carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------
class ManagementUnit(TypedDict):
    id: str
    name: str
    habitat_type: str
    acreage: int
    access_posture: str
    committed_visitor_days: int
    habitat_priority_breeding: int
    habitat_priority_annual: int
    created_at: str
    updated_at: str
    version: int


class CompatibilityDetermination(TypedDict):
    id: str
    use_type: str
    title: str
    comment_open_date: str
    comment_close_date: str
    status: str
    finding: Optional[str]
    rationale: Optional[str]
    unresolved_comment_count: int
    created_at: str
    updated_at: str
    version: int


class PublicComment(TypedDict):
    id: str
    determination_id: str
    author_name: str
    body: str
    status: str
    disposition: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermitApplication(TypedDict):
    id: str
    applicant_ref: str
    management_unit_id: str
    determination_id: str
    use_type: str
    crew_size: int
    start_date: str
    end_date: str
    status: str
    provisional_fee_cents: int
    assessed_fee_cents: Optional[int]
    revision_note: Optional[str]
    suspended_by_closure_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class HabitatTreatment(TypedDict):
    id: str
    management_unit_id: str
    treatment_type: str
    window_start: str
    window_end: str
    status: str
    notes: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FacilityClosure(TypedDict):
    id: str
    management_unit_id: str
    closure_type: str
    scope: str
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InterpretiveProgram(TypedDict):
    id: str
    management_unit_id: str
    title: str
    program_date: str
    min_volunteers: int
    max_volunteers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    full_name: str
    email: str
    background_status: str
    cleared_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class VolunteerAssignment(TypedDict):
    id: str
    volunteer_id: str
    program_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class GrazingOffering(TypedDict):
    id: str
    management_unit_id: str
    description: str
    aum_cap: int
    grazing_window_start: str
    grazing_window_end: str
    application_deadline: str
    min_stewardship_rating: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CooperatorBid(TypedDict):
    id: str
    offering_id: str
    cooperator_ref: str
    rate_cents_per_aum: int
    stewardship_rating: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CooperativeAgreement(TypedDict):
    id: str
    management_unit_id: str
    winning_bid_id: str
    cooperator_ref: str
    aum_cap: int
    grazing_window_start: str
    grazing_window_end: str
    compliance_points: int
    assessed_total_cents: int
    paid_total_cents: int
    refunded_total_cents: int
    outstanding_balance_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict):
    id: str
    severity: str
    points: int
    subject_permit_id: Optional[str]
    subject_agreement_id: Optional[str]
    note: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PopulationObjective(TypedDict):
    id: str
    management_unit_id: str
    species: str
    target_count: int
    current_survey_count: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class UnitPostureSnapshot(TypedDict):
    """Computed read shape returned by the unit posture endpoint."""
    access_posture: str
    committed_visitor_days: int
    habitat_priority_breeding: int
    habitat_priority_annual: int
    active_closure_count: int
