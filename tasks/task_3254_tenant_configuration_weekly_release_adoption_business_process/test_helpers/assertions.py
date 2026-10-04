"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common_fields(data: dict, entity: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity}.id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity}.created_at must be ISO 8601 UTC"
    )


def assert_tenant(data: dict):
    _assert_common_fields(data, "Tenant")
    assert isinstance(data["tenant_name"], str) and data["tenant_name"]
    assert data["tenant_kind"] in ("PRODUCTION", "SANDBOX", "IMPLEMENTATION")
    assert data["status"] in ("ACTIVE", "SUSPENDED", "RETIRED")
    assert data["handoff_state"] in ("IN_BUILD", "HANDOFF_READY", "ACCEPTED")
    assert isinstance(data["adopted_feature_count"], int)
    assert isinstance(data["active_membership_count"], int)
    assert isinstance(data["version"], int) and data["version"] >= 1
    assert is_valid_uuid(data.get("bootstrap_admin_worker_id", ""))


def assert_org_unit(data: dict):
    _assert_common_fields(data, "OrganizationUnit")
    assert data["status"] in ("PROPOSED", "ACTIVE", "INACTIVE")
    assert isinstance(data["headcount"], int) and data["headcount"] >= 0


def assert_worker(data: dict):
    _assert_common_fields(data, "Worker")
    assert isinstance(data["worker_ref"], str) and data["worker_ref"]
    assert data["status"] in ("ACTIVE", "TERMINATED")


def assert_security_group(data: dict):
    _assert_common_fields(data, "SecurityGroup")
    assert data["assignment_mode"] in ("ROLE_BASED", "USER_BASED")
    assert data["status"] in ("ACTIVE", "DISABLED")
    assert isinstance(data["min_approvers"], int) and data["min_approvers"] >= 1


def assert_membership(data: dict):
    _assert_common_fields(data, "SecurityGroupMembership")
    assert data["membership_source"] in ("ROLE_DERIVED", "USER_ASSIGNED")
    assert data["status"] in ("ACTIVE", "INVALIDATED")


def assert_definition(data: dict):
    _assert_common_fields(data, "BusinessProcessDefinition")
    assert data["transaction_type"] in ("HIRE", "TERMINATION", "EXPENSE", "ORG_CHANGE")
    assert data["status"] in ("DRAFT", "ACTIVE", "RETIRED")
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_step(data: dict):
    _assert_common_fields(data, "BusinessProcessStep")
    assert data["step_kind"] in ("APPROVAL", "REVIEW", "NOTIFICATION")
    assert data["status"] in ("ACTIVE", "REMOVED")
    assert isinstance(data["step_order"], int) and data["step_order"] >= 1


def assert_transaction(data: dict):
    _assert_common_fields(data, "TransactionInstance")
    assert data["status"] in ("IN_PROGRESS", "COMPLETED", "CANCELLED")
    assert isinstance(data["current_step_order"], int) and data["current_step_order"] >= 0
    assert isinstance(data["escalation_count"], int) and data["escalation_count"] >= 0


def assert_step_event(data: dict):
    """Append-only audit record: id + created_at only, never updated_at/version."""
    _assert_common_fields(data, "TransactionStepEvent")
    assert data["action"] in ("ADVANCE", "APPROVE", "RETURN", "SKIP", "ESCALATE", "NOTIFY")
    assert "updated_at" not in data, "TransactionStepEvent must not carry updated_at"
    assert "version" not in data, "TransactionStepEvent must not carry version"


def assert_release_train(data: dict):
    _assert_common_fields(data, "ReleaseTrain")
    assert data["release_kind"] in ("WEEKLY_SERVICE", "FEATURE_RELEASE")
    assert data["status"] in (
        "ANNOUNCED", "OPT_IN_OPEN", "OPT_IN_CLOSED", "MANDATORY_LIVE", "RETIRED",
    )


def assert_feature_adoption(data: dict):
    _assert_common_fields(data, "TenantFeatureAdoption")
    assert data["status"] in (
        "ENROLLED", "TESTING_PASSED", "ADOPTED", "DEFERRED", "FORCE_ENABLED", "ROLLED_BACK",
    )


def assert_connector(data: dict):
    _assert_common_fields(data, "IntegrationConnector")
    assert data["trigger_mode"] in ("SCHEDULED", "EVENT_DRIVEN")
    assert data["status"] in ("DRAFT", "ACTIVE", "SUSPENDED", "RETIRED")


def assert_run(data: dict):
    _assert_common_fields(data, "IntegrationRun")
    assert data["trigger_source"] in ("SCHEDULE", "EVENT", "MANUAL")
    assert data["status"] in ("QUEUED", "RUNNING", "SUCCEEDED", "FAILED", "DEAD_LETTERED")
    assert isinstance(data["attempt_count"], int) and data["attempt_count"] >= 1
    assert isinstance(data["records_processed"], int) and data["records_processed"] >= 0


def assert_refresh_job(data: dict):
    _assert_common_fields(data, "TenantRefreshJob")
    assert data["migration_mode"] in ("FULL_COPY", "DELTA_ONLY")
    assert data["status"] in ("PLANNED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED")
    assert isinstance(data["config_drift_score"], int) and data["config_drift_score"] >= 0


def assert_notification(data: dict):
    """Append-only audit record: id + created_at only, never updated_at/version."""
    _assert_common_fields(data, "Notification")
    assert data["notification_kind"] in (
        "INITIATED", "STEP_ASSIGNED", "RETURNED", "ESCALATED",
        "RETIREMENT_WARNING", "FORCE_ENABLED", "REFRESH_COMPLETED",
    )
    assert "updated_at" not in data, "Notification must not carry updated_at"
    assert "version" not in data, "Notification must not carry version"


def chain_contains(chain, step_order: int) -> bool:
    """Preview-chain membership tolerant of int or string serialization."""
    return any(
        (isinstance(item, int) and item == step_order)
        or (isinstance(item, str) and (
            item == str(step_order) or item.startswith(f"{step_order}:")
        ))
        or (isinstance(item, dict) and item.get("step_order") == step_order)
        for item in chain
    )
