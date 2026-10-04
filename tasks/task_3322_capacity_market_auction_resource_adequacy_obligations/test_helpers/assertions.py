"""Entity assertions and domain invariant checkers.

Field checks reference PRD §2.2 (envelope), §2.4 (common resource properties)
and the per-resource field semantics of §3.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common(data: dict, with_version: bool = True):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be an ISO 8601 timestamp"
    if with_version:
        assert is_iso8601_timestamp(data.get("updated_at", "")), \
            "updated_at must be an ISO 8601 timestamp"
        assert isinstance(data.get("version"), int), "version must be an integer"
    else:
        assert "updated_at" not in data, "append-only record must not carry updated_at"
        assert "version" not in data, "append-only record must not carry version"


def assert_delivery_year(data: dict):
    _assert_common(data)
    assert isinstance(data["delivery_year_label"], str)
    assert data["status"] in [
        "DRAFT", "FORECAST_LOCKED", "AUCTION_OPEN", "CLEARED", "SETTLED", "CLOSED",
    ]
    assert isinstance(data["reliability_requirement_mw"], (int, float))
    assert isinstance(data["forecast_version"], int)


def assert_zone(data: dict):
    _assert_common(data)
    assert isinstance(data["zone_code"], str)
    assert data["delivery_year_id"]
    assert "parent_zone_id" in data
    assert "import_limit_mw" in data
    assert "clearing_price_per_mw_day" in data
    assert isinstance(data["zonal_requirement_mw"], (int, float))
    assert isinstance(data["cleared_mw"], (int, float))


def assert_load_forecast(data: dict):
    _assert_common(data)
    assert isinstance(data["revision"], int) and data["revision"] >= 1
    assert data["status"] in ["DRAFT", "LOCKED", "SUPERSEDED"]
    assert isinstance(data["rto_peak_load_mw"], (int, float))
    assert isinstance(data["reserve_margin_pct"], (int, float))
    assert isinstance(data["pool_wide_avg_eford"], (int, float))


def assert_owner(data: dict):
    _assert_common(data)
    assert isinstance(data["legal_name"], str)
    assert "@" in data["contact_email"]
    assert 0 <= data["credit_score"] <= 1000
    assert data["status"] in ["ACTIVE", "SUSPENDED"]


def assert_resource(data: dict):
    _assert_common(data)
    assert data["resource_type"] in ["GEN", "DR", "EE"]
    assert data["status"] in ["REGISTERED", "ACCREDITED", "RETIRED"]
    assert data["nameplate_mw"] > 0
    assert isinstance(data["accredited_ucap_mw"], (int, float))
    assert isinstance(data["must_offer"], bool)


def assert_accreditation(data: dict):
    _assert_common(data)
    assert data["method"] in ["CLASS_AVG", "UNIT_SPECIFIC"]
    assert data["status"] in ["PENDING_REVIEW", "EFFECTIVE", "REJECTED"]


def assert_offer(data: dict):
    _assert_common(data)
    assert data["status"] in [
        "SUBMITTED", "SEALED", "CLEARED", "PARTIALLY_CLEARED", "REJECTED", "WITHDRAWN",
    ]
    assert data["mitigation_status"] in ["UNREVIEWED", "PASSED", "MITIGATED", "EXEMPT"]
    assert isinstance(data["offer_mw"], (int, float))
    assert isinstance(data["offer_price_per_mw_day"], (int, float))


def assert_mitigation_review(data: dict):
    _assert_common(data)
    assert data["outcome"] in ["PENDING", "PASS", "MITIGATE", "EXEMPT"]
    assert "resolved_at" in data


def assert_auction_run(data: dict):
    _assert_common(data)
    assert data["status"] in ["DRAFT", "OPEN", "SEALED", "CLEARED", "SETTLED"]
    assert "sealed_at" in data
    assert "cleared_at" in data


def assert_commitment(data: dict):
    _assert_common(data)
    assert data["status"] in ["ACTIVE", "REPLACEMENT_PENDING", "SETTLED", "DEFAULTED"]
    assert isinstance(data["committed_mw"], (int, float))
    assert isinstance(data["clearing_price_per_mw_day"], (int, float))
    assert isinstance(data["daily_revenue_dollars"], (int, float))
    assert isinstance(data["cumulative_performance_score"], (int, float))


def assert_replacement_transaction(data: dict):
    _assert_common(data)
    assert data["status"] in ["PENDING", "APPROVED", "REJECTED"]
    assert isinstance(data["replacement_mw"], (int, float))


def assert_emergency_event(data: dict):
    _assert_common(data)
    assert data["event_type"] in ["EMERGENCY_ACTION", "DR_TEST"]
    assert data["status"] in ["DECLARED", "ASSESSING", "ASSESSED", "SETTLED"]


def assert_performance_assessment(data: dict):
    _assert_common(data, with_version=False)
    assert data["status"] in ["DRAFT", "FINALIZED"]
    assert isinstance(data["expected_mw"], (int, float))
    assert isinstance(data["actual_mw"], (int, float))


def assert_measurement_report(data: dict):
    _assert_common(data)
    assert data["status"] in ["SUBMITTED", "UNDER_REVIEW", "VERIFIED", "REJECTED"]
    assert isinstance(data["metered_mwh"], (int, float))
    assert isinstance(data["baseline_mwh"], (int, float))


def assert_settlement_entry(data: dict):
    _assert_common(data, with_version=False)
    assert data["entry_type"] in ["CHARGE", "BONUS", "REDISTRIBUTION"]
    assert isinstance(data["amount_dollars"], (int, float))
    assert "emergency_event_id" in data
