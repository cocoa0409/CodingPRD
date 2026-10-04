"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import (
    is_iso8601_timestamp,
    is_valid_uuid,
)

TIERS = ["GLOBAL_SELECT", "GLOBAL", "CAPITAL"]


def assert_issuer(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert isinstance(data["legal_name"], str) and len(data["legal_name"]) > 0
    assert isinstance(data["ticker_symbol"], str) and len(data["ticker_symbol"]) > 0
    assert data["status"] in ["PRE_LISTING", "LISTED", "DELISTED"]
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_listing_application(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert data["target_tier"] in TIERS
    assert isinstance(data["is_transfer_from_exchange"], bool)
    assert data["application_kind"] in ["INITIAL", "TRANSFER", "TIER_TRANSFER", "READMISSION"]
    assert isinstance(data["board_directors"], list)
    assert isinstance(data["audit_committee"], list)
    assert isinstance(data["compensation_committee"], list)
    assert isinstance(data["stockholders_equity_cents"], int)
    assert isinstance(data["evaluated_standards"], list)
    assert data["status"] in ["DRAFT", "SUBMITTED", "APPROVED", "REJECTED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_listing(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert is_valid_uuid(data.get("application_id", "")), "application_id must be valid UUID"
    assert data["tier"] in TIERS
    assert data["status"] in ["ACTIVE", "SUSPENDED", "DELISTED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_snapshot(data: dict):
    """Append-only observation log: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["trade_date"], str)
    assert isinstance(data["closing_bid_cents"], int)
    assert isinstance(data["market_value_publicly_held_cents"], int)
    assert isinstance(data["market_value_listed_securities_cents"], int)
    assert isinstance(data["round_lot_holders"], int)
    assert isinstance(data["total_shareholders"], int)
    assert "version" not in data, "append-only snapshot must not carry version"
    assert "updated_at" not in data, "append-only snapshot must not carry updated_at"


def assert_deficiency(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert data["standard_code"] in [
        "BID_PRICE", "MVPHS", "MVLS",
        "ROUND_LOT_HOLDERS", "TOTAL_SHAREHOLDERS", "STOCKHOLDERS_EQUITY",
    ]
    assert data["tier_at_detection"] in TIERS
    assert isinstance(data["consecutive_days_failed"], int)
    assert is_iso8601_timestamp(data.get("detected_at", ""))
    assert is_iso8601_timestamp(data.get("compliance_due_at", ""))
    assert isinstance(data["still_open"], bool)
    assert data["status"] in [
        "OPEN", "PLAN_SUBMITTED", "REGAINED", "STAFF_DELIST_DETERMINED",
        "PANEL_REVIEW", "DELIST_UPHELD", "DELIST_REVERSED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_compliance_record(data: dict):
    """Append-only event log: id + created_at only, no version/updated_at."""
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("deficiency_id", "")), "deficiency_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("regained_at", ""))
    assert isinstance(data["qualifying_days"], int) and data["qualifying_days"] >= 0
    assert data["method"] in ["NATURAL", "REVERSE_SPLIT", "TIER_TRANSFER", "PLAN_APPROVED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert "version" not in data, "append-only record must not carry version"
    assert "updated_at" not in data, "append-only record must not carry updated_at"


def assert_compliance_plan(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert is_valid_uuid(data.get("deficiency_id", "")), "deficiency_id must be valid UUID"
    assert isinstance(data["plan_text"], str)
    assert data["plan_kind"] in ["CURE_IN_PLACE", "TIER_TRANSFER"]
    assert data["status"] in ["PENDING_REVIEW", "APPROVED", "REJECTED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_hearings_review(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert isinstance(data["panel_name"], str) and len(data["panel_name"]) > 0
    assert data["status"] in ["OPEN", "CLOSED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_appeal(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert is_valid_uuid(data.get("deficiency_id", "")), "deficiency_id must be valid UUID"
    assert is_valid_uuid(data.get("review_id", "")), "review_id must be valid UUID"
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert data.get("decided_by") in [None, "PANEL", "COUNCIL"]
    assert data["status"] in [
        "FILED", "PANEL_REVIEWING", "PANEL_AFFIRMED", "PANEL_REVERSED",
        "COUNCIL_REVIEWING", "COUNCIL_AFFIRMED", "COUNCIL_REVERSED",
    ]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_fee_assessment(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert data["fee_kind"] in ["ENTRY", "ANNUAL"]
    assert data["tier"] in TIERS
    assert isinstance(data["assessment_year"], int)
    assert isinstance(data["shares_outstanding"], int) and data["shares_outstanding"] >= 1
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] >= 0
    assert isinstance(data["delisted_mid_year"], bool)
    assert data["status"] in ["PENDING", "INVOICED", "PAID", "WAIVED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1


def assert_corporate_action(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be valid UUID"
    assert is_valid_uuid(data.get("issuer_id", "")), "issuer_id must be valid UUID"
    assert data["action_type"] == "REVERSE_SPLIT"
    assert isinstance(data["split_ratio_denominator"], int) and data["split_ratio_denominator"] >= 2
    assert is_iso8601_timestamp(data.get("announced_at", ""))
    assert data["status"] in ["SUBMITTED", "EFFECTIVE", "REJECTED", "CANCELLED"]
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert isinstance(data["version"], int) and data["version"] >= 1
