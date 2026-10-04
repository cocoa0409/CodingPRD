"""Entity assertions and domain invariant checkers (PRD §2.4, §3)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    """Every persisted resource carries id/created_at/updated_at/version (PRD §2.4)."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a valid UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be ISO 8601, got {data.get('created_at')!r}"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be ISO 8601, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        f"version must be a positive integer, got {data.get('version')!r}"
    )


def assert_customer(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["credit_tier"] in ("TIER_A", "TIER_B", "TIER_C")
    assert isinstance(data["tax_credit_flag"], bool)


def assert_module_series(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["series_code"], str) and data["series_code"]
    assert data["technology"] in ("CDTE_THIN_FILM", "CDTE_THIN_FILM_CUTE")
    assert data["nominal_wattage"] > 0
    assert isinstance(data["bin_profile"], list) and len(data["bin_profile"]) > 0
    for entry in data["bin_profile"]:
        assert isinstance(entry["bin_code"], str) and entry["bin_code"]
        assert entry["wattage"] > 0
        assert 0.0 <= entry["fraction"] <= 1.0
    assert isinstance(data["temp_coefficient"], (int, float))
    assert data["status"] in ("ACTIVE", "DISCONTINUED")


def assert_production_line(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["site_country"], str) and len(data["site_country"]) == 2
    assert data["annual_capacity_mw"] > 0
    assert data["status"] in (
        "COMMISSIONING", "RAMPING", "AT_CAPACITY", "SUSPENDED", "DECOMMISSIONED"
    )
    assert isinstance(data["ramp_quarter_index"], int)
    if data.get("actual_yield_rate") is not None:
        assert 0.0 <= data["actual_yield_rate"] <= 1.0


def assert_capacity_reservation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("series_id", ""))
    assert isinstance(data["delivery_year"], int)
    assert data["contracted_mw"] > 0
    assert data["price_usd_per_w"] > 0
    assert data["deposit_usd"] >= 0
    assert 1 <= data["term_years"] <= 5
    assert data["status"] in (
        "PENDING", "DEPOSIT_HELD", "ACTIVE", "CONSTRAINED", "COMPLETED", "CANCELLED"
    )


def assert_production_run(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert is_valid_uuid(data.get("series_id", ""))
    assert isinstance(data["quarter"], int)
    assert data["input_modules"] > 0
    assert 0 <= data["good_modules"] <= data["input_modules"]
    assert isinstance(data["bin_counts"], list)
    total = sum(entry["count"] for entry in data["bin_counts"])
    assert total == data["good_modules"], "bin_counts must sum to good_modules"
    assert 0.0 <= data["run_yield_rate"] <= 1.0


def assert_delivery(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert is_iso8601_timestamp(data.get("scheduled_window_start", ""))
    assert is_iso8601_timestamp(data.get("scheduled_window_end", ""))
    assert data["volume_mw"] > 0
    assert isinstance(data["lot_ids"], list)
    assert data["schedule_status"] in (
        "SCHEDULED", "RESCHEDULED", "DELIVERED", "RECALLED", "CANCELLED"
    )
    assert data["content_status"] in (
        "UNEVALUATED", "QUALIFIED_DOMESTIC", "NON_QUALIFYING"
    )


def assert_component_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["supplier_name"], str) and data["supplier_name"]
    assert isinstance(data["lot_code"], str) and data["lot_code"]
    assert data["component_type"] in (
        "SEMICONDUCTOR_FEEDSTOCK", "GLASS", "BACKSHEET", "FRAME", "JUNCTION_BOX"
    )
    assert isinstance(data["country_of_origin"], str) and len(data["country_of_origin"]) == 2
    assert data["lot_cost_usd"] >= 0
    assert data["status"] in ("PENDING_INSPECTION", "VERIFIED", "QUARANTINED")


def assert_compliance_attestation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("line_id", ""))
    assert isinstance(data["period_year"], int)
    for field in (
        "labor_cost_usd", "feedstock_cost_usd", "glass_cost_usd",
        "balance_of_system_cost_usd", "overhead_cost_usd",
        "total_manufactured_cost_usd",
    ):
        assert data[field] >= 0, f"{field} must be >= 0"
    assert data["status"] in ("DRAFT", "SUBMITTED", "QUALIFIED", "REJECTED")


def assert_recycling_obligation(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("customer_id", ""))
    assert isinstance(data["period_year"], int)
    assert data["shipped_volume_mw"] >= 0
    assert data["required_collected_mw"] >= 0
    assert data["collected_volume_mw"] >= 0
    assert data["fulfillment_pct"] >= 0
    assert data["status"] in ("OPEN", "COLLECTING", "RECOVERED", "SETTLED")


def assert_warranty_claim(data: dict):
    _assert_common_fields(data)
    assert is_valid_uuid(data.get("reservation_id", ""))
    assert data["claim_type"] in ("PRODUCT_DEFECT", "PERFORMANCE_SHORTFALL")
    assert data["claimed_mw"] > 0
    assert data["status"] in (
        "FILED", "UNDER_REVIEW", "APPROVED", "PAID", "DENIED", "WITHDRAWN"
    )


def assert_line_capacity_buckets(line: dict):
    """Domain invariant: committed + reserved + available == annual (PRD §2.7)."""
    committed = line["committed_capacity_mw"]
    reserved = line["reserved_capacity_mw"]
    available = line["available_capacity_mw"]
    annual = line["annual_capacity_mw"]
    assert committed >= 0 and reserved >= 0
    assert abs((committed + reserved + available) - annual) < 1e-6, (
        f"capacity buckets must sum to annual capacity: "
        f"{committed} + {reserved} + {available} != {annual}"
    )
