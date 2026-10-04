"""Domain types: entity TypedDicts, status enums, role enum.

PRD §2.4: every persisted entity carries id (server-minted UUID, no type
prefix); most entities also carry created_at / updated_at / version.
PriceLine and TeamingScope carry ONLY id and created_at.
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    CONTRACTS_MANAGER = "ContractsManager"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    RESELLER_OPS = "ResellerOps"
    INTEGRATOR = "Integrator"
    FINANCE_OPS = "FinanceOps"
    AUDITOR = "Auditor"


class ManufacturerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ManufacturerType(str, Enum):
    SOFTWARE_PUBLISHER = "SOFTWARE_PUBLISHER"
    HARDWARE_OEM = "HARDWARE_OEM"
    CLOUD_SAAS = "CLOUD_SAAS"
    HYBRID = "HYBRID"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AgreementPosture(str, Enum):
    GOOD_STANDING = "GOOD_STANDING"
    ON_HOLD = "ON_HOLD"
    SUSPENDED = "SUSPENDED"


class BuyerTier(str, Enum):
    FEDERAL = "FEDERAL"
    STATE = "STATE"
    LOCAL = "LOCAL"
    EDUCATION = "EDUCATION"
    HEALTHCARE = "HEALTHCARE"


class VehicleKind(str, Enum):
    FED_SCHEDULE = "FED_SCHEDULE"
    STATE_COOP = "STATE_COOP"
    AGENCY_SPECIFIC = "AGENCY_SPECIFIC"
    COOP_PURCHASING = "COOP_PURCHASING"


class VehicleStatus(str, Enum):
    PENDING = "PENDING"
    AUTHORIZED = "AUTHORIZED"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class PriceListStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    REJECTED = "REJECTED"


class TeamingStatus(str, Enum):
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class OrderComplianceStatus(str, Enum):
    DRAFT = "DRAFT"
    SCREENING = "SCREENING"
    CLEARED = "CLEARED"
    BLOCKED = "BLOCKED"
    CANCELLED = "CANCELLED"


class OrderBillingStatus(str, Enum):
    UNBILLED = "UNBILLED"
    DELIVERED = "DELIVERED"
    INVOICED = "INVOICED"
    PAID = "PAID"


class OriginFlag(str, Enum):
    TAA_PASS = "TAA_PASS"
    TAA_FAIL = "TAA_FAIL"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class InvoiceStatus(str, Enum):
    ISSUED = "ISSUED"
    PAID = "PAID"
    OVERDUE = "OVERDUE"
    VOID = "VOID"


class DisputeKind(str, Enum):
    PRICING_OVERCHARGE = "PRICING_OVERCHARGE"
    TAA_BREACH = "TAA_BREACH"
    SCOPE_VIOLATION = "SCOPE_VIOLATION"
    BILLING_ERROR = "BILLING_ERROR"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_CREDIT = "RESOLVED_CREDIT"
    RESOLVED_DEBIT = "RESOLVED_DEBIT"
    REJECTED = "REJECTED"


class SalesReportStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"


class AuditScope(str, Enum):
    PRICING_DISCLOSURE = "PRICING_DISCLOSURE"
    SALES_REPORTING = "SALES_REPORTING"
    TAA_ORIGIN = "TAA_ORIGIN"
    FULL = "FULL"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDING_ISSUED = "FINDING_ISSUED"
    CLOSED = "CLOSED"


class PriceModificationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReasonCode(str, Enum):
    PRC_TRIGGERED = "PRC_TRIGGERED"
    COMMERCIAL_ALIGNMENT = "COMMERCIAL_ALIGNMENT"
    ADMIN_CORRECTION = "ADMIN_CORRECTION"


# ---------------------------------------------------------------------------
# Entity TypedDicts
# ---------------------------------------------------------------------------

class Manufacturer(TypedDict, total=False):
    id: str
    legal_name: str
    duns: str
    manufacturer_type: str
    headquarters_country: str
    designated_countries: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ManufacturerAgreement(TypedDict, total=False):
    id: str
    manufacturer_id: str
    scope_tiers: List[str]
    mfc_discount_pct: float
    small_business_goal_pct: float
    product_scope: List[str]
    term_start: str
    term_end: str
    dispute_credit_cents: int
    posture: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ContractVehicle(TypedDict, total=False):
    id: str
    agreement_id: str
    vehicle_kind: str
    buyer_tiers: List[str]
    ceiling_cents: int
    taa_required: bool
    effective_from: str
    effective_to: str
    prc_accumulator_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceList(TypedDict, total=False):
    id: str
    vehicle_id: str
    submitted_by: str
    period_from: str
    period_to: str
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: PriceLine carries only id and created_at (no updated_at, no version).
class PriceLine(TypedDict, total=False):
    id: str
    price_list_id: str
    sku: str
    basis_price_cents: int
    offered_price_cents: int
    origin_country: str
    sold_qty: int
    created_at: str


class TeamingArrangement(TypedDict, total=False):
    id: str
    agreement_id: str
    integrator_name: str
    small_business: bool
    revenue_share_pct: float
    window_start: str
    window_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# PRD §2.4: TeamingScope carries only id and created_at.
class TeamingScope(TypedDict, total=False):
    id: str
    teaming_id: str
    vehicle_id: str
    sku_prefixes: List[str]
    created_at: str


class OrderLine(TypedDict):
    sku: str
    qty: int


class Order(TypedDict, total=False):
    id: str
    vehicle_id: str
    price_list_id: str
    teaming_id: Optional[str]
    buyer_tier: str
    lines: List[OrderLine]
    order_total_cents: int
    teaming_surcharge_cents: int
    subcontract_cents: int
    compliance_status: str
    billing_status: str
    origin_flag: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    order_id: str
    period_label: str
    amount_cents: int
    payment_terms_days: int
    issued_at: str
    due_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Dispute(TypedDict, total=False):
    id: str
    order_id: str
    kind: str
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SalesReport(TypedDict, total=False):
    id: str
    agreement_id: str
    period_label: str
    total_sales_cents: int
    total_sb_subcontract_cents: int
    sb_goal_met: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    agreement_id: str
    scope: str
    mfc_attestation_cents: int
    mfc_variance_cents: int
    disclosed_total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PriceModification(TypedDict, total=False):
    id: str
    price_list_id: str
    sku: str
    new_offered_price_cents: int
    reason_code: str
    expected_price_list_version: int
    status: str
    created_at: str
    updated_at: str
    version: int
