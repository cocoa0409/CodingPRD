"""Entity assertions and domain invariant helpers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_mutable_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_organization(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["qualified_device_count"], int)
    assert data["qualified_device_count"] >= 1
    assert data["price_level"] in ["A", "B", "C", "D"]


def assert_agreement(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["DRAFT", "ACTIVE", "RENEWAL_PENDING", "RENEWED", "EXPIRED", "NON_RENEWED"]
    assert isinstance(data["renewal_count"], int)
    assert isinstance(data["start_date"], str)
    assert isinstance(data["end_date"], str)


def assert_product(data: dict):
    _assert_common_mutable_fields(data)
    assert data["license_model"] in ["PER_USER", "PER_DEVICE", "PER_SERVER_CORE"]
    assert data["license_kind"] in ["PERPETUAL", "SUBSCRIPTION"]
    assert data["edition"] in ["STANDARD", "PROFESSIONAL", "ENTERPRISE"]
    assert isinstance(data["annual_unit_price_cents"], int)
    assert isinstance(data["license_mobility"], bool)


def assert_anniversary(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["year_index"], int)
    assert 1 <= data["year_index"] <= 3
    assert isinstance(data["true_up_closed"], bool)


def assert_entitlement(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["quantity"], int)
    assert isinstance(data["locked_baseline_quantity"], int)
    assert isinstance(data["unit_price_cents"], int)
    assert data["quantity"] >= data["locked_baseline_quantity"]


def assert_deployment(data: dict):
    _assert_common_mutable_fields(data)
    assert data["scope"] in ["USER", "DEVICE", "SERVER"]
    assert isinstance(data["retired"], bool)


def assert_snapshot(data: dict):
    # Append-only: id + created_at only; no updated_at/version exist.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data, "snapshots are append-only and carry no version field"
    assert "updated_at" not in data, "snapshots are append-only and carry no updated_at field"
    assert isinstance(data.get("lines"), list)


def assert_true_up_report(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["DRAFT", "SUBMITTED", "ACCEPTED", "REJECTED", "INVOICED", "SETTLED"]
    assert isinstance(data["total_amount_cents"], int)
    assert isinstance(data["revision_count"], int)


def assert_true_up_line(data: dict):
    _assert_common_mutable_fields(data)
    assert isinstance(data["growth_quantity"], int)
    assert isinstance(data["total_amount_cents"], int)
    assert data["pricing_variant"] in ["ANNIVERSARY_PRORATION", "FULL_YEAR_RETROACTIVE"]


def assert_benefit_grant(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["ACTIVE", "DEPLETED", "EXPIRED", "FORFEITED"]
    assert isinstance(data["quantity_granted"], int)
    assert isinstance(data["quantity_remaining"], int)


def assert_redemption(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data
    assert "updated_at" not in data


def assert_step_up_conversion(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["REQUESTED", "COMPLETED", "REJECTED"]
    assert isinstance(data["quantity"], int)
    assert isinstance(data["charge_cents"], int)


def assert_cloud_commitment(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["ACTIVE", "EXHAUSTED", "EXPIRED"]
    assert isinstance(data["committed_amount_cents"], int)
    assert isinstance(data["consumed_amount_cents"], int)


def assert_consumption_event(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data
    assert "updated_at" not in data


def assert_hosting_authorization(data: dict):
    _assert_common_mutable_fields(data)
    assert data["status"] in ["PENDING_REVIEW", "APPROVED", "DENIED", "SUSPENDED", "REVOKED"]


def assert_shortfall_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "version" not in data
    assert "updated_at" not in data
    assert isinstance(data.get("lines"), list)


def assert_grant_invariants(data: dict):
    """quantity_granted == quantity_remaining + redeemed units at all times."""
    assert data["quantity_remaining"] >= 0
    assert data["quantity_remaining"] <= data["quantity_granted"]
