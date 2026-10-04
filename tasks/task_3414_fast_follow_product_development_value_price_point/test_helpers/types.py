"""Domain types: entity TypedDicts, status enums, role enum.

All twelve resources carry the common fields (id, created_at, updated_at,
version). Status string values match the PRD lifecycle vocabulary exactly.
"""
from enum import Enum
from typing import Dict, List, Optional, TypedDict

__all__ = [
    "UserRole",
    "TrendSource",
    "TrendSignalStatus",
    "ConceptStatus",
    "ProductStatus",
    "PackagingStatus",
    "ManufacturerStatus",
    "QualityTier",
    "FormulaProjectStatus",
    "CostQuoteStatus",
    "IngredientStatus",
    "ClaimStatus",
    "CertStatus",
    "RegistrationStatus",
    "ReviewDimension",
    "REVIEW_OUTCOMES",
    "LineReviewStatus",
    "PlanogramSlotStatus",
    "LaunchPlanStatus",
    "SamplingStatus",
    "LockedVariant",
    "SampleEventType",
    "DiscontinuationReason",
    "DiscontinuationReviewStatus",
    "TrendSignal",
    "Concept",
    "Product",
    "ContractManufacturer",
    "FormulaProject",
    "CostQuote",
    "ComplianceDossier",
    "RetailPartner",
    "LineReview",
    "PlanogramSlot",
    "LaunchPlan",
    "DiscontinuationReview",
]


# ---------------------------------------------------------------------------
# Roles (PRD section 2.1)
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TREND_SCOUT = "TrendScout"
    PRODUCT_MANAGER = "ProductManager"
    SOURCING_LEAD = "SourcingLead"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RETAIL_PLANNER = "RetailPlanner"
    MARKETING_LEAD = "MarketingLead"
    MANUFACTURER_REP = "ManufacturerRep"


# ---------------------------------------------------------------------------
# Enums carried on resources
# ---------------------------------------------------------------------------

class TrendSource(str, Enum):
    SOCIAL_PLATFORM = "SOCIAL_PLATFORM"
    PRESTIGE_LAUNCH = "PRESTIGE_LAUNCH"


class TrendSignalStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    EVALUATING = "EVALUATING"
    PARKED = "PARKED"
    SELECTED = "SELECTED"
    ARCHIVED = "ARCHIVED"


class ConceptStatus(str, Enum):
    PITCHED = "PITCHED"
    SELECTED = "SELECTED"
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    COMMERCIALIZED = "COMMERCIALIZED"
    KILLED = "KILLED"


class ProductStatus(str, Enum):
    FORMULATION = "FORMULATION"
    SOURCING = "SOURCING"
    COMPLIANCE_GATE = "COMPLIANCE_GATE"
    LAUNCH_READY = "LAUNCH_READY"
    LAUNCHED = "LAUNCHED"
    DISCONTINUED = "DISCONTINUED"
    KILLED = "KILLED"


class PackagingStatus(str, Enum):
    """Parallel dimension on Product (PACK_SOURCING -> PACK_READY, no reverse)."""
    PACK_SOURCING = "PACK_SOURCING"
    PACK_READY = "PACK_READY"


class ManufacturerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class QualityTier(str, Enum):
    STANDARD = "STANDARD"
    PREMIUM = "PREMIUM"


class FormulaProjectStatus(str, Enum):
    IN_DEVELOPMENT = "IN_DEVELOPMENT"
    SAMPLE_REVIEW = "SAMPLE_REVIEW"
    APPROVED = "APPROVED"
    ABANDONED = "ABANDONED"


class CostQuoteStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_EVALUATION = "UNDER_EVALUATION"
    ACCEPTED = "ACCEPTED"
    SETTLED = "SETTLED"
    REJECTED = "REJECTED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    EXPIRED = "EXPIRED"
    INVALIDATED = "INVALIDATED"


class IngredientStatus(str, Enum):
    PENDING = "PENDING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"


class ClaimStatus(str, Enum):
    PENDING = "PENDING"
    SUBSTANTIATED = "SUBSTANTIATED"
    BLOCKED = "BLOCKED"


class CertStatus(str, Enum):
    NOT_APPLIED = "NOT_APPLIED"
    APPLIED = "APPLIED"
    AUDITING = "AUDITING"
    CERTIFIED = "CERTIFIED"
    DENIED = "DENIED"
    LAPSED = "LAPSED"


class RegistrationStatus(str, Enum):
    UNFILED = "UNFILED"
    FILED = "FILED"
    REGISTERED = "REGISTERED"
    REJECTED = "REJECTED"


class ReviewDimension(str, Enum):
    INGREDIENT = "INGREDIENT"
    CLAIM = "CLAIM"
    CERTIFICATION = "CERTIFICATION"
    REGISTRATION = "REGISTRATION"


#: Legal review outcomes per dimension (PRD: an outcome outside the requested
#: dimension's outcome set is rejected with ERR_INVALID_REQUEST).
REVIEW_OUTCOMES = {
    ReviewDimension.INGREDIENT.value: ("CLEARED", "BLOCKED"),
    ReviewDimension.CLAIM.value: ("SUBSTANTIATED", "BLOCKED"),
    ReviewDimension.CERTIFICATION.value: ("APPLIED", "AUDITING", "CERTIFIED", "DENIED"),
    ReviewDimension.REGISTRATION.value: ("FILED", "REGISTERED", "REJECTED"),
}


class LineReviewStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMISSION_OPEN = "SUBMISSION_OPEN"
    REVIEWING = "REVIEWING"
    DECIDED = "DECIDED"
    PLANOGRAM_LOCKED = "PLANOGRAM_LOCKED"
    CANCELLED = "CANCELLED"


class PlanogramSlotStatus(str, Enum):
    PROPOSED = "PROPOSED"
    COMMITTED = "COMMITTED"
    ACTIVE = "ACTIVE"
    VACATED = "VACATED"
    RELEASED = "RELEASED"
    WITHDRAWN = "WITHDRAWN"


class LaunchPlanStatus(str, Enum):
    DRAFT = "DRAFT"
    QUANTITY_LOCKED = "QUANTITY_LOCKED"
    APPROVED = "APPROVED"
    EXECUTED = "EXECUTED"
    RECONCILED = "RECONCILED"


class SamplingStatus(str, Enum):
    """Parallel dimension on LaunchPlan (NONE -> PLANNED -> ACTIVE -> CLOSED)."""
    NONE = "NONE"
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    CLOSED = "CLOSED"


class LockedVariant(str, Enum):
    DEMAND = "DEMAND"
    RISK_ADJUSTED = "RISK_ADJUSTED"


class SampleEventType(str, Enum):
    COMMIT = "COMMIT"
    DISTRIBUTE = "DISTRIBUTE"
    RELEASE = "RELEASE"


class DiscontinuationReason(str, Enum):
    TREND_DECAY = "TREND_DECAY"
    REFRESH_CADENCE = "REFRESH_CADENCE"
    PERFORMANCE = "PERFORMANCE"


class DiscontinuationReviewStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


# ---------------------------------------------------------------------------
# Entity shapes (all carry id, created_at, updated_at, version)
# ---------------------------------------------------------------------------

class TrendSignal(TypedDict):
    id: str
    source: str
    platform: str
    category: str
    mention_velocity_7d: int
    engagement_growth_pct: float
    prestige_similarity: Optional[float]
    cross_platform_spread: Optional[float]
    status: str
    momentum_score: Optional[float]
    evaluated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Concept(TypedDict):
    id: str
    trend_signal_id: str
    name: str
    category: str
    target_price_point_cents: int
    status: str
    target_unit_cost_cents: Optional[int]
    selected_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict):
    id: str
    concept_id: str
    sku_name: str
    tooling_code: Optional[str]
    status: str
    packaging_status: str
    tooling_reuse: bool
    packaging_lead_weeks: int
    successor_product_id: Optional[str]
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractManufacturer(TypedDict):
    id: str
    name: str
    capabilities: List[str]
    base_lead_time_weeks: int
    moq_units: int
    quality_tier: str
    capacity_slots_per_quarter: int
    status: str
    created_at: str
    updated_at: str
    version: int


class FormulaProject(TypedDict):
    id: str
    product_id: str
    contract_manufacturer_id: str
    brief: str
    status: str
    round_count: int
    due_at: str
    submitted_at: Optional[str]
    is_late: bool
    formula_version: Optional[int]
    created_at: str
    updated_at: str
    version: int


class CostQuote(TypedDict):
    id: str
    product_id: str
    contract_manufacturer_id: str
    unit_cost_cents: int
    tooling_fee_cents: int
    freight_total_cents: int
    unit_weight_grams: int
    shipment_weight_grams: int
    duty_rate: float
    initial_order_qty: int
    valid_until: str
    production_quarter: str
    status: str
    landed_provisional_cents: Optional[int]
    landed_settled_cents: Optional[int]
    pinned_formula_version: Optional[int]
    accepted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ComplianceDossier(TypedDict):
    id: str
    product_id: str
    ingredient_status: str
    blocked_ingredients: List[str]
    claim_status: str
    cert_status: str
    cert_expires_at: Optional[str]
    registration_status: str
    compliant: bool
    created_at: str
    updated_at: str
    version: int


class RetailPartner(TypedDict):
    id: str
    name: str
    banner_code: str
    category_capacities: Dict[str, int]
    committed_facings: Dict[str, int]
    available_facings: Dict[str, int]
    created_at: str
    updated_at: str
    version: int


class LineReview(TypedDict):
    id: str
    retail_partner_id: str
    season: str
    submission_window_start: str
    submission_window_end: str
    review_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class PlanogramSlot(TypedDict):
    id: str
    line_review_id: str
    product_id: str
    category: str
    position_code: str
    facings: int
    occupancy_start: str
    occupancy_end: str
    status: str
    committed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class LaunchPlan(TypedDict):
    id: str
    product_id: str
    planogram_slot_id: str
    demand_forecast_units: int
    marketing_budget_cents: int
    cogs_budget_cents: int
    sample_budget_cents: int
    status: str
    sampling_status: str
    markdown_risk_pct: float
    capacity_units: int
    qty_demand_variant_units: int
    qty_risk_variant_units: int
    qty_locked_units: Optional[int]
    locked_variant: Optional[str]
    landed_locked_cents: Optional[int]
    samples_committed: int
    samples_distributed: int
    sample_spend_cents: int
    retail_units_available: Optional[int]
    markdown_units: int
    markdown_exposure_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


class DiscontinuationReview(TypedDict):
    id: str
    product_id: str
    successor_product_id: Optional[str]
    reason: str
    status: str
    proposed_by_user_id: str
    created_at: str
    updated_at: str
    version: int
