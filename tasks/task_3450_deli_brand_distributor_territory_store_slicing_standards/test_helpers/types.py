"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3).

PRD §2.4: order lines, lots, and training certifications carry only
`id` and `created_at` — no `updated_at`, no `version`. Their TypedDicts
below omit those fields.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    BRAND_ADMIN = "BrandAdmin"
    DISTRIBUTOR_REP = "DistributorRep"
    RETAIL_MANAGER = "RetailManager"
    PLANT_SCHEDULER = "PlantScheduler"
    SAFETY_OFFICER = "SafetyOfficer"


class DistributorStatus(str, Enum):
    PROSPECT = "PROSPECT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ServiceLevelTier(str, Enum):
    STANDARD = "STANDARD"
    PREFERRED = "PREFERRED"
    ELITE = "ELITE"


class TerritoryStatus(str, Enum):
    OPEN = "OPEN"
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class AccountChannel(str, Enum):
    INDEPENDENT_GROCER = "INDEPENDENT_GROCER"
    CONVENIENCE = "CONVENIENCE"
    FOODSERVICE = "FOODSERVICE"
    MASS_MERCHANT = "MASS_MERCHANT"
    CLUB_STORE = "CLUB_STORE"


REFUSED_CHANNELS = (AccountChannel.MASS_MERCHANT.value, AccountChannel.CLUB_STORE.value)


class AccountApprovalStatus(str, Enum):
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"


class ProductStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISCONTINUED = "DISCONTINUED"


class Allergen(str, Enum):
    MILK = "MILK"
    EGG = "EGG"
    WHEAT = "WHEAT"
    SOY = "SOY"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    SESAME = "SESAME"


class SlicerAllergen(str, Enum):
    NONE = "NONE"
    MILK = "MILK"
    EGG = "EGG"
    WHEAT = "WHEAT"
    SOY = "SOY"
    PEANUT = "PEANUT"
    TREE_NUT = "TREE_NUT"
    SESAME = "SESAME"


class AuthorizationStatus(str, Enum):
    REQUESTED = "REQUESTED"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class SuspensionSource(str, Enum):
    NONE = "NONE"
    INCIDENT = "INCIDENT"
    ACCOUNT_SUSPEND = "ACCOUNT_SUSPEND"


class OrderAllocationStatus(str, Enum):
    PENDING = "PENDING"
    ALLOCATED = "ALLOCATED"
    PARTIAL = "PARTIAL"
    SHORTED = "SHORTED"
    CANCELLED = "CANCELLED"


class OrderFulfillmentStatus(str, Enum):
    UNSHIPPED = "UNSHIPPED"
    IN_TRANSIT = "IN_TRANSIT"
    DELIVERED = "DELIVERED"
    REJECTED = "REJECTED"


class PlantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SHUTDOWN = "SHUTDOWN"


class ProductionRunStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LotStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    QUARANTINED = "QUARANTINED"
    RECALLED = "RECALLED"
    EXHAUSTED = "EXHAUSTED"


