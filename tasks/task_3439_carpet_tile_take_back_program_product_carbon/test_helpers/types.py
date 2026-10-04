"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Roles (PRD §2.1) — X-User-ID is an opaque operator identifier for all six
# roles; ownership compares it against recorded created_by / contractor_name
# strings, never against any entity id.
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SUSTAINABILITY_MANAGER = "SustainabilityManager"
    VERIFIER = "Verifier"
    CLAIMS_APPROVER = "ClaimsApprover"
    SPECIFIER = "Specifier"
    INSTALLER = "Installer"


# ---------------------------------------------------------------------------
# Enum value sets (PRD §3)
# ---------------------------------------------------------------------------
class CollectionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUNSET = "SUNSET"


class BackingType(str, Enum):
    STANDARD = "STANDARD"
    ADHESIVE_FREE_CAPABLE = "ADHESIVE_FREE_CAPABLE"


class LifecycleBoundary(str, Enum):
    CRADLE_TO_GATE = "CRADLE_TO_GATE"
    CRADLE_TO_GRAVE = "CRADLE_TO_GRAVE"


class ClaimIntent(str, Enum):
    NONE = "NONE"
    CARBON_NEUTRAL = "CARBON_NEUTRAL"
    CARBON_NEGATIVE = "CARBON_NEGATIVE"


class BatchStatus(str, Enum):
    QUARANTINE = "QUARANTINE"
    RELEASED = "RELEASED"
    EXHAUSTED = "EXHAUSTED"


class SourceType(str, Enum):
    RECLAIMED_FISHING_NET = "RECLAIMED_FISHING_NET"
    POST_CONSUMER_TILE = "POST_CONSUMER_TILE"
    POST_INDUSTRIAL_SCRAP = "POST_INDUSTRIAL_SCRAP"
    VIRGIN = "VIRGIN"


class LotStatus(str, Enum):
    RECEIVED = "RECEIVED"
    QC_PASSED = "QC_PASSED"
    QC_FAILED = "QC_FAILED"
    DEPLETED = "DEPLETED"


class QcOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class SiteStatus(str, Enum):
    PLANNED = "PLANNED"
    INSTALLED = "INSTALLED"
    IN_SERVICE = "IN_SERVICE"
    DECOMMISSIONED = "DECOMMISSIONED"


class InstallationSystem(str, Enum):
    ADHESIVE_FREE = "ADHESIVE_FREE"
    CONVENTIONAL = "CONVENTIONAL"


class ZoneStatus(str, Enum):
    IN_SERVICE = "IN_SERVICE"
    REPLACED = "REPLACED"
    RECLAIMED = "RECLAIMED"


class OrderReason(str, Enum):
    WEAR = "WEAR"
    DAMAGE = "DAMAGE"
    DESIGN_CHANGE = "DESIGN_CHANGE"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    MATCHED = "MATCHED"
    MATCH_FAILED = "MATCH_FAILED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ConditionGrade(str, Enum):
    A = "A"
    B = "B"
    C = "C"


class TakebackStatus(str, Enum):
    REQUESTED = "REQUESTED"
    SCHEDULED = "SCHEDULED"
    COLLECTED = "COLLECTED"
    CREDITED = "CREDITED"
    CANCELLED = "CANCELLED"


class CreditVariant(str, Enum):
    STANDARD = "STANDARD"
    CIRCULAR = "CIRCULAR"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_VERIFICATION = "IN_VERIFICATION"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class VerificationAction(str, Enum):
    ASSIGN = "ASSIGN"
    CLEAR = "CLEAR"
    FAIL = "FAIL"


class ClaimType(str, Enum):
    CARBON_NEUTRAL = "CARBON_NEUTRAL"
    CARBON_NEGATIVE = "CARBON_NEGATIVE"


class ClaimStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class OffsetCoverage(str, Enum):
    NONE = "NONE"
    PARTIAL = "PARTIAL"
    FULL = "FULL"


class OffsetRegistry(str, Enum):
    VERRA = "VERRA"
    GOLD_STANDARD = "GOLD_STANDARD"
    ACR = "ACR"


class TargetPosture(str, Enum):
    ON_TRACK = "ON_TRACK"
    AT_RISK = "AT_RISK"
    BREACHED = "BREACHED"


class PackageStatus(str, Enum):
    ISSUED = "ISSUED"
    SUPERSEDED = "SUPERSEDED"
    REVOKED = "REVOKED"


