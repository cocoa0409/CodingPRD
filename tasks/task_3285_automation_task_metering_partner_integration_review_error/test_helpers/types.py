"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import TypedDict, Optional, List


class WorkflowStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    PAUSED = "PAUSED"
    DISABLED = "DISABLED"


class WorkflowPauseReason(str, Enum):
    AUTO_SOFT_CAP = "AUTO_SOFT_CAP"
    USER_PAUSED = "USER_PAUSED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"


class WorkflowActionStatus(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    HELD = "HELD"
    SKIPPED = "SKIPPED"


class WorkflowRunStatus(str, Enum):
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    HELD = "HELD"
    FAILED = "FAILED"


class IntegrationReviewStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    IN_REVIEW = "IN_REVIEW"
    LISTED = "LISTED"
    REJECTED = "REJECTED"


class IntegrationAuthMethod(str, Enum):
    OAUTH2 = "OAUTH2"
    API_KEY = "API_KEY"
    BASIC = "BASIC"


class ConnectionStatus(str, Enum):
    CONNECTED = "CONNECTED"
    TOKEN_EXPIRED = "TOKEN_EXPIRED"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    DISCONNECTED = "DISCONNECTED"


class WorkflowVersionStatus(str, Enum):
    CURRENT = "CURRENT"
    MIGRATION_REQUIRED = "MIGRATION_REQUIRED"
    MIGRATED = "MIGRATED"
    BROKEN = "BROKEN"


class TriggerType(str, Enum):
    POLLING = "POLLING"
    WEBHOOK = "WEBHOOK"
    INSTANT_WEBHOOK = "INSTANT_WEBHOOK"


class JobEventOutcome(str, Enum):
    SUCCEEDED = "SUCCEEDED"
    FAILED_RETRYABLE = "FAILED_RETRYABLE"
    FAILED_PERMANENT = "FAILED_PERMANENT"
    HELD = "HELD"
    REPLAYED = "REPLAYED"
    SKIPPED = "SKIPPED"


class RefundGrantKind(str, Enum):
    REFUND = "REFUND"
    REPLAY = "REPLAY"


class GrantRole(str, Enum):
    READ = "READ"
    EDIT = "EDIT"
    MANAGE = "MANAGE"


class MemberRole(str, Enum):
    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"


class LapseKind(str, Enum):
    TOKEN_LAPSE = "TOKEN_LAPSE"
    DOWNSTREAM_RECOVERY = "DOWNSTREAM_RECOVERY"
    OPS_RUN = "OPS_RUN"


class UserRole(str, Enum):
    MEMBER = "Member"
    PARTNER_ADMIN = "PartnerAdmin"
    REVIEWER = "Reviewer"
    PLATFORM_ADMIN = "PlatformAdmin"


# common_fields: true — carries id + created_at + updated_at + version
class TeamAccount(TypedDict):
    id: str
    name: str
    plan_code: str
    plan_id: str
    task_allowance: int
    closer_cost_per_task_cents: int
    opening_cost_per_task_cents: int
    overage_enabled: bool
    tasks_used_current: int
    tasks_used_previous: int
    overage_tasks_used: int
    usage_pct_current: float
    overage_amount_cents: int
    projected_overage_amount_cents: int
    locked_upgrade_code: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Member(TypedDict):
    id: str
    account_id: str
    email: str
    full_name: str
    plan_code: Optional[str]
    role: str
    created_at: str
    updated_at: str
    version: int


class Folder(TypedDict):
    id: str
    account_id: str
    name: str
    created_at: str
    updated_at: str
    version: int


class FolderGrant(TypedDict):
    id: str
    folder_id: str
    member_id: str
    grant_role: str
    created_at: str
    updated_at: str
    version: int


class Workflow(TypedDict):
    id: str
    account_id: str
    name: str
    folder_id: str
    trigger_type: str
    poll_interval_seconds: int
    trigger_latency_seconds: int
    status: str
    pause_reason: Optional[str]
    action_count: int
    created_at: str
    updated_at: str
    version: int


class WorkflowAction(TypedDict):
    id: str
    workflow_id: str
    position: int
    integration_id: str
    connection_id: str
    action_type: str
    filter_expression: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkflowRun(TypedDict):
    id: str
    workflow_id: str
    connection_id: str
    status: str
    held_action_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Integration(TypedDict):
    id: str
    name: str
    partner_name: str
    auth_method: str
    endpoint_coverage: float
    review_status: str
    review_rejection_count: int
    review_latency_hours: float
    reviewed_version: int
    version: int
    created_at: str
    updated_at: str


class IntegrationEndpoint(TypedDict):
    id: str
    integration_id: str
    path: str
    has_response_schema: bool
    created_at: str
    updated_at: str
    version: int


class IntegrationVersion(TypedDict):
    id: str
    integration_id: str
    version_number: int
    schema_coverage: float
    created_at: str
    updated_at: str
    version: int


class Connection(TypedDict):
    id: str
    account_id: str
    integration_id: str
    owner_member_id: str
    token_expires_at: Optional[str]
    status: str
    refresh_count: int
    reauth_requested_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class WorkflowVersion(TypedDict):
    id: str
    workflow_id: str
    integration_version_id: str
    connection_id: str
    status: str
    snapshot_action_count: int
    schema_issue_count: int
    created_at: str
    updated_at: str
    version: int


# common_fields: false — append-only, carries ONLY id + created_at
class FolderFolderGrant(TypedDict):
    id: str
    folder_id: str
    grant_id: str
    created_at: str


# common_fields: false — append-only, carries ONLY id + created_at
class JobEvent(TypedDict):
    id: str
    action_id: str
    connection_id: str
    attempt_no: int
    outcome: str
    latency_ms: int
    occurred_at: str
    created_at: str


# common_fields: false — append-only, carries ONLY id + created_at
class RefundGrant(TypedDict):
    id: str
    run_id: str
    connection_id: str
    kind: str
    source_job_event_id: str
    consuming_job_event_id: Optional[str]
    refunded_at: str
    consumed_at: Optional[str]
    created_at: str


class LapseIncident(TypedDict):
    id: str
    event_no: int
    occurred_at: str
    kind: str
    target_id: str
    created_at: str
    updated_at: str
    version: int