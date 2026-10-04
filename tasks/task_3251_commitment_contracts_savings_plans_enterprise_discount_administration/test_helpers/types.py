"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class LinkedAccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class AgreementLifecycle(str, Enum):
    NEGOTIATION = "NEGOTIATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class AgreementRenewal(str, Enum):
    NONE = "NONE"
    RENEWAL_REVIEW = "RENEWAL_REVIEW"
    RENEWED = "RENEWED"
    ABANDONED = "ABANDONED"


class PlanType(str, Enum):
    SAVINGS_PLAN = "SAVINGS_PLAN"
    RESERVED_CAPACITY = "RESERVED_CAPACITY"


class PlanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    TERMINATED = "TERMINATED"


class UsageStatus(str, Enum):
    INGESTED = "INGESTED"
    BILLED = "BILLED"


class CreditGrantStatus(str, Enum):
    ISSUED = "ISSUED"
    DEPLETING = "DEPLETING"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    FINALIZED = "FINALIZED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"
    VOIDED = "VOIDED"


class TrueUpType(str, Enum):
    SHORTFALL = "SHORTFALL"
    EARLY_TERMINATION = "EARLY_TERMINATION"


class TrueUpStatus(str, Enum):
    ASSESSED = "ASSESSED"
    BILLED = "BILLED"
    WAIVED = "WAIVED"
    SETTLED = "SETTLED"


class ForecastVariant(str, Enum):
    LINEAR = "LINEAR"
    COHORT_WEIGHTED = "COHORT_WEIGHTED"


class UserRole(str, Enum):
    PLATFORM_BILLING_OPERATOR = "PlatformBillingOperator"
    ORG_ADMIN = "OrgAdmin"
    FINANCE_ANALYST = "FinanceAnalyst"
    LINKED_ACCOUNT_MANAGER = "LinkedAccountManager"


class BillingOrganization(TypedDict, total=False):
    id: str
    name: str
    currency: str
    max_hourly_commitment_cents: int
    capacity_quota_units: int
    current_period_index: int
    unapplied_credit_cents: int
    created_at: str
    updated_at: str
    version: int


class LinkedAccount(TypedDict, total=False):
    id: str
    org_id: str
    name: str
    external_ref: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EnterpriseAgreement(TypedDict, total=False):
    id: str
    org_id: str
    name: str
    committed_spend_cents: int
    term_start: str
    term_end: str
    lifecycle_status: str
    renewal_status: str
    consumed_commitment_cents: int
    accrued_trueup_cents: int
    created_at: str
    updated_at: str
    version: int


class DiscountTier(TypedDict, total=False):
    id: str
    agreement_id: str
    service_family: str
    threshold_cents: int
    rate: float
    created_at: str
    updated_at: str
    version: int


class PricingAmendment(TypedDict, total=False):
    id: str
    agreement_id: str
    service_family: str
    discount_rate: float
    effective_from: str
    effective_to: str
    created_at: str
    updated_at: str
    version: int


class CommitmentPlan(TypedDict, total=False):
    id: str
    org_id: str
    agreement_id: str
    type: str
    instance_family: str
    units: int
    hourly_commitment_cents: int
    plan_discount_rate: float
    term_start: str
    term_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at, NO updated_at / version
class UsageRecord(TypedDict, total=False):
    id: str
    linked_account_id: str
    org_id: str
    service_family: str
    usage_hour_start: str
    list_price_cents: int
    is_marketplace: bool
    period_index: int
    status: str
    invoice_id: Optional[str]
    created_at: str


class CreditGrant(TypedDict, total=False):
    id: str
    org_id: str
    amount_cents: int
    consumed_cents: int
    forfeited_cents: int
    remaining_cents: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    org_id: str
    period_index: int
    status: str
    agreement_id: Optional[str]
    total_list_cents: int
    total_amendment_discount_cents: int
    total_plan_discount_cents: int
    total_tier_discount_cents: int
    total_credit_applied_cents: int
    total_due_cents: int
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at, NO updated_at / version
class InvoiceLine(TypedDict, total=False):
    id: str
    invoice_id: str
    linked_account_id: str
    service_family: str
    list_cents: int
    amendment_discount_cents: int
    plan_covered_cents: int
    plan_discount_cents: int
    tier_discount_cents: int
    credit_applied_cents: int
    net_due_cents: int
    created_at: str


class TrueUpCharge(TypedDict, total=False):
    id: str
    agreement_id: str
    type: str
    plan_id: Optional[str]
    amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: only id + created_at, NO updated_at / version
class RenewalForecast(TypedDict, total=False):
    id: str
    agreement_id: str
    variant: str
    window_periods: int
    forecast_cents: int
    generated_period_index: int
    created_at: str
