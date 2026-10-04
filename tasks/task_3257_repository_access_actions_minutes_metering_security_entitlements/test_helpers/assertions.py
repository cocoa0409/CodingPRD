"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1


def _assert_append_only_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"


def assert_enterprise(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["purchased_seats"], int)
    assert isinstance(data["used_seats"], int)
    assert isinstance(data["available_seats"], int)
    assert data["sso_enforcement"] in {"DISABLED", "CONFIGURING", "ENFORCED", "SUSPENDED"}
    assert data["pat_policy"] in {"UNRESTRICTED", "ADMIN_APPROVAL_REQUIRED", "DISALLOWED"}
    assert data["audit_log_stream_status"] in {"INACTIVE", "STREAMING", "PAUSED"}


def assert_organization(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["enterprise_id"], str)
    assert isinstance(data["login"], str) and data["login"]
    assert data["plan_tier"] in {"FREE", "TEAM", "ENTERPRISE"}
    assert data["status"] in {"ACTIVE", "SUSPENDED", "ARCHIVED"}


def assert_user_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["login"], str) and data["login"]
    assert data["status"] in {"ACTIVE", "SUSPENDED"}
    assert data["is_active_committer"] in (True, False)


def assert_commit_event(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data, "append-only record must not carry updated_at"
    assert "version" not in data, "append-only record must not carry version"
    assert isinstance(data["author_user_id"], str)
    assert isinstance(data["organization_id"], str)
    assert is_iso8601_timestamp(data["committed_at"])


def assert_team(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["name"], str) and data["name"]


def assert_team_membership(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["team_id"], str)
    assert isinstance(data["user_id"], str)
    assert data["role"] in {"MEMBER", "MAINTAINER"}


def assert_repository(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["visibility"] in {"PRIVATE", "INTERNAL", "PUBLIC"}
    assert data["advanced_security_enabled"] in (True, False)
    assert data["status"] in {"ACTIVE", "ARCHIVED"}


def assert_outside_collaborator(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["user_id"], str)
    assert isinstance(data["repository_id"], str)
    assert is_iso8601_timestamp(data["invite_expires_at"])
    assert data["status"] in {"INVITED", "ACCEPTED", "EXPIRED", "REVOKED"}


def assert_self_hosted_runner(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert data["os_type"] in {"LINUX", "WINDOWS", "MACOS"}
    assert isinstance(data["labels"], list)
    assert data["allowed_on_public_repos"] in (True, False)
    assert data["status"] in {"REGISTERED", "ACTIVE", "OFFLINE", "REMOVED"}


def assert_workflow_run(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["repository_id"], str)
    assert isinstance(data["organization_id"], str)
    assert data["runner_kind"] in {"HOSTED", "SELF_HOSTED"}
    assert data["os_type"] in {"LINUX", "WINDOWS", "MACOS"}
    assert isinstance(data["requested_minutes"], int) and data["requested_minutes"] >= 1
    assert data["execution_status"] in {"QUEUED", "RUNNING", "COMPLETED", "FAILED", "CANCELLED"}
    assert data["billing_status"] in {"METERED", "ALLOWANCE_APPLIED", "BILLED", "REFUNDED"}


def assert_storage_artifact(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["repository_id"], str)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["size_mb"], int) and data["size_mb"] >= 1
    assert isinstance(data["retention_days"], int)
    assert is_iso8601_timestamp(data["expires_at"])
    assert data["status"] in {"RETAINED", "EXPIRED", "DELETED"}


def assert_security_entitlement(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["repository_id"], str)
    assert data["product"] in {"SECRET_SCANNING", "CODE_SCANNING", "DEPENDENCY_REVIEW"}
    assert data["status"] in {"PENDING_ACTIVATION", "ACTIVE", "SUSPENDED", "CANCELLED"}


def assert_personal_access_token(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["user_id"], str)
    assert isinstance(data["enterprise_id"], str)
    assert isinstance(data["scopes"], list)
    assert data["status"] in {"PENDING_APPROVAL", "ACTIVE", "REVOKED", "EXPIRED"}


def assert_audit_log_event(data: dict):
    _assert_append_only_fields(data)
    assert "updated_at" not in data
    assert "version" not in data
    assert isinstance(data["enterprise_id"], str)
    assert isinstance(data["action"], str) and data["action"]
    assert data["streamed"] in (True, False)


def assert_marketplace_app_installation(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["organization_id"], str)
    assert isinstance(data["app_slug"], str) and data["app_slug"]
    assert isinstance(data["permission_scopes"], list)
    assert data["status"] in {"PENDING", "INSTALLED", "SUSPENDED", "UNINSTALLED"}


def assert_seat_ledger_invariant(enterprise: dict):
    """used_seats + available_seats == purchased_seats, always."""
    assert enterprise["used_seats"] + enterprise["available_seats"] == enterprise["purchased_seats"], (
        f"seat ledger broken: {enterprise['used_seats']} + {enterprise['available_seats']} "
        f"!= {enterprise['purchased_seats']}"
    )
