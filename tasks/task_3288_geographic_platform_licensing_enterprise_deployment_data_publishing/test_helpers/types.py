"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class OrgKind(str, Enum):
    COMMERCIAL = "COMMERCIAL"
    EDUCATION = "EDUCATION"
    NONPROFIT = "NONPROFIT"


class OrgStatus(str, Enum):
    PROVISIONING = "PROVISIONING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class PoolPosture(str, Enum):
    OK = "OK"
    LOW_CREDIT = "LOW_CREDIT"
    EXHAUSTED = "EXHAUSTED"
    OVERDRAWN = "OVERDRAWN"


class LicenseKind(str, Enum):
    NAMED_USER = "NAMED_USER"
    CONCURRENT_USE = "CONCURRENT_USE"
    DEPLOYMENT_SERVER = "DEPLOYMENT_SERVER"


class Edition(str, Enum):
    BASIC = "BASIC"
    STANDARD = "STANDARD"
    ADVANCED = "ADVANCED"


class ProductStatus(str, Enum):
    CATALOG = "CATALOG"
    RETIRED = "RETIRED"


class GrantKind(str, Enum):
    STANDARD = "STANDARD"
    EDUCATION_PROGRAM = "EDUCATION_PROGRAM"
    NONPROFIT_PROGRAM = "NONPROFIT_PROGRAM"


class GrantStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class ExtensionGrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class NamedUserLevel(str, Enum):
    VIEWER = "VIEWER"
    EDITOR = "EDITOR"
    FIELD_WORKER = "FIELD_WORKER"
    CREATOR = "CREATOR"
    PROFESSIONAL = "PROFESSIONAL"
    PROFESSIONAL_PLUS = "PROFESSIONAL_PLUS"


class NamedUserStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"
    DEACTIVATED = "DEACTIVATED"


class ServerRole(str, Enum):
    GIS_SERVER = "GIS_SERVER"
    PORTAL = "PORTAL"
    DATA_STORE = "DATA_STORE"
    NOTEBOOK_SERVER = "NOTEBOOK_SERVER"


class AuthMode(str, Enum):
    BUILTIN = "BUILTIN"
    SAML = "SAML"
    OIDC = "OIDC"
    IWA = "IWA"


class ServerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    AUTHORIZED = "AUTHORIZED"
    UPGRADING = "UPGRADING"
    DECOMMISSIONED = "DECOMMISSIONED"


class ItemKind(str, Enum):
    FEATURE_LAYER = "FEATURE_LAYER"
    TILE_LAYER = "TILE_LAYER"
    BASEMAP = "BASEMAP"
    WEB_MAP = "WEB_MAP"
    NOTEBOOK = "NOTEBOOK"
    API_APP = "API_APP"


class SharingLevel(str, Enum):
    PRIVATE = "PRIVATE"
    ORGANIZATION = "ORGANIZATION"
    PUBLIC = "PUBLIC"


class ItemStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    FLAGGED = "FLAGGED"
    RETRACTED = "RETRACTED"


class ApiKeyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"


class ServiceKind(str, Enum):
    GEOCODE = "GEOCODE"
    ANALYSIS = "ANALYSIS"
    STORAGE = "STORAGE"
    TILE_QUERY = "TILE_QUERY"
    ROUTING = "ROUTING"


class BatchStatus(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    REVERSED = "REVERSED"


class EVStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    RENEWAL_REQUIRED = "RENEWAL_REQUIRED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    LICENSE_ADMIN = "LicenseAdmin"
    DEPLOYMENT_ADMIN = "DeploymentAdmin"
    BILLING_ADMIN = "BillingAdmin"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    CONTENT_MODERATOR = "ContentModerator"
    NAMED_USER = "NamedUser"


class Organization(TypedDict, total=False):
    id: str
    name: str
    org_kind: str
    home_region: str
    status: str
    credit_balance: int
    seat_overage_fee_accrued_cents: int
    current_period_index: int
    created_at: str
    updated_at: str
    version: int


class CreditPool(TypedDict, total=False):
    id: str
    organization_id: str
    capacity_credits: int
    reserved_credits: int
    consumed_credits: int
    low_credit_threshold_credits: int
    posture: str
    created_at: str
    updated_at: str
    version: int


class LicenseProduct(TypedDict, total=False):
    id: str
    product_code: str
    license_kind: str
    edition: str
    major_version: int
    base_seat_count: int
    supports_offline: bool
    allows_derivative_works: bool
    extension_modules: List[dict]
    status: str
    created_at: str
    updated_at: str
    version: int


class LicenseGrant(TypedDict, total=False):
    id: str
    organization_id: str
    license_product_id: str
    grant_kind: str
    seats_allocated: int
    seats_in_use: int
    valid_from_period: int
    valid_to_period: int
    status: str
    created_at: str
    updated_at: str
    version: int


class ExtensionGrant(TypedDict, total=False):
    id: str
    license_grant_id: str
    extension_code: str
    seats_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class NamedUser(TypedDict, total=False):
    id: str
    organization_id: str
    username: str
    email: str
    named_user_level: str
    home_license_grant_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


class DeploymentServer(TypedDict, total=False):
    id: str
    organization_id: str
    hostname: str
    role: str
    installed_major_version: int
    target_major_version: int
    auth_mode: str
    license_grant_id: str
    cores_allocated: int
    status: str
    created_at: str
    updated_at: str
    version: int


class VersionCompatibilityRule(TypedDict, total=False):
    id: str
    consumer_role: str
    consumer_major_version: int
    dependency_role: str
    allowed_dependency_major_versions: List[int]
    strict: bool
    created_at: str
    updated_at: str
    version: int


class ContentItem(TypedDict, total=False):
    id: str
    organization_id: str
    owner_named_user_id: str
    title: str
    item_kind: str
    sharing_level: str
    derived_from_item_id: Optional[str]
    contains_licensed_basemap: bool
    offline_enabled: bool
    storage_bytes: int
    resolution_rationale: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class ApiKey(TypedDict, total=False):
    id: str
    named_user_id: str
    organization_id: str
    label: str
    allowed_service_kinds: List[str]
    per_key_credit_cap: int
    credits_consumed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CreditBatch(TypedDict, total=False):
    id: str
    organization_id: str
    api_key_id: Optional[str]
    service_kind: str
    requested_units: int
    extension_code: Optional[str]
    provisional_credits: int
    settled_credits: int
    idempotency_key: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityVerification(TypedDict, total=False):
    id: str
    organization_id: str
    program_kind: str
    submitted_by_named_user_id: str
    evidence_document_ref: str
    decided_by_named_user_id: Optional[str]
    decision_rationale: Optional[str]
    valid_through_period: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int
