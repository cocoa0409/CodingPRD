"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_account(data: dict):
    assert is_valid_uuid(data.get("id", "")), "Account.id must be a bare UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["account_type"] in ("PERSONAL", "BUSINESS", "ENTERPRISE")
    assert data["region"] in ("US_WEST", "US_EAST", "EU_CENTRAL")
    assert data["storage_tier"] in ("BASIC", "PLUS", "PRO")
    assert data["status"] in ("ACTIVE", "DELINQUENT", "CLOSED")
    assert isinstance(data["usage_gb"], (int, float))
    assert isinstance(data["peak_usage_gb"], (int, float))
    assert isinstance(data["restore_download_gb"], (int, float))
    assert isinstance(data["transaction_count"], int)
    assert isinstance(data["retention_days"], int)
    assert isinstance(data["has_extended_history"], bool)
    assert isinstance(data["group_count"], int)
    assert isinstance(data["deposit_held_cents"], int)
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_backup_group(data: dict):
    assert is_valid_uuid(data.get("id", "")), "BackupGroup.id must be a bare UUID"
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a bare UUID"
    assert isinstance(data.get("name"), str) and data["name"]
    assert data["tier"] in ("STANDARD", "HIGH_FREQUENCY")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["group_retention_days"], int)
    assert isinstance(data["agent_count"], int)
    assert isinstance(data["expected_daily_transactions"], int)
    assert isinstance(data["member_transaction_share"], (int, float))
    assert isinstance(data["created_seq"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))
    assert isinstance(data["version"], int)


def assert_group_policy(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("group_id", ""))
    assert data["policy_kind"] in ("RETENTION", "VERSIONING", "RANSOMWARE")
    assert data["status"] in ("ACTIVE", "SUPERSEDED")
    assert isinstance(data["min_retention_days"], int)
    assert isinstance(data["max_extended_history_days"], int)
    assert isinstance(data["min_restore_point_age_hours"], int)
    assert isinstance(data["require_mfa_for_restore"], bool)
    assert is_iso8601_timestamp(data.get("effective_from_utc", ""))


def assert_agent(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("group_id", ""))
    assert isinstance(data.get("hostname"), str) and data["hostname"]
    assert data["os_type"] in ("WINDOWS", "MACOS", "LINUX")
    assert data["license_type"] in ("PERSONAL", "BUSINESS", "ENTERPRISE")
    assert data["status"] in ("PENDING_AUTH", "ACTIVE", "RETIRED", "BLOCKED")
    assert isinstance(data["throttle_month"], int)
    assert isinstance(data["last_change_sequence"], int)
    assert isinstance(data["in_throttle_window"], bool)


