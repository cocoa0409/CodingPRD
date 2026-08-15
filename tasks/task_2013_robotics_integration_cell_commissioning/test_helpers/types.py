"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class BrandSpecialization(str, Enum):
    FANUC = "FANUC"
    ABB = "ABB"
    DUAL = "DUAL"


class PerformanceLevel(str, Enum):
    PLc = "PLc"
    PLd = "PLd"
    PLe = "PLe"


class CellProjectStatus(str, Enum):
    DRAFT = "DRAFT"
    STUDY = "STUDY"
    DESIGN = "DESIGN"
    BUILD = "BUILD"
    FAT = "FAT"
    SHIP = "SHIP"
    SAT = "SAT"
    TRAINING = "TRAINING"
    GUARANTEE = "GUARANTEE"
    CLOSED = "CLOSED"
    ON_HOLD = "ON_HOLD"
    TERMINATED = "TERMINATED"


class ApplicationStudyStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class Feasibility(str, Enum):
    FEASIBLE = "FEASIBLE"
    MARGINAL = "MARGINAL"
    INFEASIBLE = "INFEASIBLE"


class SafetyRiskAssessmentStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"


class RobotSelectionStatus(str, Enum):
    PROPOSED = "PROPOSED"
    VALIDATED = "VALIDATED"
    REJECTED = "REJECTED"
    LOCKED = "LOCKED"


class RobotBrand(str, Enum):
    FANUC = "FANUC"
    ABB = "ABB"


class ProgramDevStatus(str, Enum):
    OUTLINE = "OUTLINE"
    CODED = "CODED"
    PEER_REVIEWED = "PEER_REVIEWED"
    RELEASED = "RELEASED"
    REWORK = "REWORK"


class ProgramSimStatus(str, Enum):
    UNSIMULATED = "UNSIMULATED"
    SIM_RUNNING = "SIM_RUNNING"
    SIM_PASSED = "SIM_PASSED"
    SIM_FAILED = "SIM_FAILED"


class AcceptancePhase(str, Enum):
    FAT = "FAT"
    SAT = "SAT"


