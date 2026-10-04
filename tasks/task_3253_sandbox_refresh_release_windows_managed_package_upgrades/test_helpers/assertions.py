"""Entity assertions and domain invariant checkers.

Every resource carries ``id``, ``created_at``, ``updated_at`` and ``version``
as system-managed properties (PRD §2.5); the per-entity assertions below check
the fields the PRD declares for each type.
"""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ENVIRONMENT_TYPES = ["PRODUCTION", "FULL_COPY", "PARTIAL", "DEVELOPER"]
RELEASE_STATUSES = ["CONFIG", "SCHEDULED", "RELEASED"]
RELEASE_SCHEDULE_MODES = ["MANUAL_FIXED", "FLAG_ONLY"]
REFRESH_JOB_STATUSES = ["PENDING", "MASKING", "COMPLETING", "COMPLETED", "FAILED"]
INSTALLED_PACKAGE_STATUSES = ["INSTALLED", "UPGRADED", "NEEDS_UPGRADE", "UNINSTALLED"]
SHARING_RULE_SCOPES = ["PRIVATE", "NAMESPACE_READ", "ORG_WIDE"]
CHANGE_SET_STATUSES = ["DRAFT", "VALIDATED", "APPROVED", "STALE", "DEPLOYED", "FAILED"]
DEPLOYMENT_JOB_STATUSES = ["QUEUED", "EXECUTING", "SUCCEEDED", "FAILED"]
GOVERNOR_REQUEST_STATUSES = ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED"]
LEDGER_KINDS = ["DATA", "FILE"]
LEDGER_STATUSES = ["LIVE", "ARCHIVED"]
AUDIT_STATUSES = ["OPEN", "CLOSED"]
AUDIT_GRADES = ["PASS", "ATTENTION", "BLOCKED"]


def assert_common_fields(data: dict):
    """The four system-managed properties every resource carries."""
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"
    assert data["version"] >= 1, "version starts at 1"


def assert_environment(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and len(data["name"]) > 0
    assert data["type"] in ENVIRONMENT_TYPES
    assert data["release_status"] in RELEASE_STATUSES
    assert data["release_schedule_mode"] in RELEASE_SCHEDULE_MODES
    assert isinstance(data["refresh_interval_days"], int)
    assert 1 <= data["refresh_interval_days"] <= 365
    assert isinstance(data["masked_field_count"], int) and data["masked_field_count"] >= 0
    assert isinstance(data["storage_cap_bytes"], int) and data["storage_cap_bytes"] > 0
    assert isinstance(data["aperture_limit"], int) and 0 <= data["aperture_limit"] <= 10
    assert isinstance(data["installed_version_ids"], list)
    assert isinstance(data["storage_breach"], bool)


def assert_environment_invariants(data: dict):
    """Derived storage relations that must hold after any storage operation."""
    used = data["storage_used_bytes"]
    archived = data["storage_archived_bytes"]
    total = data["storage_total_bytes"]
    assert isinstance(used, int) and used >= 0
    assert isinstance(archived, int) and archived >= 0
    assert total == used + archived, (
        f"storage_total_bytes ({total}) must equal used + archived ({used} + {archived})"
    )
    assert data["storage_headroom_bytes"] == total - data["storage_cap_bytes"]
    assert data["storage_breach"] == (used >= data["storage_cap_bytes"]), (
        "storage_breach must be true exactly when used bytes reach the cap (inclusive)"
    )


def assert_refresh_job(data: dict):
    assert_common_fields(data)
    assert data["status"] in REFRESH_JOB_STATUSES
    assert isinstance(data["consumed_aperture"], bool)
    assert isinstance(data["masked_field_count"], int) and data["masked_field_count"] >= 0
    assert isinstance(data["environment_id"], str) and is_valid_uuid(data["environment_id"])


def assert_package_version(data: dict):
    assert_common_fields(data)
    assert isinstance(data["namespace"], str) and len(data["namespace"]) > 0
    assert isinstance(data["major_version"], int) and data["major_version"] >= 1
    assert isinstance(data["deprecated"], bool)
    assert isinstance(data["install_count"], int) and data["install_count"] >= 0


def assert_installed_package(data: dict):
    assert_common_fields(data)
    assert data["status"] in INSTALLED_PACKAGE_STATUSES
    assert isinstance(data["namespace"], str) and len(data["namespace"]) > 0
    assert isinstance(data["stale"], bool)
    assert is_valid_uuid(data["environment_id"])
    assert is_valid_uuid(data["package_version_id"])


def assert_permission_assignment(data: dict):
    assert_common_fields(data)
    assert data["principal_type"] in ["PROFILE", "PERMISSION_SET"]
    assert data["sharing_rule_scope"] in SHARING_RULE_SCOPES
    assert isinstance(data["revoked"], bool)
    assert isinstance(data["object_prefix"], str)
    assert is_valid_uuid(data["environment_id"])


def assert_change_set(data: dict):
    assert_common_fields(data)
    assert data["status"] in CHANGE_SET_STATUSES
    assert isinstance(data["component_list"], list)
    assert isinstance(data["component_dependencies"], list)
    assert isinstance(data["component_digests"], dict)
    assert is_valid_uuid(data["source_environment_id"])
    assert is_valid_uuid(data["target_environment_id"])


def assert_deployment_job(data: dict):
    assert_common_fields(data)
    assert data["status"] in DEPLOYMENT_JOB_STATUSES
    assert isinstance(data["applied_component_count"], int)
    assert isinstance(data["validated_digest_match"], bool)
    assert isinstance(data["idempotency_key"], str)
    assert is_valid_uuid(data["change_set_id"])


def assert_governor_request(data: dict):
    assert_common_fields(data)
    assert data["request_kind"] in ["BATCH", "QUEUEABLE", "SCHEDULED"]
    assert data["status"] in GOVERNOR_REQUEST_STATUSES
    assert isinstance(data["scope_count"], int) and data["scope_count"] >= 0
    assert isinstance(data["projected_governor_units"], int)
    assert isinstance(data["governor_headroom_units"], int)
    assert isinstance(data["max_concurrent_jobs"], int) and data["max_concurrent_jobs"] >= 1


def assert_storage_ledger(data: dict):
    assert_common_fields(data)
    assert data["kind"] in LEDGER_KINDS
    assert data["status"] in LEDGER_STATUSES
    assert isinstance(data["bytes"], int) and data["bytes"] > 0
    assert isinstance(data["rank_index"], int) and data["rank_index"] >= 1
    assert isinstance(data["archivable"], bool)


def assert_access_audit(data: dict):
    assert_common_fields(data)
    assert data["status"] in AUDIT_STATUSES
    assert isinstance(data["overreach_count"], int) and data["overreach_count"] >= 0
    if data["status"] == "CLOSED":
        assert data["grade"] in AUDIT_GRADES
        assert data["finding"] in ["REVOKE", "RETAIN"]
    assert isinstance(data["findings"], list)