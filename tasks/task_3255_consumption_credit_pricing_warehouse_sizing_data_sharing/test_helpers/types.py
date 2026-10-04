"""Domain types: entity TypedDicts, status enums and the role enum.

Field names follow the PRD verbatim. Entities declared with the standard
audit-trail fields carry ``id``, ``created_at``, ``updated_at`` and ``version``;
append-only ``AccountLedgerEntry`` carries only ``id`` and ``created_at``.
"""
from enum import Enum
from typing import List, Optional, TypedDict


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class UserRole(str, Enum):
    PLATFORM_OPERATOR = "PlatformOperator"
    FINANCE_CONTROLLER = "FinanceController"
    SHARE_ADMIN = "ShareAdmin"
    DATA_ENGINEER = "DataEngineer"


class WarehouseSize(str, Enum):
    XSMALL = "XSMALL"
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"
    XLARGE = "XLARGE"
    XXLARGE = "XXLARGE"
    XXXLARGE = "XXXLARGE"
    X4LARGE = "X4LARGE"


class WarehouseStatus(str, Enum):
    SUSPENDED = "SUSPENDED"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    RESIZING = "RESIZING"
    DRAINING = "DRAINING"


class SessionState(str, Enum):
    OPEN = "OPEN"
    CLOSING = "CLOSING"
    CLOSED = "CLOSED"
    RESUMING = "RESUMING"


class ContractStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    EXPIRED = "EXPIRED"
    CLOSED = "CLOSED"


class DrawdownStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVERSED = "REVERSED"


class DrawdownOutcome(str, Enum):
    BASE = "BASE"
    ROLLOVER = "ROLLOVER"
    OVERAGE = "OVERAGE"


class SnapshotState(str, Enum):
    FINALIZED = "FINALIZED"
    REVISED = "REVISED"


