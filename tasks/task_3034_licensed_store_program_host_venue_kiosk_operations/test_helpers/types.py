"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class VenueType(str, Enum):
    GROCERY = "GROCERY"
    AIRPORT = "AIRPORT"
    CAMPUS = "CAMPUS"
    HOSPITAL = "HOSPITAL"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_ACCEPTANCE = "PENDING_ACCEPTANCE"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"
    EXPIRED = "EXPIRED"


class RoyaltyBasis(str, Enum):
    CASH = "CASH"
    ACCRUAL = "ACCRUAL"


class StoreOperatingStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    CERT_PENDING = "CERT_PENDING"
    OPERATING = "OPERATING"
    SUSPENDED = "SUSPENDED"
    DELICENSED = "DELICENSED"


class CompliancePosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    WATCH = "WATCH"
    PROBATION = "PROBATION"


class ProductCategory(str, Enum):
    BEVERAGE_CORE = "BEVERAGE_CORE"
    BEVERAGE_SEASONAL = "BEVERAGE_SEASONAL"
    FOOD = "FOOD"
    MERCHANDISE = "MERCHANDISE"
    PROPRIETARY_INGREDIENT = "PROPRIETARY_INGREDIENT"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    DISPUTED = "DISPUTED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class EmployeeRoleTag(str, Enum):
    BARISTA = "BARISTA"
    SHIFT_LEAD = "SHIFT_LEAD"
    STORE_MANAGER = "STORE_MANAGER"


class CertificationStatus(str, Enum):
    ENROLLED = "ENROLLED"
    EXAM_PASSED = "EXAM_PASSED"
    CERTIFIED = "CERTIFIED"
    AUDIT_FAILED = "AUDIT_FAILED"
    EXPIRED = "EXPIRED"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class StatementStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    FINAL = "FINAL"
    SUPERSEDED = "SUPERSEDED"


class InspectionStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class InspectionResult(str, Enum):
    NONE = "NONE"
    PASSED = "PASSED"
    FAILED = "FAILED"


class CorrectiveActionStatus(str, Enum):
    OPEN = "OPEN"
    SUBMITTED = "SUBMITTED"
    VERIFIED = "VERIFIED"
    REOPENED = "REOPENED"
    ESCALATED = "ESCALATED"


class CampaignStatus(str, Enum):
    PLANNED = "PLANNED"
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"
    RECONCILED = "RECONCILED"
    CANCELLED = "CANCELLED"


class StoreFormat(str, Enum):
    LICENSED = "LICENSED"
    COMPANY_OPERATED = "COMPANY_OPERATED"


class LoyaltyEventType(str, Enum):
    EARN = "EARN"
    REDEEM = "REDEEM"
    ADJUST = "ADJUST"


class UserRole(str, Enum):
    BRAND_PROGRAM_ADMIN = "BrandProgramAdmin"
    LICENSEE_MANAGER = "LicenseeManager"
    HOST_VENUE_MANAGER = "HostVenueManager"
    DISTRIBUTOR_AGENT = "DistributorAgent"
    BRAND_INSPECTOR = "BrandInspector"
    LOYALTY_MEMBER = "LoyaltyMember"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# Entities with common_fields: true carry id + created_at + updated_at + version.
# Entities with common_fields: false (append-only) carry ONLY id + created_at.
# ---------------------------------------------------------------------------


class Licensee(TypedDict):
    id: str
    name: str
    legal_entity_code: str
    created_at: str
    updated_at: str
    version: int


class HostVenue(TypedDict):
    id: str
    name: str
    venue_type: str
    open_time_utc: str
    close_time_utc: str
    access_restricted: bool
    max_equipment_footprint_units: int
    security_badge_required: bool
    created_at: str
    updated_at: str
    version: int


class LicenseAgreement(TypedDict):
    id: str
    licensee_id: str
    venue_id: str
    royalty_tiers: List[dict]
    royalty_basis: str
    term_start_date: str
    term_end_date: str
    status: str
    breach_strikes: int
    created_at: str
    updated_at: str
    version: int


class LicensedStore(TypedDict):
    id: str
    agreement_id: str
    store_code: str
    equipment_footprint_units: int
    operating_status: str
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class ProductItem(TypedDict):
    id: str
    sku: str
    name: str
    category: str
    proprietary: bool
    venue_type_restrictions: List[str]
    unit_cost_cents: int
    case_pack_units: int
    footprint_units: int
    created_at: str
    updated_at: str
    version: int


class StoreAssortmentItem(TypedDict):
    id: str
    store_id: str
    product_item_id: str
    par_level: int
    on_hand: int
    active: bool
    created_at: str
    updated_at: str
    version: int


class Distributor(TypedDict):
    id: str
    name: str
    approved: bool
    lead_time_days: int
    created_at: str
    updated_at: str
    version: int


class SupplyOrder(TypedDict):
    id: str
    store_id: str
    distributor_id: str
    auto_replenish: bool
    status: str
    total_cost_cents: int
    received_value_cents: int
    credit_cents: int
    created_at: str
    updated_at: str
    version: int


class SupplyOrderLine(TypedDict):
    # Append-only: id + created_at only; NO updated_at, NO version.
    id: str
    supply_order_id: str
    product_item_id: str
    quantity_ordered: int
    quantity_received: int
    unit_cost_cents: int
    discount_bps: int
    line_cost_cents: int
    created_at: str


class Employee(TypedDict):
    id: str
    licensee_id: str
    full_name: str
    role_tag: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class Certification(TypedDict):
    id: str
    employee_id: str
    program_code: str
    status: str
    exam_score: int
    exam_attempts: int
    proctor_anomaly: bool
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict):
    id: str
    store_id: str
    period_start_date: str
    period_end_date: str
    gross_sales_cents: int
    returns_cents: int
    loyalty_redemption_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class RoyaltyStatement(TypedDict):
    id: str
    agreement_id: str
    period_start_date: str
    period_end_date: str
    basis: str
    recognized_sales_cents: int
    royalty_amount_cents: int
    adjustment_delta_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Inspection(TypedDict):
    id: str
    store_id: str
    inspector_id: str
    scheduled_start_utc: str
    scheduled_end_utc: str
    status: str
    result: str
    total_score: int
    critical_fail: bool
    created_at: str
    updated_at: str
    version: int


class CorrectiveAction(TypedDict):
    id: str
    inspection_id: str
    finding_code: str
    due_at: str
    status: str
    reopen_count: int
    created_at: str
    updated_at: str
    version: int


class LoyaltyMember(TypedDict):
    id: str
    email: str
    points_balance: int
    lifetime_earned: int
    lifetime_redeemed: int
    created_at: str
    updated_at: str
    version: int


class LoyaltyAccountEvent(TypedDict):
    # Append-only: id + created_at only; NO updated_at, NO version.
    id: str
    member_id: str
    store_id: Optional[str]
    store_format: str
    event_type: str
    purchase_cents: int
    points: int
    created_at: str


class PromotionCampaign(TypedDict):
    id: str
    store_id: str
    name: str
    start_date: str
    end_date: str
    discount_pct: int
    floor_price_cents: int
    status: str
    reconciled: bool
    created_at: str
    updated_at: str
    version: int
