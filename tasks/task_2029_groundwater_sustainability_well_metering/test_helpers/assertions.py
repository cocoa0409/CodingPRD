"""Entity assertions and domain invariant checkers (PRD §2.4 common properties, §3 field rules)."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp

ACCOUNT_TYPES = ["AGRICULTURAL", "MUNICIPAL", "INDUSTRIAL", "DOMESTIC"]
ACCOUNT_STATUSES = ["ACTIVE", "SUSPENDED", "CLOSED"]
WELL_TYPES = ["PRODUCTION", "MONITORING", "DOMESTIC"]
WELL_STATUSES = ["REGISTERED", "METER_INSTALLED", "ACTIVE", "DECOMMISSIONED"]
REPORT_STATUSES = ["SUBMITTED", "VERIFIED", "DISPUTED"]
TRANSFER_STATUSES = ["PROPOSED", "ACCEPTED", "SETTLED", "REJECTED", "CANCELLED", "EXPIRED"]
SNAPSHOT_STATUSES = ["DRAFT", "PUBLISHED", "DISCARDED"]
BASIN_CONDITIONS = ["NORMAL", "WATCH", "CRITICAL"]
PENALTY_REASONS = ["OVERDRAFT", "LATE_REPORT", "UNMETERED_PUMPING"]
ASSESSMENT_STATUSES = ["ASSESSED", "APPEALED", "UPHELD", "REDUCED", "OVERTURNED", "PAID"]
ANNUAL_REPORT_STATUSES = ["DRAFT", "SUBMITTED", "ACKNOWLEDGED"]


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def _assert_af(value, name):
    assert isinstance(value, (int, float)) and not isinstance(value, bool), f"{name} must be numeric"


def assert_water_user_account(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["holder_name"], str) and len(data["holder_name"]) > 0
    assert data["account_type"] in ACCOUNT_TYPES
    _assert_af(data["base_allocation_af"], "base_allocation_af")
    assert data["base_allocation_af"] > 0
    assert data["status"] in ACCOUNT_STATUSES
    assert isinstance(data["current_water_year"], int)
    for field in (
        "extracted_af_ytd",
        "pending_extraction_af",
        "credit_balance_af",
        "transfer_out_af_ytd",
        "transfer_reserved_af",
    ):
        _assert_af(data[field], field)
        assert data[field] >= 0, f"{field} must be non-negative"
    assert isinstance(data["penalty_balance_cents"], int), "penalty_balance_cents must be integer cents"
    assert data["penalty_balance_cents"] >= 0


def assert_well(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert data["well_type"] in WELL_TYPES
    assert isinstance(data["location_description"], str)
    if data["well_type"] == "MONITORING":
        _assert_af(data["minimum_threshold_ft"], "minimum_threshold_ft")
    assert data.get("meter_serial") is None or isinstance(data["meter_serial"], str)
    assert data["status"] in WELL_STATUSES


def assert_extraction_report(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("well_id", "")), "well_id must be a valid UUID"
    assert isinstance(data["water_year"], int)
    assert isinstance(data["month"], int) and 1 <= data["month"] <= 12
    _assert_af(data["reported_af"], "reported_af")
    assert data["reported_af"] >= 0
    assert isinstance(data["late_flag"], bool), "late_flag must be a boolean"
    assert data.get("fee_cents") is None or isinstance(data["fee_cents"], int), (
        "fee_cents stays null until verification, then integer cents"
    )
    assert isinstance(data["amendment_count"], int) and data["amendment_count"] >= 0
    assert data["status"] in REPORT_STATUSES


def assert_transfer_order(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("seller_account_id", "")), "seller_account_id must be a valid UUID"
    assert is_valid_uuid(data.get("buyer_account_id", "")), "buyer_account_id must be a valid UUID"
    assert data["seller_account_id"] != data["buyer_account_id"]
    _assert_af(data["quantity_af"], "quantity_af")
    assert data["quantity_af"] > 0
    assert isinstance(data["unit_price_cents"], int) and data["unit_price_cents"] >= 0
    assert isinstance(data["effective_start_date"], str)
    assert isinstance(data["effective_end_date"], str)
    assert isinstance(data["expires_at"], str) and is_iso8601_timestamp(data["expires_at"])
    assert data.get("settled_at") is None or is_iso8601_timestamp(data["settled_at"])
    assert data["status"] in TRANSFER_STATUSES


def assert_monitoring_reading(data: dict):
    # Append-only event log (PRD §2.4): only id + created_at are system-managed;
    # updated_at and version must not exist on this resource.
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "MonitoringReading has no updated_at"
    assert "version" not in data, "MonitoringReading has no version"
    assert is_valid_uuid(data.get("well_id", "")), "well_id must be a valid UUID"
    assert isinstance(data["measured_at"], str) and is_iso8601_timestamp(data["measured_at"])
    _assert_af(data["depth_to_water_ft"], "depth_to_water_ft")
    assert data["depth_to_water_ft"] > 0
    assert isinstance(data["collector_name"], str) and len(data["collector_name"]) > 0


def assert_basin_condition_snapshot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["computed_at"], str) and is_iso8601_timestamp(data["computed_at"])
    assert isinstance(data["eligible_well_count"], int) and data["eligible_well_count"] >= 0
    assert isinstance(data["breached_well_count"], int) and data["breached_well_count"] >= 0
    assert data.get("breach_pct") is None or isinstance(data["breach_pct"], (int, float))
    assert data.get("rolling_mean_depth_ft") is None or isinstance(data["rolling_mean_depth_ft"], (int, float))
    assert data["condition"] in BASIN_CONDITIONS
    assert data.get("mean_condition") is None or data["mean_condition"] in BASIN_CONDITIONS
    assert data["status"] in SNAPSHOT_STATUSES


def assert_penalty_assessment(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("account_id", "")), "account_id must be a valid UUID"
    assert data["reason"] in PENALTY_REASONS
    assert isinstance(data["water_year"], int)
    if data["reason"] == "OVERDRAFT":
        _assert_af(data["overdraft_af"], "overdraft_af")
    assert isinstance(data["amount_cents"], int) and data["amount_cents"] > 0
    assert data.get("reduced_amount_cents") is None or isinstance(data["reduced_amount_cents"], int)
    assert data.get("paid_amount_cents") is None or isinstance(data["paid_amount_cents"], int)
    assert isinstance(data["assessed_by"], str) and len(data["assessed_by"]) > 0
    assert data.get("decided_by") is None or isinstance(data["decided_by"], str)
    assert data["status"] in ASSESSMENT_STATUSES


def assert_annual_state_report(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["water_year"], int)
    _assert_af(data["total_extracted_af"], "total_extracted_af")
    assert data["total_extracted_af"] >= 0
    assert isinstance(data["verified_report_count"], int) and data["verified_report_count"] >= 0
    assert isinstance(data["overdraft_assessment_count"], int) and data["overdraft_assessment_count"] >= 0
    for field in ("penalties_assessed_cents", "penalties_collected_cents", "total_pumping_fees_cents"):
        assert isinstance(data[field], int) and data[field] >= 0, f"{field} must be non-negative integer cents"
    assert data.get("final_basin_condition") is None or data["final_basin_condition"] in BASIN_CONDITIONS
    assert data.get("avg_depth_ft") is None or isinstance(data["avg_depth_ft"], (int, float))
    assert data["status"] in ANNUAL_REPORT_STATUSES


def assert_account_penalty_invariants(data: dict):
    """Domain invariant: the unpaid penalty ledger is never negative."""
    assert data["penalty_balance_cents"] >= 0, "penalty_balance_cents must never go negative"
