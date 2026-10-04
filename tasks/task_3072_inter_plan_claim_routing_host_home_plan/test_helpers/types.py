"""Domain types for the Inter-Plan Claim Routing API.

Entity TypedDicts, status enumerations, and the role enumeration. Every
entity in this API is mutable after creation, so every TypedDict carries the
full common field set: id, created_at, updated_at, version.
"""

from enum import Enum
from typing import List, Optional, TypedDict


class BrandLicenseStatus(str, Enum):
    PENDING = "PENDING"
    LICENSED = "LICENSED"
    SUSPENDED = "SUSPENDED"
    REVOKED = "REVOKED"


class EligibilityStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class NationalAccountStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class ClaimStatus(str, Enum):
    RECEIVED = "RECEIVED"
    PRICED = "PRICED"
    ROUTED = "ROUTED"
    BENEFIT_DETERMINED = "BENEFIT_DETERMINED"
    PAID = "PAID"
    ADJUSTMENT_PENDING = "ADJUSTMENT_PENDING"
    SETTLED = "SETTLED"
    DENIED = "DENIED"


class AdjustmentStatus(str, Enum):
    INITIATED = "INITIATED"
    VALIDATED = "VALIDATED"
    PROPAGATED = "PROPAGATED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"


class SettlementVariant(str, Enum):
    NET = "NET"
    GROSS = "GROSS"


class SettlementBatchStatus(str, Enum):
    OPEN = "OPEN"
    FINALIZED = "FINALIZED"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    DISPUTED = "DISPUTED"
    DISBURSED = "DISBURSED"
    RECONCILED = "RECONCILED"


class EligibilityInquiryStatus(str, Enum):
    ROUTED = "ROUTED"
    ANSWERED = "ANSWERED"
    REJECTED = "REJECTED"


class UserRole(str, Enum):
    ASSOCIATION_ADMIN = "AssociationAdmin"
    HOME_PLAN_OPERATOR = "HomePlanOperator"
    HOST_PLAN_OPERATOR = "HostPlanOperator"


class Plan(TypedDict, total=False):
    id: str
    plan_code: str
    legal_name: str
    service_area_states: List[str]
    brand_license_status: str
    claims_paid_balance_cents: int
    fees_receivable_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    home_plan_id: str
    national_account_id: Optional[str]
    member_number: str
    full_name: str
    eligibility_status: str
    created_at: str
    updated_at: str
    version: int


class NationalAccount(TypedDict, total=False):
    id: str
    controlling_plan_id: str
    account_name: str
    employer_group_id: str
    territory_states: List[str]
    effective_start: str
    effective_end: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RateSchedule(TypedDict, total=False):
    id: str
    plan_id: str
    provider_npi: str
    procedure_code: str
    negotiated_rate_cents: int
    effective_start: str
    effective_end: str
    created_at: str
    updated_at: str
    version: int


class AccessFeeSchedule(TypedDict, total=False):
    id: str
    home_plan_id: str
    host_plan_id: str
    tier1_cap_cents: int
    tier1_fee_cents: int
    tier2_rate: float
    national_account_discount_pct: float
    effective_start: str
    effective_end: str
    created_at: str
    updated_at: str
    version: int


class Claim(TypedDict, total=False):
    id: str
    member_id: str
    host_plan_id: str
    home_plan_id: str
    national_account_id: Optional[str]
    provider_npi: str
    procedure_code: str
    service_date: str
    service_state: str
    billed_amount_cents: int
    provisional_allowed_cents: int
    priced_allowed_cents: int
    access_fee_cents: int
    admin_charge_cents: int
    provider_payment_cents: int
    current_allowed_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Adjustment(TypedDict, total=False):
    id: str
    claim_id: str
    supersedes_adjustment_id: Optional[str]
    reason: str
    delta_allowed_cents: int
    recovery_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SettlementBatch(TypedDict, total=False):
    id: str
    debtor_plan_id: str
    creditor_plan_id: str
    period_start: str
    period_end: str
    gross_claims_total_cents: int
    fees_total_cents: int
    net_settlement_cents: int
    settlement_variant: str
    status: str
    created_at: str
    updated_at: str
    version: int


class EligibilityInquiry(TypedDict, total=False):
    id: str
    inquiring_plan_id: str
    home_plan_id: str
    member_number: str
    answer_eligibility_status: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int
