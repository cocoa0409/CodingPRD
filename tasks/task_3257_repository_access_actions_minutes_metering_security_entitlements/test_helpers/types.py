"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import List, Optional, TypedDict


class UserRole(str, Enum):
    ENTERPRISE_ADMIN = "EnterpriseAdmin"
    ORG_ADMIN = "OrgAdmin"
    USER_ACCOUNT = "UserAccount"
    RUNNER_AGENT = "RunnerAgent"


class SsoEnforcement(str, Enum):
    DISABLED = "DISABLED"
    CONFIGURING = "CONFIGURING"
    ENFORCED = "ENFORCED"
    SUSPENDED = "SUSPENDED"


class AuditStreamStatus(str, Enum):
    INACTIVE = "INACTIVE"
    STREAMING = "STREAMING"
    PAUSED = "PAUSED"


class PatPolicy(str, Enum):
    UNRESTRICTED = "UNRESTRICTED"
    ADMIN_APPROVAL_REQUIRED = "ADMIN_APPROVAL_REQUIRED"
    DISALLOWED = "DISALLOWED"


class OrganizationStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    ARCHIVED = "ARCHIVED"


class PlanTier(str, Enum):
    FREE = "FREE"
    TEAM = "TEAM"
    ENTERPRISE = "ENTERPRISE"


class UserStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class RepositoryStatus(str, Enum):
    ACTIVE = "ACTIVE"
    ARCHIVED = "ARCHIVED"


class Visibility(str, Enum):
    PRIVATE = "PRIVATE"
    INTERNAL = "INTERNAL"
    PUBLIC = "PUBLIC"


class CollaboratorStatus(str, Enum):
    INVITED = "INVITED"
    ACCEPTED = "ACCEPTED"
    EXPIRED = "EXPIRED"
    REVOKED = "REVOKED"


class RunnerStatus(str, Enum):
    REGISTERED = "REGISTERED"
    ACTIVE = "ACTIVE"
    OFFLINE = "OFFLINE"
    REMOVED = "REMOVED"


class OsType(str, Enum):
    LINUX = "LINUX"
    WINDOWS = "WINDOWS"
    MACOS = "MACOS"


class RunnerKind(str, Enum):
    HOSTED = "HOSTED"
    SELF_HOSTED = "SELF_HOSTED"


class ExecutionStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BillingStatus(str, Enum):
    METERED = "METERED"
    ALLOWANCE_APPLIED = "ALLOWANCE_APPLIED"
    BILLED = "BILLED"
    REFUNDED = "REFUNDED"


class ArtifactStatus(str, Enum):
    RETAINED = "RETAINED"
    EXPIRED = "EXPIRED"
    DELETED = "DELETED"


class EntitlementStatus(str, Enum):
    PENDING_ACTIVATION = "PENDING_ACTIVATION"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    CANCELLED = "CANCELLED"


class SecurityProduct(str, Enum):
    SECRET_SCANNING = "SECRET_SCANNING"
    CODE_SCANNING = "CODE_SCANNING"
    DEPENDENCY_REVIEW = "DEPENDENCY_REVIEW"


class TokenStatus(str, Enum):
    PENDING_APPROVAL = "PENDING_APPROVAL"
    ACTIVE = "ACTIVE"
    REVOKED = "REVOKED"
    EXPIRED = "EXPIRED"


class AppInstallationStatus(str, Enum):
    PENDING = "PENDING"
    INSTALLED = "INSTALLED"
    SUSPENDED = "SUSPENDED"
    UNINSTALLED = "UNINSTALLED"


class MembershipRole(str, Enum):
    MEMBER = "MEMBER"
    MAINTAINER = "MAINTAINER"


# --- Entity TypedDicts -------------------------------------------------------
# Entities with the standard lifecycle carry id + created_at + updated_at +
# version. CommitEvent and AuditLogEvent are append-only records: they carry
# id and created_at but neither updated_at nor version (PRD §2.4).


class Enterprise(TypedDict, total=False):
    id: str
    name: str
    purchased_seats: int
    used_seats: int
    available_seats: int
    sso_enforcement: str
    pat_policy: str
    audit_log_stream_status: str
    billing_cycle_anchor_day: int
    created_at: str
    updated_at: str
    version: int


class Organization(TypedDict, total=False):
    id: str
    enterprise_id: str
    login: str
    plan_tier: str
    included_actions_minutes: int
    included_storage_gb: float
    consumed_actions_minutes: float
    consumed_storage_gb: float
    outside_collaborator_limit: int
    retention_freeze_windows: list
    status: str
    created_at: str
    updated_at: str
    version: int


class UserAccount(TypedDict, total=False):
    id: str
    login: str
    email: str
    is_active_committer: bool
    seat_held_enterprise_id: Optional[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class CommitEvent(TypedDict, total=False):
    id: str
    author_user_id: str
    organization_id: str
    committed_at: str
    created_at: str


class Team(TypedDict, total=False):
    id: str
    organization_id: str
    name: str
    parent_team_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class TeamMembership(TypedDict, total=False):
    id: str
    team_id: str
    user_id: str
    role: str
    created_at: str
    updated_at: str
    version: int


class Repository(TypedDict, total=False):
    id: str
    organization_id: str
    name: str
    visibility: str
    advanced_security_enabled: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class OutsideCollaborator(TypedDict, total=False):
    id: str
    organization_id: str
    user_id: str
    repository_id: str
    invite_expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SelfHostedRunner(TypedDict, total=False):
    id: str
    organization_id: str
    name: str
    os_type: str
    labels: List[str]
    allowed_on_public_repos: bool
    status: str
    created_at: str
    updated_at: str
    version: int


class WorkflowRun(TypedDict, total=False):
    id: str
    repository_id: str
    organization_id: str
    runner_id: Optional[str]
    runner_kind: str
    os_type: str
    requested_minutes: int
    billed_minutes: float
    overage_cost_cents: int
    execution_status: str
    billing_status: str
    created_at: str
    updated_at: str
    version: int


class StorageArtifact(TypedDict, total=False):
    id: str
    repository_id: str
    organization_id: str
    name: str
    size_mb: int
    retention_days: int
    expires_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityEntitlement(TypedDict, total=False):
    id: str
    organization_id: str
    repository_id: str
    product: str
    committer_count: int
    monthly_price_cents: int
    status: str
    created_at: str
    updated_at: str
    version: int


class PersonalAccessToken(TypedDict, total=False):
    id: str
    user_id: str
    enterprise_id: str
    scopes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int


class AuditLogEvent(TypedDict, total=False):
    id: str
    enterprise_id: str
    action: str
    actor_login: str
    streamed: bool
    created_at: str


class MarketplaceAppInstallation(TypedDict, total=False):
    id: str
    organization_id: str
    app_slug: str
    permission_scopes: List[str]
    status: str
    created_at: str
    updated_at: str
    version: int
