"""Per-entity assertion helpers and domain invariant checkers."""

from prd_bench_local_runner.testing import (
    assert_cost_precision,
    is_iso8601_timestamp,
    is_valid_uuid,
)


def _assert_common_fields(data: dict, *, expect_version: bool = True) -> None:
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    if expect_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
        assert isinstance(data.get("version"), int), "version must be an integer"
        assert data["version"] >= 1, "version starts at 1"


def assert_organization(data: dict) -> None:
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["org_type"] in ("DATA_PROVIDER", "BROKERAGE", "SUBSCRIBER")
    assert isinstance(data["home_market"], str) and data["home_market"]
    assert data["service_tier"] in ("ENTERPRISE", "MID_MARKET", "SMB")
    assert data["status"] in ("ACTIVE", "SUSPENDED")
    assert isinstance(data["authorized_market_count"], int)
    assert isinstance(data["active_contract_count"], int)


def assert_user(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("organization_id", "")), "organization_id must be a UUID"
    assert isinstance(data["email"], str) and data["email"]
    assert isinstance(data["full_name"], str) and data["full_name"]
    assert data["role"] in (
        "RESEARCH_ANALYST",
        "SEAT_USER",
        "LICENSING_ADMIN",
        "ENFORCEMENT_OFFICER",
        "BROKER_PUBLISHER",
    )
    assert data["status"] in ("ACTIVE", "INACTIVE")


def assert_property(data: dict) -> None:
    _assert_common_fields(data)
    assert data["property_type"] in (
        "OFFICE", "RETAIL", "INDUSTRIAL", "MULTIFAMILY", "HOSPITALITY",
    )
    assert data["classification"] in ("CLASS_A", "CLASS_B", "CLASS_C")
    assert data["research_status"] in ("DRAFT", "RESEARCHING", "VERIFIED")
    assert data["land_posture"] in ("OPEN", "RESTRICTED", "FROZEN")
    assert isinstance(data["rentable_sqft"], int) and data["rentable_sqft"] > 0
    assert isinstance(data["attribute_total_count"], int)
    assert isinstance(data["attribute_verified_count"], int)
    assert isinstance(data["stale_source_count"], int)
    assert isinstance(data["verified_sale_value_cents"], int)
    assert_cost_precision(float(data["completeness_pct"]), 2)


def assert_property_invariants(data: dict) -> None:
    """Counters that must hold after any research mutation."""
    assert data["attribute_total_count"] >= 0
    assert data["attribute_verified_count"] >= 0
    assert data["attribute_verified_count"] <= data["attribute_total_count"]
    assert data["stale_source_count"] >= 0
    assert data["verified_sale_value_cents"] >= 0
    assert 0.0 <= float(data["completeness_pct"]) <= 100.0


