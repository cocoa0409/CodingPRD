"""Domain types: entity TypedDicts, status enums, role enum.

Every lifecycle-bearing resource carries the standard common fields
(id, created_at, updated_at, version) per the PRD's common-resource
section; the immutable permission-scope catalog entry carries only
id and created_at.
"""
from enum import Enum
from typing import Optional, TypedDict


class DeveloperAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class AppStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    LISTED = "LISTED"
    SUSPENDED = "SUSPENDED"
    DELISTED = "DELISTED"


class ListingStatus(str, Enum):
    UNLISTED = "UNLISTED"
    LISTED = "LISTED"
    DELISTED = "DELISTED"


class PerformanceState(str, Enum):
    COMPLIANT = "COMPLIANT"
    DEGRADED = "DEGRADED"
    DELISTED_PERFORMANCE = "DELISTED_PERFORMANCE"


class AppCategory(str, Enum):
    PRODUCTIVITY = "PRODUCTIVITY"
    MARKETING = "MARKETING"
    FULFILLMENT = "FULFILLMENT"
    ANALYTICS = "ANALYTICS"
    FINANCE = "FINANCE"


class RevenueShareTier(str, Enum):
    T0 = "T0"
    T1 = "T1"
    T2 = "T2"


class AppVersionStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    CHANGES_REQUESTED = "CHANGES_REQUESTED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PUBLISHED = "PUBLISHED"
    SUPERSEDED = "SUPERSEDED"


class RiskLevel(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class ScopeRequestStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"


class ReviewWindowStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class PlanTier(str, Enum):
    BASIC = "BASIC"
    GROWTH = "GROWTH"
    ENTERPRISE = "ENTERPRISE"


class InstallationStatus(str, Enum):
    PENDING_CONSENT = "PENDING_CONSENT"
    ACTIVE = "ACTIVE"
    RECONSENT_REQUIRED = "RECONSENT_REQUIRED"
    SUSPENDED = "SUSPENDED"
    UNINSTALLING = "UNINSTALLING"
    UNINSTALLED = "UNINSTALLED"


class ConsentRecordStatus(str, Enum):
    GRANTED = "GRANTED"
    REVOKED = "REVOKED"


class WebhookSubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FAILING = "FAILING"
    DISABLED = "DISABLED"


class ChargeType(str, Enum):
    RECURRING = "RECURRING"
    USAGE = "USAGE"
    ONE_TIME = "ONE_TIME"


class ChargeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    INVOICED = "INVOICED"
    REVERSED = "REVERSED"
    SETTLED = "SETTLED"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class LedgerEntryType(str, Enum):
    ACCRUAL = "ACCRUAL"
    REVERSAL = "REVERSAL"
    ADJUSTMENT = "ADJUSTMENT"


class LedgerEntryVariant(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINAL = "FINAL"


class StrikeReason(str, Enum):
    DATA_DELETION_OVERDUE = "DATA_DELETION_OVERDUE"
    WEBHOOK_NONCOMPLIANCE = "WEBHOOK_NONCOMPLIANCE"
    PERFORMANCE_BREACH = "PERFORMANCE_BREACH"
    SUPPORT_BREACH = "SUPPORT_BREACH"


class StrikeStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    CLEARED = "CLEARED"


class TicketSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class TicketStatus(str, Enum):
    OPEN = "OPEN"
    ANSWERED = "ANSWERED"
    ESCALATED = "ESCALATED"
    RESOLVED = "RESOLVED"
    DISPUTED = "DISPUTED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    DEVELOPER = "Developer"
    REVIEWER = "Reviewer"
    MERCHANT = "Merchant"


class DeveloperAccount(TypedDict):
    id: str
    company_name: str
    contact_email: str
    payout_currency: str
    status: str
    lifetime_gross_cents: int
    created_at: str
    updated_at: str
    version: int


class App(TypedDict):
    id: str
    developer_id: str
    name: str
    status: str
    listing_status: str
    category: str
    submitted_at: Optional[str]
    revenue_share_tier: str
    performance_state: str
    created_at: str
    updated_at: str
    version: int


class AppVersion(TypedDict):
    id: str
    app_id: str
    semver: str
    status: str
    review_round: int
    created_at: str
    updated_at: str
    version: int


class PermissionScope(TypedDict):
    # Catalog entries are immutable: only id and created_at.
    id: str
    code: str
    risk_level: str
    created_at: str


class ScopeRequest(TypedDict):
    id: str
    app_version_id: str
    scope_code: str
    status: str
    denied_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ReviewWindow(TypedDict):
    id: str
    app_version_id: str
    reviewer_id: str
    starts_at: str
    ends_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class MerchantAccount(TypedDict):
    id: str
    shop_domain: str
    plan_tier: str
    created_at: str
    updated_at: str
    version: int


class Installation(TypedDict):
    id: str
    app_id: str
    merchant_id: str
    status: str
    installed_at: Optional[str]
    uninstalled_at: Optional[str]
    data_deletion_deadline: Optional[str]
    data_deletion_confirmed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict):
    id: str
    installation_id: str
    scope_code: str
    status: str
    granted_at: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WebhookSubscription(TypedDict):
    id: str
    installation_id: str
    topic: str
    endpoint_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


class AppBillingCharge(TypedDict):
    id: str
    installation_id: str
    billing_cycle: str
    charge_type: str
    status: str
    base_amount_cents: int
    discount_code: Optional[str]
    discount_amount_cents: int
    final_amount_cents: int
    platform_share_cents: int
    developer_net_cents: int
    description: str
    capped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class MonthlyInvoice(TypedDict):
    id: str
    merchant_id: str
    cycle: str
    status: str
    total_cents: int
    issued_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RevenueShareLedgerEntry(TypedDict):
    id: str
    developer_id: str
    charge_id: str
    entry_type: str
    amount_cents: int
    entry_variant: str
    cycle: str
    created_at: str
    updated_at: str
    version: int


class PerformanceSample(TypedDict):
    id: str
    installation_id: str
    storefront_load_ms: int
    sampled_at: str
    created_at: str
    updated_at: str
    version: int


class GovernanceStrike(TypedDict):
    id: str
    app_id: str
    reason: str
    status: str
    strike_start: str
    strike_ends_at: str
    created_at: str
    updated_at: str
    version: int


class SupportTicket(TypedDict):
    id: str
    app_id: str
    merchant_id: str
    severity: str
    sla_hours: int
    status: str
    opened_at: str
    first_response_at: Optional[str]
    sla_breached: bool
    created_at: str
    updated_at: str
    version: int
