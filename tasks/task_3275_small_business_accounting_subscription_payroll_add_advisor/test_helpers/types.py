"""Domain types: entity TypedDicts, status enums, role enum.

Derived from the PRD's entity table.  Entities that carry ``common_fields``
(id + created_at + updated_at + version) get the full set; append-only /
snapshot entities (SubscriptionPlan, Category) carry ONLY id + created_at.
"""

from enum import Enum
from typing import Any, List, Optional, TypedDict


# --- Status enums ------------------------------------------------------------


class FirmStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CLOSED = "CLOSED"


class ProAdvisorTier(str, Enum):
    SILVER = "SILVER"
    GOLD = "GOLD"
    PLATINUM = "PLATINUM"


class AccountantUserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class CompanyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    READ_ONLY = "READ_ONLY"
    PURGED = "PURGED"


class DataRegion(str, Enum):
    US = "US"
    EU = "EU"
    UK = "UK"


class PermissionLevel(str, Enum):
    PRIMARY_ADMIN = "PRIMARY_ADMIN"
    COMPANY_ADMIN = "COMPANY_ADMIN"
    STANDARD = "STANDARD"
    REPORTS_ONLY = "REPORTS_ONLY"
    TIME_TRACKING = "TIME_TRACKING"


class CompanyUserStatus(str, Enum):
    INVITED = "INVITED"
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class BillingOwner(str, Enum):
    CLIENT = "CLIENT"
    FIRM = "FIRM"


class LifecycleStatus(str, Enum):
    TRIAL = "TRIAL"
    ACTIVE = "ACTIVE"
    PAST_DUE = "PAST_DUE"
    SUSPENDED = "SUSPENDED"
    CANCELLED_READ_ONLY = "CANCELLED_READ_ONLY"
    CANCELLED_EXPIRED = "CANCELLED_EXPIRED"
    REACTIVATED = "REACTIVATED"


class BillingStatus(str, Enum):
    CURRENT = "CURRENT"
    PAST_DUE = "PAST_DUE"
    UNPAID = "UNPAID"


class ServiceLevel(str, Enum):
    SELF_SERVICE = "SELF_SERVICE"
    FULL_SERVICE = "FULL_SERVICE"


class AddonStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    CANCELLED = "CANCELLED"


class TaxFilingStatus(str, Enum):
    NOT_READY = "NOT_READY"
    READY = "READY"
    FILED_CURRENT = "FILED_CURRENT"
    PENALTY_RISK = "PENALTY_RISK"


class EmploymentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    PAST_DUE = "PAST_DUE"
    VOID = "VOID"


class ConnectionStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    ACTIVE = "ACTIVE"
    STALE = "STALE"
    DISCONNECTED = "DISCONNECTED"
    REVOKED = "REVOKED"


class TxnStatus(str, Enum):
    UNCATEGORIZED = "UNCATEGORIZED"
    RULE_SUGGESTED = "RULE_SUGGESTED"
    CATEGORIZED = "CATEGORIZED"
    EXCLUDED = "EXCLUDED"
    MATCHED_RECONCILED = "MATCHED_RECONCILED"


class MatchField(str, Enum):
    PAYEE_CONTAINS = "PAYEE_CONTAINS"
    AMOUNT_EQUALS = "AMOUNT_EQUALS"
    AMOUNT_GREATER_THAN = "AMOUNT_GREATER_THAN"


class RuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DELETED = "DELETED"


class ReconStatus(str, Enum):
    DRAFT = "DRAFT"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    LOCKED = "LOCKED"


class SyncDirection(str, Enum):
    PULL = "PULL"
    PUSH = "PUSH"
    BIDIRECTIONAL = "BIDIRECTIONAL"


class IntegrationStatus(str, Enum):
    LINKED = "LINKED"
    ACTIVE = "ACTIVE"
    CONFLICT_PAUSED = "CONFLICT_PAUSED"
    DISCONNECTED = "DISCONNECTED"


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED_LOCAL = "RESOLVED_LOCAL"
    RESOLVED_REMOTE = "RESOLVED_REMOTE"
    IGNORED = "IGNORED"


class SourceProduct(str, Enum):
    DESKTOP_PRO = "DESKTOP_PRO"
    DESKTOP_PREMIER = "DESKTOP_PREMIER"
    DESKTOP_ENTERPRISE = "DESKTOP_ENTERPRISE"


class MigrationStatus(str, Enum):
    QUEUED = "QUEUED"
    CONVERTING = "CONVERTING"
    COMPLETED_CLEAN = "COMPLETED_CLEAN"
    COMPLETED_WITH_LIMITATIONS = "COMPLETED_WITH_LIMITATIONS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class TransferStatus(str, Enum):
    PENDING_CLIENT_ACCEPT = "PENDING_CLIENT_ACCEPT"
    PENDING_FIRM_ACCEPT = "PENDING_FIRM_ACCEPT"
    COMPLETED = "COMPLETED"
    DECLINED = "DECLINED"
    EXPIRED = "EXPIRED"
    CANCELLED = "CANCELLED"


class AccessLevel(str, Enum):
    FULL_BOOKKEEPING = "FULL_BOOKKEEPING"
    REPORTS_READ_ONLY = "REPORTS_READ_ONLY"
    PAYROLL_ONLY = "PAYROLL_ONLY"


class GrantStatus(str, Enum):
    PENDING_ACCEPT = "PENDING_ACCEPT"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class ExportFormat(str, Enum):
    CSV = "CSV"
    XLSX = "XLSX"
    QBO_BACKUP = "QBO_BACKUP"


