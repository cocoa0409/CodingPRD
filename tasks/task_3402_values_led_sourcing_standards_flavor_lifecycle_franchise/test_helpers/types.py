"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    SOURCING_MANAGER = "SourcingManager"
    SUSTAINABILITY_AUDITOR = "SustainabilityAuditor"
    AUDIT_VERIFIER = "AuditVerifier"
    DAIRY_PROGRAM_MANAGER = "DairyProgramManager"
    FLAVOR_MANAGER = "FlavorManager"
    PLANT_SCHEDULER = "PlantScheduler"
    INDEPENDENT_BOARD_MEMBER = "IndependentBoardMember"
    PARENT_OPS_CONTROLLER = "ParentOpsController"
    FRANCHISE_ADMIN = "FranchiseAdmin"
    SHOP_OPERATOR = "ShopOperator"
    FAN = "Fan"


class SupplierStatus(str, Enum):
    PROSPECT = "PROSPECT"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    LAPSED = "LAPSED"


class CertificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class AuditStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    VERIFIED = "VERIFIED"


class AuditOutcome(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"


class EnrollmentStatus(str, Enum):
    ENROLLED = "ENROLLED"
    ASSESSED = "ASSESSED"


class PaymentStatus(str, Enum):
    CALCULATED = "CALCULATED"
    APPROVED = "APPROVED"
    PAID = "PAID"
    VOIDED = "VOIDED"


class CalcVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class FlavorStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    TEST_BATCH = "TEST_BATCH"
    LIMITED_RUN = "LIMITED_RUN"
    CORE_LINE = "CORE_LINE"
    RETIRED = "RETIRED"
    REVIVED = "REVIVED"


class ClaimStatus(str, Enum):
    UNCLAIMED = "UNCLAIMED"
    SUBSTANTIATED = "SUBSTANTIATED"
    PUBLISHED = "PUBLISHED"
    CHALLENGED = "CHALLENGED"
    RETRACTED = "RETRACTED"


class ClaimType(str, Enum):
    NONE = "NONE"
    FAIR_TRADE_SOURCING = "FAIR_TRADE_SOURCING"
    ORGANIC_INGREDIENTS = "ORGANIC_INGREDIENTS"
    NON_GMO = "NON_GMO"
    CLIMATE_POSITIVE = "CLIMATE_POSITIVE"


class RevivalRequestStatus(str, Enum):
    OPEN = "OPEN"
    QUALIFIED = "QUALIFIED"
    ADOPTED = "ADOPTED"
    DECLINED = "DECLINED"


class SlotStatus(str, Enum):
    PLANNED = "PLANNED"
    CONFIRMED = "CONFIRMED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class CampaignApprovalStatus(str, Enum):
    BOARD_REVIEW = "BOARD_REVIEW"
    BOARD_APPROVED = "BOARD_APPROVED"
    BOARD_REJECTED = "BOARD_REJECTED"
    OPS_SCHEDULED = "OPS_SCHEDULED"
    LAUNCHED = "LAUNCHED"
    WITHDRAWN = "WITHDRAWN"


class RetailNoticeStatus(str, Enum):
    NOT_REQUIRED = "NOT_REQUIRED"
    PENDING = "PENDING"
    DISPATCHED = "DISPATCHED"


class ShopStatus(str, Enum):
    SITE_REVIEW = "SITE_REVIEW"
    SITE_APPROVED = "SITE_APPROVED"
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class OrderStatus(str, Enum):
    PLACED = "PLACED"
    CONFIRMED = "CONFIRMED"
    ALLOCATED = "ALLOCATED"
    DELIVERED = "DELIVERED"
    CANCELLED = "CANCELLED"


class IngredientCategory(str, Enum):
    DAIRY = "DAIRY"
    COCOA = "COCOA"
    SUGAR = "SUGAR"
    VANILLA = "VANILLA"
    NUTS = "NUTS"
    FRUIT = "FRUIT"
    CHUNK_INCLUSION = "CHUNK_INCLUSION"


class CertScheme(str, Enum):
    FAIR_TRADE = "FAIR_TRADE"
    ORGANIC = "ORGANIC"
    NON_GMO = "NON_GMO"
    B_CORP = "B_CORP"
    RAINFOREST_ALLIANCE = "RAINFOREST_ALLIANCE"


class PlantCode(str, Enum):
    VT_WATERBURY = "VT_WATERBURY"
    VT_ST_ALBANS = "VT_ST_ALBANS"
    NL_HELLENDOORN = "NL_HELLENDOORN"


# All entities carry common fields: id, created_at, updated_at, version (PRD §2.4).

class Supplier(TypedDict, total=False):
    id: str
    name: str
    country_code: str
    ingredient_category: str
    status: str
    social_criteria_score: Optional[int]
    created_at: str
    updated_at: str
    version: int


class SourcingCommitment(TypedDict, total=False):
    id: str
    supplier_id: str
    ingredient_category: str
    fair_trade_required: bool
    min_social_score: int
    premium_over_commodity_pct: float
    effective_from: str
    effective_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict, total=False):
    id: str
    supplier_id: str
    scheme: str
    certificate_number: str
    ingredient_scope: str
    issued_at: str
    valid_until: str
    declared_coverage_pct: float
    verified_coverage_pct: Optional[float]
    status: str
    created_at: str
    updated_at: str
    version: int


