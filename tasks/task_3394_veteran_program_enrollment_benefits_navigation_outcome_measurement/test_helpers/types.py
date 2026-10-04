"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    ACCREDITED_REPRESENTATIVE = "AccreditedRepresentative"
    BENEFITS_OFFICER = "BenefitsOfficer"
    CLINICAL_PARTNER = "ClinicalPartner"
    CAREER_COUNSELOR = "CareerCounselor"
    EVENT_COORDINATOR = "EventCoordinator"
    OUTCOME_ANALYST = "OutcomeAnalyst"
    PROGRAM_MEMBER = "ProgramMember"


class MemberType(str, Enum):
    VETERAN = "VETERAN"
    FAMILY_SUPPORT = "FAMILY_SUPPORT"


class BranchOfService(str, Enum):
    ARMY = "ARMY"
    NAVY = "NAVY"
    AIR_FORCE = "AIR_FORCE"
    MARINES = "MARINES"
    COAST_GUARD = "COAST_GUARD"
    SPACE_FORCE = "SPACE_FORCE"


class ServiceEra(str, Enum):
    POST_911 = "POST_911"
    PRE_911_GULF = "PRE_911_GULF"
    VIETNAM_ERA = "VIETNAM_ERA"
    PEACETIME = "PEACETIME"


class InjuryConnection(str, Enum):
    SERVICE_CONNECTED = "SERVICE_CONNECTED"
    NON_SERVICE_CONNECTED = "NON_SERVICE_CONNECTED"


class VerificationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"


class EngagementStatus(str, Enum):
    INACTIVE = "INACTIVE"
    ENGAGED = "ENGAGED"
    GRADUATED = "GRADUATED"


class EligibilityCaseStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    PENDED = "PENDED"
    VERIFIED = "VERIFIED"
    DENIED = "DENIED"
    SUPERSEDED = "SUPERSEDED"


class ExternalRecordStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class ServiceCategory(str, Enum):
    MENTAL_HEALTH = "MENTAL_HEALTH"
    PHYSICAL_HEALTH = "PHYSICAL_HEALTH"
    CAREER = "CAREER"
    INDEPENDENCE = "INDEPENDENCE"
    BENEFITS = "BENEFITS"


class TrackCode(str, Enum):
    MENTAL_HEALTH = "MENTAL_HEALTH"
    PHYSICAL_HEALTH = "PHYSICAL_HEALTH"
    CAREER = "CAREER"
    INDEPENDENCE = "INDEPENDENCE"


class EnrollmentStatus(str, Enum):
    INTAKE = "INTAKE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    WITHDRAWN = "WITHDRAWN"


class IntensityTier(str, Enum):
    STANDARD = "STANDARD"
    ENHANCED = "ENHANCED"
    INTENSIVE = "INTENSIVE"


class ClaimType(str, Enum):
    DISABILITY_COMPENSATION = "DISABILITY_COMPENSATION"
    HEALTHCARE_ACCESS = "HEALTHCARE_ACCESS"


class ClaimStatus(str, Enum):
    FILED = "FILED"
    DECIDED = "DECIDED"
    APPEAL_PENDING = "APPEAL_PENDING"
    CLOSED = "CLOSED"


class ClaimOutcome(str, Enum):
    GRANTED = "GRANTED"
    DENIED = "DENIED"


class AppealStatus(str, Enum):
    OPEN = "OPEN"
    DECIDED = "DECIDED"


class AppealOutcome(str, Enum):
    UPHELD = "UPHELD"
    OVERTURNED = "OVERTURNED"


class Specialty(str, Enum):
    PTSD = "PTSD"
    TBI = "TBI"
    SUBSTANCE_USE = "SUBSTANCE_USE"
    DEPRESSION = "DEPRESSION"


class ReferralStatus(str, Enum):
    PENDING_MATCH = "PENDING_MATCH"
    MATCHED = "MATCHED"
    IN_TREATMENT = "IN_TREATMENT"
    DISCHARGED = "DISCHARGED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ReferralAction(str, Enum):
    ADMIT = "ADMIT"
    DISCHARGE = "DISCHARGE"


class PlacementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MILESTONE_30 = "MILESTONE_30"
    MILESTONE_90 = "MILESTONE_90"
    MILESTONE_180 = "MILESTONE_180"
    RETAINED = "RETAINED"
    SEPARATED = "SEPARATED"


class PlacementAction(str, Enum):
    CONFIRM_MILESTONE = "CONFIRM_MILESTONE"
    SEPARATE = "SEPARATE"


class Milestone(str, Enum):
    DAY_30 = "DAY_30"
    DAY_90 = "DAY_90"
    DAY_180 = "DAY_180"


class AccommodationNeed(str, Enum):
    WHEELCHAIR = "WHEELCHAIR"
    ASL_INTERPRETER = "ASL_INTERPRETER"
    SERVICE_ANIMAL = "SERVICE_ANIMAL"
    SENSORY_FRIENDLY = "SENSORY_FRIENDLY"


class RegistrationStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    WAITLISTED = "WAITLISTED"
    CANCELLED = "CANCELLED"
    ATTENDED = "ATTENDED"
    NO_SHOW = "NO_SHOW"
    EXPIRED = "EXPIRED"


class RegistrationAction(str, Enum):
    CANCEL = "CANCEL"
    ATTEND = "ATTEND"


class SurveyWave(str, Enum):
    BASELINE = "BASELINE"
    EXIT = "EXIT"
    FOLLOWUP_90 = "FOLLOWUP_90"


class SurveyStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    EXPIRED = "EXPIRED"


class Methodology(str, Enum):
    ITT = "ITT"
    COMPLETER = "COMPLETER"


# ---- Entity TypedDicts -------------------------------------------------
# Common-fielded entities carry id + created_at + updated_at + version.

class Member(TypedDict, total=False):
    id: str
    full_name: str
    member_type: str
    branch_of_service: Optional[str]
    service_era_claimed: str
    injury_connection_claimed: str
    verification_status: str
    verified_service_era: Optional[str]
    verified_injury_connection: Optional[str]
    engagement_status: str
    total_monthly_compensation_cents: int
    created_at: str
    updated_at: str
    version: int


class EligibilityCase(TypedDict, total=False):
    id: str
    member_id: str
    status: str
    pend_reason: Optional[str]
    denial_reason: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExternalServiceRecord(TypedDict, total=False):
    id: str
    member_id: str
    organization_name: str
    service_category: str
    start_date: str
    end_date: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ProgramTrack(TypedDict, total=False):
    id: str
    track_code: str
    name: str
    capacity: int
    active_enrollment_count: int
    created_at: str
    updated_at: str
    version: int


class Enrollment(TypedDict, total=False):
    id: str
    member_id: str
    program_track_id: str
    status: str
    intensity_tier: Optional[str]
    latest_acuity_score: Optional[int]
    coordination_consent: bool
    exit_disposition: Optional[str]
    exit_reason: Optional[str]
    exit_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only; only id + created_at, NO updated_at/version
class Assessment(TypedDict, total=False):
    id: str
    enrollment_id: str
    psych_score: int
    phys_score: int
    voc_score: int
    soc_score: int
    notes: Optional[str]
    acuity_score: int
    tier_result: str
    created_at: str


class BenefitsClaim(TypedDict, total=False):
    id: str
    member_id: str
    claim_type: str
    claimed_rating_pct: Optional[int]
    dependent_count: int
    coordination_consent: bool
    provisional_monthly_cents: Optional[int]
    decided_rating_pct: Optional[int]
    final_monthly_cents: Optional[int]
    outcome: Optional[str]
    decided_by_officer_id: Optional[str]
    decided_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Appeal(TypedDict, total=False):
    id: str
    claim_id: str
    grounds: Optional[str]
    status: str
    outcome: Optional[str]
    new_rating_pct: Optional[int]
    filed_at: str
    decided_by_officer_id: Optional[str]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Referral(TypedDict, total=False):
    id: str
    member_id: str
    partner_site_id: Optional[str]
    region: str
    required_specialty: str
    treatment_start: str
    treatment_end: str
    coordination_consent: bool
    request_seq: int
    status: str
    matched_at: Optional[str]
    admitted_at: Optional[str]
    discharged_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerSite(TypedDict, total=False):
    id: str
    name: str
    region: str
    specialties: List[str]
    capacity: int
    current_census: int
    created_at: str
    updated_at: str
    version: int


class EmployerPartner(TypedDict, total=False):
    id: str
    name: str
    industry: str
    open_requisitions: int
    created_at: str
    updated_at: str
    version: int


class Placement(TypedDict, total=False):
    id: str
    member_id: str
    employer_partner_id: str
    start_date: str
    salary_cents: int
    status: str
    separated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CommunityEvent(TypedDict, total=False):
    id: str
    name: str
    starts_at: str
    ends_at: str
    capacity: int
    accessibility_seat_count: int
    travel_budget_cents: int
    registered_count: int
    accessibility_seats_used: int
    travel_budget_remaining_cents: int
    created_at: str
    updated_at: str
    version: int


class EventRegistration(TypedDict, total=False):
    id: str
    member_id: str
    community_event_id: str
    accommodation_needs: List[str]
    travel_request_cents: int
    travel_award_cents: int
    queue_position: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OutcomeSurvey(TypedDict, total=False):
    id: str
    enrollment_id: str
    wave: str
    status: str
    window_open_at: str
    window_close_at: str
    q1: Optional[int]
    q2: Optional[int]
    q3: Optional[int]
    q4: Optional[int]
    q5: Optional[int]
    wellbeing_score: Optional[int]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# common_fields: false — immutable report; only id + created_at, NO updated_at/version
class DonorReport(TypedDict, total=False):
    id: str
    period_start: str
    period_end: str
    methodology: str
    track_weights: Optional[dict]
    cohort_size_total: int
    per_track: List[dict]
    overall_effect: float
    created_at: str
