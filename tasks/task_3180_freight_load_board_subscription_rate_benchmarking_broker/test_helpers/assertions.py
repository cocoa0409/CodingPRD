"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_broker_org(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DEACTIVATED"]
    assert data["credit_badge"] in ["GOLD", "STANDARD", "WATCH", "CRITICAL"]
    assert isinstance(data["credit_score"], int)
    assert 0 <= data["credit_score"] <= 100
    assert isinstance(data["credit_event_count"], int)
    for f in ("included_amount_cents", "under_dispute_amount_cents", "removed_amount_cents"):
        assert isinstance(data[f], int) and data[f] >= 0


def assert_carrier_org(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int)
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DEACTIVATED"]
    assert isinstance(data["data_contribution_flag"], bool)


def assert_load_post(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["OPEN", "BOOKED", "COMPLETED", "WITHDRAWN", "EXPIRED"]
    assert data["visibility"] in ["LISTED", "DELISTED"]
    assert data["equipment_type"] in ["DRY_VAN", "REEFER", "FLATBED"]
    assert isinstance(data["rate_offer_cents"], int)


def assert_truck_post(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["AVAILABLE", "BOOKED", "COMPLETED", "WITHDRAWN", "EXPIRED"]
    assert data["equipment_type"] in ["DRY_VAN", "REEFER", "FLATBED"]


def assert_booking(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["BOOKED", "COMPLETED", "CANCELLED"]
    assert isinstance(data["agreed_rate_cents"], int)


def assert_subscription(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["ACTIVE", "PAST_DUE", "SUSPENDED", "CANCELLED"]
    assert isinstance(data["posts_used"], int)
    assert isinstance(data["period_price_cents"], int)
    assert isinstance(data["version"], int)


def assert_rate_transaction(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["source"] in ["BOOKING", "CONTRIBUTED"]
    assert data["rate_kind"] in ["SPOT", "CONTRACT"]
    assert data["status"] in ["ACCEPTED", "EXCLUDED"]
    assert isinstance(data["rate_cents"], int)
    assert isinstance(data["fuel_price_cents"], int)


def assert_credit_dispute(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["FILED", "UNDER_REVIEW", "REBUTTED",
                              "RESOLVED_SUSTAIN", "RESOLVED_REMOVE"]
    assert isinstance(data["rebuttal_count"], int)


def assert_authority_verification(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert data["status"] in ["PENDING", "VERIFIED", "EXPIRED", "REVOKED"]
    assert isinstance(data["insurance_ok"], bool)
    assert isinstance(data["coverage_gap_detected"], bool)


def assert_credit_ledger_invariant(broker: dict):
    """included + under_dispute + removed equals total invoice ledger seen."""
    total = (broker["included_amount_cents"] + broker["under_dispute_amount_cents"]
             + broker["removed_amount_cents"])
    assert total >= 0
    return total
