"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    """The six roles recognized by the API (PRD §2.1)."""

    PLATFORM_ADMIN = "PlatformAdmin"
    NETWORK_MANAGER = "NetworkManager"
    AUDITOR = "Auditor"
    QUALITY_MANAGER = "QualityManager"
    PLANT_OPERATOR = "PlantOperator"
    RETAILER_BUYER = "RetailerBuyer"


class FarmStatus(str, Enum):
    ONBOARDING = "ONBOARDING"
    ACTIVE = "ACTIVE"
    PROBATION = "PROBATION"
    SUSPENDED = "SUSPENDED"
    REMOVED = "REMOVED"


class CertificationStatus(str, Enum):
    CERTIFICATION_PENDING = "CERTIFICATION_PENDING"
    CERTIFIED = "CERTIFIED"
    CERT_LAPSED = "CERT_LAPSED"
    DECERTIFIED = "DECERTIFIED"


class ContractStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    TERMINATED = "TERMINATED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    PASSED = "PASSED"
    FAILED = "FAILED"
    CORRECTIVE_ACTION_REQUIRED = "CORRECTIVE_ACTION_REQUIRED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AuditType(str, Enum):
    INITIAL = "INITIAL"
    ANNUAL = "ANNUAL"
    FOR_CAUSE = "FOR_CAUSE"
    RE_AUDIT = "RE_AUDIT"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED_CLOSED = "VERIFIED_CLOSED"
    OVERDUE = "OVERDUE"
    CANCELLED = "CANCELLED"


class FindingSeverity(str, Enum):
    MINOR = "MINOR"
    MAJOR = "MAJOR"
    CRITICAL = "CRITICAL"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    RESOLVED = "RESOLVED"


class IncidentDisposition(str, Enum):
    NONE = "NONE"
    PROBATION = "PROBATION"
    SUSPENSION = "SUSPENSION"
    REMOVAL = "REMOVAL"


class RouteStatus(str, Enum):
    PLANNED = "PLANNED"
    COMPLETED = "COMPLETED"


class StopStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    SKIPPED = "SKIPPED"


class LotGrade(str, Enum):
    AA = "AA"
    A = "A"
    B = "B"
    NONE = "NONE"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    GRADED = "GRADED"
    ON_HOLD = "ON_HOLD"
    RELEASED = "RELEASED"
    REJECTED = "REJECTED"
    PACKED = "PACKED"


class PackSize(str, Enum):
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    EXTRA_LARGE = "EXTRA_LARGE"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FILLED = "FILLED"
    SHORTFALL = "SHORTFALL"
    CANCELLED = "CANCELLED"


class Season(str, Enum):
    SPRING = "SPRING"
    SUMMER = "SUMMER"
    AUTUMN = "AUTUMN"
    WINTER = "WINTER"


class WeatherSeverity(str, Enum):
    NONE = "NONE"
    MODERATE = "MODERATE"
    SEVERE = "SEVERE"


class SettlementStatus(str, Enum):
    CALCULATED = "CALCULATED"
    FINALIZED = "FINALIZED"


# --- Entity TypedDicts -------------------------------------------------------
# Common-fields entities (PRD §2.4): id, created_at, updated_at, version.


class Farm(TypedDict, total=False):
    id: str
    name: str
    region: str
    pasture_sqft: float
    barn_sqft: float
    nest_box_count: int
    declared_bird_count: int
    status: str
    certification_status: str
    effective_bird_capacity: int
    last_passed_audit_at: Optional[str]
    removal_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class FarmContract(TypedDict, total=False):
    id: str
    farm_id: str
    commodity_base_cents_per_dozen: int
    premium_cents_per_dozen: int
    start_date: str
    end_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    farm_id: str
    audit_type: str
    scheduled_for: str
    status: str
    auditor_user_id: Optional[str]
    non_conformities_count: int
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict, total=False):
    id: str
    audit_id: str
    severity: str
    description: str
    status: str
    due_at: str
    evidence_notes: Optional[str]
    verified_by_user_id: Optional[str]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WelfareIncident(TypedDict, total=False):
    id: str
    farm_id: str
    severity: str
    incident_type: str
    description: str
    status: str
    disposition: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RouteStop(TypedDict, total=False):
    stop_sequence: int
    farm_id: str
    planned_cases: int
    collected_cases: Optional[int]
    status: str


class CollectionRoute(TypedDict, total=False):
    id: str
    route_date: str
    driver_name: str
    capacity_cases: int
    status: str
    stops: List[RouteStop]
    committed_cases: int
    available_cases: int
    created_at: str
    updated_at: str
    version: int


class EggLot(TypedDict, total=False):
    id: str
    farm_id: str
    route_id: str
    stop_sequence: int
    lot_code: str
    laid_start_date: str
    laid_end_date: str
    received_cases: int
    received_dozens: int
    quality_score: Optional[float]
    grade: str
    status: str
    remaining_dozens: int
    packed_dozens: int
    destroyed_dozens: int
    graded_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailerAccount(TypedDict, total=False):
    id: str
    name: str
    banner: str
    terms_net_days: int
    created_at: str
    updated_at: str
    version: int


class SupplyCommitment(TypedDict, total=False):
    id: str
    farm_id: str
    retailer_id: str
    week_start: str
    committed_dozens: int
    status: str
    delivered_dozens: Optional[int]
    fill_rate: Optional[float]
    created_at: str
    updated_at: str
    version: int


class SettlementLine(TypedDict, total=False):
    farm_id: str
    contract_id: str
    dozens_aa: int
    dozens_a: int
    dozens_b: int
    total_dozens: int
    provisional_cents: int
    final_cents: Optional[int]


class SettlementRun(TypedDict, total=False):
    id: str
    week_start: str
    status: str
    lines: List[SettlementLine]
    provisional_total_cents: int
    final_total_cents: Optional[int]
    actual_commodity_base_cents_per_dozen: Optional[int]
    finalized_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# Immutable records (PRD §2.4): carry only id and created_at of the common
# fields — NO updated_at, NO version.


class Carton(TypedDict, total=False):
    id: str
    created_at: str
    carton_code: str
    lot_id: str
    pack_size: str
    dozens: int
    source_farm_id: str
    source_farm_name: str
    packed_at: str


class ProductionForecast(TypedDict, total=False):
    id: str
    created_at: str
    farm_id: str
    week_start: str
    season: str
    weather_severity: str
    optimistic_dozens: int
    conservative_dozens: int