class ExportScope(str, Enum):
    TRANSACTIONS_ONLY = "TRANSACTIONS_ONLY"
    FULL_LEDGER = "FULL_LEDGER"
    PAYROLL_RECORDS = "PAYROLL_RECORDS"


class ExportStatus(str, Enum):
    PENDING = "PENDING"
    READY = "READY"
    DOWNLOADED = "DOWNLOADED"
    EXPIRED = "EXPIRED"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPANY_USER = "CompanyUser"
    ACCOUNTANT_USER = "AccountantUser"


# --- Entity TypedDicts ---------------------------------------------------------


class AccountantFirm(TypedDict, total=False):
    id: str
    firm_name: str
    wholesale_discount_pct: float
    proadvisor_tier: str
    firm_status: str
    created_at: str
    updated_at: str
    version: int


class AccountantUser(TypedDict, total=False):
    id: str
    firm_id: str
    full_name: str
    email: str
    is_firm_admin: bool
    user_status: str
    created_at: str
    updated_at: str
    version: int


class ClientCompany(TypedDict, total=False):
    id: str
    legal_name: str
    admin_email: str
    home_country: str
    data_region: str
    company_status: str
    primary_admin_user_id: str
    created_at: str
    updated_at: str
    version: int


class CompanyUser(TypedDict, total=False):
    id: str
    company_id: str
    email: str
    display_name: str
    permission_level: str
    user_status: str
    created_at: str
    updated_at: str
    version: int


class SubscriptionPlan(TypedDict, total=False):
    # common_fields: false — id + created_at only, NO updated_at, NO version
    id: str
    plan_code: str
    list_price_cents: int
    max_seats: int
    feature_inventory: bool
    feature_project_profitability: bool
    feature_multi_currency: bool
    feature_bank_rules: bool
    plan_rank: int
    created_at: str


class Subscription(TypedDict, total=False):
    id: str
    company_id: str
    plan_id: str
    billing_owner: str
    billing_firm_id: Optional[str]
    lifecycle_status: str
    billing_status: str
    anchor_day: Optional[int]
    started_at: str
    trial_ends_at: str
    cancelled_at: Optional[str]
    read_only_expires_at: Optional[str]
    monthly_price_cents: int
    pending_upgrade_prompt: bool
    created_at: str
    updated_at: str
    version: int


class PayrollAddon(TypedDict, total=False):
    id: str
    subscription_id: str
    service_level: str
    base_fee_cents: int
    per_employee_fee_cents: int
    addon_status: str
    tax_filing_status: str
    activated_at: str
    created_at: str
    updated_at: str
    version: int


class PayrollEmployee(TypedDict, total=False):
    id: str
    payroll_addon_id: str
    legal_name: str
    hire_date: str
    employment_status: str
    terminated_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict, total=False):
    id: str
    company_id: str
    subscription_id: str
    period_start: str
    period_end: str
    billed_to: str
    list_subscription_cents: int
    wholesale_discount_cents: int
    payroll_base_cents: int
    payroll_per_employee_cents: int
    tax_cents: int
    total_cents: int
    invoice_status: str
    created_at: str
    updated_at: str
    version: int


class BankConnection(TypedDict, total=False):
    id: str
    company_id: str
    institution_name: str
    external_account_mask: str
    connection_status: str
    last_sync_at: Optional[str]
    consent_expires_at: str
    created_at: str
    updated_at: str
    version: int


class BankTransaction(TypedDict, total=False):
    id: str
    bank_connection_id: str
    posted_at: str
    amount_cents: int
    payee_raw: str
    category_id: Optional[str]
    matched_rule_id: Optional[str]
    txn_status: str
    reconciled_in_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Category(TypedDict, total=False):
    # common_fields: false — id + created_at only
    id: str
    company_id: str
    name: str
    tax_line: str
    created_at: str


class CategorizationRule(TypedDict, total=False):
    id: str
    company_id: str
    rule_name: str
    match_field: str
    match_value: str
    assign_category_id: str
    priority: int
    auto_apply: bool
    rule_status: str
    created_at: str
    updated_at: str
    version: int


class Reconciliation(TypedDict, total=False):
    id: str
    company_id: str
    bank_connection_id: str
    statement_period_start: str
    statement_period_end: str
    statement_ending_balance_cents: int
    beginning_balance_cents: int
    cleared_cents: int
    difference_cents: int
    recon_status: str
    completed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AppIntegration(TypedDict, total=False):
    id: str
    company_id: str
    app_code: str
    sync_direction: str
    integration_status: str
    conflict_count: int
    last_sync_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SyncConflict(TypedDict, total=False):
    id: str
    app_integration_id: str
    conflict_field: str
    local_value: str
    remote_value: str
    conflict_status: str
    created_at: str
    updated_at: str
    version: int


class MigrationJob(TypedDict, total=False):
    id: str
    company_id: str
    source_product: str
    source_file_size_bytes: int
    target_list_entries: int
    migration_status: str
    limitation_codes: List[str]
    created_at: str
    updated_at: str
    version: int


class BillingTransfer(TypedDict, total=False):
    id: str
    company_id: str
    subscription_id: str
    from_owner: str
    to_owner: str
    initiating_firm_id: str
    transfer_status: str
    proforma_monthly_cents: int
    expires_at: str
    decline_reason: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessGrant(TypedDict, total=False):
    id: str
    company_id: str
    accountant_user_id: str
    firm_id: str
    access_level: str
    grant_status: str
    expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ExportRequest(TypedDict, total=False):
    id: str
    company_id: str
    requested_by_user_id: str
    format: str
    scope: str
    export_status: str
    ready_at: Optional[str]
    download_expires_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
