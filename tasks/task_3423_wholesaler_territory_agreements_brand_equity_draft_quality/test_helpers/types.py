"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD's entity narratives. DraftAudit is immutable field
evidence: it carries only ``id`` and ``created_at`` (no ``updated_at``, no
``version``); every other primary resource carries the standard system fields.
"""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    BREWER_ADMIN = "BrewerAdmin"
    BREWER_COMPLIANCE = "BrewerCompliance"
    WHOLESALER_PRINCIPAL = "WholesalerPrincipal"
    DRAFT_AUDITOR = "DraftAuditor"


class TerritoryStatus(str, Enum):
    VACANT = "VACANT"
    AWARDED = "AWARDED"


class WholesalerStatus(str, Enum):
    APPLICANT = "APPLICANT"
    APPOINTED = "APPOINTED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class WholesalerTier(str, Enum):
    GOLD = "GOLD"
    SILVER = "SILVER"
    BRONZE = "BRONZE"


class SupplierType(str, Enum):
    CRAFT = "CRAFT"
    IMPORT = "IMPORT"
    DOMESTIC_PREMIUM = "DOMESTIC_PREMIUM"


class AgreementStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class WeightingProfile(str, Enum):
    STANDARD = "STANDARD"
    SHARE_TILTED = "SHARE_TILTED"


class TransferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    QUALIFIED = "QUALIFIED"
    ROFR_OPEN = "ROFR_OPEN"
    ROFR_EXERCISED = "ROFR_EXERCISED"
    ROFR_WAIVED = "ROFR_WAIVED"
    ROFR_LAPSED = "ROFR_LAPSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    CONSUMMATED = "CONSUMMATED"
    EXPIRED = "EXPIRED"


class AllocationEventStatus(str, Enum):
    OPEN = "OPEN"
    LOCKED = "LOCKED"
    CLOSED = "CLOSED"


class AssignmentStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    RELEASED = "RELEASED"


class RetailAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SERVICE_SUSPENDED = "SERVICE_SUSPENDED"


class AuditResult(str, Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    CRITICAL_FAIL = "CRITICAL_FAIL"


class PosGrantStatus(str, Enum):
    ISSUED = "ISSUED"
    VOIDED = "VOIDED"


class ReviewStatus(str, Enum):
    PUBLISHED = "PUBLISHED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"


class PlanStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class PromotionStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class Quarter(str, Enum):
    Q1 = "Q1"
    Q2 = "Q2"
    Q3 = "Q3"
    Q4 = "Q4"


# --- Entity TypedDicts -------------------------------------------------------
# Primary resources: id + created_at + updated_at + version.

class Territory(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    status: str
    incumbent_wholesaler_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Wholesaler(TypedDict, total=False):
    id: str
    legal_name: str
    home_state: str
    license_number: str
    tier: str
    holds_retail_interest: bool
    financial_capacity_score: int
    warehouse_capacity_score: int
    market_coverage_score: int
    supplier_book: List[Dict[str, Any]]
    status: str
    suspended_account_count: int
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    territory_id: str
    wholesaler_id: str
    rofr_holder_wholesaler_id: Optional[str]
    brand_scope: List[str]
    weighting_profile: str
    distribution_target_pct: float
    freshness_target_index: float
    share_target_pct: float
    declared_distribution_pct: float
    declared_freshness_index: float
    declared_share_pct: float
    term_years: int
    status: str
    amendment_log: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int


class TransferApplication(TypedDict, total=False):
    id: str
    agreement_id: str
    seller_wholesaler_id: str
    buyer_wholesaler_id: str
    purchase_price_cents: int
    status: str
    qualification_score: Optional[float]
    rofr_deadline: Optional[str]
    successor_wholesaler_id: Optional[str]
    consummation_deadline: Optional[str]
    decision_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AllocationEvent(TypedDict, total=False):
    id: str
    brand_code: str
    total_qty_cases: int
    min_guarantee_cases: int
    territory_cap_pct: float
    status: str
    requests: List[Dict[str, Any]]
    assignments: List[Dict[str, Any]]
    unassigned_remainder: Optional[int]
    committed_qty: int
    pending_qty: int
    released_qty: int
    created_at: str
    updated_at: str
    version: int


class RetailAccount(TypedDict, total=False):
    id: str
    name: str
    state_code: str
    serving_wholesaler_id: str
    line_cleaning_frequency_days: int
    status: str
    last_audit_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


# DraftAudit is append-only field evidence: ONLY id + created_at are
# system-managed; updated_at and version are absent by contract.
class DraftAudit(TypedDict, total=False):
    id: str
    account_id: str
    conducted_at: str
    line_cleaning_last_at: str
    kegs: List[Dict[str, Any]]
    stale_keg_count: int
    critical_keg_flag: bool
    line_cleaning_overdue: bool
    result: str
    created_at: str


class PosGrant(TypedDict, total=False):
    id: str
    account_id: str
    item_description: str
    value_cents: int
    status: str
    granted_year: int
    voided_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PerformanceReview(TypedDict, total=False):
    id: str
    wholesaler_id: str
    period_year: int
    period_quarter: str
    distribution_pct: float
    share_pct: float
    freshness_index: float
    weighting_profile_snapshot: str
    composite_score: float
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CorrectivePlan(TypedDict, total=False):
    id: str
    review_id: str
    status: str
    revision_count: int
    resolution_notes: Optional[str]
    target_snapshot: Dict[str, Any]
    created_at: str
    updated_at: str
    version: int


class PromotionProgram(TypedDict, total=False):
    id: str
    brand_code: str
    starts_at: str
    ends_at: str
    suggested_discount_pct: float
    mandated_retail_price_cents: Optional[int]
    status: str
    opt_ins: List[Dict[str, Any]]
    created_at: str
    updated_at: str
    version: int
