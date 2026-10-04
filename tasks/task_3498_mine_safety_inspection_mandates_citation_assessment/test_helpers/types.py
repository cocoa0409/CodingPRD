"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3).

All twelve entities carry the uniform system-managed properties of PRD §2.4:
``id`` (server-minted dashed UUID), ``created_at`` / ``updated_at`` (ISO 8601 UTC
with exactly three fractional digits), and ``version`` (integer, +1 per mutation).
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ─── Roles (PRD §2.1) ─────────────────────────────────────────────────────────

class UserRole(str, Enum):
    MSHA_ADMIN = "MSHAAdmin"
    DISTRICT_MANAGER = "DistrictManager"
    INSPECTOR = "Inspector"
    OPERATOR_REP = "OperatorRep"
    COMMISSION_JUDGE = "CommissionJudge"
    PUBLIC_READER = "PublicReader"


# ─── Enumerations (PRD §3) ────────────────────────────────────────────────────

class MineType(str, Enum):
    UNDERGROUND = "UNDERGROUND"
    SURFACE = "SURFACE"


class MineStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IDLED = "IDLED"


class ProductionStatus(str, Enum):
    NORMAL = "NORMAL"
    HALTED = "HALTED"


class PovStatus(str, Enum):
    NONE = "NONE"
    POTENTIAL_POV = "POTENTIAL_POV"
    POV_FINAL = "POV_FINAL"


class Certification(str, Enum):
    UNDERGROUND = "UNDERGROUND"
    SURFACE = "SURFACE"
    BOTH = "BOTH"


class CycleStatus(str, Enum):
    OPEN = "OPEN"
    COMPLIANT = "COMPLIANT"
    DELINQUENT = "DELINQUENT"
    CURED = "CURED"


class InspectionKind(str, Enum):
    REGULAR = "REGULAR"
    SPOT = "SPOT"
    FOLLOW_UP = "FOLLOW_UP"
    ACCIDENT_INVESTIGATION = "ACCIDENT_INVESTIGATION"


class InspectionStatus(str, Enum):
    ASSIGNED = "ASSIGNED"
    FILE_REVIEWED = "FILE_REVIEWED"
    IN_PROGRESS = "IN_PROGRESS"
    SUSPENDED = "SUSPENDED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CitationKind(str, Enum):
    CITATION = "CITATION"
    ORDER = "ORDER"


class Negligence(str, Enum):
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    RECKLESS_DISREGARD = "RECKLESS_DISREGARD"


class GravityLikelihood(str, Enum):
    UNLIKELY = "UNLIKELY"
    REASONABLY_LIKELY = "REASONABLY_LIKELY"
    HIGHLY_LIKELY = "HIGHLY_LIKELY"


class GravitySeverity(str, Enum):
    NO_INJURY = "NO_INJURY"
    MINOR = "MINOR"
    SERIOUS = "SERIOUS"
    FATAL_POTENTIAL = "FATAL_POTENTIAL"


class AbatementStatus(str, Enum):
    OPEN = "OPEN"
    ABATED = "ABATED"
    VERIFIED = "VERIFIED"


class ContestStatus(str, Enum):
    UNCONTESTED = "UNCONTESTED"
    CONTESTED = "CONTESTED"
    AFFIRMED = "AFFIRMED"
    MODIFIED = "MODIFIED"
    VACATED = "VACATED"


class AssessmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    CONTESTED = "CONTESTED"
    FINAL = "FINAL"


class IdoStatus(str, Enum):
    ISSUED = "ISSUED"
    WITHDRAWAL_CONFIRMED = "WITHDRAWAL_CONFIRMED"
    ABATEMENT_VERIFIED = "ABATEMENT_VERIFIED"
    TERMINATED = "TERMINATED"


class ContestWorkflowStatus(str, Enum):
    FILED = "FILED"
    DOCKETED = "DOCKETED"
    DECIDED = "DECIDED"
    WITHDRAWN = "WITHDRAWN"


class ContestOutcome(str, Enum):
    AFFIRMED = "AFFIRMED"
    MODIFIED = "MODIFIED"
    VACATED = "VACATED"


class PlanType(str, Enum):
    VENTILATION = "VENTILATION"
    ROOF_CONTROL = "ROOF_CONTROL"
    EMERGENCY_RESPONSE = "EMERGENCY_RESPONSE"


class PlanStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    REVISION_DUE = "REVISION_DUE"


class AccidentSeverity(str, Enum):
    FATAL = "FATAL"
    LOST_TIME = "LOST_TIME"
    NO_LOST_TIME = "NO_LOST_TIME"


class AccidentStatus(str, Enum):
    REPORTED = "REPORTED"
    UNDER_INVESTIGATION = "UNDER_INVESTIGATION"
    REPORT_PUBLISHED = "REPORT_PUBLISHED"


class PovVariant(str, Enum):
    SCREENING = "SCREENING"
    FINAL_DETERMINATION = "FINAL_DETERMINATION"


class PovResult(str, Enum):
    POTENTIAL_POV = "POTENTIAL_POV"
    BELOW_THRESHOLD = "BELOW_THRESHOLD"
    CONFIRMED_POV = "CONFIRMED_POV"


