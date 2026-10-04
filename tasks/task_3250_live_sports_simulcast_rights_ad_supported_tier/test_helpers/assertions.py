"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def assert_common_fields(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int) and data["version"] >= 1


def assert_property(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["NEGOTIATION", "ACTIVE", "SUSPENDED", "EXPIRED", "TERMINATED"]
    assert data["amortization_method"] in ["STRAIGHT_LINE", "EVENT_WEIGHTED"]
    assert isinstance(data["rights_fee_cents"], int) and data["rights_fee_cents"] >= 0
    assert isinstance(data["simulcast_windows_consumed"], int)
    assert isinstance(data["exclusive_windows_consumed"], int)
    assert isinstance(data["amortized_fee_cents"], int)


def assert_window(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["SCHEDULED", "LIVE", "COMPLETE", "REPLACED", "CANCELLED"]
    assert data["rights_mode"] in ["SIMULCAST", "EXCLUSIVE"]
    assert isinstance(data["territory_scope"], list) and len(data["territory_scope"]) > 0
    assert isinstance(data["capacity_required_units"], int) and data["capacity_required_units"] >= 1


def assert_territory_rule(data: dict):
    assert_common_fields(data)
    assert data["rule_kind"] in ["BLACKOUT", "OVERFLOW"]
    assert data["rule_status"] in ["ACTIVE", "LIFTED"]


def assert_viewer(data: dict):
    assert_common_fields(data)
    assert data["subscription_tier"] in ["FREE", "AD_SUPPORTED", "PREMIUM"]
    assert data["subscription_status"] in ["ACTIVE", "GRACE", "SUSPENDED", "CANCELLED"]


def assert_capacity_pool(data: dict):
    assert_common_fields(data)
    assert data["scope_kind"] in ["REGION", "EVENT"]
    assert isinstance(data["total_units"], int) and data["total_units"] >= 0
    assert isinstance(data["committed_units"], int) and data["committed_units"] >= 0
    assert 0 <= data["oversubscribe_pct"] <= 50


def assert_reservation(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["HELD", "CONFIRMED", "RELEASED", "EXPIRED"]
    assert isinstance(data["units"], int) and data["units"] >= 1


def assert_ad_campaign(data: dict):
    assert_common_fields(data)
    assert data["campaign_status"] in ["DRAFT", "BOOKED", "PAUSED", "COMPLETED"]
    assert isinstance(data["cpm_cents"], int) and data["cpm_cents"] >= 1


def assert_ad_slot(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["OPEN", "RESERVED", "FILLED", "UNFILLABLE", "CANCELLED"]
    assert data["slot_scope"] in ["NATIONAL", "LOCAL"]
    assert data["duration_seconds"] in (15, 30, 60)


def assert_partner(data: dict):
    assert_common_fields(data)
    assert data["partner_status"] in ["ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["bundled_tier"] in ["AD_SUPPORTED", "PREMIUM"]
    assert isinstance(data["codes_issued"], int) and data["codes_issued"] >= 0


def assert_promo_code(data: dict):
    assert_common_fields(data)
    assert data["code_status"] in ["ISSUED", "REDEEMED", "REVOKED", "EXPIRED"]
    assert isinstance(data["code"], str) and len(data["code"]) > 0


def assert_replay_asset(data: dict):
    assert_common_fields(data)
    assert data["status"] in ["AVAILABLE", "EXPIRED", "PULLED"]
    assert isinstance(data["replay_views"], int) and data["replay_views"] >= 0


def assert_view_grant(data: dict):
    # Append-only entity (PRD §2.4): no updated_at, no version.
    assert_common_fields(data, with_version=False)
    assert data["grant_type"] in ["LIVE", "REPLAY"]
    assert isinstance(data["revoked"], bool)


def assert_impression(data: dict):
    assert_common_fields(data, with_version=False)
    assert data["fill_source"] in ["NATIONAL", "LOCAL_INSERTION"]
    assert isinstance(data["revenue_cents"], int)


def assert_entitlement(data: dict):
    assert_common_fields(data, with_version=False)
    assert data["source_type"] in ["SUBSCRIPTION", "PARTNER_BUNDLE"]
    assert data["tier_granted"] in ["AD_SUPPORTED", "PREMIUM"]
    assert isinstance(data["active"], bool)


def assert_pool_conservation(pool: dict, reservations: list):
    """PRD §3.5 capacity conservation invariant: committed_units equals the
    sum of units over reservations currently in HELD or CONFIRMED."""
    expected = sum(
        r["units"] for r in reservations if r["status"] in ("HELD", "CONFIRMED")
    )
    assert pool["committed_units"] == expected, (
        f"committed_units {pool['committed_units']} != sum of live reservations {expected}"
    )
