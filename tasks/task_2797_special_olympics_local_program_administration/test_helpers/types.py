"""Domain types for the Special Olympics Local Program API.

Entity TypedDicts and status enumerations transcribed from the PRD.  Per PRD
§2.4 "There are no entities in this system that omit `updated_at` or
`version`: all thirteen resource types carry the full set", so every entity
below declares ``id``, ``created_at``, ``updated_at`` and ``version``.
"""

from enum import Enum
from typing import List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles (PRD §2.1)
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    PROGRAM_MANAGER = "ProgramManager"
    CREDENTIALING_OFFICER = "CredentialingOfficer"
    MEDICAL_REVIEWER = "MedicalReviewer"
    COACH = "Coach"
    COMPETITION_DIRECTOR = "CompetitionDirector"
    HEALTH_SCREENING_LEAD = "HealthScreeningLead"


# --------------------------------------------------------------------------
# Enumerations
# --------------------------------------------------------------------------
class CompliancePosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class Sport(str, Enum):
    ATHLETICS = "ATHLETICS"
    BOCCE = "BOCCE"
    BASKETBALL = "BASKETBALL"
    SWIMMING = "SWIMMING"


class RegistrationStatus(str, Enum):
    PENDING_MEDICAL = "PENDING_MEDICAL"
    ACTIVE = "ACTIVE"
    LAPSED = "LAPSED"
    WITHDRAWN = "WITHDRAWN"


class MedicalStatus(str, Enum):
    NONE = "NONE"
    PENDING_REVIEW = "PENDING_REVIEW"
    CLEARED = "CLEARED"
    RESTRICTED = "RESTRICTED"
    HOLD = "HOLD"


class WithdrawalReasonCode(str, Enum):
    MOVED_AWAY = "MOVED_AWAY"
    MEDICAL = "MEDICAL"
    FAMILY_REQUEST = "FAMILY_REQUEST"
    AGED_OUT = "AGED_OUT"
    INACTIVE = "INACTIVE"


class MedicalFormStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class MedicalRestriction(str, Enum):
    NONE = "NONE"
    NO_CONTACT = "NO_CONTACT"
    HEAT_SENSITIVE = "HEAT_SENSITIVE"
    NO_SWIMMING = "NO_SWIMMING"


class RejectionReasonCode(str, Enum):
    INCOMPLETE_ATTESTATION = "INCOMPLETE_ATTESTATION"
    STALE_EXAM = "STALE_EXAM"
    ILLEGIBLE = "ILLEGIBLE"
    PHYSICIAN_UNVERIFIED = "PHYSICIAN_UNVERIFIED"


class VolunteerClass(str, Enum):
    COACH = "COACH"
    UNIFIED_PARTNER = "UNIFIED_PARTNER"
    GENERAL_VOLUNTEER = "GENERAL_VOLUNTEER"


class VolunteerStatus(str, Enum):
    PROSPECT = "PROSPECT"
    CREDENTIALED = "CREDENTIALED"
    INACTIVE = "INACTIVE"


class CredentialStatus(str, Enum):
    INITIATED = "INITIATED"
    SCREENING_CLEARED = "SCREENING_CLEARED"
    TRAINING_COMPLETE = "TRAINING_COMPLETE"
    READY_TO_CERTIFY = "READY_TO_CERTIFY"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    EXPIRED = "EXPIRED"
    RENEWAL_IN_PROGRESS = "RENEWAL_IN_PROGRESS"


class ScreeningResult(str, Enum):
    CLEAR = "CLEAR"
    FLAGGED = "FLAGGED"
    DISQUALIFYING = "DISQUALIFYING"


class DenialReasonCode(str, Enum):
    DISQUALIFYING_SCREENING = "DISQUALIFYING_SCREENING"
    MINOR_AS_COACH = "MINOR_AS_COACH"


class SeasonStatus(str, Enum):
    PLANNING = "PLANNING"
    PRACTICE_OPEN = "PRACTICE_OPEN"
    DIVISIONED = "DIVISIONED"
    ENTRIES_LOCKED = "ENTRIES_LOCKED"
    COMPLETED = "COMPLETED"


class GamesLevel(str, Enum):
    LOCAL = "LOCAL"
    STATE = "STATE"
    NATIONAL = "NATIONAL"


class SessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    HELD = "HELD"
    VOIDED = "VOIDED"


class SessionVoidReasonCode(str, Enum):
    COACH_UNAVAILABLE = "COACH_UNAVAILABLE"
    WEATHER = "WEATHER"
    VENUE_LOST = "VENUE_LOST"
    CREDENTIAL_DENIED = "CREDENTIAL_DENIED"
    CREDENTIAL_EXPIRED = "CREDENTIAL_EXPIRED"


