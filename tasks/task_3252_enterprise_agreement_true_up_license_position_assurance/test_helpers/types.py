"""Domain types: entity shapes, status enums, and role names for the licensing API."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PROGRAM_ADMINISTRATOR = "ProgramAdministrator"
    LICENSING_SPECIALIST = "LicensingSpecialist"
    CUSTOMER_ADMIN = "CustomerAdmin"
    AUDITOR = "Auditor"


class PriceLevel(str, Enum):
    A = "A"
    B = "B"
    C = "C"
    D = "D"


class AgreementStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RENEWAL_PENDING = "RENEWAL_PENDING"
    RENEWED = "RENEWED"
    EXPIRED = "EXPIRED"
    NON_RENEWED = "NON_RENEWED"


class LicenseModel(str, Enum):
    PER_USER = "PER_USER"
    PER_DEVICE = "PER_DEVICE"
    PER_SERVER_CORE = "PER_SERVER_CORE"


class LicenseKind(str, Enum):
    PERPETUAL = "PERPETUAL"
    SUBSCRIPTION = "SUBSCRIPTION"


class Edition(str, Enum):
    STANDARD = "STANDARD"
    PROFESSIONAL = "PROFESSIONAL"
    ENTERPRISE = "ENTERPRISE"


class DeploymentScope(str, Enum):
    USER = "USER"
    DEVICE = "DEVICE"
    SERVER = "SERVER"


class LicensingMode(str, Enum):
    PER_HOST = "PER_HOST"
    PER_VM = "PER_VM"


class Hosting(str, Enum):
    ON_PREMISES = "ON_PREMISES"
    AUTHORIZED_MOBILITY_PARTNER = "AUTHORIZED_MOBILITY_PARTNER"
    THIRD_PARTY_DATACENTER = "THIRD_PARTY_DATACENTER"


class TrueUpReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"
    INVOICED = "INVOICED"
    SETTLED = "SETTLED"


class PricingVariant(str, Enum):
    ANNIVERSARY_PRORATION = "ANNIVERSARY_PRORATION"
    FULL_YEAR_RETROACTIVE = "FULL_YEAR_RETROACTIVE"


class BenefitType(str, Enum):
    TRAINING_VOUCHER = "TRAINING_VOUCHER"
    SUPPORT_INCIDENT = "SUPPORT_INCIDENT"
    UPGRADE_RIGHT = "UPGRADE_RIGHT"


class GrantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEPLETED = "DEPLETED"
    EXPIRED = "EXPIRED"
    FORFEITED = "FORFEITED"


class StepUpStatus(str, Enum):
    REQUESTED = "REQUESTED"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class AuthorizationStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class Organization(TypedDict, total=False):
    id: str
    legal_name: str
    qualified_device_count: int
    price_level: str
    created_at: str
    updated_at: str
    version: int


class Agreement(TypedDict, total=False):
    id: str
    organization_id: str
    enrollment_number: str
    start_date: str
    end_date: str
    status: str
    renewal_count: int
    created_at: str
    updated_at: str
    version: int


class Product(TypedDict, total=False):
    id: str
    sku: str
    name: str
    license_model: str
    license_kind: str
    edition: str
    family: str
    annual_unit_price_cents: int
    license_mobility: bool
    created_at: str
    updated_at: str
    version: int


class EnrollmentAnniversary(TypedDict, total=False):
    id: str
    agreement_id: str
    year_index: int
    period_start: str
    period_end: str
    true_up_closed: bool
    created_at: str
    updated_at: str
    version: int


class LicenseEntitlement(TypedDict, total=False):
    id: str
    agreement_id: str
    product_id: str
    quantity: int
    locked_baseline_quantity: int
    unit_price_cents: int
    acquired_at: str
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict, total=False):
    id: str
    agreement_id: str
    product_id: str
    scope: str
    deployment_date: str
    user_count: int
    device_count: int
    physical_cores_per_server: int
    core_factor: float
    vm_count: int
    vcores_per_vm: int
    licensing_mode: str
    hosting: str
    retired: bool
    created_at: str
    updated_at: str
    version: int


class SnapshotLine(TypedDict, total=False):
    product_id: str
    scope: str
    required_licenses: int
    entitled_quantity: int
    net_position: int


class LicensePositionSnapshot(TypedDict):
    # Append-only computation record: id + created_at only, no updated_at/version.
    id: str
    agreement_id: str
    anniversary_id: str
    computed_at: str
    lines: List[SnapshotLine]
    created_at: str


class TrueUpReport(TypedDict, total=False):
    id: str
    agreement_id: str
    anniversary_id: str
    status: str
    snapshot_id: str
    total_amount_cents: int
    revision_count: int
    created_at: str
    updated_at: str
    version: int


class TrueUpLine(TypedDict, total=False):
    id: str
    report_id: str
    product_id: str
    growth_quantity: int
    months_growth: int
    pricing_variant: str
    unit_price_cents: int
    total_amount_cents: int
    created_at: str
    updated_at: str
    version: int


class AssuranceBenefitGrant(TypedDict, total=False):
    id: str
    agreement_id: str
    benefit_type: str
    quantity_granted: int
    quantity_remaining: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BenefitRedemption(TypedDict):
    # Append-only computation record: id + created_at only.
    id: str
    grant_id: str
    quantity: int
    redeemed_on: str
    created_at: str


class StepUpConversion(TypedDict, total=False):
    id: str
    entitlement_id: str
    target_product_id: str
    quantity: int
    charge_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CloudCommitment(TypedDict, total=False):
    id: str
    agreement_id: str
    committed_amount_cents: int
    consumed_amount_cents: int
    expires_on: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CloudConsumptionEvent(TypedDict):
    # Append-only computation record: id + created_at only.
    id: str
    commitment_id: str
    requested_cents: int
    consumed_cents: int
    occurred_on: str
    created_at: str


class HostingAuthorization(TypedDict, total=False):
    id: str
    agreement_id: str
    product_id: str
    provider_name: str
    status: str
    effective_on: str
    created_at: str
    updated_at: str
    version: int


class ShortfallLine(TypedDict, total=False):
    product_id: str
    license_kind: str
    required_licenses: int
    perpetual_quantity: int
    subscription_quantity: int
    effective_coverage: int
    shortfall: int


class ShortfallAssessment(TypedDict):
    # Append-only computation record: id + created_at only.
    id: str
    agreement_id: str
    agreement_status: str
    assessed_at: str
    lines: List[ShortfallLine]
    created_at: str
