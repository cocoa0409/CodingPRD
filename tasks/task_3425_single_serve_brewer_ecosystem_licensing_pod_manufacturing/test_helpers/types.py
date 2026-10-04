"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.5, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Role enum (PRD §2.1 — exactly nine roles)
# ---------------------------------------------------------------------------
class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LICENSING_MANAGER = "LicensingManager"
    QUALITY_AUDITOR = "QualityAuditor"
    BRAND_MANAGER = "BrandManager"
    OPERATIONS_DIRECTOR = "OperationsDirector"
    PRODUCTION_PLANNER = "ProductionPlanner"
    CATEGORY_MANAGER = "CategoryManager"
    FINANCE_ANALYST = "FinanceAnalyst"
    SUPPORT_AGENT = "SupportAgent"


# ---------------------------------------------------------------------------
# Status / field enums
# ---------------------------------------------------------------------------
class BrandKind(str, Enum):
    PLATFORM_OWNED = "PLATFORM_OWNED"
    LICENSED = "LICENSED"
    UNLICENSED_COMPATIBLE = "UNLICENSED_COMPATIBLE"


class LicenseAgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class PodVarietyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PHASE_OUT = "PHASE_OUT"
    DELISTED = "DELISTED"
    SUPPLY_BLOCKED = "SUPPLY_BLOCKED"


class RoastLevel(str, Enum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    DARK = "DARK"


class FlavorFamily(str, Enum):
    UNFLAVORED = "UNFLAVORED"
    FLAVORED = "FLAVORED"


class Material(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    RECYCLABLE = "RECYCLABLE"


class FirmwareCompat(str, Enum):
    OPEN = "OPEN"
    RESTRICTIVE = "RESTRICTIVE"


class FacilityKind(str, Enum):
    OWNED = "OWNED"
    PARTNER = "PARTNER"


class SupportedRoast(str, Enum):
    LIGHT = "LIGHT"
    MEDIUM = "MEDIUM"
    DARK = "DARK"
    UNIVERSAL = "UNIVERSAL"


class MaterialCapability(str, Enum):
    CONVENTIONAL = "CONVENTIONAL"
    RECYCLABLE = "RECYCLABLE"
    BOTH = "BOTH"


class ProductionRunStatus(str, Enum):
    RESERVED = "RESERVED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class Engagement(str, Enum):
    ENGAGED = "ENGAGED"
    LAPSED = "LAPSED"
    CHURNED = "CHURNED"


class WarrantyStatus(str, Enum):
    IN_WARRANTY = "IN_WARRANTY"
    EXPIRED = "EXPIRED"
    VOID = "VOID"


class OperationalStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DORMANT = "DORMANT"
    DECOMMISSIONED = "DECOMMISSIONED"


class ServiceEventKind(str, Enum):
    WARRANTY_CLAIM = "WARRANTY_CLAIM"
    DESCALING = "DESCALING"
    REPLACEMENT = "REPLACEMENT"


class ServiceEventStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"
    DENIED = "DENIED"


class ServiceEventResolution(str, Enum):
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    MISUSE_CONFIRMED = "MISUSE_CONFIRMED"
    AUTO_DENIED_DESCALE = "AUTO_DENIED_DESCALE"


class AssortmentPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    LOCKED = "LOCKED"
    CANCELLED = "CANCELLED"
    SUPERSEDED = "SUPERSEDED"


class RoyaltyStatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Common-fields resources carry id + created_at + updated_at + version.
# Immutable record types (QualityAudit, ConsumptionRecord) carry ONLY
# id + created_at among system fields (PRD §2.5).
# ---------------------------------------------------------------------------
class Brand(TypedDict):
    id: str
    name: str
    kind: str
    home_region: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyTier(TypedDict):
    up_to_units: Optional[int]
    millicents_per_pod: int


class LicenseAgreement(TypedDict):
    id: str
    brand_id: str
    territory_code: str
    effective_start: str
    effective_end: str
    royalty_tiers: List[RoyaltyTier]
    quality_min_cup_score: int
    exclusive: bool
    amendment_of_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class QualityAudit(TypedDict):
    # Immutable record type: id + created_at only (no updated_at, no version)
    id: str
    created_at: str
    agreement_id: str
    audited_at: str
    cup_score: int
    defect_rate_ppm: int
    result: str


class PodVariety(TypedDict):
    id: str
    brand_id: str
    name: str
    roast_level: str
    flavor_family: str
    material: str
    wholesale_price_cents: int
    margin_cents: int
    education_notices_sent: int
    velocity_units_90d: int
    slow_mover: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class BrewerModel(TypedDict):
    id: str
    model_code: str
    firmware_compat: str
    warranty_months: int
    descale_interval_brews: int
    msrp_cents: int
    unit_cost_cents: int
    subsidy_cents: int
    margin_cents: int
    created_at: str
    updated_at: str
    version: int


class Facility(TypedDict):
    id: str
    name: str
    kind: str
    region: str
    total_capacity_pods_per_day: int
    created_at: str
    updated_at: str
    version: int


class FillingLine(TypedDict):
    id: str
    facility_id: str
    line_code: str
    supported_roast: str
    supports_flavored: bool
    material_capability: str
    capacity_pods_per_day: int
    changeover_hours: int
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict):
    id: str
    line_id: str
    variety_id: str
    window_start: str
    window_end: str
    planned_units: int
    actual_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Household(TypedDict):
    id: str
    region: str
    size: int
    installed_brewers: int
    engagement: str
    trailing_avg_pods: float
    expected_monthly_pods: float
    created_at: str
    updated_at: str
    version: int


class Brewer(TypedDict):
    id: str
    household_id: str
    model_id: str
    serial_number: str
    registered_at: str
    brew_count: int
    last_brew_at: str
    last_descaled_brew_count: int
    descale_overdue: bool
    warranty_status: str
    operational: str
    created_at: str
    updated_at: str
    version: int


class ConsumptionRecord(TypedDict):
    # Immutable record type: id + created_at only (no updated_at, no version)
    id: str
    created_at: str
    household_id: str
    period: str
    pods_brewed: int


class ServiceEvent(TypedDict):
    id: str
    brewer_id: str
    kind: str
    note: Optional[str]
    status: str
    resolution: Optional[str]
    resolved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetailAccount(TypedDict):
    id: str
    name: str
    region: str
    shelf_slots_total: int
    productivity_floor_cents: int
    created_at: str
    updated_at: str
    version: int


class AssortmentSlot(TypedDict):
    variety_id: str
    facings: int
    clearance_flag: bool


class AssortmentPlan(TypedDict):
    id: str
    account_id: str
    period: str
    slots: List[AssortmentSlot]
    productivity_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    agreement_id: str
    period: str
    sell_in_units: int
    sell_through_units: int
    unlicensed_share_pct: int
    provisional_royalty_cents: int
    final_royalty_cents: Optional[int]
    dispute_count: int
    status: str
    created_at: str
    updated_at: str
    version: int