class AttendanceStatus(str, Enum):
    COUNTED = "COUNTED"
    NOT_COUNTED = "NOT_COUNTED"
    VOIDED = "VOIDED"


class RosterStatus(str, Enum):
    FORMING = "FORMING"
    COMPLIANT = "COMPLIANT"
    NON_COMPLIANT = "NON_COMPLIANT"


class MemberType(str, Enum):
    ATHLETE = "ATHLETE"
    PARTNER = "PARTNER"


class ParticipantType(str, Enum):
    ATHLETE = "ATHLETE"
    UNIFIED_TEAM = "UNIFIED_TEAM"


class EntryStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    DIVISIONED = "DIVISIONED"
    LOCKED = "LOCKED"
    RESULTED = "RESULTED"
    ADVANCED = "ADVANCED"
    DISQUALIFIED = "DISQUALIFIED"
    VOIDED = "VOIDED"


class AgeGroup(str, Enum):
    U12 = "U12"
    AGE_12_15 = "AGE_12_15"
    AGE_16_21 = "AGE_16_21"
    AGE_22_29 = "AGE_22_29"
    AGE_30_PLUS = "AGE_30_PLUS"


class AdvancementStatus(str, Enum):
    NOT_ADVANCED = "NOT_ADVANCED"
    ADVANCED_STATE = "ADVANCED_STATE"
    ADVANCED_NATIONAL = "ADVANCED_NATIONAL"
    INELIGIBLE_MAXING = "INELIGIBLE_MAXING"


class DisqualificationReasonCode(str, Enum):
    FALSE_START = "FALSE_START"
    LANE_VIOLATION = "LANE_VIOLATION"
    UNSPORTSMANLIKE = "UNSPORTSMANLIKE"
    NO_SHOW = "NO_SHOW"


class EntryVoidReasonCode(str, Enum):
    ATHLETE_MEDICAL_HOLD = "ATHLETE_MEDICAL_HOLD"
    ATHLETE_WITHDRAWN = "ATHLETE_WITHDRAWN"
    ROSTER_NON_COMPLIANT = "ROSTER_NON_COMPLIANT"


class DivisionStatus(str, Enum):
    DRAFT = "DRAFT"
    VALID = "VALID"
    UNDERSIZED = "UNDERSIZED"
    VOIDED = "VOIDED"


class ScreeningDiscipline(str, Enum):
    FUNFITNESS = "FUNFITNESS"
    OPENING_EYES = "OPENING_EYES"
    HEALTHY_HEARING = "HEALTHY_HEARING"
    SPECIAL_SMILES = "SPECIAL_SMILES"
    STRONG_MINDS = "STRONG_MINDS"


class FindingSeverity(str, Enum):
    ROUTINE = "ROUTINE"
    ADVISORY = "ADVISORY"
    URGENT = "URGENT"


class ReferralStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    REFERRED = "REFERRED"
    FOLLOW_UP_LOGGED = "FOLLOW_UP_LOGGED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"


class FollowupOutcome(str, Enum):
    LOGGED = "LOGGED"
    REREFER = "REREFER"
    RESOLVED = "RESOLVED"


class ContributionType(str, Enum):
    CASH_PLEDGE = "CASH_PLEDGE"
    CASH_RECEIPT = "CASH_RECEIPT"
    IN_KIND_GOODS = "IN_KIND_GOODS"
    IN_KIND_SERVICES = "IN_KIND_SERVICES"
    VOLUNTEER_HOURS = "VOLUNTEER_HOURS"


class ContributionDesignation(str, Enum):
    GENERAL = "GENERAL"
    COMPETITION = "COMPETITION"
    HEALTH_SCREENING = "HEALTH_SCREENING"
    FAMILY_ENGAGEMENT = "FAMILY_ENGAGEMENT"


class ContributionStatus(str, Enum):
    PLEDGED = "PLEDGED"
    RECEIVED = "RECEIVED"
    VOID = "VOID"


class ContributionVoidReasonCode(str, Enum):
    DONOR_RESCINDED = "DONOR_RESCINDED"
    DUPLICATE_ENTRY = "DUPLICATE_ENTRY"
    VALUATION_ERROR = "VALUATION_ERROR"
    PLEDGE_LAPSED = "PLEDGE_LAPSED"


