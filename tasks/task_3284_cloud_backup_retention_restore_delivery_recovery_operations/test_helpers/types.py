"""Domain types: status enums, role enum and entity TypedDicts."""
from enum import Enum
from typing import TypedDict, Optional, List


class UserRole(str, Enum):
    ACCOUNT_OWNER = "AccountOwner"
    BACKUP_OPERATOR = "BackupOperator"
    RETENTION_OFFICER = "RetentionOfficer"
    COMPLIANCE_OFFICER = "ComplianceOfficer"
    SYSTEM_OPERATOR = "SystemOperator"


class AccountStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DELINQUENT = "DELINQUENT"
    CLOSED = "CLOSED"


class AccountType(str, Enum):
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class Region(str, Enum):
    US_WEST = "US_WEST"
    US_EAST = "US_EAST"
    EU_CENTRAL = "EU_CENTRAL"


class StorageTier(str, Enum):
    BASIC = "BASIC"
    PLUS = "PLUS"
    PRO = "PRO"


class GroupTier(str, Enum):
    STANDARD = "STANDARD"
    HIGH_FREQUENCY = "HIGH_FREQUENCY"


class GroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"


class PolicyKind(str, Enum):
    RETENTION = "RETENTION"
    VERSIONING = "VERSIONING"
    RANSOMWARE = "RANSOMWARE"


class PolicyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"


class OSType(str, Enum):
    WINDOWS = "WINDOWS"
    MACOS = "MACOS"
    LINUX = "LINUX"


class LicenseType(str, Enum):
    PERSONAL = "PERSONAL"
    BUSINESS = "BUSINESS"
    ENTERPRISE = "ENTERPRISE"


class AgentStatus(str, Enum):
    PENDING_AUTH = "PENDING_AUTH"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"
    BLOCKED = "BLOCKED"


class BackupSetState(str, Enum):
    PROVISIONING = "PROVISIONING"
    INITIAL_RUNNING = "INITIAL_RUNNING"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    DELETED = "DELETED"


class DurabilityClass(str, Enum):
    STANDARD = "STANDARD"
    DEEP_ARCHIVE = "DEEP_ARCHIVE"


class FileOperation(str, Enum):
    CREATE = "CREATE"
    MODIFY = "MODIFY"
    DELETE = "DELETE"


class RestoreType(str, Enum):
    FILE_DOWNLOAD = "FILE_DOWNLOAD"
    ZIP_ARCHIVE = "ZIP_ARCHIVE"
    DRIVE_SHIPMENT = "DRIVE_SHIPMENT"


class RestoreState(str, Enum):
    REQUESTED = "REQUESTED"
    VALIDATING = "VALIDATING"
    IN_PROGRESS = "IN_PROGRESS"
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    REVERSED = "REVERSED"


class ShipmentState(str, Enum):
    PREPARING = "PREPARING"
    SHIPPED = "SHIPPED"
    DELIVERED = "DELIVERED"
    AWAITING_RETURN = "AWAITING_RETURN"
    RETURNED = "RETURNED"
    CLOSED = "CLOSED"
    DELINQUENT = "DELINQUENT"


class BillingPeriodState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"


class RetentionChangeState(str, Enum):
    SUBMITTED = "SUBMITTED"
    COOLING_OFF = "COOLING_OFF"
    APPLIED = "APPLIED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"


class RetentionReasonCode(str, Enum):
    UPGRADE = "UPGRADE"
    DOWNGRADE = "DOWNGRADE"
    LITIGATION_HOLD = "LITIGATION_HOLD"
    POLICY_ALIGNMENT = "POLICY_ALIGNMENT"


class DeletionScope(str, Enum):
    DELETED_FILES = "DELETED_FILES"
    ACCOUNT_CLOSURE = "ACCOUNT_CLOSURE"


class DeletionState(str, Enum):
    SUBMITTED = "SUBMITTED"
    APPROVED = "APPROVED"
    EXECUTING = "EXECUTING"
    COMPLETED = "COMPLETED"
    REJECTED = "REJECTED"


class PodStatus(str, Enum):
    HEALTHY = "HEALTHY"
    DEGRADED = "DEGRADED"
    REPAIRING = "REPAIRING"
    FAILED = "FAILED"


# --- Entity shapes -----------------------------------------------------------
# Eleven of the twelve entities carry the full mutable-resource convention;
# FileVersion is an immutable log row that carries id and created_at only.

