"""Domain types for the Residence Life & RA Staffing API.

Entity TypedDicts, status enums and the role enum, all named exactly as the
PRD names them.  Every one of the fourteen resource types carries the full
quartet of ``id``, ``created_at``, ``updated_at`` and ``version``.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


# --------------------------------------------------------------------------
# Roles
# --------------------------------------------------------------------------
class UserRole(str, Enum):
    RESIDENCE_DIRECTOR = "ResidenceDirector"
    RESIDENT_ASSISTANT = "ResidentAssistant"
    CONDUCT_OFFICER = "ConductOfficer"
    BURSAR_OFFICER = "BursarOfficer"
    STUDENT = "Student"


# --------------------------------------------------------------------------
# Status / enum vocabularies
# --------------------------------------------------------------------------
class BuildingPosture(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    EMERGENCY_CLOSED = "EMERGENCY_CLOSED"


class CampusZone(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    WEST = "WEST"


class RoomStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    OCCUPIED = "OCCUPIED"
    OFFLINE = "OFFLINE"
    CONSOLIDATED = "CONSOLIDATED"


class ProgrammingComplianceStatus(str, Enum):
    PENDING = "PENDING"
    COMPLIANT = "COMPLIANT"
    DEFICIENT = "DEFICIENT"


class CoverageStatus(str, Enum):
    NORMAL = "NORMAL"
    CRITICAL = "CRITICAL"


class HousingStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    RELOCATION_PENDING = "RELOCATION_PENDING"


class ConductStanding(str, Enum):
    GOOD = "GOOD"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"


class ClassYear(str, Enum):
    FIRST_YEAR = "FIRST_YEAR"
    SOPHOMORE = "SOPHOMORE"
    JUNIOR = "JUNIOR"
    SENIOR = "SENIOR"


class ApplicationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    REVISION_REQUESTED = "REVISION_REQUESTED"
    OFFERED = "OFFERED"
    ACCEPTED = "ACCEPTED"
    DECLINED = "DECLINED"
    REJECTED = "REJECTED"


class EmploymentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SEPARATED = "SEPARATED"


class CertificationStatus(str, Enum):
    UNCERTIFIED = "UNCERTIFIED"
    IN_TRAINING = "IN_TRAINING"
    CERTIFIED = "CERTIFIED"
    LAPSED = "LAPSED"


class ModuleCode(str, Enum):
    CRISIS = "CRISIS"
    TITLE_IX = "TITLE_IX"
    FIRE_SAFETY = "FIRE_SAFETY"
    MEDIATION = "MEDIATION"
    DIVERSITY = "DIVERSITY"
    PROGRAMMING = "PROGRAMMING"


class ShiftType(str, Enum):
    WEEKDAY = "WEEKDAY"
    WEEKEND = "WEEKEND"
    BREAK = "BREAK"


class ShiftStatus(str, Enum):
    OPEN = "OPEN"
    ASSIGNED = "ASSIGNED"
    SWAP_PENDING = "SWAP_PENDING"
    CHECKED_IN = "CHECKED_IN"
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    VOID = "VOID"


class IncidentStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    RETURNED_FOR_DETAIL = "RETURNED_FOR_DETAIL"
    ROUTED_TO_CONDUCT = "ROUTED_TO_CONDUCT"
    CLOSED_NO_ACTION = "CLOSED_NO_ACTION"
    CLOSED_ADJUDICATED = "CLOSED_ADJUDICATED"


class Severity(str, Enum):
    MINOR = "MINOR"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class PolicyCode(str, Enum):
    ALCOHOL = "ALCOHOL"
    NOISE = "NOISE"
    GUEST = "GUEST"
    DAMAGE = "DAMAGE"
    SAFETY = "SAFETY"


class ConductCaseStatus(str, Enum):
    OPEN = "OPEN"
    HEARING_SCHEDULED = "HEARING_SCHEDULED"
    SANCTIONED = "SANCTIONED"
    DISMISSED = "DISMISSED"


class InspectionType(str, Enum):
    CHECK_IN = "CHECK_IN"
    CHECK_OUT = "CHECK_OUT"
    HEALTH_SAFETY = "HEALTH_SAFETY"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    SUPERSEDED = "SUPERSEDED"
    CANCELLED = "CANCELLED"


class ComponentCode(str, Enum):
    WALL = "WALL"
    DOOR = "DOOR"
    CARPET = "CARPET"
    FURNITURE = "FURNITURE"
    WINDOW = "WINDOW"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    BILLED = "BILLED"
    APPEALED = "APPEALED"
    SETTLED = "SETTLED"
    WAIVED = "WAIVED"
    VOID = "VOID"


class AppealOutcome(str, Enum):
    ADJUSTED = "ADJUSTED"
    UPHELD = "UPHELD"


class RoomChangeOrigin(str, Enum):
    SELF_REQUEST = "SELF_REQUEST"
    ROOMMATE_CONFLICT = "ROOMMATE_CONFLICT"
    EMERGENCY_RELOCATION = "EMERGENCY_RELOCATION"


class MediationStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    INTAKE = "INTAKE"
    SESSION_SCHEDULED = "SESSION_SCHEDULED"
    AGREEMENT_REACHED = "AGREEMENT_REACHED"
    IMPASSE = "IMPASSE"


class PlacementStatus(str, Enum):
    NONE = "NONE"
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    COMPLETED = "COMPLETED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"
    REVERTED = "REVERTED"


class ProgramCategory(str, Enum):
    SOCIAL = "SOCIAL"
    EDUCATIONAL = "EDUCATIONAL"
    WELLNESS = "WELLNESS"


class ProgramStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    HELD = "HELD"
    REIMBURSED = "REIMBURSED"
    DENIED = "DENIED"
    CANCELLED = "CANCELLED"


class ReceiptLineCategory(str, Enum):
    FOOD = "FOOD"
    SUPPLIES = "SUPPLIES"
    HONORARIUM = "HONORARIUM"


class BreakCode(str, Enum):
    THANKSGIVING = "THANKSGIVING"
    WINTER = "WINTER"
    SPRING = "SPRING"


class BreakRequestStatus(str, Enum):
    REQUESTED = "REQUESTED"
    APPROVED = "APPROVED"
    CHECKED_IN = "CHECKED_IN"
    DENIED = "DENIED"
    REVOKED = "REVOKED"
    CLOSED = "CLOSED"


class RevocationCause(str, Enum):
    EMERGENCY_CLOSURE = "EMERGENCY_CLOSURE"
    CONDUCT_INELIGIBLE = "CONDUCT_INELIGIBLE"


# --------------------------------------------------------------------------
# Entity shapes
# --------------------------------------------------------------------------
class Building(TypedDict):
    id: str
    name: str
    code: str
    campus_zone: str
    break_housing_enabled: bool
    posture: str
    closure_reason: Optional[str]
    last_posture_change_at: Optional[str]
    bed_capacity: int
    assigned_bed_count: int
    created_at: str
    updated_at: str
    version: int


class Floor(TypedDict):
    id: str
    building_id: str
    floor_number: int
    required_programs_per_term: int
    programming_budget_cents: int
    programming_encumbered_cents: int
    programming_spent_cents: int
    programming_available_cents: int
    programming_frozen: bool
    held_program_count: int
    programming_compliance_status: str
    uncovered_shift_count: int
    coverage_status: str
    bed_capacity: int
    occupied_beds: int
    created_at: str
    updated_at: str
    version: int


class Room(TypedDict):
    id: str
    floor_id: str
    room_number: str
    bed_capacity: int
    last_renovation_year: int
    occupied_beds: int
    status: str
    pre_closure_status: Optional[str]
    condition_score: int
    break_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Student(TypedDict):
    id: str
    full_name: str
    email: str
    class_year: str
    financial_hardship_flag: bool
    current_room_id: Optional[str]
    housing_status: str
    conduct_standing: str
    conduct_points: int
    judicial_hold: bool
    break_housing_eligible: bool
    damage_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class RAApplication(TypedDict):
    id: str
    applicant_student_id: str
    term_code: str
    essay_ref: str
    status: str
    interview_score: Optional[float]
    revision_count: int
    revision_notes: Optional[str]
    reviewed_by_user_id: Optional[str]
    submitted_at: Optional[str]
    created_ra_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RA(TypedDict):
    id: str
    student_id: str
    application_id: str
    assigned_floor_id: Optional[str]
    employment_status: str
    certification_status: str
    training_credits_earned: int
    completed_module_codes: List[str]
    certified_at: Optional[str]
    duty_points_balance: int
    missed_shift_count: int
    separation_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DutyShift(TypedDict):
    id: str
    floor_id: str
    shift_type: str
    start_at: str
    end_at: str
    assigned_ra_id: Optional[str]
    swap_requested_ra_id: Optional[str]
    status: str
    points_value: int
    checked_in_at: Optional[str]
    completed_at: Optional[str]
    filled_by_selector: bool
    created_at: str
    updated_at: str
    version: int


class IncidentReport(TypedDict):
    id: str
    filed_by_ra_id: str
    room_id: str
    subject_student_id: str
    occurred_at: str
    severity: str
    policy_code: str
    narrative: str
    status: str
    return_count: int
    submitted_at: Optional[str]
    routed_by_user_id: Optional[str]
    conduct_case_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConductCase(TypedDict):
    id: str
    incident_report_id: str
    respondent_student_id: str
    severity: str
    status: str
    opened_at: str
    hearing_at: Optional[str]
    scheduled_by_user_id: Optional[str]
    decided_by_user_id: Optional[str]
    prior_sanctioned_count: int
    sanction_points: Optional[int]
    outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoomInspection(TypedDict):
    id: str
    room_id: str
    inspector_ra_id: str
    inspection_type: str
    scheduled_for: str
    status: str
    condition_score: Optional[int]
    damage_lines: List[Dict[str, Any]]
    responsible_student_id: Optional[str]
    damage_charge_id: Optional[str]
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DamageCharge(TypedDict):
    id: str
    inspection_id: str
    student_id: str
    provisional_subtotal_cents: int
    assessed_subtotal_cents: Optional[int]
    depreciation_rate: Optional[float]
    admin_fee_cents: Optional[int]
    hardship_relief_cents: Optional[int]
    final_amount_cents: Optional[int]
    status: str
    billed_at: Optional[str]
    appeal_deadline_at: Optional[str]
    appeal_reason: Optional[str]
    appeal_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RoomChangeCase(TypedDict):
    id: str
    student_id: str
    roommate_student_id: Optional[str]
    from_room_id: str
    to_room_id: Optional[str]
    origin: str
    mediation_status: str
    placement_status: str
    mediation_round: int
    session_at: Optional[str]
    opened_by_user_id: str
    superseded_case_id: Optional[str]
    reverted_from_room_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProgramEvent(TypedDict):
    id: str
    floor_id: str
    organizer_ra_id: str
    title: str
    category: str
    scheduled_for: str
    requested_amount_cents: int
    status: str
    encumbered_amount_cents: int
    attendance_count: Optional[int]
    receipt_lines: List[Dict[str, Any]]
    reimbursed_amount_cents: Optional[int]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BreakHousingRequest(TypedDict):
    id: str
    student_id: str
    room_id: str
    break_code: str
    start_date: str
    end_date: str
    reason: str
    status: str
    decided_by_user_id: Optional[str]
    revocation_cause: Optional[str]
    checked_in_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
