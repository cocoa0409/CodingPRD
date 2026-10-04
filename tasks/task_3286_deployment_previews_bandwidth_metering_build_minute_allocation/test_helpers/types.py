"""Domain types: entity TypedDicts, status enums, role enum.

All field names follow the PRD exactly.
"""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    TEAM_OWNER = "TeamOwner"
    TEAM_BILLING_MANAGER = "TeamBillingManager"
    DEVELOPER = "Developer"
    VIEWER = "Viewer"
    SYSTEM_WEBHOOK = "SystemWebhook"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    BILLING = "BILLING"
    DEVELOPER = "DEVELOPER"
    VIEWER = "VIEWER"


class ProjectStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class DeploymentStatus(str, Enum):
    QUEUED = "QUEUED"
    BUILDING = "BUILDING"
    READY = "READY"
    STALE = "STALE"
    PROMOTED = "PROMOTED"
    ROLLED_BACK = "ROLLED_BACK"
    ERROR = "ERROR"
    CANCELED = "CANCELED"


class DeploymentTarget(str, Enum):
    PREVIEW = "PREVIEW"
    PRODUCTION = "PRODUCTION"


class AccessProtection(str, Enum):
    NONE = "NONE"
    TEAM_ONLY = "TEAM_ONLY"


class Region(str, Enum):
    IAD = "IAD"
    SFO = "SFO"
    FRA = "FRA"
    SIN = "SIN"


class DomainVerificationStatus(str, Enum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"


class DomainStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class CertificateStatus(str, Enum):
    ISSUING = "ISSUING"
    ACTIVE = "ACTIVE"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class UsagePeriodStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    INVOICED = "INVOICED"


class UsageEventType(str, Enum):
    BANDWIDTH = "BANDWIDTH"
    INVOCATION = "INVOCATION"


class UsageEventStatus(str, Enum):
    RECORDED = "RECORDED"
    ESTIMATED = "ESTIMATED"


class AlertMetric(str, Enum):
    BANDWIDTH_BYTES = "BANDWIDTH_BYTES"
    INVOCATIONS = "INVOCATIONS"
    BUILD_MINUTES = "BUILD_MINUTES"
    SPEND_CENTS = "SPEND_CENTS"


class AlertRuleStatus(str, Enum):
    ACTIVE = "ACTIVE"
    FIRED = "FIRED"
    DISABLED = "DISABLED"


class SpendCapAction(str, Enum):
    ALERT_ONLY = "ALERT_ONLY"
    BLOCK_DEPLOYS_AND_SUSPEND = "BLOCK_DEPLOYS_AND_SUSPEND"


class SpendCapStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TRIPPED = "TRIPPED"
    DISABLED = "DISABLED"


class EnvScope(str, Enum):
    DEVELOPMENT = "DEVELOPMENT"
    PREVIEW = "PREVIEW"
    PRODUCTION = "PRODUCTION"


class PlanCatalogEntry(TypedDict, total=False):
    id: str
    tier: str
    seat_limit: int
    included_build_minutes: int
    build_concurrency_limit: int
    included_bandwidth_gb: int
    included_invocations_millions: int
    bandwidth_tier1_rate_cents_per_gb: int
    bandwidth_tier2_rate_cents_per_gb: int
    bandwidth_tier2_threshold_gb: int
    invocation_rate_cents_per_million: int
    seat_price_cents_monthly: int
    overage_build_minute_rate_cents: int
    created_at: str
    updated_at: str
    version: int


class Team(TypedDict, total=False):
    id: str
    name: str
    plan_tier: str
    seat_limit: int
    included_build_minutes: int
    build_concurrency_limit: int
    included_bandwidth_gb: int
    included_invocations_millions: int
    seats_used: int
    prorated_charges_cents: int
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict, total=False):
    id: str
    team_id: str
    user_email: str
    role: str
    created_at: str
    updated_at: str
    version: int


class Project(TypedDict, total=False):
    id: str
    team_id: str
    name: str
    production_branch: str
    framework: Optional[str]
    preview_protection: str
    status: str
    suspended_reason: Optional[str]
    production_deployment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Deployment(TypedDict, total=False):
    id: str
    project_id: str
    branch: str
    git_ref: str
    commit_sha: str
    target: str
    region: str
    access_protection: str
    status: str
    url_slug: str
    url: str
    estimated_build_minutes: int
    billable_minutes: Optional[int]
    build_duration_seconds: Optional[int]
    completed_at: Optional[str]
    previous_promoted_deployment_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class EnvironmentVariable(TypedDict, total=False):
    id: str
    project_id: str
    key: str
    value: Optional[str]
    scopes: list
    is_secret: bool
    created_at: str
    updated_at: str
    version: int


class Domain(TypedDict, total=False):
    id: str
    project_id: str
    name: str
    certificate_id: Optional[str]
    verification_status: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Certificate(TypedDict, total=False):
    id: str
    domain_id: str
    issuer: str
    status: str
    not_before: str
    not_after: str
    auto_renewed_from_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Redirect(TypedDict, total=False):
    id: str
    project_id: str
    source: str
    target: str
    status_code: int
    priority: int
    created_at: str
    updated_at: str
    version: int


class UsagePeriod(TypedDict, total=False):
    id: str
    team_id: str
    period_start: str
    period_end: str
    status: str
    bandwidth_bytes: int
    invocations: int
    build_minutes_used: int
    projected_bill_cents: int
    final_bill_cents: Optional[int]
    total_due_cents: Optional[int]
    created_at: str
    updated_at: str
    version: int


# Append-only: carries ONLY id + created_at (no updated_at, no version).
class UsageEvent(TypedDict, total=False):
    id: str
    period_id: str
    team_id: str
    deployment_id: str
    event_type: str
    bandwidth_bytes: int
    invocations: int
    region: str
    edge_execution: bool
    status: str
    recorded_at: str
    effective_rate_cents: Optional[int]
    created_at: str


class AlertRule(TypedDict, total=False):
    id: str
    team_id: str
    metric: str
    threshold_value: int
    window_minutes: int
    status: str
    last_fired_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class SpendCap(TypedDict, total=False):
    id: str
    team_id: str
    cap_cents: int
    action: str
    status: str
    tripped_at: Optional[str]
    created_at: str
    updated_at: str
    version: int
