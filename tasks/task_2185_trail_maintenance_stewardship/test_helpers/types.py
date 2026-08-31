"""Domain types: entity TypedDicts, status enums and the role enum (PRD sections 2 and 3)."""

from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    VOLUNTEER = "Volunteer"
    CREW_LEADER = "CrewLeader"
    STEWARDSHIP_COORDINATOR = "StewardshipCoordinator"
    LAND_MANAGER_OFFICER = "LandManagerOfficer"
    SAFETY_OFFICER = "SafetyOfficer"
    GRANTS_ADMINISTRATOR = "GrantsAdministrator"


class SegmentPosture(str, Enum):
    OPEN = "OPEN"
    HAZARD_RESTRICTED = "HAZARD_RESTRICTED"
    WET_RESTRICTED = "WET_RESTRICTED"
    SEASONAL_CLOSED = "SEASONAL_CLOSED"
    INCIDENT_CLOSED = "INCIDENT_CLOSED"


class AdoptionStatus(str, Enum):
    UNADOPTED = "UNADOPTED"
    ADOPTED = "ADOPTED"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED = "RETURNED"
    APPROVED = "APPROVED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class SuspensionReason(str, Enum):
    BUDGET_OVER_COMMIT = "BUDGET_OVER_COMMIT"
    SEGMENT_INCIDENT = "SEGMENT_INCIDENT"


class WorkPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    APPROVED = "APPROVED"
    CLOSED = "CLOSED"


class BudgetPosture(str, Enum):
    HEALTHY = "HEALTHY"
    TIGHT = "TIGHT"
    EXHAUSTED = "EXHAUSTED"
    OVER_COMMITTED = "OVER_COMMITTED"


class ConditionReportStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    TRIAGED = "TRIAGED"
    SCHEDULED = "SCHEDULED"
    DEFERRED = "DEFERRED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    VOIDED = "VOIDED"


class PriorityVariant(str, Enum):
    INITIAL_TRIAGE = "INITIAL_TRIAGE"
    REASSESSED = "REASSESSED"


class HazardType(str, Enum):
    BLOWDOWN = "BLOWDOWN"
    TREAD_EROSION = "TREAD_EROSION"
    DRAINAGE_FAILURE = "DRAINAGE_FAILURE"
    BRIDGE_DAMAGE = "BRIDGE_DAMAGE"
    SIGNAGE_MISSING = "SIGNAGE_MISSING"
    BRUSH_ENCROACHMENT = "BRUSH_ENCROACHMENT"


