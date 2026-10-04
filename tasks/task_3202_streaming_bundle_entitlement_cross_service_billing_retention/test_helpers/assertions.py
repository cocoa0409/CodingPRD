"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict, with_version: bool):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), (
            f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
        )
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_plan(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "Plan must not expose updated_at"
    assert "version" not in data, "Plan must not expose version"
    assert isinstance(data["plan_code"], str) and data["plan_code"]
    assert data["plan_kind"] in ("STANDALONE", "BUNDLE")
    assert isinstance(data["service_scope"], list) and data["service_scope"]
    assert all(s in ("DPLUS", "HULU") for s in data["service_scope"])
    assert data["ad_tier"] in ("AD_SUPPORTED", "AD_FREE")
    assert isinstance(data["monthly_price_cents"], int)
    assert isinstance(data["allow_app_store_billing"], bool)
    assert isinstance(data["allow_distributor_billing"], bool)


def assert_subscriber_account(data: dict):
    _assert_common_fields(data, with_version=True)
    assert isinstance(data["email"], str) and data["email"]
    assert data["account_status"] in ("ACTIVE", "SUSPENDED", "CLOSED")
    assert data.get("grandfathered_price_cents") is None or isinstance(
        data["grandfathered_price_cents"], int
    )
    assert isinstance(data["retention_redemption_count"], int)
    assert isinstance(data["account_credit_cents"], int)


def assert_service_profile(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["service"] in ("DPLUS", "HULU")
    assert data["profile_status"] in ("LINKED", "SUSPENDED", "UNLINKED")
    assert data["maturity_rating_cap"] in ("TV_Y", "TV_G", "TV_PG", "TV_14", "TV_MA")
    assert isinstance(data["kids_mode"], bool)
    assert isinstance(data["watchlist_count"], int)


def assert_watchlist_item(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "WatchlistItem must not expose updated_at"
    assert "version" not in data, "WatchlistItem must not expose version"
    assert isinstance(data["title_id"], str) and data["title_id"]
    assert data["title_maturity"] in ("TV_Y", "TV_G", "TV_PG", "TV_14", "TV_MA")


def assert_billing_account(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["biller_type"] in ("PLATFORM", "APP_STORE", "DISTRIBUTOR")
    assert data["billing_status"] in ("CURRENT", "PAST_DUE", "HARD_FAILED")
    assert isinstance(data["consecutive_failure_count"], int)


def assert_subscription(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["lifecycle_status"] in (
        "PENDING_ENTITLEMENT", "ACTIVE", "PAST_DUE",
        "CANCEL_SCHEDULED", "CANCELLED", "MIGRATED_OUT",
    )
    assert data["billing_dimension"] in ("PAID_UP", "GRACE", "UNPAID")
    assert isinstance(data["price_cents"], int)
    assert isinstance(data["retention_discount_cents"], int)


def assert_entitlement(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["service"] in ("DPLUS", "HULU")
    assert data["entitlement_status"] in (
        "PROVISIONING", "ACTIVE", "SUSPENDED", "REVOKED"
    )
    assert isinstance(data["mismatch_flag"], bool)


def assert_migration(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["migration_status"] in ("QUOTED", "CONFIRMED", "VOIDED")
    assert isinstance(data["proration_credit_cents"], int)
    assert data["proration_method_used"] in (
        "CHRONOLOGICAL_REMAINING", "FORWARD_LOOKING_PERIOD"
    )


def assert_retention_offer(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "RetentionOffer must not expose updated_at"
    assert "version" not in data, "RetentionOffer must not expose version"
    assert isinstance(data["offer_code"], str) and data["offer_code"]
    assert isinstance(data["discount_cents"], int)
    assert isinstance(data["duration_months"], int)
    assert isinstance(data["max_redemptions_per_account"], int)
    assert data["offer_status"] in ("OPEN", "RETIRED")


def assert_retention_redemption(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["redemption_status"] in ("ACTIVE", "EXPIRED", "VOIDED")
    assert isinstance(data["months_remaining"], int)


def assert_invoice(data: dict):
    _assert_common_fields(data, with_version=True)
    assert data["invoice_status"] in ("ISSUED", "PAID", "FAILED", "VOIDED")
    assert data["invoice_kind"] in ("INITIAL", "RENEWAL", "MIGRATION_ADJUSTMENT")
    assert isinstance(data["gross_cents"], int)
    assert isinstance(data["credit_applied_cents"], int)
    assert isinstance(data["net_cents"], int)
    assert data["net_cents"] == data["gross_cents"] - data["credit_applied_cents"], (
        "net_cents must equal gross_cents - credit_applied_cents"
    )


def assert_revenue_allocation(data: dict):
    _assert_common_fields(data, with_version=False)
    assert "updated_at" not in data, "RevenueAllocation must not expose updated_at"
    assert "version" not in data, "RevenueAllocation must not expose version"
    assert data["service"] in ("DPLUS", "HULU")
    assert isinstance(data["allocated_cents"], int)


def assert_invoice_invariants(data: dict):
    """Invoice money invariants that must always hold (PRD §3.11)."""
    assert data["net_cents"] == data["gross_cents"] - data["credit_applied_cents"]
    assert data["credit_applied_cents"] >= 0
    assert data["net_cents"] >= 0