class Audit(TypedDict, total=False):
    id: str
    supplier_id: str
    scheduled_for: str
    auditor_user_id: Optional[str]
    labor_score: Optional[int]
    environment_score: Optional[int]
    community_score: Optional[int]
    findings_count: Optional[int]
    composite_score: Optional[int]
    outcome: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class FarmProgramEnrollment(TypedDict, total=False):
    id: str
    farm_name: str
    region: str
    herd_size: int
    season_year: int
    baseline_volume_liters: int
    env_practice_score: Optional[int]
    welfare_practice_score: Optional[int]
    blended_score: Optional[int]
    status: str
    total_approved_cents: int
    created_at: str
    updated_at: str
    version: int


class PremiumPayment(TypedDict, total=False):
    id: str
    enrollment_id: str
    period: str
    declared_volume_liters: int
    metered_volume_liters: Optional[int]
    non_conformance_count: int
    commodity_price_cents_per_liter: int
    calc_variant: str
    premium_pct: Optional[float]
    gross_amount_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Flavor(TypedDict, total=False):
    id: str
    name: str
    base_type: str
    chunk_load_pct: float
    swirl_load_pct: float
    pint_price_cents: int
    status: str
    retired_at: Optional[str]
    claim_type: str
    claim_status: str
    claim_certification_ids: List[str]
    claim_coverage_declared_pct: Optional[float]
    claim_coverage_verified_pct: Optional[float]
    created_at: str
    updated_at: str
    version: int


class RevivalRequest(TypedDict, total=False):
    id: str
    flavor_id: str
    fan_email: str
    title: str
    signature_count: int
    signer_emails: List[str]
    status: str
    qualified_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ProductionSlot(TypedDict, total=False):
    id: str
    plant_code: str
    flavor_id: str
    production_date: str
    shift: str
    planned_pints: int
    capacity_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Campaign(TypedDict, total=False):
    id: str
    title: str
    issue_area: str
    retail_partner_impact: str
    proposer_user_id: str
    approval_status: str
    retail_notice_status: str
    decided_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ScoopShop(TypedDict, total=False):
    id: str
    name: str
    operator_type: str
    nonprofit_verified: bool
    city: str
    country_code: str
    credit_limit_cents: int
    franchise_fee_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class ShopSupplyOrder(TypedDict, total=False):
    id: str
    scoop_shop_id: str
    production_date: str
    allocated_plant_code: Optional[str]
    lines: List[dict]
    total_pints: Optional[int]
    total_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
