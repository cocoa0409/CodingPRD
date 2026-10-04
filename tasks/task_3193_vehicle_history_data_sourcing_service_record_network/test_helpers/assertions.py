"""Entity assertions and domain invariant checkers."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict, entity_label: str):
    assert is_valid_uuid(data.get("id", "")), f"{entity_label}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), f"{entity_label}.created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), f"{entity_label}.updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), f"{entity_label}.version must be an integer"


def assert_network(data: dict):
    _assert_common_fields(data, "Network")
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["epoch_index"], int) and data["epoch_index"] >= 0
    assert isinstance(data["guarantee_payout_cap_cents"], int)
    assert isinstance(data["enrolled_listing_count"], int) and data["enrolled_listing_count"] >= 0


def assert_data_source(data: dict):
    _assert_common_fields(data, "DataSource")
    assert data["source_type"] in ["MVA", "INSURER", "AUCTION", "SERVICE_SHOP", "INSPECTION_STATION"]
    assert data["status"] in ["PENDING", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert isinstance(data["reliability_score"], int) and 0 <= data["reliability_score"] <= 100
    assert isinstance(data["consecutive_missed_epochs"], int)
    assert isinstance(data["record_rejection_streak"], int)


def assert_shop(data: dict):
    _assert_common_fields(data, "Shop")
    assert data["status"] in ["APPLIED", "ACTIVE", "SUSPENDED", "TERMINATED"]
    assert data["reporting_tool_tier"] in ["NONE", "BASIC", "PRO"]


def assert_vehicle(data: dict):
    _assert_common_fields(data, "Vehicle")
    assert data["canonical_brand"] in ["NONE", "CLEAN", "LEMON", "FLOOD", "REBUILT", "SALVAGE"]
    assert isinstance(data["brand_severity"], int) and 0 <= data["brand_severity"] <= 5
    assert isinstance(data["max_confirmed_accident_severity"], int)
    assert isinstance(data["active_record_count"], int) and data["active_record_count"] >= 0
    assert isinstance(data["superseded_record_count"], int) and data["superseded_record_count"] >= 0


def assert_history_record(data: dict):
    _assert_common_fields(data, "HistoryRecord")
    assert data["record_type"] in ["TITLE_BRAND", "ACCIDENT", "SERVICE", "INSPECTION"]
    assert data["status"] in ["ACTIVE", "SUPERSEDED", "WITHDRAWN", "VOIDED"]
    assert data["match_method"] in ["EXACT_VIN", "FUZZY_VIN"]
    if data["record_type"] == "ACCIDENT":
        assert isinstance(data["confidence_score"], int) and 0 <= data["confidence_score"] <= 100
        assert data["confidence_level"] in ["HIGH", "MEDIUM", "LOW", "UNRELIABLE"]


def assert_correction_request(data: dict):
    _assert_common_fields(data, "CorrectionRequest")
    assert data["status"] in ["OPEN", "AWAITING_SOURCE", "VERIFIED", "APPLIED", "REJECTED", "EXPIRED"]
    assert data["requester_role"] in ["OWNER", "SHOP"]


def assert_consumer(data: dict):
    _assert_common_fields(data, "ConsumerAccount")
    assert isinstance(data["credit_balance_cents"], int) and data["credit_balance_cents"] >= 0


def assert_dealer(data: dict):
    _assert_common_fields(data, "Dealer")
    assert data["subscription_tier"] in ["NONE", "STANDARD", "PRO"]
    assert data["status"] in ["ACTIVE", "SUSPENDED"]
    assert isinstance(data["period_reports_used"], int) and data["period_reports_used"] >= 0
    assert isinstance(data["invoice_balance_cents"], int) and data["invoice_balance_cents"] >= 0


def assert_listing(data: dict):
    _assert_common_fields(data, "InventoryListing")
    assert data["status"] in ["DRAFT", "PUBLISHED", "DELISTED"]
    assert data["guarantee_status"] in ["UNENROLLED", "ENROLLED", "VOIDED"]
    assert isinstance(data["asking_price_cents"], int) and data["asking_price_cents"] >= 0


def assert_claim(data: dict):
    _assert_common_fields(data, "GuaranteeClaim")
    assert data["status"] in ["OPEN", "APPROVED", "REJECTED", "DENIED", "PAID"]
    assert isinstance(data["payout_cents"], int) and data["payout_cents"] >= 0


def assert_report_order(data: dict):
    _assert_common_fields(data, "ReportOrder")
    assert data["product"] in ["CONSUMER_SINGLE", "DEALER_SUBSCRIPTION"]
    assert data["status"] == "CONFIRMED"
    assert isinstance(data["price_cents"], int) and data["price_cents"] >= 0
    assert isinstance(data["snapshot"], dict)


def assert_confidence_level_for_score(score: int, level: str):
    """Level bands: HIGH >= 85, MEDIUM >= 70, LOW >= 40, UNRELIABLE below 40."""
    if score >= 85:
        expected = "HIGH"
    elif score >= 70:
        expected = "MEDIUM"
    elif score >= 40:
        expected = "LOW"
    else:
        expected = "UNRELIABLE"
    assert level == expected, f"confidence_level {level} inconsistent with score {score} (expected {expected})"
