"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity catalogue and lifecycle descriptions.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    OPS_MANAGER = "OpsManager"
    CUSTOMER = "Customer"
    HAULER_AGENT = "HaulerAgent"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    TERMINATION_PENDING = "TERMINATION_PENDING"
    TERMINATED = "TERMINATED"


class ContainerSize(str, Enum):
    CY_2 = "CY_2"
    CY_4 = "CY_4"
    CY_6 = "CY_6"
    CY_8 = "CY_8"


class PickupOutcome(str, Enum):
    COMPLETED = "COMPLETED"
    MISSED = "MISSED"
    CONTAMINATED = "CONTAMINATED"
    OVERWEIGHT = "OVERWEIGHT"
    CONTAMINATED_OVERWEIGHT = "CONTAMINATED_OVERWEIGHT"


class DisputeStatus(str, Enum):
    NONE = "NONE"
    DISPUTED = "DISPUTED"
    RESOLVED_UPHELD = "RESOLVED_UPHELD"
    RESOLVED_CREDITED = "RESOLVED_CREDITED"


class FuelMode(str, Enum):
    FIXED = "FIXED"
    INDEXED = "INDEXED"


class RateNoticeReason(str, Enum):
    CPI = "CPI"
    FUEL_INDEX = "FUEL_INDEX"
    COST_RECOVERY = "COST_RECOVERY"


class RateNoticeStatus(str, Enum):
    SCHEDULED = "SCHEDULED"
    APPLIED = "APPLIED"
    CANCELLED = "CANCELLED"


class ServiceChangeStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    CANCELLED = "CANCELLED"


class CompetingOfferStatus(str, Enum):
    SUBMITTED = "SUBMITTED"
    MATCHED = "MATCHED"
    NOT_MATCHED = "NOT_MATCHED"
    VOID = "VOID"


class LdStatus(str, Enum):
    NONE = "NONE"
    ASSESSED = "ASSESSED"
    WAIVED = "WAIVED"


class CancellationStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    DENIED = "DENIED"
    WITHDRAWN = "WITHDRAWN"


class ServiceCreditStatus(str, Enum):
    ACTIVE = "ACTIVE"
    CANCELLED = "CANCELLED"


class RolloffContainerSize(str, Enum):
    YD_10 = "YD_10"
    YD_20 = "YD_20"
    YD_30 = "YD_30"
    YD_40 = "YD_40"


class RolloffStatus(str, Enum):
    RESERVED = "RESERVED"
    DELIVERED = "DELIVERED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class LedgerSource(str, Enum):
    RATE_NOTICE = "RATE_NOTICE"
    SERVICE_CHANGE = "SERVICE_CHANGE"
    ROFR_MATCH = "ROFR_MATCH"


class Customer(TypedDict, total=False):
    id: str
    legal_name: str
    billing_email: str
    credit_balance_cents: int
    created_at: str
    updated_at: str
    version: int


class Contract(TypedDict, total=False):
    id: str
    customer_id: str
    start_date: str
    term_months: int
    end_date: str
    renewal_term_months: int
    cancellation_notice_days: int
    rofr_enabled: bool
    rofr_window_days: int
    status: str
    current_term_index: int
    base_monthly_total_cents: int
    created_at: str
    updated_at: str
    version: int


class ContractServiceLine(TypedDict, total=False):
    id: str
    contract_id: str
    container_size: str
    frequency_per_week: int
    base_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class PickupEvent(TypedDict, total=False):
    id: str
    service_line_id: str
    occurred_date: str
    outcome: str
    photo_evidence_url: Optional[str]
    contamination_fee_cents: int
    overweight_fee_cents: int
    dispute_status: str
    appeal_count: int
    created_at: str
    updated_at: str
    version: int


class SurchargeConfig(TypedDict, total=False):
    id: str
    fuel_mode: str
    fuel_fixed_pct: Optional[float]
    fuel_index_base: Optional[float]
    fuel_index_current: Optional[float]
    environmental_pct: float
    admin_pct: float
    contamination_fee_cents: int
    overweight_fee_cents: int
    credit_pct_of_base: Optional[float]
    effective_from: str
    created_at: str
    updated_at: str
    version: int


class RateAdjustmentNotice(TypedDict, total=False):
    id: str
    contract_id: str
    reason: str
    pct_increase: float
    effective_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceChangeRequest(TypedDict, total=False):
    id: str
    service_line_id: str
    new_container_size: str
    new_frequency_per_week: int
    effective_date: str
    old_rate_cents: int
    quoted_new_rate_cents: int
    final_applied_rate_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class CompetingOffer(TypedDict, total=False):
    id: str
    contract_id: str
    competitor_monthly_cents: int
    evidence_doc_url: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CancellationRequest(TypedDict, total=False):
    id: str
    contract_id: str
    requested_end_date: str
    timely: bool
    months_remaining: int
    ld_base_cents: int
    ld_total_cents: int
    ld_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class ServiceCredit(TypedDict, total=False):
    id: str
    service_line_id: str
    pickup_event_id: str
    credit_cents: int
    filed_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class RolloffOrder(TypedDict, total=False):
    id: str
    customer_id: str
    container_size: str
    delivery_date: str
    rental_days: int
    included_tons: float
    actual_tons: Optional[float]
    delivery_fee_cents: int
    daily_rental_cents: int
    overage_ton_cents: int
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only: carries only id + created_at plus its payload fields.
class LedgerEntry(TypedDict, total=False):
    id: str
    contract_id: str
    effective_date: str
    old_base_monthly_cents: int
    new_base_monthly_cents: int
    source: str
    created_at: str


class MonthlyInvoice(TypedDict, total=False):
    base_cents: int
    fuel_cents: int
    env_cents: int
    admin_cents: int
    fees_cents: int
    credits_cents: int
    total_cents: int