class SeverityClass(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ExposureClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TrafficClass(str, Enum):
    LIGHT = "LIGHT"
    MODERATE = "MODERATE"
    HEAVY = "HEAVY"


class SurfaceClass(str, Enum):
    NATIVE_SOIL = "NATIVE_SOIL"
    GRAVEL = "GRAVEL"
    BOARDWALK = "BOARDWALK"
    ROCK = "ROCK"


class PermitStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ISSUED = "ISSUED"
    DENIED = "DENIED"
    CONSUMED = "CONSUMED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class WorkType(str, Enum):
    TREAD_WORK = "TREAD_WORK"
    CHAINSAW = "CHAINSAW"
    BRIDGE_CONSTRUCTION = "BRIDGE_CONSTRUCTION"
    SIGNAGE = "SIGNAGE"
    BRUSHING = "BRUSHING"
    DRY_WORK = "DRY_WORK"


class ScheduleStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class ReadinessStatus(str, Enum):
    PENDING = "PENDING"
    BRIEFED = "BRIEFED"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class BlockReason(str, Enum):
    PERMIT_REVOKED = "PERMIT_REVOKED"
    PERMIT_EXPIRED = "PERMIT_EXPIRED"
    SEGMENT_CLOSED = "SEGMENT_CLOSED"
    AGREEMENT_SUSPENDED = "AGREEMENT_SUSPENDED"


class ShiftStatus(str, Enum):
    REGISTERED = "REGISTERED"
    CHECKED_IN = "CHECKED_IN"
    CHECKED_OUT = "CHECKED_OUT"
    HOURS_VERIFIED = "HOURS_VERIFIED"
    HOURS_DISPUTED = "HOURS_DISPUTED"
    HOURS_CERTIFIED = "HOURS_CERTIFIED"
    WITHDRAWN = "WITHDRAWN"
    NO_SHOW = "NO_SHOW"


class RoleOnCrew(str, Enum):
    CREW_MEMBER = "CREW_MEMBER"
    SAWYER = "SAWYER"
    FIRST_AIDER = "FIRST_AIDER"
    CREW_LEADER = "CREW_LEADER"


class SkillClass(str, Enum):
    GENERAL = "GENERAL"
    SKILLED_TRAIL = "SKILLED_TRAIL"
    CERTIFIED_SAWYER = "CERTIFIED_SAWYER"
    PROFESSIONAL = "PROFESSIONAL"


class Certification(str, Enum):
    CERT_FIRST_AID = "CERT_FIRST_AID"
    CERT_WFA = "CERT_WFA"
    CERT_SAWYER_B = "CERT_SAWYER_B"
    CERT_SAWYER_C = "CERT_SAWYER_C"
    CERT_TRAIL_SKILLS = "CERT_TRAIL_SKILLS"
    CERT_ENGINEER = "CERT_ENGINEER"
    CERT_CREW_LEADER = "CERT_CREW_LEADER"


class MaterialOrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class MaterialCategory(str, Enum):
    BRIDGE = "BRIDGE"
    SIGNAGE = "SIGNAGE"
    TOOLS = "TOOLS"
    DRAINAGE = "DRAINAGE"
    SURFACING = "SURFACING"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CLOSED = "CLOSED"


class IncidentSeverity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class GrantMatchVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    CERTIFIED = "CERTIFIED"


# --- Entity shapes.  PRD section 2.4: all eleven entity types carry the full
# --- set of id / created_at / updated_at / version.

class LandManager(TypedDict):
    id: str
    agency_name: str
    jurisdiction_code: str
    permit_required: bool
    permit_lead_days: int
    max_party_size: int
    wet_threshold_index: float
    requires_engineering_review: bool
    requires_certified_sawyer: bool
    policy_version: int
    adopted_segment_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerProfile(TypedDict):
    id: str
    full_name: str
    email: str
    waiver_signed_on: Optional[str]
    waiver_expires_on: Optional[str]
    certifications: List[str]
    first_aid_expires_on: Optional[str]
    skill_class: str
    lifetime_credited_hours: float
    pending_hours: float
    verified_hours: float
    certified_hours: float
    active_registration_count: int
    created_at: str
    updated_at: str
    version: int


class TrailSegment(TypedDict):
    id: str
    land_manager_id: str
    name: str
    length_miles: float
    surface_class: str
    traffic_class: str
    seasonal_closure_start_mmdd: Optional[str]
    seasonal_closure_end_mmdd: Optional[str]
    latest_soil_moisture_index: Optional[float]
    latest_moisture_observed_at: Optional[str]
    hazard_index: int
    escalated_hazard_count: int
    open_severe_incident_count: int
    posture: str
    adoption_status: str
    created_at: str
    updated_at: str
    version: int


class AdoptionAgreement(TypedDict):
    id: str
    trail_segment_id: str
    crew_leader_volunteer_id: str
    term_start_date: str
    term_end_date: str
    status: str
    revision_round: int
    pinned_policy_version: Optional[int]
    reviewed_by_user_id: Optional[str]
    activated_at: Optional[str]
    suspension_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkPlan(TypedDict):
    id: str
    adoption_agreement_id: str
    season_year: int
    requested_budget_cents: int
    approved_budget_cents: int
    committed_cents: int
    spent_cents: int
    available_cents: int
    budget_posture: str
    verified_volunteer_hours: float
    certified_volunteer_hours: float
    status: str
    revision_round: int
    created_at: str
    updated_at: str
    version: int


class ConditionReport(TypedDict):
    id: str
    trail_segment_id: str
    reported_by_volunteer_id: str
    hazard_type: str
    severity_class: str
    description: str
    exposure_class: Optional[str]
    traffic_class_snapshot: Optional[str]
    priority_score: int
    priority_variant: Optional[str]
    linked_work_party_id: Optional[str]
    defer_until_date: Optional[str]
    resolved_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkPermit(TypedDict):
    id: str
    work_plan_id: str
    trail_segment_id: str
    land_manager_id: str
    window_start_date: str
    window_end_date: str
    requested_work_types: List[str]
    allowed_work_types: Optional[List[str]]
    max_party_size: Optional[int]
    issued_by_user_id: Optional[str]
    issued_at: Optional[str]
    denial_reason: Optional[str]
    revocation_reason: Optional[str]
    consumed_party_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkParty(TypedDict):
    id: str
    work_plan_id: str
    trail_segment_id: str
    work_permit_id: Optional[str]
    start_at: str
    end_at: str
    work_type: str
    max_participants: int
    roster_capacity: int
    travel_allowance_minutes: int
    required_certifications: List[str]
    schedule_status: str
    readiness_status: str
    block_reason: Optional[str]
    briefing_delivered_at: Optional[str]
    briefing_leader_user_id: Optional[str]
    tool_checklist_complete: bool
    first_aid_kit_count: int
    registered_count: int
    checked_in_count: int
    first_aid_capable_count: int
    linked_report_count: int
    created_at: str
    updated_at: str
    version: int


class VolunteerShift(TypedDict):
    id: str
    work_party_id: str
    volunteer_id: str
    role_on_crew: str
    status: str
    checked_in_at: Optional[str]
    checked_out_at: Optional[str]
    worked_minutes: int
    billable_minutes: int
    credited_hours: float
    adjusted_hours: Optional[float]
    dispute_reason: Optional[str]
    skill_class_snapshot: Optional[str]
    hours_verified_by_user_id: Optional[str]
    hours_certified_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MaterialOrder(TypedDict):
    id: str
    work_plan_id: str
    condition_report_id: Optional[str]
    category: str
    lines: List[dict]
    line_subtotal_cents: int
    discount_pct: float
    discount_cents: int
    discounted_subtotal_cents: int
    freight_cents: int
    bridge_surcharge_cents: int
    total_cents: int
    engineering_review_ref: Optional[str]
    approved_by_user_id: Optional[str]
    delivered_at: Optional[str]
    cancellation_reason: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    work_party_id: str
    trail_segment_id: str
    injured_volunteer_id: Optional[str]
    severity_class: str
    first_aid_rendered: bool
    narrative: str
    occurred_at: str
    reported_by_user_id: str
    closed_by_user_id: Optional[str]
    corrective_action: Optional[str]
    closed_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