# --------------------------------------------------------------------------
# Entity shapes (all thirteen carry id/created_at/updated_at/version)
# --------------------------------------------------------------------------
class Program(TypedDict):
    id: str
    name: str
    region_code: str
    compliance_posture: str
    certified_coach_count: int
    credential_denominator_count: int
    expired_credential_count: int
    expired_credential_ratio: float
    unresolved_urgent_referral_count: int
    active_athlete_count: int
    program_practice_minutes: int
    recognized_support_cents: int
    pledged_support_cents: int
    family_engagement_credit_cents: int
    sweep_epoch: int
    last_sweep_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Athlete(TypedDict):
    id: str
    program_id: str
    legal_name: str
    birth_date: str
    sport: str
    down_syndrome_flag: bool
    registration_status: str
    medical_status: str
    registration_expires_on: Optional[str]
    current_medical_form_id: Optional[str]
    cumulative_practice_minutes: int
    counted_session_count: int
    withdrawal_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MedicalForm(TypedDict):
    id: str
    athlete_id: str
    exam_date: str
    physician_name: str
    physician_license_id: str
    attestation_cardiac_clearance: bool
    attestation_seizure_history: bool
    attestation_atlantoaxial_screen: Optional[bool]
    restrictions: Optional[List[str]]
    status: str
    revision_count: int
    reviewed_by_user_id: Optional[str]
    approved_at: Optional[str]
    expires_on: str
    rejection_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Volunteer(TypedDict):
    id: str
    program_id: str
    full_name: str
    email: str
    date_of_birth: str
    volunteer_class: str
    is_minor: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    volunteer_id: str
    role_class: str
    status: str
    screening_result: Optional[str]
    screening_completed_on: Optional[str]
    screening_expires_on: Optional[str]
    screening_recorded_by_user_id: Optional[str]
    screening_vendor_reference: Optional[str]
    training_completed_on: Optional[str]
    training_expires_on: Optional[str]
    training_recorded_by_user_id: Optional[str]
    training_curriculum_code: Optional[str]
    certified_by_user_id: Optional[str]
    certified_at: Optional[str]
    flag_override_reason: Optional[str]
    expires_on: Optional[str]
    denial_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SportSeason(TypedDict):
    id: str
    program_id: str
    sport: str
    season_name: str
    practice_minimum_sessions: int
    practice_minimum_minutes: int
    registration_deadline: str
    divisioning_date: str
    competition_date: str
    games_level: str
    entry_slot_budget: int
    advancement_slots_per_division: int
    status: str
    divisioning_run_count: int
    entry_count: int
    divisioned_entry_count: int
    created_at: str
    updated_at: str
    version: int


class PracticeSession(TypedDict):
    id: str
    season_id: str
    coach_credential_id: str
    scheduled_start: str
    scheduled_end: str
    duration_minutes: int
    capacity_slots: int
    counts_toward_minimum: bool
    status: str
    recorded_attendance_count: int
    void_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AttendanceRecord(TypedDict):
    id: str
    session_id: str
    season_id: str
    athlete_id: str
    minutes_present: int
    required_minutes: int
    counted_minutes: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UnifiedTeam(TypedDict):
    id: str
    season_id: str
    team_name: str
    roster_status: str
    athlete_ids: List[str]
    partner_volunteer_ids: List[str]
    athlete_count: int
    partner_count: int
    age_span_years: int
    created_at: str
    updated_at: str
    version: int


class CompetitionEntry(TypedDict):
    id: str
    season_id: str
    participant_type: str
    participant_id: str
    event_code: str
    skill_score: float
    status: str
    division_id: Optional[str]
    seed_rank: Optional[int]
    age_on_competition_date: int
    age_group: str
    result_value: Optional[float]
    performance_ratio: Optional[float]
    placement: Optional[int]
    advancement_status: str
    disqualification_reason_code: Optional[str]
    void_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Division(TypedDict):
    id: str
    season_id: str
    event_code: str
    participant_type: str
    age_group: str
    ability_band_high: float
    ability_band_low: float
    ability_spread_ratio: float
    entry_count: int
    status: str
    merged_into_division_id: Optional[str]
    merged_source_count: int
    created_at: str
    updated_at: str
    version: int


class HealthScreening(TypedDict):
    id: str
    athlete_id: str
    event_name: str
    discipline: str
    screened_on: str
    finding_severity: str
    finding_note: Optional[str]
    referral_status: str
    referral_due_on: Optional[str]
    followup_count: int
    last_followup_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Contribution(TypedDict):
    id: str
    program_id: str
    donor_name: str
    contribution_type: str
    designation: str
    stated_value_cents: Optional[int]
    volunteer_hours: Optional[float]
    received_on: Optional[str]
    recognized_value_cents: int
    match_credit_cents: int
    status: str
    void_reason_code: Optional[str]
    created_at: str
    updated_at: str
    version: int
