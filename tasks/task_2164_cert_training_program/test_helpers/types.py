"""Domain types for the CERT Training Program API: entity TypedDicts, status enums, roles."""

from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_COORDINATOR = "ProgramCoordinator"
    INSTRUCTOR = "Instructor"
    SKILLS_EVALUATOR = "SkillsEvaluator"
    LOGISTICS_OFFICER = "LogisticsOfficer"
    EMERGENCY_MANAGER = "EmergencyManager"
    TRAINEE = "Trainee"
    AUDITOR = "Auditor"


class CohortStatus(str, Enum):
    RECRUITING = "RECRUITING"
    SCHEDULED = "SCHEDULED"
    IN_SESSION = "IN_SESSION"
    GRADUATION_REVIEW = "GRADUATION_REVIEW"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class ModuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class FacilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class InstructorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class ClassSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class EnrollmentStatus(str, Enum):
    APPLIED = "APPLIED"
    WAITLISTED = "WAITLISTED"
    ENROLLED = "ENROLLED"
    GRADUATED = "GRADUATED"
    WITHDRAWN = "WITHDRAWN"


class CurrencyStatus(str, Enum):
    NOT_CREDENTIALED = "NOT_CREDENTIALED"
    CURRENT = "CURRENT"
    LAPSING = "LAPSING"
    LAPSED = "LAPSED"
    REVOKED = "REVOKED"


class CompletionStatus(str, Enum):
    RECORDED = "RECORDED"
    SKILLS_PENDING = "SKILLS_PENDING"
    PASSED = "PASSED"
    FAILED = "FAILED"
    VOIDED = "VOIDED"


class CredentialStatus(str, Enum):
    ACTIVE = "ACTIVE"
    GRACE = "GRACE"
    EXPIRED = "EXPIRED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class RenewalTier(str, Enum):
    STANDARD = "STANDARD"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class KitType(str, Enum):
    BACKPACK_STANDARD = "BACKPACK_STANDARD"
    BACKPACK_ADVANCED = "BACKPACK_ADVANCED"
    RADIO_KIT = "RADIO_KIT"


class AssetStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    ISSUED = "ISSUED"
    RETIRED = "RETIRED"
    LOST = "LOST"


class AssetCondition(str, Enum):
    NEW = "NEW"
    SERVICEABLE = "SERVICEABLE"
    DAMAGED = "DAMAGED"
    WRITTEN_OFF = "WRITTEN_OFF"


class IssuanceStatus(str, Enum):
    ISSUED = "ISSUED"
    RETURNED = "RETURNED"
    LOST_WRITTEN_OFF = "LOST_WRITTEN_OFF"


class SettlementVariant(str, Enum):
    DEPRECIATED_WRITEOFF = "DEPRECIATED_WRITEOFF"
    FULL_REPLACEMENT = "FULL_REPLACEMENT"


class ExerciseType(str, Enum):
    TABLETOP = "TABLETOP"
    FUNCTIONAL = "FUNCTIONAL"
    FULL_SCALE = "FULL_SCALE"


class ExerciseStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    AAR_SUBMITTED = "AAR_SUBMITTED"
    AAR_ACCEPTED = "AAR_ACCEPTED"
    CANCELLED = "CANCELLED"


class RolePlayed(str, Enum):
    TEAM_LEADER = "TEAM_LEADER"
    SEARCH_RESCUE = "SEARCH_RESCUE"
    MEDICAL = "MEDICAL"
    LOGISTICS = "LOGISTICS"
    OBSERVER = "OBSERVER"


class ParticipationStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CREDITED = "CREDITED"
    VOIDED = "VOIDED"


class Severity(str, Enum):
    ROUTINE = "ROUTINE"
    URGENT = "URGENT"
    CRITICAL = "CRITICAL"


class ActivationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ROSTERED = "ROSTERED"
    ACTIVATED = "ACTIVATED"
    DEMOBILIZED = "DEMOBILIZED"
    CANCELLED = "CANCELLED"


class FillStatus(str, Enum):
    UNFILLED = "UNFILLED"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"


