"""Domain types: status enums, role enum, and entity TypedDicts.

All twelve primary resources carry the standard system-managed fields
(id, created_at, updated_at, version) per the PRD common-properties section.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    INCIDENT_COMMANDER = "IncidentCommander"
    OPERATIONS_LEAD = "OperationsLead"
    SAFETY_OFFICER = "SafetyOfficer"
    INTAKE_COORDINATOR = "IntakeCoordinator"
    PARTNER_LIAISON = "PartnerLiaison"
    TRAINING_DIRECTOR = "TrainingDirector"
    VOLUNTEER = "Volunteer"


class ReadinessStatus(str, Enum):
    REGISTERED = "REGISTERED"
    VETTED = "VETTED"
    DEPLOYABLE = "DEPLOYABLE"
    SUSPENDED = "SUSPENDED"
    INACTIVE = "INACTIVE"


class CertKind(str, Enum):
    CHAINSAW = "CHAINSAW"
    HEAVY_EQUIPMENT = "HEAVY_EQUIPMENT"
    STRUCTURAL = "STRUCTURAL"
    MEDICAL = "MEDICAL"


class Skill(str, Enum):
    CHAINSAW = "CHAINSAW"
    HEAVY_EQUIPMENT = "HEAVY_EQUIPMENT"
    STRUCTURAL = "STRUCTURAL"
    MEDICAL = "MEDICAL"
    LOGISTICS = "LOGISTICS"
    DEBRIS = "DEBRIS"


class CertificationStatus(str, Enum):
    PENDING_VERIFICATION = "PENDING_VERIFICATION"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"
    REJECTED = "REJECTED"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    ASSESSED = "ASSESSED"
    TYPED = "TYPED"
    STANDING_DOWN = "STANDING_DOWN"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class IncidentType(str, Enum):
    WIND = "WIND"
    FLOOD = "FLOOD"
    FIRE = "FIRE"
    EARTHQUAKE = "EARTHQUAKE"


class HazardKind(str, Enum):
    TREE_REMOVAL = "TREE_REMOVAL"
    MUCK_OUT = "MUCK_OUT"
    TARPING = "TARPING"
    DEBRIS = "DEBRIS"
    STRUCTURAL = "STRUCTURAL"


class OperationStatus(str, Enum):
    DRAFT = "DRAFT"
    OPEN = "OPEN"
    MUSTERED = "MUSTERED"
    ACTIVE = "ACTIVE"
    DEMOBILIZING = "DEMOBILIZING"
    COMPLETE = "COMPLETE"
    CANCELLED = "CANCELLED"


class AarStatus(str, Enum):
    NONE = "NONE"
    SUBMITTED = "SUBMITTED"
    ADOPTED = "ADOPTED"


class DeploymentStatus(str, Enum):
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    ON_SITE = "ON_SITE"
    SAFETY_HOLD = "SAFETY_HOLD"
    DEMOBED = "DEMOBED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    NO_SHOW = "NO_SHOW"


class DutyStatus(str, Enum):
    RESTING = "RESTING"
    ON_DUTY = "ON_DUTY"


class TravelMode(str, Enum):
    SELF = "SELF"
    TEAM_TRANSPORT = "TEAM_TRANSPORT"


class ShiftKind(str, Enum):
    OPERATIONS = "OPERATIONS"
    SAFETY_WATCH = "SAFETY_WATCH"
    LOGISTICS = "LOGISTICS"


class ShiftStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class WorkOrderStatus(str, Enum):
    INTAKE = "INTAKE"
    TRIAGED = "TRIAGED"
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    DONE_PENDING_VERIFICATION = "DONE_PENDING_VERIFICATION"
    VERIFIED_DONE = "VERIFIED_DONE"
    CANCELLED = "CANCELLED"


class PriorityTier(str, Enum):
    P1 = "P1"
    P2 = "P2"
    P3 = "P3"


class PartnerKind(str, Enum):
    EMERGENCY_MANAGEMENT = "EMERGENCY_MANAGEMENT"
    NONPROFIT = "NONPROFIT"
    LTRG = "LTRG"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    WAITLISTED = "WAITLISTED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    DROPPED = "DROPPED"


class WellnessReason(str, Enum):
    FATIGUE_THRESHOLD = "FATIGUE_THRESHOLD"
    LONG_DEPLOYMENT = "LONG_DEPLOYMENT"


class WellnessStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class Volunteer(TypedDict, total=False):
    id: str
    full_name: str
    email: str
    home_region: str
    skills: List[str]
    availability_windows: List[Dict[str, str]]
    instructor_certified: bool
    readiness_status: str
    operational_readiness_score: int
    readiness_score: int
    fatigue_hours: int
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    volunteer_id: str
    kind: str
    status: str
    issued_at: str
    expires_at: str
    verified_by_user_id: Optional[str]
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    name: str
    region: str
    status: str
    severity: Optional[int]
    affected_households: Optional[int]
    incident_type: Optional[str]
    reported_at: str
    created_at: str
    updated_at: str
    version: int


class Operation(TypedDict, total=False):
    id: str
    incident_id: str
    title: str
    hazard_focus: str
    team_size_required: int
    duration_days: int
    required_capabilities: List[str]
    start_date: str
    status: str
    aar_status: str
    aar_notes: Optional[str]
    aar_submitted_by_role: Optional[str]
    rostered_count: int
    capability_gap: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict, total=False):
    id: str
    operation_id: str
    volunteer_id: str
    status: str
    duty_status: str
    travel_mode: str
    needs_lodging: bool
    planned_start: str
    planned_end: str
    fob_site_id: Optional[str]
    checked_in_at: Optional[str]
    demobed_at: Optional[str]
    stipend_provisional_cents: int
    stipend_final_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class FobSite(TypedDict, total=False):
    id: str
    operation_id: str
    name: str
    bunks_total: int
    nightly_rate_cents: int
    bunks_occupied: int
    lodging_cost_cents: int
    created_at: str
    updated_at: str
    version: int


class DutyShift(TypedDict, total=False):
    id: str
    operation_id: str
    deployment_id: str
    kind: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkOrder(TypedDict, total=False):
    id: str
    incident_id: str
    operation_id: Optional[str]
    source_partner_id: Optional[str]
    requester_name: str
    hazard_kind: str
    vulnerable_resident: bool
    municipality_sourced: bool
    status: str
    priority_score: Optional[int]
    priority_tier: Optional[str]
    blocked_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PartnerAgency(TypedDict, total=False):
    id: str
    name: str
    kind: str
    contact_email: str
    created_at: str
    updated_at: str
    version: int


class TrainingCourse(TypedDict, total=False):
    id: str
    title: str
    grants_cert_kind: str
    capacity: int
    starts_at: str
    lead_instructor_volunteer_id: str
    seats_taken: int
    created_at: str
    updated_at: str
    version: int


class TrainingEnrollment(TypedDict, total=False):
    id: str
    course_id: str
    volunteer_id: str
    status: str
    waitlist_position: Optional[int]
    created_at: str
    updated_at: str
    version: int


class WellnessCheck(TypedDict, total=False):
    id: str
    deployment_id: str
    reason: str
    status: str
    resolved_notes: Optional[str]
    created_at: str
    updated_at: str
    version: int
