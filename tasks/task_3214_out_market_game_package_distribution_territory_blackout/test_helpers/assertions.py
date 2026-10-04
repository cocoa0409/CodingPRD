"""Entity assertions and domain invariant checkers.

Each assert_* validates the response shape of one entity against the fields
the PRD names. Append-only entities (Payment, TerritoryCheck) assert the
absence of updated_at/version per the PRD's common-fields exception.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"{entity_name}.updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"{entity_name}.version must be an int >= 1"
    )


def _assert_append_only_fields(data, entity_name):
    assert is_valid_uuid(data.get("id", "")), f"{entity_name}.id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"{entity_name}.created_at must be ISO 8601"
    )
    assert "updated_at" not in data, f"{entity_name} is append-only: no updated_at"
    assert "version" not in data, f"{entity_name} is append-only: no version"


def assert_rights_grant(data):
    _assert_common_fields(data, "RightsGrant")
    assert data["status"] in ["ACTIVE", "EXPIRED", "TERMINATED"]
    assert data["scope"] == "OUT_OF_MARKET"
    assert data["exclusivity"] in ["EXCLUSIVE", "NON_EXCLUSIVE"]
    assert isinstance(data["max_commercial_occupancy_cap"], int)
    assert data["max_commercial_occupancy_cap"] > 0


def assert_season(data):
    _assert_common_fields(data, "Season")
    assert data["phase"] in ["PRE_SALE", "REGULAR", "POST"]
    assert 1 <= data["regular_season_weeks"] <= 22
    assert 0 <= data["grace_days"] <= 30
    assert 0 <= data["student_discount_pct"] <= 90


def assert_market(data):
    _assert_common_fields(data, "Market")
    assert isinstance(data["code"], str) and len(data["code"]) > 0
    assert isinstance(data["zip_prefixes"], list) and len(data["zip_prefixes"]) > 0
    assert isinstance(data["home_team_codes"], list)


def assert_game(data):
    _assert_common_fields(data, "Game")
    assert isinstance(data["week_index"], int) and data["week_index"] >= 1
    assert data["away_team_code"] != data["home_team_code"]


def assert_week_slate(data):
    _assert_common_fields(data, "WeekSlate")
    assert data["slate_status"] in ["PRELIMINARY", "FINALIZED", "LOCKED"]
    assert isinstance(data["national_game_ids"], list)
    assert isinstance(data["finalized_game_ids"], list)
    assert isinstance(data["package_game_count"], int) and data["package_game_count"] >= 0


def assert_offer(data):
    _assert_common_fields(data, "Offer")
    assert data["plan_tier"] in ["BASE", "PREMIUM", "STUDENT"]
    assert isinstance(data["base_price_cents"], int) and data["base_price_cents"] > 0
    assert data["status"] in ["ACTIVE", "WITHDRAWN"]


def assert_account(data):
    _assert_common_fields(data, "Account")
    assert data["account_kind"] in ["RESIDENTIAL", "COMMERCIAL"]
    assert data["status"] in ["ACTIVE", "SUSPENDED", "CLOSED"]
    assert isinstance(data["billing_zip"], str) and len(data["billing_zip"]) == 5


def assert_student_verification(data):
    _assert_common_fields(data, "StudentVerification")
    assert data["status"] in ["VERIFIED", "EXPIRED", "REVOKED"]
    assert data["verification_method"] in ["SHEERID", "DOCUMENT_REVIEW"]


def assert_venue_license(data):
    _assert_common_fields(data, "VenueLicense")
    assert data["status"] in ["PENDING", "CERTIFIED", "SUSPENDED", "REVOKED"]
    assert isinstance(data["fire_code_occupancy"], int) and data["fire_code_occupancy"] > 0


def assert_subscription(data):
    _assert_common_fields(data, "Subscription")
    assert data["status"] in ["PENDING_PAYMENT", "ACTIVE", "CANCELLED", "EXPIRED"]
    assert data["entitlement_state"] in ["ENABLED", "SUSPENDED", "REVOKED"]
    assert data["plan_tier"] in ["BASE", "PREMIUM", "STUDENT"]
    assert isinstance(data["price_charged_cents"], int) and data["price_charged_cents"] >= 0
    assert isinstance(data["paid_amount_cents"], int) and data["paid_amount_cents"] >= 0
    assert isinstance(data["purchase_week_index"], int) and data["purchase_week_index"] >= 1


def assert_payment(data):
    _assert_append_only_fields(data, "Payment")
    assert data["kind"] in ["CHARGE", "REFUND"]
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0


def assert_territory_check(data):
    _assert_append_only_fields(data, "TerritoryCheck")
    assert data["verdict"] in ["AVAILABLE", "BLACKED_OUT", "NOT_IN_PACKAGE", "NO_ENTITLEMENT"]
    assert is_iso8601_timestamp(data.get("checked_at", "")), (
        "TerritoryCheck.checked_at must be ISO 8601"
    )


def assert_game_entitlement(data):
    _assert_common_fields(data, "GameEntitlement")
    assert data["status"] in ["GRANTED", "WITHDRAWN", "BLACKED_OUT"]


def assert_complaint_case(data):
    _assert_common_fields(data, "ComplaintCase")
    assert data["status"] in ["OPEN", "APPROVED_REFUND", "DENIED", "ESCALATED"]
    assert data["category"] in ["BLACKOUT_DISPUTE", "BILLING", "QUALITY"]
    assert isinstance(data["refund_amount_cents"], int) and data["refund_amount_cents"] >= 0


def assert_entitlement_override(data):
    _assert_common_fields(data, "EntitlementOverride")
    assert data["status"] in ["ACTIVE", "RESCINDED"]
    assert data["reason_code"] in ["GOODWILL", "SERVICE_OUTAGE", "REGULATORY"]
    assert isinstance(data["created_by"], str) and len(data["created_by"]) > 0


def assert_ledger_conservation(charge_sum, refund_sum, paid_amount_cents):
    """paid_amount_cents must equal signed ledger sum (CHARGE minus REFUND)."""
    assert paid_amount_cents == charge_sum - refund_sum, (
        f"ledger conservation violated: paid_amount_cents {paid_amount_cents} != "
        f"{charge_sum} - {refund_sum}"
    )
