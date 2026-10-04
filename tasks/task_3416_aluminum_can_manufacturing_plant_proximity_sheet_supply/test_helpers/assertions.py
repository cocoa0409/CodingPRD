"""Entity assertions and domain invariant checkers (PRD §2.2, §2.5, §3)."""
import pytest
from prd_bench_local_runner.testing import is_valid_uuid, is_iso8601_timestamp


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), \
        "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, \
        "version must be a positive integer"


def assert_plant(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["region"], str) and data["region"]
    assert isinstance(data["warehouse_capacity_units"], int)
    assert data["warehouse_capacity_units"] > 0
    assert isinstance(data["warehouse_on_hand_units"], int)
    assert isinstance(data["projected_warehouse_units"], int)
    assert data["posture"] in ("OPEN", "CONGESTED", "LOCKDOWN")
    assert isinstance(data["ops_run_index"], int)
    assert data["scrap_credit_lbs_ytd"] >= 0
    assert data["metal_consumed_lbs_ytd"] >= 0
    assert data["recycled_content_pct"] >= 0


def assert_customer(data: dict):
    _assert_common(data)
    assert isinstance(data["name"], str) and data["name"]
    assert isinstance(data["home_region"], str) and data["home_region"]
    assert isinstance(data["filling_lines_count"], int)
    assert data["filling_lines_count"] >= 1


def assert_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert data["freight_zone"] in ("NEAR", "MID", "FAR")
    assert data["committed_annual_units"] >= 1_000_000
    assert 0 < data["pass_through_pct"] <= 1
    assert data["conversion_cost_cents_per_1000"] > 0
    assert data["status"] in ("DRAFT", "ACTIVE", "RENEGOTIATING", "EXPIRED",
                              "TERMINATED")
    assert data["ytd_settled_units"] >= 0
    assert data["delivered_revenue_cents"] >= 0
    assert data["volume_tier"] in ("STANDARD", "REBATE")


def assert_metal_index(data: dict):
    # Immutable row: only id + created_at of the common set (PRD §2.5).
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), \
        "created_at must be ISO 8601"
    assert "version" not in data, "metal price index must not carry version"
    assert "updated_at" not in data, "metal price index must not carry updated_at"
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["index_cents_per_lb"] > 0


def assert_line(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert isinstance(data["name"], str) and data["name"]
    assert data["nominal_speed_cans_per_hour"] > 0
    assert 0 <= data["base_spoilage_pct"] < 1
    assert data["operational_status"] in ("RUNNING", "QUALITY_HOLD")


def assert_format(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("plant_id", ""))
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["size_code"], str) and data["size_code"]
    assert data["shape"] in ("STANDARD", "SLEEK", "SLIM", "STUBBY")
    assert isinstance(data["is_specialty"], bool)
    assert data["metal_lbs_per_1000_units"] > 0
    assert data["status"] in ("PROPOSED", "TOOLED", "QUALIFIED", "RETIRED")
    assert data["delivered_units"] >= 0
    assert data["unamortized_exposure_cents"] >= 0


def assert_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("format_id", ""))
    assert data["scheduled_qty"] >= 5000
    assert isinstance(data["graphics_code"], str) and data["graphics_code"]
    assert data["status"] in ("SCHEDULED", "IN_PROGRESS", "HELD", "COMPLETED",
                              "SETTLED", "CANCELLED", "VOIDED")
    assert data["tier_delta_cents"] is not None


def assert_forecast(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", ""))
    assert isinstance(data["period"], str) and len(data["period"]) == 7
    assert data["forecast_qty"] >= 0
    assert data["status"] in ("OPEN", "CLOSED")


def assert_scrap_return(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("plant_id", ""))
    assert data["declared_weight_lbs"] > 0
    assert data["status"] in ("SCHEDULED", "CREDITED", "EXPIRED")


def assert_incident(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("run_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert data["severity"] in ("MINOR", "MAJOR", "CRITICAL")
    assert data["defect_class"] in ("SEAM_INTEGRITY", "COATING",
                                    "FILLING_LINE_PERFORMANCE")
    assert data["status"] in ("OPEN", "ESCALATED", "RESOLVED")


def assert_money(value, expected, label="money"):
    """Money is cents rounded half-up to 2 decimals (PRD §2.8)."""
    assert value == pytest.approx(expected, abs=0.005), \
        f"{label}: expected {expected}, got {value}"
