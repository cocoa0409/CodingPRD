"""Domain types: entity TypedDicts, status enums, role enum."""
from enum import Enum
from typing import Optional, TypedDict


class UserRole(str, Enum):
    PLATFORM_OPERATOR = "PlatformOperator"
    TENANT_ADMINISTRATOR = "TenantAdministrator"
    IMPLEMENTATION_PARTNER = "ImplementationPartner"
    APPROVER = "Approver"
    INTEGRATION_DEVELOPER = "IntegrationDeveloper"


class TenantStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class TenantKind(str, Enum):
    PRODUCTION = "PRODUCTION"
    SANDBOX = "SANDBOX"
    IMPLEMENTATION = "IMPLEMENTATION"


class HandoffState(str, Enum):
    IN_BUILD = "IN_BUILD"
    HANDOFF_READY = "HANDOFF_READY"
    ACCEPTED = "ACCEPTED"


class OrgUnitStatus(str, Enum):
    PROPOSED = "PROPOSED"
    ACTIVE = "ACTIVE"
    INACTIVE = "INACTIVE"


class WorkerStatus(str, Enum):
    ACTIVE = "ACTIVE"
    TERMINATED = "TERMINATED"


class SecurityGroupStatus(str, Enum):
    ACTIVE = "ACTIVE"
    DISABLED = "DISABLED"


class MembershipStatus(str, Enum):
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"


class MembershipSource(str, Enum):
    ROLE_DERIVED = "ROLE_DERIVED"
    USER_ASSIGNED = "USER_ASSIGNED"


class DefinitionStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    RETIRED = "RETIRED"


class StepStatus(str, Enum):
    ACTIVE = "ACTIVE"
    REMOVED = "REMOVED"


class StepKind(str, Enum):
    APPROVAL = "APPROVAL"
    REVIEW = "REVIEW"
    NOTIFICATION = "NOTIFICATION"


class InclusionCondition(str, Enum):
    ALWAYS = "ALWAYS"
    IF_HEADCOUNT_GE_50 = "IF_HEADCOUNT_GE_50"
    IF_CROSS_UNIT = "IF_CROSS_UNIT"
    IF_AMOUNT_GT_1000 = "IF_AMOUNT_GT_1000"


class TransactionStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class StepEventAction(str, Enum):
    ADVANCE = "ADVANCE"
    APPROVE = "APPROVE"
    RETURN = "RETURN"
    SKIP = "SKIP"
    ESCALATE = "ESCALATE"
    NOTIFY = "NOTIFY"


class ReleaseTrainStatus(str, Enum):
    ANNOUNCED = "ANNOUNCED"
    OPT_IN_OPEN = "OPT_IN_OPEN"
    OPT_IN_CLOSED = "OPT_IN_CLOSED"
    MANDATORY_LIVE = "MANDATORY_LIVE"
    RETIRED = "RETIRED"


class ReleaseKind(str, Enum):
    WEEKLY_SERVICE = "WEEKLY_SERVICE"
    FEATURE_RELEASE = "FEATURE_RELEASE"


class AdoptionStatus(str, Enum):
    ENROLLED = "ENROLLED"
    TESTING_PASSED = "TESTING_PASSED"
    ADOPTED = "ADOPTED"
    DEFERRED = "DEFERRED"
    FORCE_ENABLED = "FORCE_ENABLED"
    ROLLED_BACK = "ROLLED_BACK"


class ConnectorStatus(str, Enum):
    DRAFT = "DRAFT"
    ACTIVE = "ACTIVE"
    SUSPENDED = "SUSPENDED"
    RETIRED = "RETIRED"


class TriggerMode(str, Enum):
    SCHEDULED = "SCHEDULED"
    EVENT_DRIVEN = "EVENT_DRIVEN"


class RunStatus(str, Enum):
    QUEUED = "QUEUED"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    DEAD_LETTERED = "DEAD_LETTERED"


class TriggerSource(str, Enum):
    SCHEDULE = "SCHEDULE"
    EVENT = "EVENT"
    MANUAL = "MANUAL"


class RefreshJobStatus(str, Enum):
    PLANNED = "PLANNED"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class MigrationMode(str, Enum):
    FULL_COPY = "FULL_COPY"
    DELTA_ONLY = "DELTA_ONLY"


class NotificationKind(str, Enum):
    INITIATED = "INITIATED"
    STEP_ASSIGNED = "STEP_ASSIGNED"
    RETURNED = "RETURNED"
    ESCALATED = "ESCALATED"
    RETIREMENT_WARNING = "RETIREMENT_WARNING"
    FORCE_ENABLED = "FORCE_ENABLED"
    REFRESH_COMPLETED = "REFRESH_COMPLETED"


