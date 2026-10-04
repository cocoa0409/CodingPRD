"""Domain types: entity TypedDicts, status enums, role enum.

Field sets follow the PRD common-properties rule: primary resources carry
id/created_at/updated_at/version, while DataScopeGrant, WebhookEvent,
BreakageEvent and AuditLog carry only id and created_at.
"""

from enum import Enum
from typing import Any, Dict, List, Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    COMPLIANCE_REVIEWER = "ComplianceReviewer"
    CONSUMER = "Consumer"
    RECIPIENT = "Recipient"


class InstitutionStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    BROKEN = "BROKEN"


class MigrationState(str, Enum):
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETE = "COMPLETE"


class ConnectivityMode(str, Enum):
    LEGACY_MODE = "LEGACY_MODE"
    HYBRID = "HYBRID"
    API_ONLY = "API_ONLY"


class ConnectMethod(str, Enum):
    CREDENTIALS = "CREDENTIALS"
    OAUTH_TOKEN = "OAUTH_TOKEN"
    BANK_API = "BANK_API"


class DataScope(str, Enum):
    BALANCE = "BALANCE"
    TRANSACTIONS = "TRANSACTIONS"
    IDENTITY = "IDENTITY"
    INCOME = "INCOME"
    ASSETS = "ASSETS"


class RecipientStatus(str, Enum):
    PENDING_REVIEW = "PENDING_REVIEW"
    APPROVED = "APPROVED"
    SUSPENDED = "SUSPENDED"
    REJECTED = "REJECTED"


class MinimizationPolicy(str, Enum):
    STRICT = "STRICT"
    STANDARD = "STANDARD"
    BROAD = "BROAD"


class ConsentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"
    SUPERSEDED = "SUPERSEDED"


class ConnectionStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    ACTIVE = "ACTIVE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    BROKEN = "BROKEN"
    MIGRATING = "MIGRATING"
    DISCONNECTED = "DISCONNECTED"


class RefreshJobStatus(str, Enum):
    QUEUED = "QUEUED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class RefreshJobKind(str, Enum):
    FULL = "FULL"
    INCREMENTAL = "INCREMENTAL"


class FailureReason(str, Enum):
    TRANSIENT = "TRANSIENT"
    INSTITUTION_DOWN = "INSTITUTION_DOWN"
    CREDENTIALS_INVALID = "CREDENTIALS_INVALID"
    RATE_LIMITED = "RATE_LIMITED"


class RateClass(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class WebhookEventType(str, Enum):
    TRANSACTIONS_AVAILABLE = "TRANSACTIONS_AVAILABLE"
    REAUTH_REQUIRED = "REAUTH_REQUIRED"
    CONSENT_REVOKED = "CONSENT_REVOKED"
    CONSENT_EXPIRED = "CONSENT_EXPIRED"
    DATA_DELETED = "DATA_DELETED"
    CONNECTION_MIGRATED = "CONNECTION_MIGRATED"
    INSTITUTION_BROKEN = "INSTITUTION_BROKEN"


class DeletionRequestStatus(str, Enum):
    PENDING = "PENDING"
    PROPAGATING = "PROPAGATING"
    ACKED_BY_ALL = "ACKED_BY_ALL"
    COMPLETED = "COMPLETED"


class TierAssignmentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ENDED = "ENDED"


# ── Primary resources (id + created_at + updated_at + version) ─────────────


class Institution(TypedDict, total=False):
    id: str
    name: str
    supported_methods: List[str]
    target_method: str
    migration_window_start: str
    migration_window_end: str
    migration_state: str
    status: str
    connectivity_mode: str
    created_at: str
    updated_at: str
    version: int


class InstitutionAgreement(TypedDict, total=False):
    id: str
    institution_id: str
    rate_limit_per_hour: int
    permitted_fields_by_scope: Dict[str, List[str]]
    active: bool
    created_at: str
    updated_at: str
    version: int


class Recipient(TypedDict, total=False):
    id: str
    name: str
    status: str
    declared_use_case: str
    minimization_policy: str
    created_at: str
    updated_at: str
    version: int


class ConsentRecord(TypedDict, total=False):
    id: str
    recipient_id: str
    consumer_ref: str
    data_scopes: List[str]
    expires_at: str
    status: str
    revoked_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class Connection(TypedDict, total=False):
    id: str
    institution_id: str
    consumer_ref: str
    consent_id: str
    method: str
    status: str
    reauth_not_before: Optional[str]
    reauth_cooldown_seconds: int
    consecutive_failures: int
    last_refreshed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DataProductTier(TypedDict, total=False):
    id: str
    tier_name: str
    scopes_included: List[str]
    rate_class: str
    active: bool
    created_at: str
    updated_at: str
    version: int


class RefreshJob(TypedDict, total=False):
    id: str
    connection_id: str
    kind: str
    status: str
    attempt_count: int
    requested_at: str
    executed_at: Optional[str]
    failure_reason: Optional[str]
    new_transaction_count: int
    created_at: str
    updated_at: str
    version: int


class DataDeletionRequest(TypedDict, total=False):
    id: str
    consent_id: str
    status: str
    requested_at: str
    completed_at: Optional[str]
    acked_recipient_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class RecipientTierAssignment(TypedDict, total=False):
    id: str
    recipient_id: str
    tier_id: str
    status: str
    created_at: str
    updated_at: str
    version: int


# ── Append-only resources (id + created_at only; NO updated_at, NO version) ──


class DataScopeGrant(TypedDict, total=False):
    id: str
    consent_id: str
    scope: str
    created_at: str


class WebhookEvent(TypedDict, total=False):
    id: str
    connection_id: str
    recipient_id: str
    event_type: str
    payload: Dict[str, Any]
    delivery_attempts: int
    delivered_at: Optional[str]
    created_at: str


class BreakageEvent(TypedDict, total=False):
    id: str
    institution_id: str
    connection_id: str
    kind: str
    occurred_at: str
    created_at: str


class AuditLog(TypedDict, total=False):
    id: str
    actor_role: str
    action: str
    entity_type: str
    entity_id: str
    occurred_at: str
    detail: Dict[str, Any]
    created_at: str