class ShareStatus(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    SUSPENDED = "SUSPENDED"


class ListingState(str, Enum):
    DRAFT = "DRAFT"
    PUBLISHED = "PUBLISHED"
    WITHDRAWN = "WITHDRAWN"


class PricingModel(str, Enum):
    FREE = "FREE"
    FLAT = "FLAT"
    USAGE_BASED = "USAGE_BASED"


class UsageState(str, Enum):
    PENDING = "PENDING"
    SETTLED = "SETTLED"
    DISPUTED = "DISPUTED"


class MonitorState(str, Enum):
    OK = "OK"
    NOTIFY_SENT = "NOTIFY_SENT"
    SUSPENDED = "SUSPENDED"


class MonitorAction(str, Enum):
    NOTIFY = "NOTIFY"
    SUSPEND = "SUSPEND"
    SUSPEND_IMMEDIATE = "SUSPEND_IMMEDIATE"


class AccountState(str, Enum):
    OPEN = "OPEN"
    RESTRICTED = "RESTRICTED"
    DRAINING = "DRAINING"


class ReplicationState(str, Enum):
    CONFIGURED = "CONFIGURED"
    REFRESHING = "REFRESHING"
    REFRESHED = "REFRESHED"
    FAILED = "FAILED"


class LedgerBucket(str, Enum):
    CONSUMPTION = "CONSUMPTION"
    OVERAGE = "OVERAGE"
    ROLLOVER = "ROLLOVER"
    REPLICATION = "REPLICATION"
    SHARE_CONSUMPTION = "SHARE_CONSUMPTION"
    STORAGE = "STORAGE"
    STORAGE_ADJUST = "STORAGE_ADJUST"
    PAYOUT = "PAYOUT"
    PAYOUT_ADJUST = "PAYOUT_ADJUST"


# ---------------------------------------------------------------------------
# Entity shapes (standard audit trail: id + created_at + updated_at + version)
# ---------------------------------------------------------------------------

class Account(TypedDict, total=False):
    id: str
    org_name: str
    account_locator: str
    region: str
    region_factor: float
    cloud_provider: str
    monitor_scope: str
    posted_consumption_credits_reconciled: float
    posted_storage_dollars_reconciled: float
    account_state: str
    created_at: str
    updated_at: str
    version: int


class VirtualWarehouse(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    size: str
    credits_per_hour: float
    auto_suspend_seconds: int
    auto_resume: bool
    status: str
    cluster_count: int
    clusters_min: int
    clusters_max: int
    multi_cluster_queued_queries: int
    latency_slo_ms: int
    created_at: str
    updated_at: str
    version: int


class WarehouseSession(TypedDict, total=False):
    id: str
    warehouse_id: str
    size: str
    clusters: int
    started_at: str
    ended_at: Optional[str]
    elapsed_seconds: int
    state: str
    metered_credits: float
    billed_credits: float
    billed_seconds: int
    created_at: str
    updated_at: str
    version: int


class CapacityContract(TypedDict, total=False):
    id: str
    account_id: str
    term_start: str
    term_end: str
    base_credits: float
    overage_rate_per_credit: float
    rollover_cap_credits: float
    currency: str
    status: str
    drawdown_count: int
    remaining_credits: float
    drawn_credits: float
    rolled_over_credits: float
    base_consumed_credits: float
    term_end_remaining_credits: float
    activated_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class CreditDrawdown(TypedDict, total=False):
    id: str
    contract_id: str
    warehouse_id: str
    amount_credits: float
    source_kind: str
    status: str
    idempotency_key: str
    outcome: str
    overage_usd: float
    created_at: str
    updated_at: str
    version: int


class StorageUsageRecord(TypedDict, total=False):
    id: str
    account_id: str
    usage_date: str
    active_tb: float
    time_travel_tb: float
    fail_safe_tb: float
    time_travel_days: int
    fail_safe_days: int
    billable_storage_tb: float
    storage_cost_dollars: float
    snapshot_state: str
    created_at: str
    updated_at: str
    version: int


class DataShare(TypedDict, total=False):
    id: str
    provider_account_id: str
    name: str
    objects_exposed: int
    consumer_account_ids: List[str]
    status: str
    consumer_query_count: int
    consumer_credits: float
    created_at: str
    updated_at: str
    version: int


class ShareUsageEvent(TypedDict, total=False):
    id: str
    share_id: str
    consumer_account_id: str
    queried_at: str
    credits_consumed: float
    row_count: int
    attribution: str
    attributed_row_count: int
    credited_account_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Listing(TypedDict, total=False):
    id: str
    share_id: str
    title: str
    pricing_model: str
    flat_price_usd: float
    listing_state: str
    gross_credit_volume: float
    provider_payout_usd: float
    platform_fee_usd: float
    frozen_price_usd: Optional[float]
    created_at: str
    updated_at: str
    version: int


class PaidShareUsage(TypedDict, total=False):
    id: str
    listing_id: str
    buyer_account_id: str
    credits_used: float
    price_per_credit: float
    usage_state: str
    disputed_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class ResourceMonitor(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    credit_quota: float
    interval: str
    action: str
    monitor_state: str
    interval_consumption_credits: float
    used_pct: float
    last_reset_at: str
    created_at: str
    updated_at: str
    version: int


class ReplicationConfiguration(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    target_region: str
    target_cloud: str
    replicated_tb: float
    refresh_count: int
    transfer_cost_dollars: float
    last_refresh_at: Optional[str]
    replication_state: str
    created_at: str
    updated_at: str
    version: int


# Append-only: no updated_at, no version.
class AccountLedgerEntry(TypedDict, total=False):
    id: str
    account_id: str
    bucket: str
    source_entity: str
    source_entity_id: str
    amount_credits: float
    amount_usd: float
    posted_at: str
    created_at: str


class StorageBillingSummary(TypedDict, total=False):
    storage_cost_dollars_reported: float
    storage_cost_dollars_stored: float
    rounding_mode: str
    per_component: dict


class ProviderPayoutReport(TypedDict, total=False):
    gross_credit_volume: float
    provider_payout_usd: float
    platform_fee_usd: float
    frozen_price_usd: Optional[float]
    price_source: str


class AccountBillingSummary(TypedDict, total=False):
    posted_consumption_credits_reconciled: float
    posted_storage_dollars_reconciled: float
    account_dollars_balance: float
    bucket_totals: dict