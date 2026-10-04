"""Domain types: entity TypedDicts, status enums and the role enum.

Every resource in this API carries the four system-managed properties ``id``,
``created_at``, ``updated_at`` and ``version``; none of them is client-supplied
(PRD §2.5).
"""
from enum import Enum
from typing import TypedDict, Optional, List, Dict, Any


class EnvironmentType(str, Enum):
    PRODUCTION = "PRODUCTION"
    FULL_COPY = "FULL_COPY"
    PARTIAL = "PARTIAL"
    DEVELOPER = "DEVELOPER"


class ReleaseStatus(str, Enum):
    CONFIG = "CONFIG"
    SCHEDULED = "SCHEDULED"
    RELEASED = "RELEASED"


class ReleaseScheduleMode(str, Enum):
    MANUAL_FIXED = "MANUAL_FIXED"
    FLAG_ONLY = "FLAG_ONLY"


class RefreshJobStatus(str, Enum):
    PENDING = "PENDING"
    MASKING = "MASKING"
    COMPLETING = "COMPLETING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class RefreshPartition(str, Enum):
    FULL = "FULL"
    ACCOUNT_PARTIAL = "ACCOUNT_PARTIAL"


class InstalledPackageStatus(str, Enum):
    INSTALLED = "INSTALLED"
    UPGRADED = "UPGRADED"
    NEEDS_UPGRADE = "NEEDS_UPGRADE"
    UNINSTALLED = "UNINSTALLED"


class PrincipalType(str, Enum):
    PROFILE = "PROFILE"
    PERMISSION_SET = "PERMISSION_SET"


class SharingRuleScope(str, Enum):
    PRIVATE = "PRIVATE"
    NAMESPACE_READ = "NAMESPACE_READ"
    ORG_WIDE = "ORG_WIDE"


class ChangeSetStatus(str, Enum):
    DRAFT = "DRAFT"
    VALIDATED = "VALIDATED"
    APPROVED = "APPROVED"
    STALE = "STALE"
    DEPLOYED = "DEPLOYED"
    FAILED = "FAILED"


class DeploymentJobStatus(str, Enum):
    QUEUED = "QUEUED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"


class GovernorRequestKind(str, Enum):
    BATCH = "BATCH"
    QUEUEABLE = "QUEUEABLE"
    SCHEDULED = "SCHEDULED"


class GovernorRequestStatus(str, Enum):
    DRAFT = "DRAFT"
    SUBMITTED = "SUBMITTED"
    ACCEPTED = "ACCEPTED"
    REJECTED = "REJECTED"


class StorageLedgerKind(str, Enum):
    DATA = "DATA"
    FILE = "FILE"


class StorageLedgerStatus(str, Enum):
    LIVE = "LIVE"
    ARCHIVED = "ARCHIVED"


class AccessAuditStatus(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class AuditGrade(str, Enum):
    PASS = "PASS"
    ATTENTION = "ATTENTION"
    BLOCKED = "BLOCKED"


class AuditFinding(str, Enum):
    REVOKE = "REVOKE"
    RETAIN = "RETAIN"


class UserRole(str, Enum):
    PLATFORM_ADMIN = "PlatformAdmin"
    RELEASE_MANAGER = "ReleaseManager"
    ENVIRONMENT_ADMIN = "EnvironmentAdmin"
    STORAGE_ARCHIVIST = "StorageArchivist"
    SECURITY_AUDITOR = "SecurityAuditor"
    APP_DEVELOPER = "AppDeveloper"


# Every entity in this API carries the same four system-managed properties.
class Environment(TypedDict):
    id: str
    name: str
    type: str
    parent_environment_id: Optional[str]
    refresh_interval_days: int
    last_refresh_at: Optional[str]
    next_refresh_at: Optional[str]
    masked_field_count: int
    storage_cap_bytes: int
    storage_used_bytes: int
    storage_archived_bytes: int
    storage_total_bytes: int
    storage_breach: bool
    storage_headroom_bytes: int
    last_archive_batch_id: Optional[str]
    permission_layer_total: int
    level: Optional[int]
    release_status: str
    scheduled_release_version: Optional[str]
    applied_release_version: Optional[str]
    release_schedule_mode: str
    aperture_limit: int
    aperture_used: int
    aperture_consumed: bool
    release_window_index: int
    refresh_generation: int
    installed_version_ids: List[str]
    created_at: str
    updated_at: str
    version: int


class RefreshJob(TypedDict):
    id: str
    environment_id: str
    partition: str
    status: str
    masked_field_count: int
    consumed_aperture: bool
    supersedes_job_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PackageVersion(TypedDict):
    id: str
    namespace: str
    major_version: int
    name: str
    deprecated: bool
    supersedes_version_id: Optional[str]
    requires_namespace: Optional[str]
    requires_min_version_id: Optional[str]
    unlimited_remaining_bytes_dec: Optional[str]
    install_count: int
    created_at: str
    updated_at: str
    version: int


class InstalledPackage(TypedDict):
    id: str
    environment_id: str
    package_version_id: str
    namespace: str
    status: str
    stale: bool
    installed_at: Optional[str]
    refreshed_at: Optional[str]
    pending_refresh_job_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class PermissionAssignment(TypedDict):
    id: str
    environment_id: str
    principal_type: str
    principal_name: str
    user_id: str
    object_prefix: str
    sharing_rule_scope: str
    revoked: bool
    created_at: str
    updated_at: str
    version: int


class MetadataChangeSet(TypedDict):
    id: str
    source_environment_id: str
    target_environment_id: str
    component_dependencies: List[Dict[str, Any]]
    component_list: List[Dict[str, Any]]
    status: str
    component_digests: Dict[str, int]
    validated_at: Optional[str]
    approved_at: Optional[str]
    approved_by_user_id: Optional[str]
    created_at: str
    updated_at: str
    version: int


class DeploymentJob(TypedDict):
    id: str
    change_set_id: str
    idempotency_key: str
    status: str
    applied_component_count: int
    validated_digest_match: bool
    created_at: str
    updated_at: str
    version: int


class GovernorLimitRequest(TypedDict):
    id: str
    environment_id: str
    request_kind: str
    scope_count: int
    callout_graph: List[Dict[str, Any]]
    max_concurrent_jobs: int
    status: str
    projected_governor_units: int
    governor_headroom_units: int
    created_at: str
    updated_at: str
    version: int


class StorageLedger(TypedDict):
    id: str
    environment_id: str
    kind: str
    bytes: int
    rank_index: int
    status: str
    archived_at: Optional[str]
    archivable: bool
    archive_batch_id: Optional[str]
    benchmark_outcome: Optional[str]
    created_at: str
    updated_at: str
    version: int


class AccessAudit(TypedDict):
    id: str
    environment_id: str
    reviewed_assignment_ids: List[str]
    status: str
    grade: Optional[str]
    overreach_count: int
    finding: Optional[str]
    findings: List[Dict[str, Any]]
    closed_at: Optional[str]
    created_at: str
    updated_at: str
    version: int