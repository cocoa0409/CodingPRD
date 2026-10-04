"""Entity assertions and domain invariant checkers."""
from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _parse_iso(value: str) -> datetime:
    v = value.replace("Z", "+00:00")
    return datetime.fromisoformat(v).astimezone(timezone.utc)


def assert_ts_equal(actual, expected, msg: str = ""):
    """Assert two ISO 8601 timestamps denote the same instant.

    PRD §2.4 fixes the fractional-digit rendering only for `created_at`,
    `updated_at`, and `api_request_timestamp`; for all other server-stamped
    timestamps the rendering (with or without `.000`) is implementation
    choice, so tests compare instants, not strings.
    """
    assert isinstance(actual, str) and is_iso8601_timestamp(actual), (
        f"expected ISO 8601 timestamp, got {actual!r}. {msg}")
    assert _parse_iso(actual) == _parse_iso(expected), (
        f"timestamp instant mismatch: {actual!r} != {expected!r}. {msg}")


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be a positive int"


def assert_smart_account(data: dict):
    _assert_common(data)
    assert isinstance(data["account_ref"], str) and data["account_ref"]
    assert isinstance(data["display_name"], str) and data["display_name"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert data["compliance_posture"] in ["COMPLIANT", "GRACE", "NON_COMPLIANT"]


def assert_partner_org(data: dict):
    _assert_common(data)
    assert isinstance(data["partner_ref"], str) and data["partner_ref"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_partner_delegation(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["partner_org_id"])
    assert is_valid_uuid(data["smart_account_id"])
    assert data["scope"] in ["LICENSING", "SERVICE_CONTRACTS", "FULL"]
    assert data["status"] in ["ACTIVE", "REVOKED"]


def assert_virtual_account(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["smart_account_id"])
    assert isinstance(data["name"], str) and data["name"]
    assert data["status"] in ["ACTIVE", "ARCHIVED"]


def assert_license_pool(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["virtual_account_id"])
    assert isinstance(data["sku"], str) and data["sku"]
    assert data["license_model"] in ["PERPETUAL", "SUBSCRIPTION"]
    assert data["feature_tier"] in ["ESSENTIALS", "ADVANTAGE", "PREMIER"]
    assert isinstance(data["purchased_quantity"], int) and data["purchased_quantity"] >= 0
    assert isinstance(data["consumed_quantity"], int) and data["consumed_quantity"] >= 0
    assert data["compliance_state"] in ["COMPLIANT", "IN_GRACE", "OUT_OF_COMPLIANCE"]


def assert_device(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["virtual_account_id"])
    assert isinstance(data["serial_number"], str) and data["serial_number"]
    assert isinstance(data["product_family"], str) and data["product_family"]
    assert data["registration_state"] in ["PENDING", "REGISTERED", "DEREGISTERED", "RETIRED"]


def assert_assignment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["device_id"])
    assert is_valid_uuid(data["license_pool_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["status"] in ["ACTIVE", "RELEASED"]


def assert_usage_report(data: dict):
    # Append-only: no updated_at / version (PRD §2.4)
    _assert_common(data, with_version=False)
    assert "version" not in data, "append-only report must not carry version"
    assert is_valid_uuid(data["device_id"])
    assert data["status"] in ["ACCEPTED", "REJECTED"]


def assert_compliance_event(data: dict):
    _assert_common(data, with_version=False)
    assert data["event_type"] in [
        "OVERAGE_DETECTED",
        "GRACE_STARTED",
        "GRACE_EXPIRED",
        "RESTORED_TO_COMPLIANCE",
    ]


def assert_milestone(data: dict):
    _assert_common(data, with_version=False)
    assert data["milestone_type"] in ["END_OF_SALE", "END_OF_LIFE", "END_OF_SUPPORT"]


def assert_service_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["smart_account_id"])
    assert isinstance(data["contract_number"], str) and data["contract_number"]
    assert data["service_level"] in ["DEPOT_RETURN", "ADVANCE_NBD", "ADVANCE_4H"]
    assert data["support_tier"] in ["SOFTWARE_ONLY", "SOFTWARE_HARDWARE", "FULL"]
    assert data["status"] in ["ACTIVE", "EXPIRED", "CANCELLED"]


def assert_contract_coverage(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["service_contract_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["status"] in ["ACTIVE", "RELEASED", "VOIDED"]


def assert_rma_case(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["contract_coverage_id"])
    assert is_valid_uuid(data["device_id"])
    assert data["status"] in [
        "OPENED",
        "REPLACEMENT_SHIPPED",
        "REPLACEMENT_DELIVERED",
        "DEFECTIVE_RETURNED",
        "CLOSED",
        "CANCELLED",
    ]
    assert isinstance(data["sla_breached"], bool)


def assert_transfer_request(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data["source_pool_id"])
    assert is_valid_uuid(data["target_virtual_account_id"])
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["reason"] in ["HARDWARE_REFRESH", "ACCOUNT_REORG", "PARTNER_EXIT"]
    assert data["status"] in ["PENDING_APPROVAL", "APPROVED", "REJECTED", "EXECUTED", "CANCELLED"]