class AcceptanceVerdict(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    CONDITIONAL_PASS = "CONDITIONAL_PASS"
    FAIL = "FAIL"


class SparePartsPackageStatus(str, Enum):
    QUOTED = "QUOTED"
    ORDERED = "ORDERED"
    DELIVERED = "DELIVERED"
    SUPERSEDED = "SUPERSEDED"


class MaintenancePlanStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class TrainingAudience(str, Enum):
    OPERATOR = "OPERATOR"
    TECHNICIAN = "TECHNICIAN"


class TrainingSessionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"
    NO_SHOW = "NO_SHOW"


class GuaranteeStatus(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    MEASURING = "MEASURING"
    MET = "MET"
    MISSED = "MISSED"
    WAIVED = "WAIVED"


class LedgerEntryType(str, Enum):
    WITHHOLD = "WITHHOLD"
    RELEASE = "RELEASE"
    PENALTY = "PENALTY"
    ADJUST = "ADJUST"


class UserRole(str, Enum):
    PROJECT_ENGINEER = "PROJECT_ENGINEER"
    SAFETY_LEAD = "SAFETY_LEAD"
    CONTROLS_PROGRAMMER = "CONTROLS_PROGRAMMER"
    SITE_SUPERVISOR = "SITE_SUPERVISOR"
    TRAINER = "TRAINER"
    SERVICE_MANAGER = "SERVICE_MANAGER"
    FINANCE_ADMIN = "FINANCE_ADMIN"


# Header role strings (PRD §2.1) — the wire spelling of each role.
class ApiRole(str, Enum):
    PROJECT_ENGINEER = "ProjectEngineer"
    SAFETY_LEAD = "SafetyLead"
    CONTROLS_PROGRAMMER = "ControlsProgrammer"
    SITE_SUPERVISOR = "SiteSupervisor"
    TRAINER = "Trainer"
    SERVICE_MANAGER = "ServiceManager"
    FINANCE_ADMIN = "FinanceAdmin"


# ---------------------------------------------------------------------------
# Entity TypedDicts — common_fields: true entities carry id/created_at/
# updated_at/version. RetentionLedgerEntry (append-only) carries only
# id and created_at (PRD §2.4).
# ---------------------------------------------------------------------------


class IntegratorOrg(TypedDict, total=False):
    id: str
    legal_name: str
    brand_specialization: str
    retention_rate_bps: int
    default_pl_category_target: str
    created_at: str
    updated_at: str
    version: int


class IntegratorUser(TypedDict, total=False):
    id: str
    integrator_org_id: str
    display_name: str
    user_role: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class CustomerSite(TypedDict, total=False):
    id: str
    integrator_org_id: str
    site_name: str
    plant_tz: str
    shift_windows_per_day: int
    created_at: str
    updated_at: str
    version: int


class CellProject(TypedDict, total=False):
    id: str
    customer_site_id: str
    project_code: str
    contracted_cycle_time_s: float
    contract_value_cents: int
    status: str
    hold_reason: Optional[str]
    rework_count: int
    retention_balance_cents: int
    guaranteed_oee_pct: float
    guarantee_window_days: int
    created_at: str
    updated_at: str
    version: int


class ApplicationStudy(TypedDict, total=False):
    id: str
    cell_project_id: str
    revision: int
    sim_cycle_time_s: float
    sim_confidence_pct: float
    feasibility: str
    adjusted_cycle_time_s: float
    supersedes_study_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class SafetyRiskAssessment(TypedDict, total=False):
    id: str
    cell_project_id: str
    assessment_revision: int
    risk_score_pre_mitigation: int
    pl_target: str
    pl_achieved: str
    fencing_length_m: float
    light_curtain_zones: int
    muting_required: bool
    safety_function_budget_pct: float
    status: str
    approved_by_safety_lead_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RobotSelection(TypedDict, total=False):
    id: str
    cell_project_id: str
    robot_model: str
    brand: str
    rated_payload_kg: float
    end_effector_weight_kg: float
    part_weight_kg: float
    wrist_inertia_kgm2: float
    wrist_inertia_limit_kgm2: float
    payload_margin_pct: float
    selection_status: str
    created_at: str
    updated_at: str
    version: int


class RobotProgram(TypedDict, total=False):
    id: str
    cell_project_id: str
    program_name: str
    dev_status: str
    sim_status: str
    last_sim_cycle_time_s: Optional[float]
    sim_iteration_count: int
    release_revision: int
    created_at: str
    updated_at: str
    version: int


class AcceptanceTest(TypedDict, total=False):
    id: str
    cell_project_id: str
    phase: str
    attempt: int
    measured_cycle_time_s: float
    measured_oee_pct: float
    defects_observed: int
    verdict: str
    retention_released_cents: int
    recorded_by_user_id: str
    created_at: str
    updated_at: str
    version: int


class SparePartsPackage(TypedDict, total=False):
    id: str
    cell_project_id: str
    package_code: str
    list_price_cents: int
    recommended_coverage_months: int
    forecast_consumption_months: float
    package_status: str
    created_at: str
    updated_at: str
    version: int


class MaintenancePlan(TypedDict, total=False):
    id: str
    cell_project_id: str
    interval_operating_hours: int
    first_due_at_hours: int
    plan_status: str
    current_operating_hours: int
    hours_until_due: int
    created_at: str
    updated_at: str
    version: int


class TrainingSession(TypedDict, total=False):
    id: str
    cell_project_id: str
    audience: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    trainer_user_id: str
    attendee_count: int
    completion_score_pct: Optional[float]
    practical_score_pct: Optional[float]
    written_score_pct: Optional[float]
    session_status: str
    created_at: str
    updated_at: str
    version: int


class ThroughputGuarantee(TypedDict, total=False):
    id: str
    cell_project_id: str
    guarantee_window_days: int
    window_start_utc: Optional[str]
    window_end_utc: Optional[str]
    guarantee_status: str
    observed_uptime_pct: Optional[float]
    observed_cycle_time_s: Optional[float]
    shortfall_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RetentionLedgerEntry(TypedDict, total=False):
    """Append-only ledger entry: only id + created_at from common fields (PRD §2.4)."""

    id: str
    cell_project_id: str
    entry_type: str
    amount_cents: int
    milestone_ref: str
    recorded_at_utc: str
    created_at: str