def assert_source_document(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert data["source_type"] in (
        "DEED", "PUBLIC_RECORD", "DIRECT_CONTACT", "BROKER_LISTING", "THIRD_PARTY_FEED",
    )
    assert data["contact_method"] in (
        "PHONE", "EMAIL", "SITE_VISIT", "RECORDS_REQUEST", "FEED_IMPORT",
    )
    assert data["source_classification"] in ("FIRST_PARTY", "THIRD_PARTY_LICENSED")
    assert is_iso8601_timestamp(data["obtained_at"])


def assert_property_attribute(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert isinstance(data["field_name"], str) and data["field_name"]
    assert data["proposed_status"] in ("NONE", "PENDING", "VERIFIED", "REJECTED")
    assert isinstance(data["revision_index"], int) and data["revision_index"] >= 1
    assert isinstance(data["from_third_party"], bool)
    assert isinstance(data["third_party_approved"], bool)


def assert_lease_comparable(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert is_iso8601_timestamp(data["lease_start"])
    assert is_iso8601_timestamp(data["lease_end"])
    assert isinstance(data["effective_rent_psf"], (int, float))
    assert isinstance(data["escalated_rent_psf"], (int, float))
    assert isinstance(data["renewal_option"], bool)


def assert_sale_transaction(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert isinstance(data["gross_sale_price_cents"], int)
    assert data["subordination_status"] in ("PENDING", "SUBORDINATED", "LAPSED")
    assert isinstance(data["cap_rate_bps"], int)
    assert isinstance(data["rolled_attributions"], int)
    assert is_iso8601_timestamp(data["subordination_deadline"])


def assert_licensing_contract(data: dict) -> None:
    _assert_common_fields(data)
    assert data["product"] in (
        "CORE_MARKET_DATA", "ANALYTICS_INDEX", "LISTING_SERVICE", "GLOBAL_ALL",
    )
    assert isinstance(data["licensed_markets"], list)
    assert data["status"] in (
        "PENDING", "ACTIVE", "GRACE", "RENEWED", "LAPSED", "TERMINATED",
    )
    assert data["renewal_decision"] in ("NONE", "FAILED", "TERMINATED")
    assert data["audit_intensity"] in ("STANDARD", "ENHANCED")
    assert isinstance(data["seat_count"], int) and data["seat_count"] >= 1
    assert isinstance(data["annual_fee_cents"], int)
    assert is_iso8601_timestamp(data["renewal_due_at"])
    assert data["term_end"] > data["term_start"], "term_end must be after term_start"


def assert_license_seat(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("contract_id", "")), "contract_id must be a UUID"
    assert data["index_tier"] in ("TIER_1", "TIER_2", "TIER_3")
    assert isinstance(data["monthly_active_days"], int)
    assert isinstance(data["monthly_unauthorized_markets"], list)
    assert isinstance(data["distinctive_ip_count"], int)
    assert isinstance(data["shared_flag"], bool)
    assert isinstance(data["access_revoked"], bool)
    assert isinstance(data["overage_fee_cents"], int) and data["overage_fee_cents"] >= 0
    assert_cost_precision(float(data["owner_share_pct"]), 2)
    assert_cost_precision(float(data["billed_owner_share_pct"]), 2)


def assert_usage_event(data: dict) -> None:
    # Immutable ledger entry: only id and created_at, no updated_at/version.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "UsageEvent must not carry updated_at"
    assert "version" not in data, "UsageEvent must not carry version"
    assert data["event_type"] in (
        "DATASET_DOWNLOAD", "REPORT_EXPORT", "BULK_LOOKUP", "API_QUERY",
    )
    assert isinstance(data["record_count"], int) and data["record_count"] >= 0


def assert_enforcement_case(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("organization_id", "")), "organization_id must be a UUID"
    assert data["case_type"] in ("AUDIT", "LITIGATION")
    assert data["status"] in ("OPEN", "ESCALATED", "SETTLED", "WITHDRAWN")
    assert isinstance(data["finding_cents"], int)
    assert isinstance(data["penalty_cents"], int)


def assert_analytics_run(data: dict) -> None:
    _assert_common_fields(data)
    assert data["run_type"] in ("INDEX", "FORECAST")
    assert data["adjustment_mode"] in ("UNADJUSTED", "HEDONIC")
    assert data["attribution_status"] in ("ATTRIBUTED", "UNWOUND")
    assert isinstance(data["comp_count"], int)
    assert isinstance(data["attributed_records_delta"], int)


def assert_listing(data: dict) -> None:
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("property_id", "")), "property_id must be a UUID"
    assert data["listing_type"] in ("AVAILABLE", "LEASED", "SOLD")
    assert data["status"] in ("DRAFT", "PUBLISHED", "WITHDRAWN", "EXPIRED")
    assert isinstance(data["available_sqft"], int)
    assert isinstance(data["redistributed_markets"], list)


def assert_pagination_meta(
    meta: dict,
    *,
    total_count: int,
    limit: int,
    offset: int,
    has_more: bool,
) -> None:
    assert meta["total_count"] == total_count, (
        f"Expected total_count {total_count}, got {meta['total_count']}"
    )
    assert meta["limit"] == limit, f"Expected limit {limit}, got {meta['limit']}"
    assert meta["offset"] == offset, f"Expected offset {offset}, got {meta['offset']}"
    assert meta["has_more"] is has_more, (
        f"Expected has_more {has_more}, got {meta['has_more']}"
    )


def assert_half_up_cents(value: int, expected: int) -> None:
    """Round-half-up monetary assertion on an integer number of cents."""
    assert int(value) == int(expected), f"Expected {expected} cents, got {value}"