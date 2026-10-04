"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ACCREDITATION_OFFICER = "AccreditationOfficer"
    LABORATORY_DIRECTOR = "LaboratoryDirector"
    PT_COORDINATOR = "PTCoordinator"
    INSPECTOR = "Inspector"


class AccreditationStatus(str, Enum):
    APPLIED = "APPLIED"
    ENROLLED = "ENROLLED"
    ACCREDITED = "ACCREDITED"
    PROBATION = "PROBATION"
    ACCREDITATION_REVOKED = "ACCREDITATION_REVOKED"


class InspectorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class Discipline(str, Enum):
    CHEMISTRY = "CHEMISTRY"
    HEMATOLOGY = "HEMATOLOGY"
    MICROBIOLOGY = "MICROBIOLOGY"
    IMMUNOLOGY = "IMMUNOLOGY"
    MOLECULAR = "MOLECULAR"
    TRANSFUSION = "TRANSFUSION"


class EnrollmentStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CEASED = "CEASED"


class Standing(str, Enum):
    SATISFACTORY = "SATISFACTORY"
    UNSATISFACTORY = "UNSATISFACTORY"


class ChecklistStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    CHECKLIST_INVALIDATED = "CHECKLIST_INVALIDATED"


class ShipmentStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class ClosureReason(str, Enum):
    ADMIN_CLOSED = "ADMIN_CLOSED"
    DEADLINE_ELAPSED = "DEADLINE_ELAPSED"


class ResultStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    GRADED = "GRADED"
    VOID = "VOID"


class InvestigationStatus(str, Enum):
    OPEN = "OPEN"
    UNDER_REVIEW = "UNDER_REVIEW"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"
    RESOLVED = "RESOLVED"
    TESTING_CEASED = "TESTING_CEASED"


class TriggerVariant(str, Enum):
    PER_EVENT = "PER_EVENT"
    ROLLING = "ROLLING"
    BOTH = "BOTH"


class CycleStatus(str, Enum):
    TEAM_ASSEMBLY = "TEAM_ASSEMBLY"
    SCREENED = "SCREENED"
    CONDUCTED = "CONDUCTED"
    FINDINGS_ISSUED = "FINDINGS_ISSUED"
    DECIDED = "DECIDED"
    APPEALED = "APPEALED"
    INTERIM_SELF_INSPECTION = "INTERIM_SELF_INSPECTION"
    RE_DECIDED = "RE_DECIDED"


class Decision(str, Enum):
    ACCREDITED = "ACCREDITED"
    CONDITIONAL = "CONDITIONAL"
    DENIED = "DENIED"


class TeamRole(str, Enum):
    LEAD = "LEAD"
    MEMBER = "MEMBER"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    CONFLICTED = "CONFLICTED"
    REPLACED = "REPLACED"


class DeficiencyLevel(str, Enum):
    LEVEL_1 = "LEVEL_1"
    LEVEL_2 = "LEVEL_2"


class FindingStatus(str, Enum):
    CITED = "CITED"
    RESPONSE_SUBMITTED = "RESPONSE_SUBMITTED"
    ACCEPTED = "ACCEPTED"
    ESCALATED = "ESCALATED"
    WITHDRAWN = "WITHDRAWN"


class PersonnelRole(str, Enum):
    DIRECTOR = "DIRECTOR"
    TECHNICAL_SUPERVISOR = "TECHNICAL_SUPERVISOR"
    TESTING_PERSONNEL = "TESTING_PERSONNEL"


class QualificationStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    QUALIFIED = "QUALIFIED"
    COMPETENCY_REVIEW = "COMPETENCY_REVIEW"
    DISQUALIFIED = "DISQUALIFIED"


class MethodValidationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class Laboratory(TypedDict, total=False):
    id: str
    name: str
    clia_number: str
    accreditation_status: str
    active_discipline_count: int
    created_at: str
    updated_at: str
    version: int


class InspectorProfile(TypedDict, total=False):
    id: str
    full_name: str
    affiliated_laboratory_id: str
    specialties: list
    status: str
    created_at: str
    updated_at: str
    version: int


class DisciplineEnrollment(TypedDict, total=False):
    id: str
    laboratory_id: str
    discipline: str
    status: str
    standing_per_event: str
    standing_rolling: str
    unsuccessful_event_streak: int
    created_at: str
    updated_at: str
    version: int


class TestingSection(TypedDict, total=False):
    id: str
    enrollment_id: str
    section_name: str
    critical_testing: bool
    checklist_code: Optional[str]
    checklist_version: Optional[str]
    checklist_status: str
    created_at: str
    updated_at: str
    version: int


class PTSubscription(TypedDict, total=False):
    id: str
    enrollment_id: str
    analytes: list
    created_at: str
    updated_at: str
    version: int


class PTShipment(TypedDict, total=False):
    id: str
    subscription_id: str
    event_code: str
    shipped_at: str
    due_at: str
    status: str
    closure_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PTResult(TypedDict, total=False):
    id: str
    shipment_id: str
    collected_at: str
    analyte_scores: list
    event_score: Optional[float]
    event_evaluation: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PTInvestigation(TypedDict, total=False):
    id: str
    enrollment_id: str
    trigger_variant: str
    status: str
    corrective_action_notes: Optional[str]
    linked_result_ids: list
    created_at: str
    updated_at: str
    version: int


class InspectionCycle(TypedDict, total=False):
    id: str
    laboratory_id: str
    scheduled_start: str
    scheduled_end: str
    status: str
    posture_ready: bool
    deficiency_burden_score: int
    provisional_decision: Optional[str]
    final_decision: Optional[str]
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class TeamAssignment(TypedDict, total=False):
    id: str
    inspection_cycle_id: str
    inspector_id: str
    role_in_team: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InspectionFinding(TypedDict, total=False):
    id: str
    inspection_cycle_id: str
    section_id: str
    checklist_item_code: str
    deficiency_level: str
    cited_by_inspector_id: str
    response_due_at: Optional[str]
    response_text: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class PersonnelRecord(TypedDict, total=False):
    id: str
    enrollment_id: str
    person_name: str
    personnel_role: str
    qualification_status: str
    consecutive_failed_assessments: int
    created_at: str
    updated_at: str
    version: int


class CompetencyAssessment(TypedDict, total=False):
    id: str
    personnel_id: str
    assessed_at: str
    element_scores: list
    composite_score: float
    passed: bool
    valid_until: str
    created_at: str
    updated_at: str
    version: int


class MethodValidation(TypedDict, total=False):
    id: str
    enrollment_id: str
    method_name: str
    instrument_name: str
    correlation_r_squared: float
    precision_cv_pct: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ChecklistEditionSummary(TypedDict, total=False):
    id: str
    checklist_code: str
    checklist_version: str
    retires_checklist_version: Optional[str]
    retired_count: int
    created_at: str
    updated_at: str
    version: int
