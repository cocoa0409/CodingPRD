"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional


class UserRole(str, Enum):
    SYSTEM_ADMIN = "SystemAdmin"
    ORG_ADMIN = "OrgAdmin"
    DEPLOYMENT_ADMIN = "DeploymentAdmin"
    RESELLER_AGENT = "ResellerAgent"
    END_USER = "EndUser"


class OrgType(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"
    ENTERPRISE = "ENTERPRISE"


class OrgStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class CompliancePosture(str, Enum):
    COMPLIANT = "COMPLIANT"
    OVER_ALLOCATED = "OVER_ALLOCATED"
    UNDER_AUDIT = "UNDER_AUDIT"
    FROZEN = "FROZEN"


class AdminKind(str, Enum):
    SYSTEM_ADMIN = "SYSTEM_ADMIN"
    PRODUCT_ADMIN = "PRODUCT_ADMIN"
    DEPLOYMENT_ADMIN = "DEPLOYMENT_ADMIN"


class EndUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    DEPARTED = "DEPARTED"


class ResellerRegion(str, Enum):
    NA = "NA"
    EMEA = "EMEA"
    APAC = "APAC"
    LATAM = "LATAM"


class ResellerTier(str, Enum):
    CERTIFIED = "CERTIFIED"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class ResellerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PlanSegment(str, Enum):
    INDIVIDUAL = "INDIVIDUAL"
    TEAM = "TEAM"
    ENTERPRISE = "ENTERPRISE"


class BillingModel(str, Enum):
    MONTHLY = "MONTHLY"
    ANNUAL_MONTHLY_BILLED = "ANNUAL_MONTHLY_BILLED"
    ANNUAL_PREPAID = "ANNUAL_PREPAID"


class DeploymentMode(str, Enum):
    NAMED_USER = "NAMED_USER"
    SERIALIZED = "SERIALIZED"
    SHARED_DEVICE = "SHARED_DEVICE"


class SubscriptionStatus(str, Enum):
    PENDING_PAYMENT = "PENDING_PAYMENT"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    CANCELLED_IN_WINDOW = "CANCELLED_IN_WINDOW"
    CANCELLED_ETF = "CANCELLED_ETF"
    EXPIRED = "EXPIRED"


class SeatStatus(str, Enum):
    UNASSIGNED = "UNASSIGNED"
    ASSIGNED = "ASSIGNED"
    PENDING_RECLAIM = "PENDING_RECLAIM"
    RECLAIMED = "RECLAIMED"
    TRANSFERRING = "TRANSFERRING"


class DeviceStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"


class EntitlementStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class PackageStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    PUBLISHED = "PUBLISHED"
    RETIRED = "RETIRED"
    REJECTED = "REJECTED"


class VersionAvailability(str, Enum):
    AVAILABLE = "AVAILABLE"
    DEPRECATED = "DEPRECATED"
    FORCED_UPGRADE = "FORCED_UPGRADE"


class AddOnKind(str, Enum):
    STOCK_CREDITS = "STOCK_CREDITS"
    FONTS = "FONTS"
    CLOUD_SERVICES = "CLOUD_SERVICES"


class AddOnStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    CANCELLED = "CANCELLED"


class AssetStatus(str, Enum):
    ACTIVE = "ACTIVE"
    IN_TRANSFER = "IN_TRANSFER"
    TRANSFERRED = "TRANSFERRED"
    ORPHANED = "ORPHANED"
    PURGED = "PURGED"


class TransferRequestStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    EXECUTED = "EXECUTED"
    EXPIRED = "EXPIRED"


class ResellerOrderStatus(str, Enum):
    ROUTED = "ROUTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"


class AuditStatus(str, Enum):
    OPEN = "OPEN"
    FINDINGS_RAISED = "FINDINGS_RAISED"
    REMEDIATED = "REMEDIATED"
    CLOSED = "CLOSED"


class CancellationStatus(str, Enum):
    PENDING = "PENDING"
    REFUNDED = "REFUNDED"
    ETF_CHARGED = "ETF_CHARGED"
    DENIED = "DENIED"


# --- Entity TypedDicts (all primary resources carry common fields) ---

class Organization(TypedDict, total=False):
    id: str
    name: str
    org_type: str
    status: str
    primary_admin_id: str
    storage_pool_gb: float
    compliance_posture: str
    created_at: str
    updated_at: str
    version: int


class Admin(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    admin_kind: str
    org_id: str
    created_at: str
    updated_at: str
    version: int


class EndUser(TypedDict, total=False):
    id: str
    email: str
    full_name: str
    org_id: str
    status: str
    storage_used_gb: float
    created_at: str
    updated_at: str
    version: int


class Reseller(TypedDict, total=False):
    id: str
    name: str
    region: str
    tier: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Plan(TypedDict, total=False):
    id: str
    code: str
    segment: str
    billing_model: str
    monthly_price_cents: int
    annual_monthly_price_cents: int
    storage_gb_per_seat: int
    seat_limit: int
    deployment_modes: list
    allows_offline_activation: bool
    max_devices_per_seat: int
    cancellation_window_days: int
    etf_rate_pct: int
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    org_id: str
    plan_id: str
    reseller_id: Optional[str]
    status: str
    seats_purchased: int
    seats_assigned: int
    commitment_start: Optional[str]
    commitment_months: int
    months_elapsed: int
    monthly_charge_cents: int
    created_at: str
    updated_at: str
    version: int


class Seat(TypedDict, total=False):
    id: str
    subscription_id: str
    end_user_id: Optional[str]
    status: str
    assigned_at: Optional[str]
    pending_reclaim_not_before: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    end_user_id: str
    device_fingerprint: str
    label: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Entitlement(TypedDict, total=False):
    id: str
    seat_id: str
    device_id: Optional[str]
    status: str
    product_version_id: str
    storage_granted_gb: int
    created_at: str
    updated_at: str
    version: int


class DeploymentPackage(TypedDict, total=False):
    id: str
    org_id: str
    created_by_admin_id: str
    name: str
    plan_id: str
    deployment_mode: str
    offline_activation: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class ProductVersion(TypedDict, total=False):
    id: str
    plan_id: str
    version_label: str
    release_date: str
    availability: str
    forced_upgrade_deadline: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AddOnService(TypedDict, total=False):
    id: str
    subscription_id: str
    kind: str
    quota_total: int
    quota_used: int
    status: str
    overage_unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Asset(TypedDict, total=False):
    id: str
    owner_user_id: str
    org_id: str
    title: str
    size_mb: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TransferRequest(TypedDict, total=False):
    id: str
    org_id: str
    seat_id: str
    from_user_id: str
    to_user_id: str
    requested_by_admin_id: str
    approver_admin_id: Optional[str]
    status: str
    expires_at: str
    created_at: str
    updated_at: str
    version: int


class ResellerOrder(TypedDict, total=False):
    id: str
    reseller_id: str
    org_id: str
    plan_id: str
    seats: int
    region: str
    status: str
    discount_pct: int
    created_at: str
    updated_at: str
    version: int


class ComplianceAudit(TypedDict, total=False):
    id: str
    org_id: str
    opened_by_admin_id: str
    status: str
    over_allocated_seats: int
    findings_count: int
    created_at: str
    updated_at: str
    version: int


class CancellationRequest(TypedDict, total=False):
    id: str
    subscription_id: str
    requested_by_admin_id: str
    requested_at: str
    status: str
    etf_amount_cents: int
    created_at: str
    updated_at: str
    version: int