class Account(TypedDict, total=False):
    id: str
    name: str
    account_type: str
    region: str
    storage_tier: str
    status: str
    encryption_key_id: str
    usage_gb: float
    restore_download_gb: float
    transaction_count: int
    peak_usage_gb: float
    retention_days: int
    has_extended_history: bool
    group_count: int
    deposit_held_cents: int
    initial_full_backup_gb: float
    first_closed_period_utc: Optional[str]
    created_at: str
    updated_at: str
    version: int


class BackupGroup(TypedDict, total=False):
    id: str
    account_id: str
    name: str
    tier: str
    retention_days_override: Optional[int]
    status: str
    group_retention_days: int
    agent_count: int
    expected_daily_transactions: int
    member_transaction_share: float
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class GroupPolicy(TypedDict, total=False):
    id: str
    group_id: str
    policy_kind: str
    min_retention_days: int
    max_extended_history_days: int
    min_restore_point_age_hours: int
    require_mfa_for_restore: bool
    effective_from_utc: str
    status: str
    created_at: str
    updated_at: str
    version: int


class Agent(TypedDict, total=False):
    id: str
    account_id: str
    group_id: str
    hostname: str
    os_type: str
    license_type: str
    status: str
    throttle_month: int
    data_stored_gb: float
    last_change_sequence: int
    in_throttle_window: bool
    data_stored_share: float
    created_at: str
    updated_at: str
    version: int


class BackupSet(TypedDict, total=False):
    id: str
    agent_id: str
    account_id: str
    state: str
    durability_class: str
    initial_started_at: Optional[str]
    last_backup_at: Optional[str]
    storage_gb: float
    version_chain_depth: int
    retention_floor_utc: Optional[str]
    recovery_points: int
    is_initial_flush: bool
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class FileVersion(TypedDict, total=False):
    # immutable log row: id + created_at only, no updated_at and no version
    id: str
    backup_set_id: str
    file_path: str
    version_number: int
    operation: str
    size_bytes: int
    content_hash: str
    event_utc: str
    recoverable_until_utc: str
    is_deleted: bool
    is_expired: bool
    created_at: str


class RestoreRequest(TypedDict, total=False):
    id: str
    account_id: str
    subject_agent_id: str
    restore_point_in_utc: str
    restore_type: str
    requested_file_count: int
    requested_size_gb: float
    requester_mfa_ticket: Optional[str]
    drive_capacity_gb: Optional[float]
    drive_count: Optional[int]
    deposit_fee_cents: Optional[int]
    restore_transaction_count: int
    state: str
    is_ransomware_recovery: bool
    egress_gb: float
    egress_fee_cents: int
    archive_entry_count: int
    created_at: str
    updated_at: str
    version: int


class DriveShipment(TypedDict, total=False):
    id: str
    restore_request_id: str
    account_id: str
    drive_capacity_gb: float
    drive_count: int
    deposit_fee_cents: int
    state: str
    shipped_at: Optional[str]
    return_deadline_utc: Optional[str]
    return_credit_cents: int
    was_delinquent: bool
    created_at: str
    updated_at: str
    version: int


class BillingPeriod(TypedDict, total=False):
    id: str
    account_id: str
    period_start_utc: str
    period_end_utc: str
    restore_active_days: int
    state: str
    usage_gb_avg: float
    peak_usage_gb: float
    egress_gb: float
    transaction_count: int
    storage_fee_cents: int
    initial_upload_credit_cents: int
    storage_credit_applied_cents: int
    egress_fee_cents: int
    transaction_fee_cents: int
    total_cents: int
    created_at: str
    updated_at: str
    version: int


class StoragePod(TypedDict, total=False):
    id: str
    region: str
    status: str
    total_shards: int
    data_shards: int
    parity_shards: int
    failed_shards: int
    reliability_pct: float
    is_reconstructable: bool
    last_repair_utc: Optional[str]
    created_seq: int
    created_at: str
    updated_at: str
    version: int


class RetentionChangeRequest(TypedDict, total=False):
    id: str
    account_id: str
    group_id: str
    requested_retention_days: int
    reason_code: str
    state: str
    submitted_at_utc: Optional[str]
    cooling_off_until_utc: Optional[str]
    original_retention_days: int
    created_at: str
    updated_at: str
    version: int


class DataDeletionRequest(TypedDict, total=False):
    id: str
    account_id: str
    deletion_scope: str
    authorization_ref: str
    state: str
    approved_at_utc: Optional[str]
    executability_utc: Optional[str]
    files_purged: int
    bytes_purged: int
    created_at: str
    updated_at: str
    version: int