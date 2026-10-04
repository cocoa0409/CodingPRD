"""Domain types: entity TypedDicts, status enums, role enum.

All eleven resources carry the full common-field set (id, created_at,
updated_at, version) per PRD common-properties rules.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD user/role model: 7 roles, two entity-backed)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    COMMITTEE_ADMIN = "CommitteeAdmin"
    CERTIFICATION_AUDITOR = "CertificationAuditor"
    NGB_ADMIN = "NGBAdmin"
    ATHLETE = "Athlete"
    SAFE_SPORT_OFFICER = "SafeSportOfficer"
    ARBITRATOR = "Arbitrator"
    RESULTS_OFFICIAL = "ResultsOfficial"


# ---------------------------------------------------------------------------
# Status / field enums
# ---------------------------------------------------------------------------

class GoverningBodyStatus(str, Enum):
    APPLIED = "APPLIED"
    CERTIFIED = "CERTIFIED"
    PROBATION = "PROBATION"
    INTERIM_MANAGED = "INTERIM_MANAGED"
    DECERTIFIED = "DECERTIFIED"


class ComplaintPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"


class CertificationCycleStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    REMEDIATION = "REMEDIATION"
    CLOSED_PASSED = "CLOSED_PASSED"
    CLOSED_FAILED = "CLOSED_FAILED"


class ComplaintCategory(str, Enum):
    GOVERNANCE = "GOVERNANCE"
    ATHLETE_REPRESENTATION = "ATHLETE_REPRESENTATION"
    FINANCIAL = "FINANCIAL"
    SAFE_SPORT = "SAFE_SPORT"
    SELECTION = "SELECTION"


class ComplaintSeverity(str, Enum):
    CRITICAL = "CRITICAL"
    MAJOR = "MAJOR"
    MINOR = "MINOR"


class ComplaintStatus(str, Enum):
    FILED = "FILED"
    TRIAGED = "TRIAGED"
    INVESTIGATING = "INVESTIGATING"
    SUBSTANTIATED = "SUBSTANTIATED"
    DISMISSED = "DISMISSED"


class EligibilityStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ELIGIBLE = "ELIGIBLE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class ScreeningStatus(str, Enum):
    SCREENING_PENDING = "SCREENING_PENDING"
    SCREENING_CLEARED = "SCREENING_CLEARED"
    SCREENING_FLAGGED = "SCREENING_FLAGGED"
    SCREENING_EXPIRED = "SCREENING_EXPIRED"


class EventGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class ResultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class PointsMethod(str, Enum):
    TRAILING_365 = "TRAILING_365"
    CALENDAR_SEASON = "CALENDAR_SEASON"


class FundingTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"
    NONE = "NONE"


class AgreementStatus(str, Enum):
    OFFERED = "OFFERED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class InsuranceStatus(str, Enum):
    INS_NONE = "INS_NONE"
    INS_ENROLLED = "INS_ENROLLED"
    INS_LAPSED = "INS_LAPSED"


class ReporterRole(str, Enum):
    ATHLETE = "ATHLETE"
    NGB_STAFF = "NGB_STAFF"
    PUBLIC = "PUBLIC"


class AbuseReportStatus(str, Enum):
    REPORTED = "REPORTED"
    FORWARDED = "FORWARDED"
    ADJUDICATED_SUBSTANTIATED = "ADJUDICATED_SUBSTANTIATED"
    ADJUDICATED_UNSUBSTANTIATED = "ADJUDICATED_UNSUBSTANTIATED"


class ProcStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    LOCKED = "LOCKED"
    SUPERSEDED = "SUPERSEDED"
    COMPLETED = "COMPLETED"


class TrialsStatus(str, Enum):
    TRIALS_NOT_OPEN = "TRIALS_NOT_OPEN"
    REGISTRATION_OPEN = "REGISTRATION_OPEN"
    HELD = "HELD"
    RESULTS_FINALIZED = "RESULTS_FINALIZED"


class EntryStatus(str, Enum):
    REGISTERED = "REGISTERED"
    QUALIFIED = "QUALIFIED"
    UNQUALIFIED = "UNQUALIFIED"


class RosterStatus(str, Enum):
    DRAFT = "DRAFT"
    NOMINATED = "NOMINATED"
    SUBMITTED = "SUBMITTED"
    CONFIRMED = "CONFIRMED"
    CANCELLED = "CANCELLED"


class SlotType(str, Enum):
    PRIMARY = "PRIMARY"
    ALTERNATE = "ALTERNATE"


class SlotStatus(str, Enum):
    NOMINATED = "NOMINATED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    PROMOTED = "PROMOTED"
    REMOVED = "REMOVED"


class AppealGrounds(str, Enum):
    SELECTION_PROCESS = "SELECTION_PROCESS"
    ELIGIBILITY = "ELIGIBILITY"
    SCORING_ERROR = "SCORING_ERROR"


class AppealStatus(str, Enum):
    FILED = "FILED"
    HEARING = "HEARING"
    UPHELD = "UPHELD"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class DealBasis(str, Enum):
    GROSS_BASIS = "GROSS_BASIS"
    NET_BASIS = "NET_BASIS"


class DealStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONSENT_GRANTED = "CONSENT_GRANTED"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


# ---------------------------------------------------------------------------
# Embedded sub-structures
# ---------------------------------------------------------------------------

class TrialsEntry(TypedDict, total=False):
    athlete_id: str
    entry_status: str
    score: Optional[float]
    result_recorded_at: Optional[str]


class RosterSlot(TypedDict, total=False):
    athlete_id: str
    slot_type: str
    slot_status: str
    rank: int
    composite_score: float
    trials_score: float
    season_points: float


# ---------------------------------------------------------------------------
# Entity TypedDicts — every resource carries id/created_at/updated_at/version
# ---------------------------------------------------------------------------

class GoverningBody(TypedDict, total=False):
    id: str
    name: str
    sport_code: str
    status: str
    certified_at: Optional[str]
    interim_manager_id: Optional[str]
    funding_budget_cents: int
    sport_science_pool_hours: int
    committed_monthly_stipend_cents: int
    allocated_science_hours: int
    substantiated_complaint_count: int
    complaint_posture: str
    created_at: str
    updated_at: str
    version: int


class CertificationCycle(TypedDict, total=False):
    id: str
    governing_body_id: str
    window_start: str
    window_end: str
    status: str
    governance_score: Optional[float]
    athlete_rep_score: Optional[float]
    financial_score: Optional[float]
    provisional_score: Optional[float]
    final_score: Optional[float]
    remediation_applied: bool
    opened_at: Optional[str]
    issued_by_user_id: Optional[str]
    closed_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Complaint(TypedDict, total=False):
    id: str
    governing_body_id: str
    category: str
    severity: str
    description: str
    status: str
    triaged_by_user_id: Optional[str]
    resolved_by_user_id: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict, total=False):
    id: str
    governing_body_id: str
    full_name: str
    date_of_birth: str
    team_sport: bool
    eligibility_status: str
    screening_status: str
    screening_expires_at: Optional[str]
    training_completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceResult(TypedDict, total=False):
    id: str
    athlete_id: str
    event_name: str
    event_grade: str
    placing: int
    event_date: str
    base_points: Optional[float]
    status: str
    verified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FundingAgreement(TypedDict, total=False):
    id: str
    athlete_id: str
    coverage_start: str
    coverage_end: str
    points_method: str
    trailing_points: float
    season_points: float
    tier: str
    monthly_stipend_cents: int
    status: str
    insurance_status: str
    insurance_enrolled_at: Optional[str]
    activated_at: Optional[str]
    science_hours_allocated: int
    created_at: str
    updated_at: str
    version: int


class AbuseReport(TypedDict, total=False):
    id: str
    athlete_id: str
    reporter_role: str
    allegation: str
    status: str
    forwarded_at: Optional[str]
    adjudicated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SelectionProcedure(TypedDict, total=False):
    id: str
    governing_body_id: str
    games_name: str
    trials_start: str
    trials_end: str
    registration_deadline: str
    qualifying_score: float
    quota_slots: int
    proc_status: str
    trials_status: str
    published_at: Optional[str]
    locked_at: Optional[str]
    entries: List[TrialsEntry]
    created_at: str
    updated_at: str
    version: int


class Roster(TypedDict, total=False):
    id: str
    selection_procedure_id: str
    status: str
    quota_effective: Optional[int]
    bonus_slot_applied: bool
    slots: List[RosterSlot]
    declined_athlete_ids: List[str]
    nominated_at: Optional[str]
    submitted_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    roster_id: str
    filed_by_athlete_id: str
    grounds: str
    status: str
    filed_at: str
    decision_rationale: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommercialDeal(TypedDict, total=False):
    id: str
    athlete_id: str
    sponsor_name: str
    gross_value_cents: int
    basis: str
    exclusivity_start: str
    exclusivity_end: str
    status: str
    committee_share_cents: Optional[int]
    ngb_share_cents: Optional[int]
    athlete_share_cents: Optional[int]
    consented_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
