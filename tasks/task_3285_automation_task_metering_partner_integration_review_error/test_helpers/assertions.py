"""Entity assertions and domain invariant checkers (PRD sections 2 and 3)."""
from prd_bench_local_runner.testing import (
    is_valid_uuid,
    is_iso8601_timestamp,
    assert_cost_precision,
)


def _assert_common_fields(data: dict):
    """The shared composite of platform-managed fields (PRD section 2.10)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_append_only(data: dict):
    """Immutable-after-creation rows carry only id and created_at (PRD section 2.10)."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "append-only rows must not expose updated_at"
    assert "version" not in data, "append-only rows must not expose version"


def assert_team_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert isinstance(data["plan_code"], str)
    assert isinstance(data["task_allowance"], int) and data["task_allowance"] >= 0
    assert isinstance(data["closer_cost_per_task_cents"], int)
    assert isinstance(data["opening_cost_per_task_cents"], int)
    assert isinstance(data["overage_enabled"], bool)
    assert isinstance(data["tasks_used_current"], int) and data["tasks_used_current"] >= 0
    assert isinstance(data["tasks_used_previous"], int) and data["tasks_used_previous"] >= 0
    assert isinstance(data["overage_tasks_used"], int) and data["overage_tasks_used"] >= 0
    assert isinstance(data["overage_amount_cents"], int) and data["overage_amount_cents"] >= 0
    assert isinstance(data["projected_overage_amount_cents"], int)
    assert isinstance(data["usage_pct_current"], (int, float))
    assert data["locked_upgrade_code"] is None or isinstance(data["locked_upgrade_code"], str)


def assert_member(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert "@" in data["email"], "email must contain @"
    assert data["role"] in ("OWNER", "ADMIN", "MEMBER")
    assert data["plan_code"] is None or isinstance(data["plan_code"], str)


def assert_folder(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"]), "account_id must be a UUID"
    assert isinstance(data["name"], str) and len(data["name"]) > 0


def assert_folder_grant(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["folder_id"])
    assert is_valid_uuid(data["member_id"])
    assert data["grant_role"] in ("READ", "EDIT", "MANAGE")


def assert_workflow(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["folder_id"])
    assert data["trigger_type"] in ("POLLING", "WEBHOOK", "INSTANT_WEBHOOK")
    assert data["status"] in ("DRAFT", "ACTIVE", "PAUSED", "DISABLED")
    assert data["pause_reason"] in ("AUTO_SOFT_CAP", "USER_PAUSED", "TOKEN_EXPIRED", None)
    assert isinstance(data["action_count"], int) and data["action_count"] >= 0
    assert isinstance(data["trigger_latency_seconds"], int)


def assert_workflow_action(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["workflow_id"])
    assert is_valid_uuid(data["integration_id"])
    assert is_valid_uuid(data["connection_id"])
    assert isinstance(data["position"], int) and data["position"] >= 1
    assert data["status"] in ("PENDING", "RUNNING", "SUCCEEDED", "FAILED", "HELD", "SKIPPED")


def assert_workflow_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["workflow_id"])
    assert data["status"] in ("RUNNING", "COMPLETED", "HELD", "FAILED")
    assert data["held_action_id"] is None or is_valid_uuid(data["held_action_id"])


def assert_integration(data: dict):
    _assert_common_fields(data)
    assert data["auth_method"] in ("OAUTH2", "API_KEY", "BASIC")
    assert data["review_status"] in ("DRAFT", "SUBMITTED", "IN_REVIEW", "LISTED", "REJECTED")
    assert isinstance(data["endpoint_coverage"], (int, float))
    assert 0 <= data["endpoint_coverage"] <= 1
    assert isinstance(data["review_rejection_count"], int)
    assert isinstance(data["reviewed_version"], int)


def assert_integration_endpoint(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["integration_id"])
    assert isinstance(data["path"], str)
    assert isinstance(data["has_response_schema"], bool)


def assert_integration_version(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["integration_id"])
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert isinstance(data["schema_coverage"], (int, float))
    assert 0 <= data["schema_coverage"] <= 1


def assert_connection(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["account_id"])
    assert is_valid_uuid(data["integration_id"])
    assert is_valid_uuid(data["owner_member_id"])
    assert data["status"] in ("CONNECTED", "TOKEN_EXPIRED", "REAUTH_REQUIRED", "DISCONNECTED")
    assert isinstance(data["refresh_count"], int) and data["refresh_count"] >= 0


def assert_workflow_version(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data["workflow_id"])
    assert is_valid_uuid(data["integration_version_id"])
    assert is_valid_uuid(data["connection_id"])
    assert data["status"] in ("CURRENT", "MIGRATION_REQUIRED", "MIGRATED", "BROKEN")
    assert isinstance(data["snapshot_action_count"], int)
    assert isinstance(data["schema_issue_count"], int)


def assert_job_event(data: dict):
    assert_append_only(data)
    assert is_valid_uuid(data["action_id"])
    assert is_valid_uuid(data["connection_id"])
    assert isinstance(data["attempt_no"], int) and data["attempt_no"] >= 1
    assert data["outcome"] in (
        "SUCCEEDED", "FAILED_RETRYABLE", "FAILED_PERMANENT", "HELD", "REPLAYED", "SKIPPED",
    )
    assert isinstance(data["latency_ms"], int)


def assert_refund_grant(data: dict):
    assert_append_only(data)
    assert is_valid_uuid(data["run_id"])
    assert is_valid_uuid(data["connection_id"])
    assert data["kind"] in ("REFUND", "REPLAY")
    assert data["consuming_job_event_id"] is None or is_valid_uuid(data["consuming_job_event_id"])


def assert_lapse_incident(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["event_no"], int) and data["event_no"] >= 1
    assert data["kind"] in ("TOKEN_LAPSE", "DOWNSTREAM_RECOVERY", "OPS_RUN")
    assert isinstance(data["target_id"], str)


def assert_account_metering_invariants(data: dict):
    """Ledger invariants that must hold after any operation (PRD sections 2.4-2.5)."""
    assert data["tasks_used_current"] >= 0
    assert data["tasks_used_previous"] >= 0
    assert data["overage_tasks_used"] >= 0
    assert data["overage_tasks_used"] <= data["tasks_used_current"]
    assert_cost_precision(data["overage_amount_cents"], min_precision=0)
    assert data["overage_amount_cents"] >= 0
    assert data["projected_overage_amount_cents"] >= 0
    # The maximum figure re-charges every epoch at the higher step rate, so it can
    # never fall below the current-epoch base figure (PRD section 2.5).
    assert data["projected_overage_amount_cents"] >= data["overage_amount_cents"]