"""Domain types: entity TypedDicts, status enums, role enum.

Field sets mirror the PRD's resource descriptions (PRD §2.5, §3.1–§3.8).
Top-level resources carry id/created_at/updated_at/version. Embedded records
(launch decisions, group seats, factual reports, readout sessions) carry their
own fields plus a server-minted sub-path id only — no updated_at, no version
(PRD §2.5).
"""
from enum import Enum
from typing import List, Optional, TypedDict

# ---------------------------------------------------------------------------
# Role enum (PRD §2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    DUTY_OFFICER = "DutyOfficer"
    MANAGING_DIRECTOR = "ManagingDirector"
    IIC = "IIC"
    GROUP_CHAIRMAN = "GroupChairman"
    PARTY_COORDINATOR = "PartyCoordinator"
    ADDRESSEE_CONTACT = "AddresseeContact"
    RECORDER_CUSTODIAN = "RecorderCustodian"
    DOCKET_OFFICER = "DocketOfficer"
    BOARD_ADMIN = "BoardAdmin"
    BOARD_MEMBER = "BoardMember"

# ---------------------------------------------------------------------------
# Status / kind enums
# ---------------------------------------------------------------------------

class AccidentCategory(str, Enum):
    AVIATION = "AVIATION"
    RAIL = "RAIL"
    HIGHWAY = "HIGHWAY"
    MARINE = "MARINE"
    PIPELINE = "PIPELINE"
    HAZMAT = "HAZMAT"

class AccidentCaseStatus(str, Enum):
    SCREENING = "SCREENING"
    LAUNCHED = "LAUNCHED"
    LIMITED_TRACK = "LIMITED_TRACK"
    DECLINED = "DECLINED"
    CLOSED_ADOPTED = "CLOSED_ADOPTED"

class LaunchMode(str, Enum):
    FULL_GO_TEAM = "FULL_GO_TEAM"
    LIMITED = "LIMITED"
    DECLINED = "DECLINED"

class LaunchDecisionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ADOPTED = "ADOPTED"
    SUPERSEDED = "SUPERSEDED"

class InvestigationPhase(str, Enum):
    GO_TEAM_ASSEMBLED = "GO_TEAM_ASSEMBLED"
    ON_SCENE = "ON_SCENE"
    FACTUAL = "FACTUAL"
    ANALYSIS = "ANALYSIS"
    BOARD_REVIEW = "BOARD_REVIEW"
    ADOPTED = "ADOPTED"

class DocketStatus(str, Enum):
    SEALED = "SEALED"
    OPEN = "OPEN"
    FINAL = "FINAL"

class OrgType(str, Enum):
    OPERATOR = "OPERATOR"
    MANUFACTURER = "MANUFACTURER"
    UNION = "UNION"
    REGULATOR = "REGULATOR"
    INDUSTRY_OTHER = "INDUSTRY_OTHER"
    CLAIMANT_COUNSEL = "CLAIMANT_COUNSEL"
    INSURER = "INSURER"

class PartyDesignationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPELLED = "EXPELLED"

class GroupSeatStatus(str, Enum):
    SEATED = "SEATED"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"

class ViolationKind(str, Enum):
    PREMATURE_PUBLIC_STATEMENT = "PREMATURE_PUBLIC_STATEMENT"
    UNAUTHORIZED_ANALYSIS_DISCLOSURE = "UNAUTHORIZED_ANALYSIS_DISCLOSURE"
    EX_PARTE_CONTACT = "EX_PARTE_CONTACT"

class GroupSpecialty(str, Enum):
    OPERATIONS = "OPERATIONS"
    STRUCTURES = "STRUCTURES"
    HUMAN_PERFORMANCE = "HUMAN_PERFORMANCE"
    RECORDERS = "RECORDERS"

class InvestigativeGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    DISBANDED = "DISBANDED"

class ReportKind(str, Enum):
    GROUP_FACTUAL = "GROUP_FACTUAL"
    RECORDER_TRANSCRIPT = "RECORDER_TRANSCRIPT"
    SPECIALIST = "SPECIALIST"

class FactualReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    DOCKETED = "DOCKETED"

class RecorderType(str, Enum):
    CVR = "CVR"
    FDR = "FDR"
    OTHER = "OTHER"

class RecorderCondition(str, Enum):
    INTACT = "INTACT"
    DAMAGED = "DAMAGED"
    SEVERELY_DAMAGED = "SEVERELY_DAMAGED"

class RecorderPackageStatus(str, Enum):
    SECURED = "SECURED"
    IN_READOUT = "IN_READOUT"
    READOUT_COMPLETE = "READOUT_COMPLETE"
    RELEASED = "RELEASED"

class ReadoutSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETE = "COMPLETE"

class SafetyRecommendationStatus(str, Enum):
    OPEN_AWAITING_RESPONSE = "OPEN_AWAITING_RESPONSE"
    OPEN_UNCLASSIFIED = "OPEN_UNCLASSIFIED"
    OPEN_ACCEPTABLE = "OPEN_ACCEPTABLE"
    OPEN_UNACCEPTABLE = "OPEN_UNACCEPTABLE"
    CLOSED_ACCEPTABLE = "CLOSED_ACCEPTABLE"
    CLOSED_UNACCEPTABLE = "CLOSED_UNACCEPTABLE"
    CLOSED_EXCEEDS = "CLOSED_EXCEEDS"

class ResponseClassification(str, Enum):
    ACCEPTABLE = "ACCEPTABLE"
    UNACCEPTABLE = "UNACCEPTABLE"

class AgingBucket(str, Enum):
    GREEN = "GREEN"
    AMBER = "AMBER"
    RED = "RED"

class BoardMeetingStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    COMPLETED = "COMPLETED"

class VotePosition(str, Enum):
    ADOPT = "ADOPT"
    REJECT = "REJECT"
    ABSTAIN = "ABSTAIN"
    # RETRACT is a request-only position (PRD §3.8): it removes the caller's
    # entry and is never stored on member_votes.
    RETRACT = "RETRACT"

class BoardOutcome(str, Enum):
    ADOPTED = "ADOPTED"
    NOT_ADOPTED = "NOT_ADOPTED"

# ---------------------------------------------------------------------------
# Embedded sub-record entry shapes (PRD §2.5, §3.4, §3.7, §3.8)
# ---------------------------------------------------------------------------

class ConductLogEntry(TypedDict):
    violation_kind: str
    detail: str
    recorded_at: str

class ResponseLogEntry(TypedDict):
    response_id: str
    response_text: str
    responded_at: str
    classification_pending: bool
    classification: Optional[str]
    classified_at: Optional[str]

class MemberVote(TypedDict):
    member_user_id: str
    position: str
    dissent_text: Optional[str]
    cast_at: str

# ---------------------------------------------------------------------------
# Embedded records (no updated_at / version of their own — PRD §2.5)
# ---------------------------------------------------------------------------

class LaunchDecision(TypedDict):
    decision_id: str
    mode: str
    status: str
    proposed_by_user_id: str
    proposed_at: str
    adopted_at: Optional[str]
    snapshot_statutory_score: float
    snapshot_risk_adjusted_score: float
    rationale: Optional[str]

class GroupSeat(TypedDict):
    seat_id: str
    group_id: str
    status: str
    strike_count: int
    conduct_log: List[ConductLogEntry]

class FactualReport(TypedDict):
    report_id: str
    report_kind: str
    content: str
    # Present exactly when report_kind == RECORDER_TRANSCRIPT; absent otherwise.
    recorder_id: Optional[str]
    status: str
    submitted_by_user_id: str
    submitted_at: str
    verified_at: Optional[str]

class ReadoutSession(TypedDict):
    session_id: str
    bench_id: str
    window_start_utc: str
    window_end_utc: str
    status: str

# ---------------------------------------------------------------------------
# Top-level resources (id + created_at + updated_at + version — PRD §2.5)
# ---------------------------------------------------------------------------

class AccidentCase(TypedDict):
    id: str
    report_number: str
    category: str
    occurred_at: str
    location_state: str
    fatalities_count: int
    injuries_count: int
    damage_estimate_cents: int
    is_public_transport: bool
    statutory_score: float
    risk_adjusted_score: float
    suggested_mode: str
    status: str
    launch_decisions: List[LaunchDecision]
    created_at: str
    updated_at: str
    version: int

class Investigation(TypedDict):
    id: str
    accident_case_id: str
    iic_user_id: str
    phase: str
    docket_status: str
    docket_completeness_pct: int
    created_at: str
    updated_at: str
    version: int

class PartyOrganization(TypedDict):
    id: str
    legal_name: str
    org_type: str
    created_at: str
    updated_at: str
    version: int

class PartyDesignation(TypedDict):
    id: str
    investigation_id: str
    organization_id: str
    status: str
    designated_at: str
    expulsion_reason: Optional[str]
    group_seats: List[GroupSeat]
    created_at: str
    updated_at: str
    version: int

class InvestigativeGroup(TypedDict):
    id: str
    investigation_id: str
    specialty: str
    chairman_user_id: str
    status: str
    seated_count: int
    factual_reports: List[FactualReport]
    created_at: str
    updated_at: str
    version: int

class RecorderPackage(TypedDict):
    id: str
    investigation_id: str
    recorder_type: str
    condition: str
    status: str
    readout_sessions: List[ReadoutSession]
    created_at: str
    updated_at: str
    version: int

class SafetyRecommendation(TypedDict):
    id: str
    investigation_id: str
    addressee_org_id: str
    recommendation_text: str
    status: str
    issued_at: str
    response_log: List[ResponseLogEntry]
    unacceptable_streak: int
    calendar_elapsed_days: int
    business_elapsed_days: int
    overdue: bool
    aging_bucket: str
    created_at: str
    updated_at: str
    version: int

class BoardMeeting(TypedDict):
    id: str
    investigation_id: str
    room_id: str
    window_start_utc: str
    window_end_utc: str
    sitting_member_ids: List[str]
    status: str
    member_votes: List[MemberVote]
    adopt_count: int
    reject_count: int
    abstain_count: int
    dissenting_member_ids: List[str]
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int

__all__ = [
    "UserRole",
    "AccidentCategory",
    "AccidentCaseStatus",
    "LaunchMode",
    "LaunchDecisionStatus",
    "InvestigationPhase",
    "DocketStatus",
    "OrgType",
    "PartyDesignationStatus",
    "GroupSeatStatus",
    "ViolationKind",
    "GroupSpecialty",
    "InvestigativeGroupStatus",
    "ReportKind",
    "FactualReportStatus",
    "RecorderType",
    "RecorderCondition",
    "RecorderPackageStatus",
    "ReadoutSessionStatus",
    "SafetyRecommendationStatus",
    "ResponseClassification",
    "AgingBucket",
    "BoardMeetingStatus",
    "VotePosition",
    "BoardOutcome",
    "ConductLogEntry",
    "ResponseLogEntry",
    "MemberVote",
    "LaunchDecision",
    "GroupSeat",
    "FactualReport",
    "ReadoutSession",
    "AccidentCase",
    "Investigation",
    "PartyOrganization",
    "PartyDesignation",
    "InvestigativeGroup",
    "RecorderPackage",
    "SafetyRecommendation",
    "BoardMeeting",
]