# ---------------------------------------------------------------------------
# Entity TypedDicts (PRD §2.4 common fields: id, created_at, updated_at,
# version — except OffsetRetirement, which carries id and created_at only).
# ---------------------------------------------------------------------------
class ProductCollection(TypedDict):
    id: str
    name: str
    pattern_code: str
    backing_type: str
    lifecycle_boundary: str
    claim_intent: str
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedstockMixEntry(TypedDict):
    lot_id: str
    quantity_kg: float


class TileBatch(TypedDict):
    id: str
    collection_id: str
    dye_lot_code: str
    production_date: str
    produced_m2: float
    mfg_intensity_kgco2e_per_m2: float
    delta_e: float
    feedstock_mix: List[FeedstockMixEntry]
    allocated_mass_kg: float
    available_m2: float
    recycled_content_pct: Optional[float]
    embodied_carbon_kg_per_m2: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class FeedstockLot(TypedDict):
    id: str
    supplier_name: str
    source_type: str
    quantity_kg: float
    carbon_factor_kgco2e_per_kg: float
    origin_takeback_id: Optional[str]
    supplier_reliability_pct: float
    available_kg: float
    allocated_kg: float
    status: str
    created_at: str
    updated_at: str
    version: int


class CustomerSite(TypedDict):
    id: str
    created_by: str
    contractor_name: str
    address: str
    install_window_start: str
    install_window_end: str
    installation_system: str
    adhesive_free_certified: bool
    cert_expires_on: str
    annual_replacement_budget_cents: int
    spent_replacement_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InstalledZone(TypedDict):
    id: str
    site_id: str
    batch_id: str
    zone_code: str
    area_m2: float
    status: str
    created_at: str
    updated_at: str
    version: int


class ReplacementOrder(TypedDict):
    id: str
    site_id: str
    zone_id: str
    reason: str
    new_zone_code: str
    matched_batch_id: Optional[str]
    quoted_cost_cents: Optional[int]
    status: str
    created_by: str
    created_at: str
    updated_at: str
    version: int


class TakeBackRequest(TypedDict):
    id: str
    site_id: str
    collection_id: str
    condition_grade: str
    declared_area_m2: float
    pickup_window_start: Optional[str]
    pickup_window_end: Optional[str]
    collected_kg: Optional[float]
    reuse_kg: Optional[float]
    depolymerize_kg: Optional[float]
    downcycle_kg: Optional[float]
    landfill_kg: Optional[float]
    credit_variant: Optional[str]
    credit_cents: Optional[int]
    credited_at: Optional[str]
    status: str
    created_by: str
    created_at: str
    updated_at: str
    version: int


class PCFReport(TypedDict):
    id: str
    collection_id: str
    period_start: str
    period_end: str
    boundary: str
    operational_kgco2e_per_m2: Optional[float]
    lifecycle_kgco2e_per_m2: Optional[float]
    submitted_by: Optional[str]
    verifier_org: Optional[str]
    verified_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CarbonClaim(TypedDict):
    id: str
    collection_id: str
    report_id: str
    manufacturing_target_id: Optional[str]
    claim_type: str
    claimed_volume_m2: float
    boundary: str
    required_offset_kgco2e: Optional[float]
    retired_kgco2e: float
    offset_coverage: str
    created_by: str
    reviewed_by: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OffsetRetirement(TypedDict):
    """Immutable event record (PRD §2.4): id and created_at ONLY — no
    updated_at, no version."""
    id: str
    claim_id: str
    registry: str
    vintage_year: int
    quantity_kgco2e: float
    retired_at: str
    created_at: str


class TargetReading(TypedDict):
    period_end: str
    intensity_kgco2e_per_m2: float
    recorded_at: str


class ManufacturingTarget(TypedDict):
    id: str
    program_name: str
    baseline_intensity_kgco2e_per_m2: float
    target_reduction_pct: float
    current_intensity_kgco2e_per_m2: float
    posture: str
    readings_log: List[TargetReading]
    created_at: str
    updated_at: str
    version: int


class SpecPackage(TypedDict):
    id: str
    architect_firm: str
    collection_id: str
    report_id: str
    claim_id: Optional[str]
    package_version: int
    status: str
    created_by: str
    created_at: str
    updated_at: str
    version: int
