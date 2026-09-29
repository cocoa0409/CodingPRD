"""Domain types: status enums, code-set enums, role enum and entity TypedDicts."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    OUTREACH_WORKER = "OutreachWorker"
    SHELTER_CASE_MANAGER = "ShelterCaseManager"
    REUNIFICATION_SPECIALIST = "ReunificationSpecialist"
    TLP_COORDINATOR = "TlpCoordinator"
    PROGRAM_ADMIN = "ProgramAdmin"
    YOUTH_MEMBER = "YouthMember"


class ProgramType(str, Enum):
    EMERGENCY_SHELTER = "EMERGENCY_SHELTER"
    TRANSITIONAL_LIVING = "TRANSITIONAL_LIVING"


class Posture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    FROZEN = "FROZEN"


class YouthStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ENGAGED = "ENGAGED"
    SHELTERED = "SHELTERED"
    TLP_ENROLLED = "TLP_ENROLLED"
    REUNIFIED_PENDING = "REUNIFIED_PENDING"
    REUNIFIED = "REUNIFIED"
    EXITED = "EXITED"


class RiskTier(str, Enum):
    LOW = "LOW"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class EngagementStage(str, Enum):
    FIRST_CONTACT = "FIRST_CONTACT"
    RAPPORT_BUILDING = "RAPPORT_BUILDING"
    SERVICE_OFFER = "SERVICE_OFFER"
    TRUST_ESTABLISHED = "TRUST_ESTABLISHED"


class BasicNeed(str, Enum):
    FOOD = "FOOD"
    HYGIENE_KIT = "HYGIENE_KIT"
    CLOTHING = "CLOTHING"
    TRANSIT_PASS = "TRANSIT_PASS"
    MEDICAL_REFERRAL = "MEDICAL_REFERRAL"


class IndicatorCode(str, Enum):
    THIRD_PARTY_CONTROL = "THIRD_PARTY_CONTROL"
    QUOTA_DEBT = "QUOTA_DEBT"
    COMMERCIAL_SEX = "COMMERCIAL_SEX"
    DOCUMENT_WITHHELD = "DOCUMENT_WITHHELD"
    RECRUITER_PRESENT = "RECRUITER_PRESENT"
    CURFEW_ENFORCED = "CURFEW_ENFORCED"


class ScreeningStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    CLEARED = "CLEARED"
    ESCALATED = "ESCALATED"


class SpecializedResponseCode(str, Enum):
    NONE = "NONE"
    ADVOCATE_ASSIGNED = "ADVOCATE_ASSIGNED"
    LAW_ENFORCEMENT_LIAISON = "LAW_ENFORCEMENT_LIAISON"
    EMERGENCY_RELOCATION = "EMERGENCY_RELOCATION"


class AdmissionStatus(str, Enum):
    PENDING_SCREENING = "PENDING_SCREENING"
    WAITLISTED = "WAITLISTED"
    ACTIVE = "ACTIVE"
    EXTENDED = "EXTENDED"
    DISCHARGE_SCHEDULED = "DISCHARGE_SCHEDULED"
    DISCHARGED = "DISCHARGED"
    DENIED = "DENIED"


class ExitDestination(str, Enum):
    FAMILY_REUNIFIED = "FAMILY_REUNIFIED"
    TRANSITIONAL_LIVING = "TRANSITIONAL_LIVING"
    INDEPENDENT_HOUSING = "INDEPENDENT_HOUSING"
    OTHER_SHELTER = "OTHER_SHELTER"
    UNKNOWN = "UNKNOWN"


class NotificationStatus(str, Enum):
    PENDING = "PENDING"
    ATTEMPTED = "ATTEMPTED"
    OVERDUE = "OVERDUE"
    CONTACTED = "CONTACTED"
    WAIVED = "WAIVED"
    LAW_ENFORCEMENT_REPORTED = "LAW_ENFORCEMENT_REPORTED"


class AttemptChannel(str, Enum):
    PHONE = "PHONE"
    IN_PERSON = "IN_PERSON"
    CERTIFIED_MAIL = "CERTIFIED_MAIL"
    EMAIL = "EMAIL"


class WaiverReason(str, Enum):
    ABUSE_DISCLOSED = "ABUSE_DISCLOSED"
    TRAFFICKING_RISK = "TRAFFICKING_RISK"
    COURT_ORDER = "COURT_ORDER"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    MEDIATION_SCHEDULED = "MEDIATION_SCHEDULED"
    MEDIATION_HELD = "MEDIATION_HELD"
    HOME_ASSESSMENT = "HOME_ASSESSMENT"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    AFTERCARE = "AFTERCARE"
    CLOSED = "CLOSED"
    SUPERSEDED = "SUPERSEDED"


class MediationOutcome(str, Enum):
    PROGRESS = "PROGRESS"
    IMPASSE = "IMPASSE"
    GUARDIAN_NO_SHOW = "GUARDIAN_NO_SHOW"
    AGREEMENT = "AGREEMENT"


class SafetyAssessmentResult(str, Enum):
    SAFE = "SAFE"
    CONDITIONAL = "CONDITIONAL"
    UNSAFE = "UNSAFE"


class TenancyStatus(str, Enum):
    PLACED = "PLACED"
    NOTICE_GIVEN = "NOTICE_GIVEN"
    EXITED = "EXITED"


class ComplianceStatus(str, Enum):
    IN_COMPLIANCE = "IN_COMPLIANCE"
    SAVINGS_DEFICIENT = "SAVINGS_DEFICIENT"
    PROBATION = "PROBATION"


class ExitReason(str, Enum):
    DURATION_LIMIT = "DURATION_LIMIT"
    INDEPENDENT_HOUSING = "INDEPENDENT_HOUSING"
    REUNIFIED = "REUNIFIED"
    NONCOMPLIANCE = "NONCOMPLIANCE"
    YOUTH_INITIATED = "YOUTH_INITIATED"


class SavingsEntryType(str, Enum):
    DEPOSIT = "DEPOSIT"
    WITHDRAWAL = "WITHDRAWAL"
    REVERSAL = "REVERSAL"


class LifeSkillsModule(str, Enum):
    BUDGETING = "BUDGETING"
    TENANCY = "TENANCY"
    EMPLOYMENT_READINESS = "EMPLOYMENT_READINESS"
    HEALTH_LITERACY = "HEALTH_LITERACY"
    CONFLICT_RESOLUTION = "CONFLICT_RESOLUTION"
    CIVIC_ENGAGEMENT = "CIVIC_ENGAGEMENT"


class EnrollmentType(str, Enum):
    PUBLIC_K12 = "PUBLIC_K12"
    GED_PROGRAM = "GED_PROGRAM"
    POSTSECONDARY = "POSTSECONDARY"
    VOCATIONAL = "VOCATIONAL"


class EnrollmentStatus(str, Enum):
    IMMEDIATE_ENROLLMENT = "IMMEDIATE_ENROLLMENT"
    VERIFIED = "VERIFIED"


class ProposalCategory(str, Enum):
    HOUSE_RULES = "HOUSE_RULES"
    PROGRAMMING = "PROGRAMMING"
    GRIEVANCE_PROCESS = "GRIEVANCE_PROCESS"
    FOOD_SERVICE = "FOOD_SERVICE"


class ProposalStatus(str, Enum):
    OPEN_FOR_VOTE = "OPEN_FOR_VOTE"
    ADOPTED = "ADOPTED"
    REJECTED = "REJECTED"


class VoteStance(str, Enum):
    SUPPORT = "SUPPORT"
    OPPOSE = "OPPOSE"


class VoteStatus(str, Enum):
    COUNTED = "COUNTED"
    RETRACTED = "RETRACTED"


# ─── Entity shapes ────────────────────────────────────
# Resources that carry the full audit set: id, created_at, updated_at, version.


class ShelterProgram(TypedDict):
    id: str
    name: str
    program_type: str
    licensed_bed_capacity: int
    min_age_years: int
    max_age_years: int
    max_stay_nights: int
    max_placement_days: int
    savings_match_rate_bp: int
    required_savings_rate_bp: int
    occupied_beds: int
    waitlisted_count: int
    overdue_notification_count: int
    utilization_bp: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class Youth(TypedDict):
    id: str
    legal_first_name: str
    legal_last_name: str
    date_of_birth: str
    age_years: int
    unaccompanied: bool
    status: str
    risk_posture: str
    trafficking_risk_score: int
    trafficking_risk_tier: str
    engagement_contact_count: int
    basic_needs_provision_count: int
    cumulative_shelter_nights: int
    lifetime_savings_deposited_cents: int
    governance_vote_eligible: bool
    intake_worker_user_id: str
    created_at: str
    updated_at: str
    version: int


class Admission(TypedDict):
    id: str
    youth_id: str
    program_id: str
    status: str
    requested_at: str
    admitted_at: Optional[str]
    planned_discharge_at: str
    discharged_at: Optional[str]
    projected_billable_nights: Optional[int]
    final_billable_nights: Optional[int]
    extension_count: int
    capacity_blocked: bool
    priority_score: int
    exit_destination: Optional[str]
    outcome_positive: Optional[bool]
    admitting_user_id: str
    created_at: str
    updated_at: str
    version: int


class GuardianNotification(TypedDict):
    id: str
    admission_id: str
    status: str
    attempt_count: int
    attempt_channel: Optional[str]
    last_attempt_at: Optional[str]
    due_at: str
    resolved_at: Optional[str]
    outcome: Optional[str]
    waiver_reason: Optional[str]
    runaway_report_filed_at: Optional[str]
    resolving_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SafetyScreening(TypedDict):
    id: str
    youth_id: str
    status: str
    indicator_codes: List[str]
    score: int
    tier: str
    specialized_response_code: str
    screened_at: str
    screener_user_id: str
    disposition_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReunificationCase(TypedDict):
    id: str
    youth_id: str
    guardian_household_label: str
    status: str
    opened_at: str
    mediation_round: int
    max_mediation_rounds: int
    safety_assessment_result: Optional[str]
    decision: Optional[str]
    decision_user_id: Optional[str]
    aftercare_plan_due_at: Optional[str]
    aftercare_contacts_completed: int
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MediationSession(TypedDict):
    id: str
    case_id: str
    round_number: int
    scheduled_start_at: str
    scheduled_end_at: str
    held_at: Optional[str]
    outcome: Optional[str]
    scheduler_user_id: str
    recorded_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TlpPlacement(TypedDict):
    id: str
    youth_id: str
    program_id: str
    tenancy_status: str
    compliance_status: str
    placed_at: str
    exited_at: Optional[str]
    exit_reason: Optional[str]
    documented_monthly_income_cents: int
    required_savings_cents: int
    savings_balance_cents: int
    match_awarded_cents: int
    consecutive_probation_reviews: int
    life_skills_credit_hours: int
    base_allowance_days: int
    earned_bonus_days: int
    allowance_days: int
    consumed_ratio_bp: int
    days_elapsed: int
    coordinator_user_id: str
    created_at: str
    updated_at: str
    version: int


class EducationEnrollment(TypedDict):
    id: str
    youth_id: str
    school_name: str
    enrollment_type: str
    status: str
    enrolled_at: str
    verified_at: Optional[str]
    records_waived: bool
    liaison_user_id: str
    created_at: str
    updated_at: str
    version: int


class GovernanceProposal(TypedDict):
    id: str
    program_id: str
    title: str
    category: str
    status: str
    voting_closes_at: str
    support_vote_count: int
    oppose_vote_count: int
    eligible_electorate_size: int
    support_ratio_bp: int
    adopted_at: Optional[str]
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class GovernanceVote(TypedDict):
    id: str
    proposal_id: str
    youth_id: str
    stance: str
    status: str
    cast_at: str
    retracted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable event records: these carry ONLY id and created_at — no updated_at
# and no version field at all.


class OutreachContact(TypedDict):
    id: str
    youth_id: str
    engagement_stage: str
    basic_needs_provided: List[str]
    indicator_flags: List[str]
    contacted_at: str
    worker_user_id: str
    created_at: str


class SavingsLedgerEntry(TypedDict):
    id: str
    placement_id: str
    entry_type: str
    amount_cents: int
    signed_amount_cents: int
    match_component_cents: int
    balance_after_cents: int
    source_note: Optional[str]
    posted_at: str
    recorded_by_user_id: str
    created_at: str


class LifeSkillsCompletion(TypedDict):
    id: str
    placement_id: str
    module_code: str
    credit_hours: int
    completed_at: str
    verified_by_user_id: str
    created_at: str