def assert_backup_set(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("agent_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["state"] in ("PROVISIONING", "INITIAL_RUNNING", "ACTIVE", "SUSPENDED", "DELETED")
    assert data["durability_class"] in ("STANDARD", "DEEP_ARCHIVE")
    assert isinstance(data["storage_gb"], (int, float))
    assert isinstance(data["version_chain_depth"], int)
    assert isinstance(data["recovery_points"], int)
    assert isinstance(data["is_initial_flush"], bool)
    assert isinstance(data["created_seq"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert is_iso8601_timestamp(data.get("updated_at", ""))


def assert_file_version(data: dict):
    """FileVersion is an immutable log row: id and created_at only."""
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("backup_set_id", ""))
    assert isinstance(data.get("file_path"), str) and data["file_path"]
    assert isinstance(data["version_number"], int) and data["version_number"] >= 1
    assert data["operation"] in ("CREATE", "MODIFY", "DELETE")
    assert isinstance(data["size_bytes"], int)
    assert isinstance(data.get("content_hash"), str) and data["content_hash"]
    assert is_iso8601_timestamp(data.get("event_utc", ""))
    assert is_iso8601_timestamp(data.get("recoverable_until_utc", ""))
    assert isinstance(data["is_deleted"], bool)
    assert isinstance(data["is_expired"], bool)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_restore_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("subject_agent_id", ""))
    assert is_iso8601_timestamp(data.get("restore_point_in_utc", ""))
    assert data["restore_type"] in ("FILE_DOWNLOAD", "ZIP_ARCHIVE", "DRIVE_SHIPMENT")
    assert isinstance(data["requested_file_count"], int)
    assert isinstance(data["requested_size_gb"], (int, float))
    assert data["state"] in (
        "REQUESTED", "VALIDATING", "IN_PROGRESS", "READY",
        "COMPLETED", "FAILED", "CANCELLED", "REVERSED",
    )
    assert isinstance(data["egress_gb"], (int, float))
    assert isinstance(data["egress_fee_cents"], int)
    assert isinstance(data["archive_entry_count"], int)
    assert is_iso8601_timestamp(data.get("created_at", ""))


def assert_drive_shipment(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("restore_request_id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["state"] in (
        "PREPARING", "SHIPPED", "DELIVERED", "AWAITING_RETURN",
        "RETURNED", "CLOSED", "DELINQUENT",
    )
    assert isinstance(data["drive_capacity_gb"], (int, float))
    assert isinstance(data["drive_count"], int)
    assert isinstance(data["deposit_fee_cents"], int)
    assert isinstance(data["return_credit_cents"], int)
    assert isinstance(data["was_delinquent"], bool)


def assert_billing_period(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_iso8601_timestamp(data.get("period_start_utc", ""))
    assert is_iso8601_timestamp(data.get("period_end_utc", ""))
    assert data["state"] in ("OPEN", "CLOSED")
    for field in (
        "storage_fee_cents", "initial_upload_credit_cents",
        "storage_credit_applied_cents", "egress_fee_cents",
        "transaction_fee_cents", "total_cents",
    ):
        assert isinstance(data[field], int), f"{field} must be integer cents"


def assert_storage_pod(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert data["region"] in ("US_WEST", "US_EAST", "EU_CENTRAL")
    assert data["status"] in ("HEALTHY", "DEGRADED", "REPAIRING", "FAILED")
    assert isinstance(data["total_shards"], int)
    assert isinstance(data["data_shards"], int)
    assert isinstance(data["parity_shards"], int)
    assert isinstance(data["failed_shards"], int)
    assert isinstance(data["reliability_pct"], (int, float))
    assert isinstance(data["is_reconstructable"], bool)


def assert_retention_change_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert is_valid_uuid(data.get("group_id", ""))
    assert isinstance(data["requested_retention_days"], int)
    assert data["reason_code"] in ("UPGRADE", "DOWNGRADE", "LITIGATION_HOLD", "POLICY_ALIGNMENT")
    assert data["state"] in ("SUBMITTED", "COOLING_OFF", "APPLIED", "REJECTED", "EXPIRED")
    assert isinstance(data["original_retention_days"], int)


def assert_data_deletion_request(data: dict):
    assert is_valid_uuid(data.get("id", ""))
    assert is_valid_uuid(data.get("account_id", ""))
    assert data["deletion_scope"] in ("DELETED_FILES", "ACCOUNT_CLOSURE")
    assert isinstance(data.get("authorization_ref"), str)
    assert data["state"] in ("SUBMITTED", "APPROVED", "EXECUTING", "COMPLETED", "REJECTED")
    assert isinstance(data["files_purged"], int)
    assert isinstance(data["bytes_purged"], int)


def assert_account_invariants(data: dict):
    """Ledger and volume invariants that hold after any operation."""
    assert data["usage_gb"] >= 0
    assert data["peak_usage_gb"] >= data["usage_gb"] - 1e-6
    assert data["restore_download_gb"] >= 0
    assert data["transaction_count"] >= 0
    assert data["deposit_held_cents"] >= 0


def assert_pod_invariants(data: dict):
    assert data["parity_shards"] == data["total_shards"] - data["data_shards"]
    assert data["is_reconstructable"] == (data["failed_shards"] <= data["parity_shards"])
    assert 0 <= data["reliability_pct"] <= 100