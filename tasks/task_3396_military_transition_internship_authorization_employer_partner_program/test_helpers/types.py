"""Domain types: entity TypedDicts, status enums, role enum.

Mirrors the resources and state vocabularies of the Military Transition
Internship API (PRD §2.5, §3). Ledger-style resources (SupervisionReport,
WageRecord, ConversionRecord) carry only ``id`` and ``created_at`` - they
have no ``updated_at`` and no ``version`` (PRD §2.5).
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_OFFICE = "ProgramOffice"
    TRANSITION_COUNSELOR = "TransitionCounselor"
    SERVICE_MEMBER = "ServiceMember"
    UNIT_COMMANDER = "UnitCommander"
    INSTALLATION_AUTHORITY = "InstallationAuthority"
    EMPLOYER_REP = "EmployerRep"


class ServiceBranch(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    SPACE_FORCE = "SPACE_FORCE"
    COAST_GUARD = "COAST_GUARD"


class ServiceStatus(str, Enum):
    ACTIVE_DUTY = "ACTIVE_DUTY"
    SEPARATED = "SEPARATED"


class TapStage(str, Enum):
    TAP_NOT_STARTED = "TAP_NOT_STARTED"
    PRESEPARATION_COUNSELING_DONE = "PRESEPARATION_COUNSELING_DONE"
    CORE_CURRICULUM_DONE = "CORE_CURRICULUM_DONE"
    CAPSTONE_DONE = "CAPSTONE_DONE"


class ApplicationStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    UNDER_APPEAL = "UNDER_APPEAL"


class AuthorizationStatus(str, Enum):
    PENDING_AUTHORIZATION = "PENDING_AUTHORIZATION"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    AUTHORIZATION_LAPSED = "AUTHORIZATION_LAPSED"
    REVOKED = "REVOKED"


class LocationType(str, Enum):
    ON_SITE = "ON_SITE"
    REMOTE = "REMOTE"


class OpeningStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class MatchStatus(str, Enum):
    PROPOSED = "PROPOSED"
    INSTALLATION_APPROVED = "INSTALLATION_APPROVED"
    INSTALLATION_DENIED = "INSTALLATION_DENIED"
    ACTIVE = "ACTIVE"
    COMPLETED = "COMPLETED"
    TERMINATED_EARLY = "TERMINATED_EARLY"
    MATCH_VOIDED = "MATCH_VOIDED"


class PlanStatus(str, Enum):
    PLAN_DRAFT = "PLAN_DRAFT"
    PLAN_SUBMITTED = "PLAN_SUBMITTED"
    PLAN_APPROVED = "PLAN_APPROVED"
    PLAN_RETURNED = "PLAN_RETURNED"


class ObjectiveStatus(str, Enum):
    PENDING = "PENDING"
    ACHIEVED = "ACHIEVED"
    EXCUSED = "EXCUSED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED_CLEARED = "CLOSED_CLEARED"
    CLOSED_SANCTIONED = "CLOSED_SANCTIONED"


class TerminationReason(str, Enum):
    VOLUNTARY = "VOLUNTARY"
    MEDICAL = "MEDICAL"
    EMPLOYER_REQUEST = "EMPLOYER_REQUEST"
    CONDUCT = "CONDUCT"
    SEPARATION = "SEPARATION"
    EMPLOYER_REVOKED = "EMPLOYER_REVOKED"


class LearningObjective(TypedDict, total=False):
    objective_code: str
    description: str
    weight_hours: int
    status: str


class Installation(TypedDict, total=False):
    id: str
    name: str
    command_code: str
    region_code: str
    max_internship_duration_days: int
    appeal_window_days: int
    requires_tap_complete: bool
    excluded_pay_grades: List[str]
    created_at: str
    updated_at: str
    version: int


class ServiceMember(TypedDict, total=False):
    id: str
    full_name: str
    service_branch: str
    pay_grade: str
    separation_date: str
    skills: List[str]
    home_installation_id: str
    service_status: str
    tap_stage: str
    active_match_count: int
    days_until_separation: int
    created_at: str
    updated_at: str
    version: int


class InternshipApplication(TypedDict, total=False):
    id: str
    service_member_id: str
    installation_id: str
    status: str
    submitted_at: str
    days_until_separation_at_submission: int
    decided_by_user_id: Optional[str]
    decision_reason: Optional[str]
    decided_at: Optional[str]
    appeal_count: int
    appeal_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Employer(TypedDict, total=False):
    id: str
    legal_name: str
    industry_code: str
    authorization_status: str
    authorized_at: Optional[str]
    next_review_due_date: Optional[str]
    pending_violations: int
    last_cleared_audit_at: Optional[str]
    last_compliance_score: Optional[float]
    created_at: str
    updated_at: str
    version: int


class EmployerOpening(TypedDict, total=False):
    id: str
    employer_id: str
    title: str
    required_skills: List[str]
    location_type: str
    region_code: Optional[str]
    capacity: int
    filled_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InternshipMatch(TypedDict, total=False):
    id: str
    internship_application_id: str
    employer_opening_id: str
    service_member_id: str
    employer_id: str
    installation_id: str
    start_date: str
    end_date: str
    match_status: str
    plan_status: str
    learning_objectives: List[LearningObjective]
    supervisor_name: Optional[str]
    weekly_hours: Optional[int]
    plan_revision_count: int
    flagged_wage_violation: bool
    resolution_ratio: float
    mastery_ratio: float
    completed_at: Optional[str]
    termination_reason: Optional[str]
    installation_decision_by: Optional[str]
    installation_decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SupervisionReport(TypedDict, total=False):
    # Ledger-style resource: id + created_at only (no updated_at, no version).
    id: str
    internship_match_id: str
    week_start_date: str
    hours_supervised: int
    objectives_achieved: List[str]
    objectives_excused: List[str]
    supervisor_name: str
    attestation_text: str
    created_at: str


class WageRecord(TypedDict, total=False):
    # Ledger-style resource: id + created_at only (no updated_at, no version).
    id: str
    internship_match_id: str
    period_start_date: str
    period_end_date: str
    amount_cents: int
    memo: Optional[str]
    is_violation: bool
    created_at: str


class ComplianceAudit(TypedDict, total=False):
    id: str
    employer_id: str
    status: str
    opened_at: str
    findings: List[Dict[str, Any]]
    compliance_score: Optional[float]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConversionRecord(TypedDict, total=False):
    # Ledger-style resource: id + created_at only (no updated_at, no version).
    id: str
    internship_match_id: str
    conversion_date: str
    offer_made: bool
    offer_accepted: bool
    hired: bool
    created_at: str
