"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §2.4, §3)."""
from enum import Enum
from typing import TypedDict, Optional


class TierCode(str, Enum):
    PERSONAL = "PERSONAL"
    EDUCATION = "EDUCATION"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class TierConfigStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OrgStanding(str, Enum):
    GOOD = "GOOD"
    REVIEW = "REVIEW"
    SUSPENDED = "SUSPENDED"


class MigrationStatus(str, Enum):
    NONE = "NONE"
    ASSESSING = "ASSESSING"
    COOLING_OFF = "COOLING_OFF"
    MIGRATED = "MIGRATED"


class SubscriptionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"


class SupportStatus(str, Enum):
    SUPPORTED = "SUPPORTED"
    LTS = "LTS"
    DEPRECATED = "DEPRECATED"
    SUNSET = "SUNSET"


class ProjectStatus(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    SHIPPED = "SHIPPED"
    FROZEN = "FROZEN"
    ARCHIVED = "ARCHIVED"


class ReportStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACCEPTED = "ACCEPTED"
    DISPUTED = "DISPUTED"
    ARCHIVED = "ARCHIVED"


class AssessmentStatus(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    ADJUSTED = "ADJUSTED"
    VOIDED = "VOIDED"


class PaymentStatus(str, Enum):
    UNPAID = "UNPAID"
    PAID = "PAID"
    WAIVED = "WAIVED"
    OVERDUE = "OVERDUE"


class PolicyChangeStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RESCINDED = "RESCINDED"


class CommitmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    VOIDED = "VOIDED"


class ListingStatus(str, Enum):
    DRAFT = "DRAFT"
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DELISTED = "DELISTED"


class PurchaseStatus(str, Enum):
    COMPLETED = "COMPLETED"
    REFUNDED = "REFUNDED"


class AgreementStatus(str, Enum):
    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class PlatformCode(str, Enum):
    CONSOLE_A = "CONSOLE_A"
    CONSOLE_B = "CONSOLE_B"
    CONSOLE_C = "CONSOLE_C"


class CaseStatus(str, Enum):
    OPENED = "OPENED"
    EVIDENCE_REQUESTED = "EVIDENCE_REQUESTED"
    CLEARED = "CLEARED"
    CONVERTED = "CONVERTED"
    APPEALED = "APPEALED"


class TriggerReason(str, Enum):
    REVENUE_CEILING_BREACH = "REVENUE_CEILING_BREACH"
    EDUCATION_ELIGIBILITY = "EDUCATION_ELIGIBILITY"
    MANUAL = "MANUAL"


class MigrationAssessmentStatus(str, Enum):
    REQUESTED = "REQUESTED"
    EXPORT_READY = "EXPORT_READY"
    COOLING_OFF = "COOLING_OFF"
    COMPLETED = "COMPLETED"
    ABANDONED = "ABANDONED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    ORG_OWNER = "OrgOwner"
    FINANCE_OPS = "FinanceOps"
    AUDITOR = "Auditor"
    REVIEW_BOARD = "ReviewBoard"


# Full common-field entities (PRD §2.4): id, created_at, updated_at, version.

class TierConfig(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    tier_code: str
    revenue_ceiling_cents: int
    funding_ceiling_cents: int
    seat_minimum: int
    seat_overage_cents: int
    runtime_fee_exempt: bool
    export_module_allowed: bool
    marketplace_sell_allowed: bool
    supersedes_tier_config_id: Optional[str]
    tier_config_status: str


class DeveloperOrg(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    legal_name: str
    contact_email: str
    education_verified: bool
    declared_tier_code: str
    effective_tier_code: str
    org_standing: str
    trust_score: int
    migration_status: str
    balance_due_cents: int
    marketplace_credit_cents: int


class SeatSubscription(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_id: str
    tier_code: str
    purchased_seats: int
    active_seats: int
    available_seats: int
    coverage_start: str
    coverage_end: str
    subscription_status: str


class EditorVersion(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    version_string: str
    major_line: str
    released_on: str
    support_status: str
    lts_window_start: Optional[str]
    lts_window_end: Optional[str]
    deprecated_api_count: int


class GameProject(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_id: str
    title: str
    editor_version_id: str
    charity_flag: bool
    project_status: str
    shipped_on: Optional[str]
    lifetime_installs: int
    upgrade_risk_score: int
    pinned_policy_change_id: Optional[str]


class InstallReport(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    period_month: str
    new_device_installs: int
    reinstalls: int
    bundle_installs: int
    report_status: str
    billable_installs: int
    supersedes_report_id: Optional[str]
    review_note: Optional[str]


class RuntimeFeeInvoice(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    project_id: str
    report_id: str
    assessment_status: str
    payment_status: str
    provisional_amount_cents: int
    final_amount_cents: int
    paid_cents: int
    waived_cents: int
    due_date: Optional[str]
    fee_schedule_label: str


class PolicyChange(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    change_code: str
    announcement_date: str
    effective_date: str
    retroactive_flag: bool
    adverse_flag: bool
    grandfather_window_days: int
    new_per_install_cents: int
    change_status: str


class GrandfatherCommitment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    policy_change_id: str
    org_id: str
    project_id: str
    locked_schedule_label: str
    commitment_status: str
    attestation_deadline: str


class AssetListing(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    creator_org_id: str
    title: str
    price_cents: int
    listing_status: str
    review_rounds: int


class ExportAgreement(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_id: str
    platform_code: str
    term_start: str
    term_end: str
    agreement_status: str


class AuditCase(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_id: str
    trigger_reason: str
    case_status: str
    resolved_tier_code: Optional[str]
    back_bill_cents: int
    appeal_count: int


class MigrationAssessment(TypedDict, total=False):
    id: str
    created_at: str
    updated_at: str
    version: int
    org_id: str
    target_engine: str
    assessment_status: str
    buyout_quote_cents: int
    cooling_off_until: Optional[str]


# Lean common-field entities (PRD §2.4): id and created_at ONLY — no updated_at,
# no version. RevenueDeclaration, ExportBuild, AssetPurchase.

class RevenueDeclaration(TypedDict, total=False):
    id: str
    created_at: str
    org_id: str
    period_month: str
    gross_revenue_cents: int
    funding_received_cents: int
    declared_at: str


class ExportBuild(TypedDict, total=False):
    id: str
    created_at: str
    project_id: str
    agreement_id: str
    platform_code: str
    build_label: str
    created_on: str


class AssetPurchase(TypedDict, total=False):
    id: str
    created_at: str
    listing_id: str
    buyer_org_id: str
    gross_cents: int
    platform_share_cents: int
    creator_share_cents: int
    purchase_status: str
    purchased_at: str
