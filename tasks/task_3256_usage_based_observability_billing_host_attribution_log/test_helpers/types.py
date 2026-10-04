"""Domain types: entity TypedDicts, status enums, role enum (PRD §2.1, §3)."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    BILLING_ADMIN = "BillingAdmin"
    INGESTION_AGENT = "IngestionAgent"
    TEAM_LEAD = "TeamLead"
    FINANCE_READER = "FinanceReader"


class PlanTier(str, Enum):
    FREE = "FREE"
    PRO = "PRO"
    ENTERPRISE = "ENTERPRISE"


class Meter(str, Enum):
    INFRA_HOST = "INFRA_HOST"
    CUSTOM_METRIC = "CUSTOM_METRIC"
    LOG_INGEST = "LOG_INGEST"
    LOG_INDEX = "LOG_INDEX"
    TRACE = "TRACE"
    SYNTHETIC = "SYNTHETIC"


class AccountStanding(str, Enum):
    GOOD = "GOOD"
    DELINQUENT = "DELINQUENT"


class BillingPeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    SETTLED = "SETTLED"


class ExclusionState(str, Enum):
    PENDING = "PENDING"
    INDEXED = "INDEXED"
    EXCLUDED = "EXCLUDED"


class SeriesStatus(str, Enum):
    ACTIVE = "ACTIVE"
    QUARANTINED = "QUARANTINED"


class IncidentStatus(str, Enum):
    OPEN = "OPEN"
    TRIAGED = "TRIAGED"
    REMEDIATED = "REMEDIATED"
    VERIFIED = "VERIFIED"
    CLOSED = "CLOSED"


class CommitmentStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    EXHAUSTED = "EXHAUSTED"
    SETTLED = "SETTLED"


class DisputeStatus(str, Enum):
    OPEN = "OPEN"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class InvoiceStatus(str, Enum):
    DRAFT = "DRAFT"
    ISSUED = "ISSUED"
    PAID = "PAID"
    VOID = "VOID"


class MonitorKind(str, Enum):
    METRIC = "METRIC"
    LOG = "LOG"
    APM = "APM"
    SYNTHETIC = "SYNTHETIC"


class MonitorStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MUTED = "MUTED"
    DELETED = "DELETED"


class Enforcement(str, Enum):
    WARN = "WARN"
    BLOCK = "BLOCK"


class BillingAccount(TypedDict):
    id: str
    name: str
    plan_tier: str
    billing_cycle_anchor_day: int
    standing: str
    created_at: str
    updated_at: str
    version: int


class PlanTierConfig(TypedDict):
    id: str
    plan_tier: str
    max_monitors: int
    included_custom_metrics: int
    host_overage_rate_cents: int
    log_ingest_rate_cents_per_gb: int
    log_index_rate_cents_per_million: int
    custom_metric_rate_cents_per_unit: int
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict):
    id: str
    billing_account_id: str
    period_start_utc: str
    period_end_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class HostHourRecord(TypedDict):
    id: str
    billing_period_id: str
    hour_bucket_utc: str
    infra_host_count: int
    container_host_count: int
    serverless_invocation_count: int
    created_at: str
    updated_at: str
    version: int


class MeterAccumulator(TypedDict):
    id: str
    billing_period_id: str
    meter: str
    quantity: int
    committed_consumed_quantity: int
    on_demand_quantity: int
    created_at: str
    updated_at: str
    version: int


class LogEvent(TypedDict):
    id: str
    billing_period_id: str
    size_bytes: int
    service_tag: str
    ingested_at_utc: str
    exclusion_state: str
    retention_tier_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class RetentionTier(TypedDict):
    id: str
    billing_account_id: str
    name: str
    retention_days: int
    effective_from_utc: str
    effective_to_utc: str
    index_rate_multiplier_bp: int
    created_at: str
    updated_at: str
    version: int


class ExclusionFilter(TypedDict):
    id: str
    billing_account_id: str
    service_tag_pattern: str
    sample_rate_pct: int
    priority: int
    enabled: bool
    created_at: str
    updated_at: str
    version: int


class CustomMetricSeries(TypedDict):
    id: str
    billing_account_id: str
    metric_name: str
    team_id: str
    cardinality_estimate: int
    status: str
    created_at: str
    updated_at: str
    version: int


class CardinalityIncident(TypedDict):
    id: str
    custom_metric_series_id: str
    opened_at_cardinality: int
    threshold_used: int
    status: str
    remediation_note: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Commitment(TypedDict):
    id: str
    billing_account_id: str
    meter: str
    committed_quantity: int
    consumed_quantity: int
    expired_quantity: int
    window_start_utc: str
    window_end_utc: str
    committed_unit_rate_cents: int
    overage_unit_rate_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict):
    id: str
    billing_account_id: str
    name: str
    cost_center: str
    created_at: str
    updated_at: str
    version: int


class UsageRecord(TypedDict):
    id: str
    billing_period_id: str
    team_id: Optional[str]
    meter: str
    quantity: int
    tag_compliant: bool
    disputed: bool
    created_at: str
    updated_at: str
    version: int


class AttributionDispute(TypedDict):
    id: str
    usage_record_id: str
    raised_by_team_id: str
    reason: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TagPolicy(TypedDict):
    id: str
    billing_account_id: str
    required_tag_key: str
    allowed_values: List[str]
    enforcement: str
    created_at: str
    updated_at: str
    version: int


class Monitor(TypedDict):
    id: str
    billing_account_id: str
    name: str
    monitor_kind: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Invoice(TypedDict):
    id: str
    billing_period_id: str
    total_amount_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class InvoiceLine(TypedDict):
    # Immutable once written: carries ONLY id + created_at (no updated_at, no version).
    id: str
    invoice_id: str
    meter: str
    rated_quantity: int
    amount_cents: int
    created_at: str