class TransactionType(str, Enum):
    HIRE = "HIRE"
    TERMINATION = "TERMINATION"
    EXPENSE = "EXPENSE"
    ORG_CHANGE = "ORG_CHANGE"


# --- Entity TypedDicts ---
# Entities with common fields carry id + created_at + updated_at + version.
# Append-only entities (TransactionStepEvent, Notification) carry only id + created_at.


class Tenant(TypedDict, total=False):
    id: str
    tenant_name: str
    tenant_kind: str
    service_level_tier: str
    code_version: str
    weekly_update_auto_apply: bool
    maintenance_slot_utc: int
    refresh_source_tenant_id: Optional[str]
    bootstrap_admin_worker_id: str
    handoff_state: str
    adopted_feature_count: int
    active_membership_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


class OrganizationUnit(TypedDict, total=False):
    id: str
    tenant_id: str
    parent_unit_id: Optional[str]
    unit_name: str
    unit_type: str
    effective_date: str
    headcount: int
    status: str
    created_at: str
    updated_at: str
    version: int


class Worker(TypedDict, total=False):
    id: str
    tenant_id: str
    worker_ref: str
    full_name: str
    org_unit_id: Optional[str]
    manager_worker_id: Optional[str]
    hire_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityGroup(TypedDict, total=False):
    id: str
    tenant_id: str
    group_name: str
    assignment_mode: str
    org_unit_id: Optional[str]
    min_approvers: int
    status: str
    created_at: str
    updated_at: str
    version: int


class SecurityGroupMembership(TypedDict, total=False):
    id: str
    security_group_id: str
    worker_id: str
    membership_source: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessProcessDefinition(TypedDict, total=False):
    id: str
    tenant_id: str
    transaction_type: str
    definition_name: str
    notify_on_initiate: bool
    escalation_after_hours: int
    version_pin_policy: str
    status: str
    created_at: str
    updated_at: str
    version: int


class BusinessProcessStep(TypedDict, total=False):
    id: str
    definition_id: str
    step_order: int
    step_kind: str
    approver_security_group_id: Optional[str]
    inclusion_condition: str
    return_target_step_order: Optional[int]
    status: str
    created_at: str
    updated_at: str
    version: int


class TransactionInstance(TypedDict, total=False):
    id: str
    tenant_id: str
    definition_id: str
    definition_version_pinned: Optional[int]
    initiator_worker_id: str
    source_org_unit_id: Optional[str]
    target_org_unit_id: str
    amount: float
    current_step_order: int
    escalation_count: int
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): only id + created_at plus own fields.
class TransactionStepEvent(TypedDict, total=False):
    id: str
    instance_id: str
    step_order: int
    action: str
    actor_worker_id: Optional[str]
    comment: Optional[str]
    occurred_at: str
    created_at: str


class ReleaseTrain(TypedDict, total=False):
    id: str
    release_label: str
    release_kind: str
    opt_in_window_start: Optional[str]
    opt_in_window_end: Optional[str]
    mandatory_date: str
    status: str
    created_at: str
    updated_at: str
    version: int


class TenantFeatureAdoption(TypedDict, total=False):
    id: str
    tenant_id: str
    release_train_id: str
    feature_key: str
    deprecates_feature_key: Optional[str]
    sandbox_test_evidence_id: Optional[str]
    enrolled_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationConnector(TypedDict, total=False):
    id: str
    tenant_id: str
    connector_name: str
    trigger_mode: str
    schedule_cron: Optional[str]
    subscribed_event: Optional[str]
    blackout_window_start_utc: int
    blackout_window_end_utc: int
    status: str
    created_at: str
    updated_at: str
    version: int


class IntegrationRun(TypedDict, total=False):
    id: str
    connector_id: str
    tenant_id: str
    trigger_source: str
    attempt_count: int
    records_processed: int
    status: str
    created_at: str
    updated_at: str
    version: int


class TenantRefreshJob(TypedDict, total=False):
    id: str
    source_tenant_id: str
    target_tenant_id: str
    include_workers: bool
    migration_mode: str
    config_drift_score: int
    scheduled_at: str
    status: str
    created_at: str
    updated_at: str
    version: int


# Append-only (common_fields: false): only id + created_at plus own fields.
class Notification(TypedDict, total=False):
    id: str
    tenant_id: str
    recipient_worker_id: str
    notification_kind: str
    reference_entity: str
    reference_id: str
    created_at: str
