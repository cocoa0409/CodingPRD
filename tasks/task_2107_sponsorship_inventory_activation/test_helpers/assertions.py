"""Resource assertions and domain invariant checkers."""

from datetime import datetime, timezone

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

from .types import (
    ASSET_CLASSES,
    BOOKING_STATUSES,
    CONTRACT_STATUSES,
    ENTITLEMENT_STATUSES,
    FULFILLMENT_STATUSES,
    PROOF_STATES,
    PROPERTY_STATUSES,
)


# --------------------------------------------------------------------------
# Shared field checks
# --------------------------------------------------------------------------
def assert_common_fields(data: dict, label: str = "resource") -> None:
    """Resources that are mutated carry id, created_at, updated_at and version."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID with no type prefix, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{label}.updated_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{label}.version must be an integer of at least 1, got {data.get('version')!r}"
    )


def assert_write_once_fields(data: dict, label: str = "resource") -> None:
    """Write-once resources carry only id and created_at."""
    assert is_valid_uuid(data.get("id", "")), (
        f"{label}.id must be a bare UUID, got {data.get('id')!r}"
    )
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{label}.created_at must be an ISO 8601 UTC timestamp, "
        f"got {data.get('created_at')!r}"
    )
    assert "updated_at" not in data, (
        f"{label} is written once and must never return updated_at"
    )
    assert "version" not in data, (
        f"{label} is written once and must never return version"
    )


def parse_instant(value: str) -> datetime:
    """Parse an ISO 8601 UTC instant returned by the API."""
    assert isinstance(value, str) and value, f"expected an instant, got {value!r}"
    normalised = value.replace("Z", "+00:00")
    parsed = datetime.fromisoformat(normalised)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def assert_instant_equals(actual: str, expected: str, label: str = "instant") -> None:
    """Assert two ISO 8601 instants denote the same moment."""
    assert parse_instant(actual) == parse_instant(expected), (
        f"{label}: expected the instant {expected}, got {actual}"
    )


def assert_whole_cents(value, label: str = "value") -> None:
    """Monetary quantities are integer counts of cents."""
    assert isinstance(value, (int, float)) and not isinstance(value, bool), (
        f"{label} must be a numeric count of cents, got {value!r}"
    )
    assert float(value).is_integer(), (
        f"{label} must be a whole number of cents, got {value}"
    )


def assert_two_decimals(value, label: str = "value") -> None:
    assert isinstance(value, (int, float)), f"{label} must be numeric, got {value!r}"
    assert round(float(value), 2) == float(value), (
        f"{label} must carry at most 2 decimal places, got {value}"
    )


# --------------------------------------------------------------------------
# Per-resource assertions
# --------------------------------------------------------------------------
def assert_property(data: dict) -> None:
    assert_common_fields(data, "Property")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["sport_code"] in (
        "FOOTBALL", "BASKETBALL", "SOCCER", "HOCKEY", "BASEBALL"
    )
    assert isinstance(data["season_year"], int) and 2020 <= data["season_year"] <= 2100
    assert is_iso8601_timestamp(data["season_start"])
    assert is_iso8601_timestamp(data["season_end"])
    assert parse_instant(data["season_end"]) > parse_instant(data["season_start"]), (
        "season_end must be strictly after season_start"
    )
    assert data["status"] in PROPERTY_STATUSES
    assert 0.50 <= float(data["seasonality_index"]) <= 2.00
    assert_whole_cents(
        data["inventory_target_value_cents"],
        "Property.inventory_target_value_cents",
    )
    assert data["inventory_target_value_cents"] >= 0
    assert_whole_cents(
        data["committed_gross_value_cents"],
        "Property.committed_gross_value_cents",
    )
    assert_whole_cents(
        data["delivered_media_value_cents"],
        "Property.delivered_media_value_cents",
    )
    assert_two_decimals(data["sellout_pct"], "Property.sellout_pct")


def assert_rate_card(data: dict) -> None:
    assert_common_fields(data, "RateCard")
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["label"], str) and 1 <= len(data["label"]) <= 80
    assert isinstance(data["effective_year"], int)
    assert data["status"] in ("DRAFT", "PUBLISHED", "SUPERSEDED")
    assert isinstance(data["line_count"], int) and data["line_count"] >= 0
    if data["status"] == "DRAFT":
        assert data.get("published_at") is None, "a DRAFT card has published_at null"
    else:
        assert is_iso8601_timestamp(data.get("published_at", ""))


def assert_rate_card_line(data: dict) -> None:
    assert_write_once_fields(data, "RateCardLine")
    assert is_valid_uuid(data["rate_card_id"])
    assert data["asset_class"] in ASSET_CLASSES
    assert_whole_cents(
        data["base_unit_price_cents"], "RateCardLine.base_unit_price_cents"
    )
    assert data["base_unit_price_cents"] >= 1
    assert isinstance(data["tier_breaks"], list) and len(data["tier_breaks"]) <= 5
    assert 1.00 <= float(data["exclusivity_multiplier"]) <= 2.00


def assert_inventory_asset(data: dict) -> None:
    assert_common_fields(data, "InventoryAsset")
    assert is_valid_uuid(data["property_id"])
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["asset_class"] in ASSET_CLASSES
    assert isinstance(data["capacity_units"], int) and data["capacity_units"] >= 1
    assert 0 <= data["changeover_buffer_minutes"] <= 240
    assert isinstance(data["requires_staffing"], bool)
    assert 0 <= data["min_staff_count"] <= 20
    assert data["status"] in ("AVAILABLE", "MAINTENANCE", "RETIRED")
    assert isinstance(data["reserved_units_total"], int)
    assert data["reserved_units_total"] >= 0


def assert_sponsor(data: dict) -> None:
    assert_common_fields(data, "Sponsor")
    assert isinstance(data["name"], str) and 1 <= len(data["name"]) <= 120
    assert data["category"] in (
        "BEVERAGE", "AUTOMOTIVE", "FINANCIAL", "TELECOM", "APPAREL", "TECH"
    )
    assert "@" in data["contact_email"]
    assert data["status"] in ("PROSPECT", "ACTIVE", "CHURNED")
    assert_two_decimals(
        data["renewal_likelihood_score"], "Sponsor.renewal_likelihood_score"
    )
    assert 0 <= float(data["renewal_likelihood_score"]) <= 100
    assert data["renewal_band"] in ("LOW", "MEDIUM", "HIGH")


def assert_contract(data: dict) -> None:
    assert_common_fields(data, "Contract")
    assert is_valid_uuid(data["sponsor_id"])
    assert is_valid_uuid(data["property_id"])
    assert data["status"] in CONTRACT_STATUSES
    assert data["fulfillment_status"] in FULFILLMENT_STATUSES
    assert is_iso8601_timestamp(data["term_start"])
    assert is_iso8601_timestamp(data["term_end"])
    assert parse_instant(data["term_end"]) > parse_instant(data["term_start"])
    assert data["exclusivity_scope"] in ("NONE", "CATEGORY")
    assert data["in_kind_category"] in (
        "MEDIA_TRADE", "PRODUCT", "SERVICES", "TICKETS"
    )
    for money_field in (
        "in_kind_declared_value_cents",
        "gross_entitlement_value_cents",
        "cash_value_cents",
        "in_kind_recognized_value_cents",
        "total_recognized_value_cents",
        "delivered_media_value_cents",
        "makegood_credit_cents",
    ):
        assert_whole_cents(data[money_field], f"Contract.{money_field}")
        assert data[money_field] >= 0
    assert_two_decimals(
        data["volume_discount_pct"], "Contract.volume_discount_pct"
    )
    assert isinstance(data["revision_round"], int) and data["revision_round"] >= 0


def assert_entitlement(data: dict) -> None:
    assert_common_fields(data, "Entitlement")
    assert is_valid_uuid(data["contract_id"])
    assert is_valid_uuid(data["inventory_asset_id"])
    assert isinstance(data["clause_ref"], str) and 1 <= len(data["clause_ref"]) <= 24
    assert data["asset_class"] in ASSET_CLASSES
    assert isinstance(data["promised_units"], int) and data["promised_units"] >= 1
    assert_whole_cents(data["unit_value_cents"], "Entitlement.unit_value_cents")
    assert_whole_cents(data["gross_value_cents"], "Entitlement.gross_value_cents")
    assert isinstance(data["delivered_units"], int) and data["delivered_units"] >= 0
    assert_two_decimals(data["delivery_pct"], "Entitlement.delivery_pct")
    assert data["status"] in ENTITLEMENT_STATUSES
    assert_whole_cents(
        data["makegood_credit_cents"], "Entitlement.makegood_credit_cents"
    )


def assert_asset_booking(data: dict) -> None:
    assert_common_fields(data, "AssetBooking")
    assert is_valid_uuid(data["entitlement_id"])
    assert is_valid_uuid(data["inventory_asset_id"])
    assert is_iso8601_timestamp(data["window_start"])
    assert is_iso8601_timestamp(data["window_end"])
    assert parse_instant(data["window_end"]) > parse_instant(data["window_start"])
    assert isinstance(data["units_booked"], int) and data["units_booked"] >= 1
    assert data["status"] in BOOKING_STATUSES
    assert data["proof_state"] in PROOF_STATES
    assert isinstance(data["verified_impressions"], int)
    assert data["verified_impressions"] >= 0


def assert_proof_of_performance(data: dict) -> None:
    assert_common_fields(data, "ProofOfPerformance")
    assert is_valid_uuid(data["asset_booking_id"])
    assert data["evidence_type"] in ("PHOTO", "IMPRESSIONS", "SOCIAL")
    assert isinstance(data["measured_value"], int) and data["measured_value"] >= 0
    if data["evidence_type"] == "PHOTO":
        assert data["measured_value"] == 0, "PHOTO evidence measures nothing"
    assert data["status"] in ("SUBMITTED", "VERIFIED", "REJECTED")
    assert isinstance(data["captured_by_user_id"], str)
    assert data["captured_by_user_id"]


def assert_staff_member(data: dict) -> None:
    assert_common_fields(data, "StaffMember")
    assert isinstance(data["full_name"], str) and 1 <= len(data["full_name"]) <= 120
    assert_whole_cents(data["hourly_rate_cents"], "StaffMember.hourly_rate_cents")
    assert data["hourly_rate_cents"] >= 0
    assert data["status"] in ("ACTIVE", "INACTIVE")
    assert isinstance(data["scheduled_minutes"], int)
    assert data["scheduled_minutes"] >= 0


def assert_staff_assignment(data: dict) -> None:
    assert_common_fields(data, "StaffAssignment")
    assert is_valid_uuid(data["asset_booking_id"])
    assert is_valid_uuid(data["staff_member_id"])
    assert is_iso8601_timestamp(data["shift_start"])
    assert is_iso8601_timestamp(data["shift_end"])
    assert parse_instant(data["shift_end"]) > parse_instant(data["shift_start"])
    assert isinstance(data["role_label"], str) and 1 <= len(data["role_label"]) <= 60
    assert data["status"] in ("ASSIGNED", "CHECKED_IN", "NO_SHOW", "RELEASED")


def assert_sponsor_survey(data: dict) -> None:
    assert_write_once_fields(data, "SponsorSurvey")
    assert is_valid_uuid(data["contract_id"])
    for score_field in (
        "satisfaction_score",
        "activation_quality_score",
        "reporting_quality_score",
    ):
        assert isinstance(data[score_field], int)
        assert 1 <= data[score_field] <= 10
    assert data["renewal_intent"] in ("NO", "MAYBE", "YES")
    assert isinstance(data["submitted_by_user_id"], str)
    assert_two_decimals(data["composite_score"], "SponsorSurvey.composite_score")
    assert 0 <= float(data["composite_score"]) <= 100


def assert_roi_report(data: dict) -> None:
    assert is_valid_uuid(data["contract_id"])
    assert data["basis"] in ("VERIFIED", "GROSS")
    assert_whole_cents(data["media_value_cents"], "media_value_cents")
    assert isinstance(data["impressions_total"], int)
    assert isinstance(data["roi_ratio"], (int, float))
    assert round(float(data["roi_ratio"]), 4) == float(data["roi_ratio"]), (
        "roi_ratio carries at most 4 decimal places"
    )
    assert_two_decimals(data["roo_attainment_pct"], "roo_attainment_pct")
    assert_whole_cents(data["makegood_credit_cents"], "makegood_credit_cents")
    cpm = data["cost_per_thousand_impressions_cents"]
    if data["impressions_total"] == 0:
        assert cpm is None, (
            "cost_per_thousand_impressions_cents is null when impressions_total is 0"
        )
    else:
        assert_two_decimals(cpm, "cost_per_thousand_impressions_cents")


# --------------------------------------------------------------------------
# Domain invariants
# --------------------------------------------------------------------------
def assert_reserved_units_total(asset: dict, expected: int) -> None:
    """reserved_units_total is the sum of units_booked over SCHEDULED bookings."""
    assert asset["reserved_units_total"] == expected, (
        f"Expected reserved_units_total {expected}, got "
        f"{asset['reserved_units_total']} on asset {asset['id']}"
    )


def assert_scheduled_minutes(staff_member: dict, expected: int) -> None:
    """scheduled_minutes totals the ASSIGNED and CHECKED_IN shifts of a staffer."""
    assert staff_member["scheduled_minutes"] == expected, (
        f"Expected scheduled_minutes {expected}, got "
        f"{staff_member['scheduled_minutes']} on staffer {staff_member['id']}"
    )


def assert_contract_money_consistency(contract: dict) -> None:
    """total_recognized_value_cents is cash plus the recognized in-kind leg."""
    assert (
        contract["total_recognized_value_cents"]
        == contract["cash_value_cents"] + contract["in_kind_recognized_value_cents"]
    ), (
        "total_recognized_value_cents must equal cash_value_cents plus "
        "in_kind_recognized_value_cents"
    )
