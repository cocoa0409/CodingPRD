"""Domain types for the Athletics Eligibility and Scheduling service.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Role enum (PRD 2.1 - the seven roles, spelling exact and case-sensitive)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    SCHOOL_ATHLETIC_DIRECTOR = "SchoolAthleticDirector"
    REGISTRAR = "Registrar"
    ELIGIBILITY_REVIEWER = "EligibilityReviewer"
    MEDICAL_OFFICER = "MedicalOfficer"
    OFFICIALS_COORDINATOR = "OfficialsCoordinator"
    OFFICIAL = "Official"


# --------------------------------------------------------------------------
# Enumerated domain vocabularies
# --------------------------------------------------------------------------
class Sport(str, Enum):
    FOOTBALL = "FOOTBALL"
    BASKETBALL = "BASKETBALL"
    TRACK = "TRACK"
    SOCCER = "SOCCER"


class Classification(str, Enum):
    C1A = "C1A"
    C2A = "C2A"
    C3A = "C3A"
    C4A = "C4A"
    C5A = "C5A"


class SportTier(str, Enum):
    TIER_A = "TIER_A"
    TIER_B = "TIER_B"
    TIER_C = "TIER_C"


class SanctionStatus(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class StaffCredentialStatus(str, Enum):
    BACKGROUND_PENDING = "BACKGROUND_PENDING"
    CLEARED = "CLEARED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RoleTitle(str, Enum):
    HEAD_COACH = "HEAD_COACH"
    ASSISTANT_COACH = "ASSISTANT_COACH"


class SportSeasonStatus(str, Enum):
    PLANNED = "PLANNED"
    PRACTICE_OPEN = "PRACTICE_OPEN"
    REGULAR_SEASON = "REGULAR_SEASON"
    SEEDING_LOCKED = "SEEDING_LOCKED"
    PLAYOFFS = "PLAYOFFS"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class EligibilityStatus(str, Enum):
    INTAKE = "INTAKE"
    UNDER_REVIEW = "UNDER_REVIEW"
    UNDER_APPEAL = "UNDER_APPEAL"
    PROVISIONAL_ELIGIBLE = "PROVISIONAL_ELIGIBLE"
    ELIGIBLE = "ELIGIBLE"
    MEDICALLY_SUSPENDED = "MEDICALLY_SUSPENDED"
    INELIGIBLE = "INELIGIBLE"


class FeeStatus(str, Enum):
    ASSESSED = "ASSESSED"
    PARTIALLY_PAID = "PARTIALLY_PAID"
    PAID = "PAID"
    WAIVER_REQUESTED = "WAIVER_REQUESTED"
    WAIVED = "WAIVED"
    WAIVER_DENIED = "WAIVER_DENIED"
    REFUNDED = "REFUNDED"


class IneligibilityReason(str, Enum):
    AGE_LIMIT = "AGE_LIMIT"
    RESIDENCY_UNVERIFIED = "RESIDENCY_UNVERIFIED"
    TRANSFER_SITOUT = "TRANSFER_SITOUT"
    DOCS_INCOMPLETE = "DOCS_INCOMPLETE"
    ACADEMIC_GPA = "ACADEMIC_GPA"


class GpaVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class DocType(str, Enum):
    PHYSICAL = "PHYSICAL"
    PARENT_CONSENT = "PARENT_CONSENT"
    CONCUSSION_ACK = "CONCUSSION_ACK"


class DocumentFreshness(str, Enum):
    VALID = "VALID"
    EXPIRED = "EXPIRED"


class ContestStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OFFICIALS_ASSIGNED = "OFFICIALS_ASSIGNED"
    CONFIRMED = "CONFIRMED"
    PLAYED = "PLAYED"
    FORFEITED = "FORFEITED"


class HoldReason(str, Enum):
    COACH_CREDENTIAL_REVOKED = "COACH_CREDENTIAL_REVOKED"
    ADMIN_POSTPONE = "ADMIN_POSTPONE"


class CertificationLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"
    LEVEL_3 = "LEVEL_3"


class AssignmentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    WITHDRAWN = "WITHDRAWN"


class TransportStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class CancelledReason(str, Enum):
    SCHOOL_REQUEST = "SCHOOL_REQUEST"
    CONTEST_HOLD_CASCADE = "CONTEST_HOLD_CASCADE"


class InjuryType(str, Enum):
    CONCUSSION = "CONCUSSION"
    FRACTURE = "FRACTURE"
    SPRAIN = "SPRAIN"
    OTHER = "OTHER"


class InjuryStatus(str, Enum):
    REPORTED = "REPORTED"
    RTP_IN_PROGRESS = "RTP_IN_PROGRESS"
    CLEARED = "CLEARED"
    SEASON_ENDED = "SEASON_ENDED"


class TiebreakTrace(str, Enum):
    POWER_RATING = "POWER_RATING"
    RAW_WIN_PCT = "RAW_WIN_PCT"
    HEAD_TO_HEAD = "HEAD_TO_HEAD"
    FORFEIT_LOSSES = "FORFEIT_LOSSES"
    OPP_AVG_WIN_PCT = "OPP_AVG_WIN_PCT"
    CREATED_AT = "CREATED_AT"


# --------------------------------------------------------------------------
# Entity shapes.  Ten families carry id/created_at/updated_at/version;
# ClearanceDocument and PlayoffSeed carry only id and created_at.
# --------------------------------------------------------------------------
class School(TypedDict):
    id: str
    name: str
    classification: str
    region_code: str
    school_day_end_utc_hhmm: str
    bus_fleet_size: int
    max_release_minutes_per_request: int
    fee_cap_cents: int
    venue_concurrent_capacity: int
    sanction_status: str
    forfeit_count: int
    release_minutes_used: int
    fee_collected_cents: int
    credential_gap_sports: List[str]
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    school_id: str
    previous_school_id: Optional[str]
    full_name: str
    birth_date: str
    grade_level: int
    residency_verified: bool
    residency_verified_on: Optional[str]
    transfer_date: Optional[str]
    hardship_waiver_granted: bool
    free_reduced_lunch: bool
    gpa_prior_period: Optional[float]
    gpa_current_period: Optional[float]
    credits_prior_period: int
    credits_current_period: int
    academic_record_submitted_by: Optional[str]
    academic_record_submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class StaffCredential(TypedDict):
    id: str
    school_id: str
    coach_name: str
    sport: str
    role_title: str
    certification_expires_on: str
    status: str
    background_check_completed_on: Optional[str]
    background_check_reference: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SportSeason(TypedDict):
    id: str
    sport: str
    classification: str
    school_year: str
    sport_tier: str
    practice_start_date: str
    first_contest_date: str
    season_end_date: str
    age_cutoff_date: str
    residency_deadline: str
    grading_lock_date: str
    contest_limit: int
    required_officials: int
    status: str
    scheduled_contest_count: int
    seeded_school_count: int
    unseeded_school_count: int
    created_at: str
    updated_at: str
    version: int


class EligibilityCase(TypedDict):
    id: str
    student_id: str
    sport_season_id: str
    status: str
    fee_status: str
    ineligibility_reason: Optional[str]
    gpa_variant_applied: Optional[str]
    effective_gpa: Optional[float]
    fee_amount_cents: int
    fee_paid_cents: int
    fee_waived_cents: int
    fee_refunded_cents: int
    fee_outstanding_cents: int
    appeal_count: int
    evaluation_count: int
    provisional_revoked_at: Optional[str]
    activated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ClearanceDocument(TypedDict):
    # A filed form is never edited: no updated_at, no version.
    id: str
    eligibility_case_id: str
    doc_type: str
    issued_on: str
    expires_on: str
    signer_name: str
    status: str
    created_at: str


class Contest(TypedDict):
    id: str
    sport_season_id: str
    home_school_id: str
    away_school_id: str
    starts_at: str
    ends_at: str
    travel_miles: float
    is_playoff: bool
    status: str
    accepted_official_count: int
    home_score: Optional[int]
    away_score: Optional[int]
    forfeiting_school_id: Optional[str]
    hold_reason: Optional[str]
    result_recorded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Official(TypedDict):
    id: str
    full_name: str
    certification_level: str
    home_region_code: str
    accepted_assignment_count: int
    created_at: str
    updated_at: str
    version: int


class OfficialAssignment(TypedDict):
    id: str
    contest_id: str
    official_id: str
    status: str
    stipend_cents: Optional[int]
    responded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TransportRequest(TypedDict):
    id: str
    contest_id: str
    requesting_school_id: str
    bus_count: int
    travel_minutes: int
    depart_at: str
    return_at: str
    release_minutes: int
    status: str
    cancelled_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class InjuryReport(TypedDict):
    id: str
    student_id: str
    contest_id: Optional[str]
    injury_type: str
    reported_at: str
    reported_by_user_id: str
    status: str
    rtp_stage: int
    last_stage_advanced_at: Optional[str]
    recurrence_count: int
    cleared_by_user_id: Optional[str]
    cleared_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PlayoffSeed(TypedDict):
    # Seeds are minted once and never mutated: no updated_at, no version.
    id: str
    sport_season_id: str
    school_id: str
    wins: int
    losses: int
    forfeit_losses: int
    raw_win_pct: float
    opponent_avg_win_pct: float
    power_rating: float
    seed_number: int
    tiebreak_trace: str
    created_at: str