class AssignmentStatus(str, Enum):
    NOTIFIED = "NOTIFIED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    NO_RESPONSE = "NO_RESPONSE"
    DEPLOYED = "DEPLOYED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class AssignmentSource(str, Enum):
    AUTO_ROSTER = "AUTO_ROSTER"
    MANUAL_ADD = "MANUAL_ADD"


# --- Entity shapes.  Every entity in this API carries id, created_at,
# --- updated_at and version.


class Program(TypedDict):
    id: str
    name: str
    sponsor_agency: str
    jurisdiction_code: str
    equipment_budget_cents: int
    equipment_committed_cents: int
    active_member_count: int
    pending_graduation_count: int
    created_at: str
    updated_at: str
    version: int


class Cohort(TypedDict):
    id: str
    program_id: str
    cohort_code: str
    seat_capacity: int
    seats_confirmed: int
    seats_waitlisted: int
    session_window_start: str
    session_window_end: str
    delivered_contact_hours: float
    next_waitlist_position: int
    graduation_reviewer_user_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CurriculumModule(TypedDict):
    id: str
    module_code: str
    title: str
    contact_hours: float
    is_core: bool
    requires_skills_demo: bool
    refresher_eligible: bool
    sequence_index: int
    prerequisite_module_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    room_code: str
    capacity_seats: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Instructor(TypedDict):
    id: str
    full_name: str
    certification_expires_on: str
    max_daily_contact_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ClassSession(TypedDict):
    id: str
    cohort_id: str
    module_id: str
    facility_id: str
    instructor_id: str
    starts_at: str
    ends_at: str
    delivered_at: Optional[str]
    recorded_completion_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Trainee(TypedDict):
    id: str
    program_id: str
    cohort_id: str
    full_name: str
    email: str
    deployment_hold: bool
    enrollment_status: str
    currency_status: str
    waitlist_position: Optional[int]
    earned_contact_hours: float
    passed_core_count: int
    readiness_score: float
    equipment_liability_cents: int
    last_deployed_at: Optional[str]
    last_qualifying_activity_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ModuleCompletion(TypedDict):
    id: str
    trainee_id: str
    class_session_id: str
    module_id: str
    evaluator_id: Optional[str]
    attendance_minutes: int
    attendance_ratio: float
    demo_score: Optional[float]
    attempt_number: int
    credited_contact_hours: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Credential(TypedDict):
    id: str
    trainee_id: str
    credential_number: str
    issued_on: str
    term_start_on: str
    expires_on: str
    grace_ends_on: str
    reinstatement_count: int
    renewal_tier: str
    required_refresher_hours: float
    refresher_hours_in_term: float
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentAsset(TypedDict):
    id: str
    program_id: str
    asset_tag: str
    kit_type: str
    unit_value_cents: int
    issue_count: int
    condition: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EquipmentIssuance(TypedDict):
    id: str
    trainee_id: str
    asset_id: str
    kit_type: str
    issued_on: str
    returned_on: Optional[str]
    lost_reported_on: Optional[str]
    months_held: Optional[int]
    residual_pct: Optional[float]
    settlement_cents: int
    settlement_variant: Optional[str]
    issued_by_user_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Exercise(TypedDict):
    id: str
    program_id: str
    title: str
    exercise_type: str
    starts_at: str
    ends_at: str
    base_credit_hours: float
    aar_summary: Optional[str]
    accepted_participant_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExerciseParticipation(TypedDict):
    id: str
    exercise_id: str
    trainee_id: str
    role_played: str
    role_multiplier: float
    hours_credited: float
    status: str
    created_at: str
    updated_at: str
    version: int


class Activation(TypedDict):
    id: str
    program_id: str
    incident_number: str
    requesting_agency: str
    severity: str
    requested_responders: int
    rostered_count: int
    accepted_count: int
    deployed_count: int
    response_deadline_at: Optional[str]
    fill_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RosterAssignment(TypedDict):
    id: str
    activation_id: str
    trainee_id: str
    selection_rank: int
    notified_at: Optional[str]
    responded_at: Optional[str]
    source: str
    status: str
    created_at: str
    updated_at: str
    version: int
