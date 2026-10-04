"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class LicenseModel(str, Enum):
    OCOU = "OCOU"
    METERED_TIME = "METERED_TIME"
    METERED_CIRC = "METERED_CIRC"
    COST_PER_CIRC = "COST_PER_CIRC"
    SIMULTANEOUS_USE = "SIMULTANEOUS_USE"


class UserRole(str, Enum):
    CONSORTIUM_ADMIN = "ConsortiumAdmin"
    LIBRARY_ADMIN = "LibraryAdmin"
    PATRON = "Patron"
    SYSTEM_ANALYST = "SystemAnalyst"


class ConsortiumStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class LibraryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class FundStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class PatronStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    EXPIRED = "EXPIRED"


class LicenseStatus(str, Enum):
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    EXHAUSTED = "EXHAUSTED"
    RETIRED = "RETIRED"


class HoldStatus(str, Enum):
    PLACED = "PLACED"
    READY = "READY"
    SUSPENDED = "SUSPENDED"
    FULFILLED = "FULFILLED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class LoanStatus(str, Enum):
    ACTIVE = "ACTIVE"
    RETURNED = "RETURNED"
    EXPIRED = "EXPIRED"


class OrderStatus(str, Enum):
    DRAFT = "DRAFT"
    PROPOSED = "PROPOSED"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    FULFILLED = "FULFILLED"
    CANCELLED = "CANCELLED"


class OrderOrigin(str, Enum):
    MANUAL = "MANUAL"
    AUTO_RATIO = "AUTO_RATIO"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    DISPUTED = "DISPUTED"
    SETTLED = "SETTLED"


class EventType(str, Enum):
    CHECKOUT = "CHECKOUT"
    RENEW = "RENEW"
    RETURN = "RETURN"
    LOAN_EXPIRED = "LOAN_EXPIRED"
    HOLD_PLACED = "HOLD_PLACED"
    HOLD_READY = "HOLD_READY"
    HOLD_FULFILLED = "HOLD_FULFILLED"
    HOLD_EXPIRED = "HOLD_EXPIRED"
    HOLD_CANCELLED = "HOLD_CANCELLED"
    PURCHASE = "PURCHASE"


class SharingScope(str, Enum):
    LOCAL_ONLY = "LOCAL_ONLY"
    CONSORTIUM = "CONSORTIUM"


class Consortium(TypedDict, total=False):
    id: str
    name: str
    cpc_discount_pct: float
    host_share_floor_pct: float
    invoice_period: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Library(TypedDict, total=False):
    id: str
    consortium_id: str
    name: str
    residency_region_codes: List[str]
    card_validity_days: int
    max_concurrent_loans: int
    max_concurrent_holds: int
    loan_period_days: int
    renewal_period_days: int
    max_renewals: int
    pickup_window_hours: int
    skip_the_line_loan_days: int
    auto_purchase_enabled: bool
    holds_per_copy_ratio: int
    wait_target_days: int
    auto_purchase_max_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class BudgetFund(TypedDict, total=False):
    id: str
    library_id: str
    fiscal_year: int
    period_start: str
    period_end: str
    budget_cents: int
    committed_cents: int
    spent_cents: int
    cpc_accrued_cents: int
    available_committed_cents: int
    available_actual_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Patron(TypedDict, total=False):
    id: str
    library_id: str
    external_card_number: str
    full_name: str
    postal_code: str
    status: str
    card_expires_at: str
    active_loan_count: int
    active_hold_count: int
    created_at: str
    updated_at: str
    version: int


class Title(TypedDict, total=False):
    id: str
    consortium_id: str
    isbn: str
    name: str
    author: str
    sharing_scope: str
    skip_the_line_enabled: bool
    simultaneous_use_allowed: bool
    price_ocou_cents: int
    metered_time_price_cents: int
    metered_time_days: int
    metered_circ_price_cents: int
    metered_circ_count: int
    cpc_price_per_circ_cents: int
    simultaneous_use_price_cents: int
    simultaneous_use_days: int
    created_at: str
    updated_at: str
    version: int


class License(TypedDict, total=False):
    id: str
    title_id: str
    library_id: str
    acquisition_order_id: str
    model: str
    copies_total: int
    copies_on_loan: int
    activated_at: str
    expires_at: Optional[str]
    circs_total: Optional[int]
    circs_consumed: Optional[int]
    balance_cents: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class Hold(TypedDict, total=False):
    id: str
    title_id: str
    patron_id: str
    library_id: str
    status: str
    placed_at: str
    ready_since: Optional[str]
    ready_until: Optional[str]
    suspension_count: int
    optimistic_wait_days: int
    pessimistic_wait_days: int
    created_at: str
    updated_at: str
    version: int


class Loan(TypedDict, total=False):
    id: str
    license_id: str
    patron_id: str
    hold_id: Optional[str]
    is_skip_the_line: bool
    checkout_at: str
    due_at: str
    returned_at: Optional[str]
    renewals_used: int
    circ_price_charged_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class AcquisitionOrder(TypedDict, total=False):
    id: str
    library_id: str
    budget_fund_id: str
    title_id: str
    model: str
    copies: int
    prepaid_balance_cents: Optional[int]
    estimated_cost_cents: int
    invoiced_cost_cents: Optional[int]
    origin: str
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict, total=False):
    library_id: str
    share_cents: int


class ConsortiumInvoice(TypedDict, total=False):
    id: str
    consortium_id: str
    period_start: str
    period_end: str
    lines: List[InvoiceLine]
    total_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CirculationEvent(TypedDict, total=False):
    id: str
    created_at: str
    library_id: str
    title_id: str
    patron_id: Optional[str]
    loan_id: Optional[str]
    hold_id: Optional[str]
    license_id: Optional[str]
    event_type: str
    occurred_at: str
    charge_cents: int


class UsageSnapshot(TypedDict, total=False):
    id: str
    library_id: str
    period_start: str
    period_end: str
    generated_at: str
    checkouts_by_model: Dict[str, int]
    cpc_spend_cents: int
    holds_filled: int
    avg_fulfillment_wait_days: float
    created_at: str
    updated_at: str
    version: int