# ─── Entity TypedDicts (PRD §2.4 common fields on every entity) ───────────────

class Operator(TypedDict, total=False):
    id: str
    legal_name: str
    annual_tonnage_tons: int
    home_district: str
    created_at: str
    updated_at: str
    version: int


class Mine(TypedDict, total=False):
    id: str
    operator_id: str
    mine_name: str
    mine_type: str
    activation_date: str          # plain ISO YYYY-MM-DD calendar date
    status: str                   # MineStatus
    production_status: str        # ProductionStatus
    pov_status: str               # PovStatus
    created_at: str
    updated_at: str
    version: int


class Inspector(TypedDict, total=False):
    id: str
    full_name: str
    badge_number: str
    district_code: str
    certification: str            # Certification
    conflicted_operator_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class InspectionCycle(TypedDict, total=False):
    id: str
    mine_id: str
    cycle_index: int
    period_start: str             # plain ISO YYYY-MM-DD, inclusive
    period_end: str               # plain ISO YYYY-MM-DD, inclusive
    required_inspections: int
    completed_inspections: int
    status: str                   # CycleStatus
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict, total=False):
    id: str
    mine_id: str
    cycle_id: Optional[str]       # required iff kind == REGULAR
    inspector_id: str
    kind: str                     # InspectionKind
    accident_id: Optional[str]    # required iff kind == ACCIDENT_INVESTIGATION
    planned_start_at: str
    planned_end_at: str
    file_reviewed_at: Optional[str]
    actual_entry_at: Optional[str]
    completed_at: Optional[str]
    status: str                   # InspectionStatus
    created_at: str
    updated_at: str
    version: int


class Citation(TypedDict, total=False):
    id: str
    inspection_id: Optional[str]        # null only for system-issued late-report citations
    mine_id: str
    issued_by_inspector_id: Optional[str]  # null only for system-issued citations
    standard_code: str
    kind: str                     # CitationKind
    negligence: str               # Negligence
    gravity_likelihood: str       # GravityLikelihood
    gravity_severity: str         # GravitySeverity
    persons_affected: int
    significant_and_substantial: bool
    repeat_violation: bool
    issued_at: str
    abatement_base_days: int
    abatement_deadline: str
    abatement_extended: bool
    abated_at: Optional[str]
    verified_at: Optional[str]
    verified_by_inspector_id: Optional[str]
    abatement_status: str         # AbatementStatus
    contest_status: str           # ContestStatus
    system_issued: bool
    created_at: str
    updated_at: str
    version: int


class PenaltyAssessment(TypedDict, total=False):
    id: str
    citation_id: str
    points_total: int
    proposed_penalty_cents: int
    final_penalty_cents: Optional[int]   # null until status FINAL
    good_faith_applied: bool
    statutory_floor_applied: bool
    status: str                   # AssessmentStatus
    created_at: str
    updated_at: str
    version: int


class ImminentDangerOrder(TypedDict, total=False):
    id: str
    mine_id: str
    inspection_id: Optional[str]         # null for POV-auto-generated orders
    issued_by_inspector_id: Optional[str]
    hazard_description: str
    issued_at: str
    miners_withdrawn_count: Optional[int]  # set on confirm-withdrawal
    withdrawal_confirmed_at: Optional[str]
    abatement_verified_at: Optional[str]
    verified_by_inspector_id: Optional[str]
    terminated_at: Optional[str]
    status: str                   # IdoStatus
    created_at: str
    updated_at: str
    version: int


class Contest(TypedDict, total=False):
    id: str
    citation_id: str
    filed_by_operator_id: str
    grounds: str
    filed_at: str
    status: str                   # ContestWorkflowStatus
    outcome: Optional[str]        # ContestOutcome; null until DECIDED
    modified_penalty_cents: Optional[int]
    decided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MinePlan(TypedDict, total=False):
    id: str
    mine_id: str
    plan_type: str                # PlanType
    revision_no: int
    document_ref: str
    submitted_at: str
    supersedes_plan_id: Optional[str]  # set on approval of a successor revision
    next_revision_due_at: Optional[str]  # approved_at + 180 days
    approved_at: Optional[str]
    rejection_reason: Optional[str]
    status: str                   # PlanStatus
    created_at: str
    updated_at: str
    version: int


class Accident(TypedDict, total=False):
    id: str
    mine_id: str
    occurred_at: str
    reported_at: str
    severity: str                 # AccidentSeverity
    description: str
    late_report: bool
    root_cause: Optional[str]     # required at publish-report
    report_text: Optional[str]    # required at publish-report
    published_at: Optional[str]
    status: str                   # AccidentStatus
    created_at: str
    updated_at: str
    version: int


class POVScreening(TypedDict, total=False):
    id: str
    mine_id: str
    variant: str                  # PovVariant
    screened_at: str
    window_start: str             # screened_at - 365 days
    ss_citation_count: int
    weighted_score: int
    result: str                   # PovResult
    created_at: str
    updated_at: str
    version: int
