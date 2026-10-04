"""Domain types: entity TypedDicts, status enums, role enum.

All entities in this domain carry the full common-field set: id, created_at,
updated_at, and version (PRD common-properties section).
"""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    SECURITY_ADMIN = "SecurityAdmin"
    PROCUREMENT_ADMIN = "ProcurementAdmin"
    LOGISTICS_COORDINATOR = "LogisticsCoordinator"
    HELP_DESK_AGENT = "HelpDeskAgent"
    EMPLOYEE = "Employee"


class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AssuranceTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_ASSURANCE = "HIGH_ASSURANCE"


class AuthenticationPolicy(str, Enum):
    STANDARD = "STANDARD"
    PHISHING_RESISTANT = "PHISHING_RESISTANT"


class FormFactor(str, Enum):
    KEYCHAIN = "KEYCHAIN"
    NANO = "NANO"
    CARD = "CARD"
    BIOMETRIC = "BIOMETRIC"


class Platform(str, Enum):
    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"
    CHROMEOS = "CHROMEOS"
    ANDROID = "ANDROID"
    IOS = "IOS"


class DeviceLifecycle(str, Enum):
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class IdentityAccountStatus(str, Enum):
    UNENROLLED = "UNENROLLED"
    ENROLLED = "ENROLLED"
    LOCKED = "LOCKED"


class PurchaseOrderStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVED = "APPROVED"
    IN_TRANSIT = "IN_TRANSIT"
    RECEIVED = "RECEIVED"
    QUARANTINED = "QUARANTINED"


class HardwareStatus(str, Enum):
    PRE_REGISTERED = "PRE_REGISTERED"
    ASSIGNED = "ASSIGNED"
    DISTRIBUTED = "DISTRIBUTED"
    REVOKED = "REVOKED"


class AttestationStatus(str, Enum):
    UNVERIFIED = "UNVERIFIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class EnrollmentStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    EXPIRING = "EXPIRING"
    REVOKED = "REVOKED"
    SUPERSEDED = "SUPERSEDED"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    USED = "USED"
    VOIDED = "VOIDED"
    EXPIRED = "EXPIRED"


class GrantMethod(str, Enum):
    TOTP = "TOTP"
    SMART_CARD = "SMART_CARD"
    SERVICE_DESK_TOKEN = "SERVICE_DESK_TOKEN"


class SubscriptionTier(str, Enum):
    BASIC = "BASIC"
    ENTERPRISE = "ENTERPRISE"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class CaseCategory(str, Enum):
    LOST_KEY = "LOST_KEY"
    LOCKOUT = "LOCKOUT"
    OTHER = "OTHER"


class CaseStatus(str, Enum):
    OPEN = "OPEN"
    PENDING_REVIEW = "PENDING_REVIEW"
    RESOLVED = "RESOLVED"
    REJECTED = "REJECTED"


class CaseResolution(str, Enum):
    REVOKED_AND_REPLACED = "REVOKED_AND_REPLACED"
    TEMP_ACCESS_ISSUED = "TEMP_ACCESS_ISSUED"
    REJECTED = "REJECTED"


class Organization(TypedDict, total=False):
    id: str
    legal_name: str
    assurance_tier: str
    authentication_policy: str
    idp_protocols: List[str]
    approved_firmware_versions: List[str]
    backup_key_minimum: int
    status: str
    created_at: str
    updated_at: str
    version: int


class KeyModel(TypedDict, total=False):
    id: str
    model_code: str
    connectors: List[str]
    protocols: List[str]
    form_factor: str
    unit_price_cents: int
    created_at: str
    updated_at: str
    version: int


class Device(TypedDict, total=False):
    id: str
    organization_id: str
    asset_tag: str
    platform: str
    connectors: List[str]
    protocol_capability: List[str]
    lifecycle_status: str
    created_at: str
    updated_at: str
    version: int


class Employee(TypedDict, total=False):
    id: str
    organization_id: str
    employee_ref: str
    location: str
    directory_user_id: str
    identity_account_id: str
    employment_status: str
    created_at: str
    updated_at: str
    version: int


class IdentityAccount(TypedDict, total=False):
    id: str
    employee_id: str
    organization_id: str
    directory_user_id: str
    employee_ref: str
    registered_key_count: int
    backup_compliant: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class PurchaseOrder(TypedDict, total=False):
    id: str
    organization_id: str
    lines: list
    shipping_location: str
    supply_chain_cert_id: Optional[str]
    created_by: str
    line_count: int
    quoted_total_cents: int
    final_total_cents: Optional[int]
    credit_applied_cents: int
    quantity_discount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityKey(TypedDict, total=False):
    id: str
    purchase_order_id: str
    serial_number: str
    model_code: str
    firmware_version: str
    hardware_status: str
    attestation_status: str
    assigned_identity_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnrollmentCeremony(TypedDict, total=False):
    id: str
    identity_account_id: str
    security_key_id: str
    status: str
    activated_at: Optional[str]
    expires_at: Optional[str]
    renewal_count: int
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TemporaryAccessGrant(TypedDict, total=False):
    id: str
    identity_account_id: str
    method: str
    starts_at: str
    duration_hours: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Subscription(TypedDict, total=False):
    id: str
    organization_id: str
    tier: str
    refresh_interval_days: int
    replacement_credits_total: int
    credits_used: int
    credits_remaining: int
    coverage_cents_total: int
    coverage_cents_used: int
    coverage_cents_remaining: int
    percent_discount: float
    status: str
    current_period_start: str
    current_period_end: str
    created_at: str
    updated_at: str
    version: int


class HelpDeskCase(TypedDict, total=False):
    id: str
    identity_account_id: str
    category: str
    description: str
    opened_by_agent_id: str
    resolution: Optional[str]
    resolved_by_agent_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