class DeliveryStatus(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ServiceVisitStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REWORK = "REWORK"
    CANCELLED = "CANCELLED"


class SlicerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DECOMMISSIONED = "DECOMMISSIONED"


class OpenedProductLogStatus(str, Enum):
    OPEN = "OPEN"
    PULLED_ON_TIME = "PULLED_ON_TIME"
    PULLED_LATE = "PULLED_LATE"
    FORCE_PULLED = "FORCE_PULLED"


class CertificationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class PromoProgramStatus(str, Enum):
    DRAFT = "DRAFT"
    AUTHORIZED = "AUTHORIZED"
    REJECTED = "REJECTED"
    SUSPENDED = "SUSPENDED"
    SETTLED = "SETTLED"


class IncidentStatus(str, Enum):
    REPORTED = "REPORTED"
    TRIAGED = "TRIAGED"
    CONFIRMED_RECALL = "CONFIRMED_RECALL"
    CONTAINED = "CONTAINED"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class IncidentSeverity(str, Enum):
    LOW = "LOW"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ResolutionOutcome(str, Enum):
    CONFIRMED = "CONFIRMED"
    FALSE_ALARM = "FALSE_ALARM"


class ReviewDecision(str, Enum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class VisitVerdict(str, Enum):
    VERIFY = "VERIFY"
    REWORK = "REWORK"


# ---------------- Entity TypedDicts ----------------
# common_fields entities: id, created_at, updated_at, version (PRD §2.4).

class Distributor(TypedDict, total=False):
    id: str
    code: str
    name: str
    status: str
    service_level_tier: str
    performance_score_provisional: float
    performance_score_final: float
    created_at: str
    updated_at: str
    version: int


class Territory(TypedDict, total=False):
    id: str
    code: str
    name: str
    region: str
    status: str
    granted_distributor_id: Optional[str]
    granted_at: Optional[str]
    revoked_at: Optional[str]
    min_weekly_visits_per_account: int
    created_at: str
    updated_at: str
    version: int


class Account(TypedDict, total=False):
    id: str
    name: str
    channel: str
    approval_status: str
    territory_id: str
    distributor_id: str
    approved_at: Optional[str]
    late_pulls_30d: int
    training_compliant: bool
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    code: str
    name: str
    base_price_cents: int
    shelf_life_opened_hours: int
    shelf_life_unopened_days: int
    allergen_tags: List[str]
    requires_dedicated_slicer: bool
    channel_restricted: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class AccountProductAuthorization(TypedDict, total=False):
    id: str
    account_id: str
    product_id: str
    status: str
    suspension_source: str
    created_at: str
    updated_at: str
    version: int


class Order(TypedDict, total=False):
    id: str
    distributor_id: str
    delivery_week: str
    allocation_status: str
    fulfillment_status: str
    merchandise_total_cents: int
    discount_cents: int
    delivery_fee_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class OrderLine(TypedDict, total=False):
    # common_fields: false — id + created_at only (PRD §2.4)
    id: str
    order_id: str
    product_id: str
    qty_requested: int
    qty_allocated: int
    unit_price_cents: int
    line_total_cents: int
    created_at: str


class Plant(TypedDict, total=False):
    id: str
    code: str
    name: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductionRun(TypedDict, total=False):
    id: str
    plant_id: str
    line_code: str
    product_id: str
    window_start: str
    window_end: str
    capacity_units: int
    planned_units: int
    actual_units: Optional[int]
    waste_units: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Lot(TypedDict, total=False):
    # common_fields: false — id + created_at only (PRD §2.4)
    id: str
    production_run_id: str
    product_id: str
    available_units: int
    allocated_units: int
    delivered_units: int
    expires_at: str
    status: str
    created_at: str


class DeliveryLine(TypedDict, total=False):
    lot_id: str
    qty: int


class Delivery(TypedDict, total=False):
    id: str
    order_id: str
    account_id: str
    distributor_id: str
    lines: List[DeliveryLine]
    status: str
    confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ServiceVisit(TypedDict, total=False):
    id: str
    account_id: str
    distributor_id: str
    window_start: str
    window_end: str
    status: str
    score: Optional[int]
    rotation_compliant: Optional[bool]
    slicer_presentation_ok: Optional[bool]
    submitted_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Slicer(TypedDict, total=False):
    id: str
    account_id: str
    label: str
    dedicated_allergen: str
    cleaning_verified_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class OpenedProductLog(TypedDict, total=False):
    id: str
    account_id: str
    product_id: str
    slicer_id: str
    opened_at: str
    pull_deadline: str
    pulled_at: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class TrainingCertification(TypedDict, total=False):
    # common_fields: false — id + created_at only (PRD §2.4)
    id: str
    account_id: str
    associate_name: str
    slicing_module_passed: bool
    allergen_module_passed: bool
    certified_at: str
    expires_at: str
    status: str
    created_at: str


class RedemptionLine(TypedDict):
    period: str
    units: int


class PromoProgram(TypedDict, total=False):
    id: str
    account_id: str
    product_id: str
    promo_price_cents: int
    start_date: str
    end_date: str
    budget_cents: int
    estimated_units: int
    status: str
    unit_allowance_cents: int
    reserved_cents: int
    spent_cents: int
    released_cents: int
    created_at: str
    updated_at: str
    version: int


class Incident(TypedDict, total=False):
    id: str
    plant_id: str
    title: str
    severity: str
    affected_run_ids: List[str]
    status: str
    resolution_outcome: Optional[str]
    affected_account_count: int
    created_at: str
    updated_at: str
    version: int
