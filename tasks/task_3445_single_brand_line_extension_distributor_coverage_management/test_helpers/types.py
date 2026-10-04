"""Domain types: entity TypedDicts, status enums, role enum.

Field names and enum values mirror the PRD exactly. Entities with the
standard system-managed fields carry id/created_at/updated_at/version;
SellThroughReport is immutable and carries only id/created_at.
"""
from enum import Enum
from typing import TypedDict, Optional, List


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    """The eleven declared caller roles."""
    PLATFORM_ADMIN = "PlatformAdmin"
    BRAND_MANAGER = "BrandManager"
    TRADE_SECRET_OFFICER = "TradeSecretOfficer"
    COMPLIANCE_AUDITOR = "ComplianceAuditor"
    CHANNEL_MANAGER = "ChannelManager"
    PRICING_ANALYST = "PricingAnalyst"
    MARKETING_MANAGER = "MarketingManager"
    REGULATORY_AFFAIRS = "RegulatoryAffairs"
    SUPPLY_PLANNER = "SupplyPlanner"
    DISTRIBUTOR_CONTACT = "DistributorContact"
    CONSUMER = "Consumer"


class Channel(str, Enum):
    HARDWARE = "HARDWARE"
    AUTOMOTIVE = "AUTOMOTIVE"
    INDUSTRIAL = "INDUSTRIAL"
    MASS = "MASS"


class BrandStatus(str, Enum):
    OPERATING = "OPERATING"
    PROTECTIVE_LOCKDOWN = "PROTECTIVE_LOCKDOWN"


class LockdownReason(str, Enum):
    CONFIDENTIALITY_BREACH = "CONFIDENTIALITY_BREACH"
    COUNTERFEIT_SURGE = "COUNTERFEIT_SURGE"
    MANUAL = "MANUAL"


class ProtectionPosture(str, Enum):
    NORMAL = "NORMAL"
    ELEVATED = "ELEVATED"
    CRITICAL = "CRITICAL"


class ProductLineStatus(str, Enum):
    FORMULATION = "FORMULATION"
    PILOT = "PILOT"
    LAUNCHED = "LAUNCHED"
    DISCONTINUED = "DISCONTINUED"


class FormulationStatus(str, Enum):
    DRAFT = "DRAFT"
    SEALED = "SEALED"
    COMPARTMENTALIZED = "COMPARTMENTALIZED"


class VocClass(str, Enum):
    STANDARD = "STANDARD"
    LOW_VOC = "LOW_VOC"


class ManufacturerStatus(str, Enum):
    VETTING = "VETTING"
    QUALIFIED = "QUALIFIED"
    SUSPENDED = "SUSPENDED"


class ManufacturerCapability(str, Enum):
    BLENDING = "BLENDING"
    AEROSOL_FILL = "AEROSOL_FILL"
    LIQUID_FILL = "LIQUID_FILL"
    PACKAGING = "PACKAGING"


class GrantStatus(str, Enum):
    REQUESTED = "REQUESTED"
    GRANTED = "GRANTED"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class GrantReason(str, Enum):
    PRODUCTION = "PRODUCTION"
    PILOT_SUPPLY = "PILOT_SUPPLY"
    SECOND_SOURCE = "SECOND_SOURCE"


class DistributorStatus(str, Enum):
    APPLICANT = "APPLICANT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class QuotaComplianceTier(str, Enum):
    GOLD = "GOLD"
    STANDARD = "STANDARD"
    WATCH = "WATCH"
    SANCTION = "SANCTION"


class MarketStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class VocRegime(str, Enum):
    STANDARD = "STANDARD"
    STRICT = "STRICT"


class RegistrationStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    REJECTED = "REJECTED"
    ACTIVE = "ACTIVE"
    RENEWAL_DUE = "RENEWAL_DUE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AssignmentStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    SUPERSEDED = "SUPERSEDED"
    WITHDRAWN = "WITHDRAWN"
    CLOSED = "CLOSED"
    TERMINATED = "TERMINATED"


class DeliverySystem(str, Enum):
    AEROSOL = "AEROSOL"
    TRIGGER_SPRAY = "TRIGGER_SPRAY"
    PUMP = "PUMP"
    PRECISION_PEN = "PRECISION_PEN"
    BULK_CONTAINER = "BULK_CONTAINER"


class PackFormatStatus(str, Enum):
    DESIGNED = "DESIGNED"
    TOOLED = "TOOLED"
    IN_PRODUCTION = "IN_PRODUCTION"
    RETIRED = "RETIRED"


class PriceListStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


class PromotionStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    LIVE = "LIVE"
    SUSPENDED = "SUSPENDED"
    ENDED = "ENDED"


class CounterfeitCaseStatus(str, Enum):
    REPORTED = "REPORTED"
    ACTION_TAKEN = "ACTION_TAKEN"
    CLOSED = "CLOSED"


class UseCaseStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    RETRACTED = "RETRACTED"


class BrandReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class UseCaseReviewDecision(str, Enum):
    VERIFY = "VERIFY"
    REJECT = "REJECT"


# ---------------------------------------------------------------------------
# Entity TypedDicts (standard system fields: id, created_at, updated_at,
# version — except the immutable SellThroughReport)
# ---------------------------------------------------------------------------

class Brand(TypedDict, total=False):
    id: str
    name: str
    legal_entity_name: str
    equity_budget_bps: int
    status: str
    lockdown_reason: Optional[str]
    protection_posture: str
    dilution_consumed_bps: int
    core_identity_share_bps: int
    genericization_risk_bps: int
    created_at: str
    updated_at: str
    version: int


class ProductLine(TypedDict, total=False):
    id: str
    brand_id: str
    line_code: str
    name: str
    is_core: bool
    target_channels: List[str]
    status: str
    brand_review_attempts: int
    dilution_cost_bps: int
    launched_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Formulation(TypedDict, total=False):
    id: str
    product_line_id: str
    version_label: str
    master_formulation_id: Optional[str]
    component_codes: List[str]
    voc_class: str
    status: str
    sealed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ContractManufacturer(TypedDict, total=False):
    id: str
    legal_name: str
    site_country: str
    capabilities: List[str]
    sponsoring_officer_id: str
    status: str
    suspended_at: Optional[str]
    disclosed_component_count: int
    created_at: str
    updated_at: str
    version: int


class ConfidentialityGrant(TypedDict, total=False):
    id: str
    manufacturer_id: str
    formulation_id: str
    component_scope: List[str]
    grant_reason: str
    expires_on: str
    status: str
    granted_by_user_id: Optional[str]
    revoked_for_cause: bool
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict, total=False):
    id: str
    legal_name: str
    home_market_id: str
    channels_served: List[str]
    credit_limit_cents: int
    status: str
    suspension_count: int
    attainment_actual_bps: Optional[int]
    attainment_projected_bps: Optional[int]
    quota_compliance_tier: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Market(TypedDict, total=False):
    id: str
    country_code: str
    name: str
    registration_required: bool
    voc_regime: str
    allowed_channels: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class MarketRegistration(TypedDict, total=False):
    id: str
    market_id: str
    product_line_id: str
    formulation_id: str
    registration_number: Optional[str]
    status: str
    expires_on: str
    revise_count: int
    submitted_at: Optional[str]
    approved_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CoverageAssignment(TypedDict, total=False):
    id: str
    distributor_id: str
    market_id: str
    product_line_id: str
    channel: str
    exclusive: bool
    starts_on: str
    ends_on: str
    annual_quota_units: int
    status: str
    supersedes_assignment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackFormat(TypedDict, total=False):
    id: str
    product_line_id: str
    size_ml: int
    delivery_system: str
    channel_restrictions: List[str]
    case_pack_qty: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ChannelPriceList(TypedDict, total=False):
    id: str
    pack_format_id: str
    channel: str
    list_price_cents: int
    map_price_cents: int
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Promotion(TypedDict, total=False):
    id: str
    product_line_id: str
    channel: str
    discount_pct: float
    starts_on: str
    ends_on: str
    funding_budget_cents: int
    accrued_funding_cents: int
    redemptions_count: int
    unit_funding_provisional_cents: Optional[int]
    status: str
    created_by_user_id: str
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CounterfeitCase(TypedDict, total=False):
    id: str
    brand_id: str
    market_id: str
    channel: str
    severity: int
    units_seized: int
    status: str
    created_at: str
    updated_at: str
    version: int


class UseCaseSubmission(TypedDict, total=False):
    id: str
    product_line_id: str
    submitter_ref: str
    title: str
    description: str
    generic_use_flag: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class SellThroughReport(TypedDict, total=False):
    """Immutable report: carries only id + created_at as system fields.

    There is deliberately NO updated_at and NO version here.
    """
    id: str
    distributor_id: str
    coverage_assignment_id: str
    period_month: str
    units_sold: int
    units_returned: int
    net_units: int
    created_at: str
