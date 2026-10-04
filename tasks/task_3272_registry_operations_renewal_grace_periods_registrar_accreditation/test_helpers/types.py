"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.4, §3)."""
from enum import Enum
from typing import Optional, TypedDict


class RegistrarStatus(str, Enum):
    PENDING_TESTS = "PENDING_TESTS"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    TERMINATED = "TERMINATED"


class AnnualFeeMode(str, Enum):
    PROVISIONAL = "PROVISIONAL"
    AUDIT = "AUDIT"


class PriceScheduleStatus(str, Enum):
    PROPOSED = "PROPOSED"
    EFFECTIVE = "EFFECTIVE"
    SUPERSEDED = "SUPERSEDED"


class DomainStatus(str, Enum):
    ACTIVE = "ACTIVE"
    AUTO_RENEW_GRACE = "AUTO_RENEW_GRACE"
    REDEMPTION_GRACE = "REDEMPTION_GRACE"
    PENDING_DELETE = "PENDING_DELETE"
    DELETED = "DELETED"
    TRANSFERRING = "TRANSFERRING"


class LockStatus(str, Enum):
    NONE = "NONE"
    CLIENT_LOCK = "CLIENT_LOCK"
    REGISTRY_LOCK = "REGISTRY_LOCK"


class SuspensionStatus(str, Enum):
    NONE = "NONE"
    HOLD = "HOLD"


class TransferStatus(str, Enum):
    REQUESTED = "REQUESTED"
    ACKED = "ACKED"
    NACKED = "NACKED"
    AUTO_ACKED = "AUTO_ACKED"
    COMPLETED = "COMPLETED"
    DISPUTED = "DISPUTED"
    REVERSED = "REVERSED"


class InvoiceKind(str, Enum):
    CREATE = "CREATE"
    RENEW = "RENEW"
    AUTO_RENEW = "AUTO_RENEW"
    RESTORE = "RESTORE"
    TRANSFER = "TRANSFER"
    ACCREDITATION = "ACCREDITATION"


class InvoiceStatus(str, Enum):
    OPEN = "OPEN"
    VOIDED = "VOIDED"


class LedgerEntryType(str, Enum):
    TOP_UP = "TOP_UP"
    DEBIT = "DEBIT"
    VOID_CREDIT = "VOID_CREDIT"
    WRITE_OFF = "WRITE_OFF"


class AbuseReportStatus(str, Enum):
    FILED = "FILED"
    UNDER_REVIEW = "UNDER_REVIEW"
    ACTIONED = "ACTIONED"
    DISMISSED = "DISMISSED"


class AbuseCategory(str, Enum):
    PHISHING = "PHISHING"
    MALWARE = "MALWARE"
    SPAM = "SPAM"
    OTHER = "OTHER"


class CourtOrderAction(str, Enum):
    SUSPEND = "SUSPEND"
    UNSUSPEND = "UNSUSPEND"
    TRANSFER_TO_REGISTRY = "TRANSFER_TO_REGISTRY"


class CourtOrderStatus(str, Enum):
    LODGED = "LODGED"
    ENFORCED = "ENFORCED"


class NoticeKind(str, Enum):
    PRICE_INCREASE_ANNOUNCED = "PRICE_INCREASE_ANNOUNCED"
    PRICE_INCREASE_EFFECTIVE = "PRICE_INCREASE_EFFECTIVE"


class UserRole(str, Enum):
    REGISTRY_ADMIN = "RegistryAdmin"
    REGISTRAR_OPERATOR = "RegistrarOperator"
    REGISTRY_FINANCE = "RegistryFinance"
    ABUSE_ANALYST = "AbuseAnalyst"


class Registrar(TypedDict, total=False):
    id: str
    iana_number: int
    legal_name: str
    application_fee_cents: int
    annual_fee_cents: int
    escrow_deposit_cents: int
    technical_test_score: int
    financial_statement_verified: bool
    credit_hold: bool
    status: str
    accredited_on: Optional[str]
    accredited_version: Optional[int]
    all_in_cost_cents: Optional[int]
    annual_fee_mode: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PriceSchedule(TypedDict, total=False):
    id: str
    create_fee_cents: int
    renew_fee_cents: int
    restore_fee_cents: int
    transfer_fee_cents: int
    effective_on: str
    announced_at: str
    supersedes_schedule_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class Domain(TypedDict, total=False):
    id: str
    name: str
    registrar_id: Optional[str]
    years: int
    premium: bool
    expires_on: str
    grace_deadline: str
    status: str
    lock_status: str
    suspension_status: str
    registry_lock_token_hash: Optional[str]
    auto_renewed_on: Optional[str]
    delete_scheduled_on: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Nameserver(TypedDict, total=False):
    id: str
    hostname: str
    ip_addresses: list
    capacity_qps: int
    created_at: str
    updated_at: str
    version: int


class DomainNameserverLink(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    domain_id: str
    nameserver_id: str
    created_at: str


class Transfer(TypedDict, total=False):
    id: str
    domain_id: str
    from_registrar_id: str
    to_registrar_id: str
    auth_code: Optional[str]
    auth_code_hash: Optional[str]
    auth_code_expires_at: str
    requested_at: str
    status: str
    dispute_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    registrar_id: str
    domain_id: Optional[str]
    kind: str
    base_cents: int
    premium_surcharge_cents: int
    total_cents: int
    price_schedule_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class LedgerEntry(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    registrar_id: str
    invoice_id: Optional[str]
    amount_cents: int
    entry_type: str
    created_at: str


class AbuseReport(TypedDict, total=False):
    id: str
    domain_id: str
    reporter_contact: str
    category: str
    detail: str
    status: str
    created_at: str
    updated_at: str
    version: int


class CourtOrder(TypedDict, total=False):
    id: str
    case_reference: str
    domain_id: str
    action: str
    effective_immediately: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class RegistrarAccreditationNotice(TypedDict, total=False):
    # Append-only: carries ONLY id + created_at (no updated_at, no version).
    id: str
    registrar_id: str
    price_schedule_id: str
    notice_kind: str
    sent_at: str
    created_at: str
