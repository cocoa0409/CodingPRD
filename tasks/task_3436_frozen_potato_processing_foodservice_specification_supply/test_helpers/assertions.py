"""Entity assertions and domain invariant checkers.

assert_<entity>(data) checks the fields the PRD makes observable on each
resource, using the framework's UUID/timestamp validators. These are shape
assertions for setup and read-back, not substitutes for test-specific
value assertions.
"""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid

COMMON_FIELDS = ("id", "created_at", "updated_at", "version")


def _assert_common(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int) and data["version"] >= 1, "version must be an int >= 1"


def assert_grower(data: dict):
    _assert_common(data)
    assert isinstance(data["grower_code"], str) and data["grower_code"]
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert data["region"] in ["COLUMBIA_BASIN", "SNAKE_RIVER_VALLEY", "RED_RIVER_VALLEY", "MAINE_AROOSTOOK"]


def assert_crop_contract(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("grower_id", "")), "grower_id must be a UUID"
    assert data["variety"] in ["RUSSET_BURBANK", "RANGER_RUSSET", "UMATILLA_RUSSET", "CLEARWATER_RUSSET"]
    assert data["contracted_acres"] > 0
    assert data["expected_yield_cwt_per_acre"] > 0
    assert isinstance(data["base_price_per_cwt_cents"], int) and data["base_price_per_cwt_cents"] > 0
    assert isinstance(data["contracted_volume_cwt"], (int, float))
    assert isinstance(data["delivered_volume_cwt"], (int, float))
    assert data["status"] in ["DRAFT", "ACTIVE", "AMENDMENT_PENDING", "FULFILLED", "SHORTFALL_DECLARED"]
    assert data["settlement_amount_cents"] is None or isinstance(data["settlement_amount_cents"], int)


def assert_potato_lot(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("facility_id", "")), "facility_id must be a UUID"
    assert data["origin"] in ["CONTRACTED", "IMPORT"]
    assert data["gross_weight_cwt"] > 0
    assert 0 <= data["tare_weight_cwt"] < data["gross_weight_cwt"]
    assert isinstance(data["net_weight_cwt"], (int, float)) and data["net_weight_cwt"] > 0
    assert data["grade"] in ["A", "B", "C", "REJECT"]
    assert data["status"] in ["IN_STORAGE", "ALLOCATED", "CONSUMED", "DISPOSED"]
    assert data["disposition"] in [None, "CONDEMNED_WASTE", "CATTLE_FEED", "STARCH_RECOVERY"]


def assert_storage_facility(data: dict):
    _assert_common(data)
    assert isinstance(data["facility_code"], str) and data["facility_code"]
    assert isinstance(data["capacity_cwt"], int) and data["capacity_cwt"] > 0
    assert isinstance(data["current_stock_cwt"], (int, float)) and data["current_stock_cwt"] >= 0
    assert data["posture"] in ["NORMAL", "WATCH", "QUARANTINED"]
    assert isinstance(data["recent_readings"], list) and len(data["recent_readings"]) <= 10


def assert_processing_line(data: dict):
    _assert_common(data)
    assert isinstance(data["line_code"], str) and data["line_code"]
    assert isinstance(data["supported_cut_families"], list) and len(data["supported_cut_families"]) >= 1
    assert data["rated_throughput_cases_per_hour"] > 0


def assert_cut_specification(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert data["cut_family"] in ["STRAIGHT", "CRINKLE", "WEDGE", "SHOESTRING"]
    assert data["cut_size_mm"] > 0
    assert data["coating_type"] in ["NONE", "CLEAR", "SEASONED", "BATTER"]
    assert data["max_cook_time_sec"] > 0
    assert isinstance(data["sensory_panel_required"], bool)
    assert isinstance(data["ever_locked"], bool)
    assert data["status"] in ["SUBMITTED", "VALIDATED", "LOCKED", "REVISION_REQUESTED"]


def assert_customer_chain(data: dict):
    _assert_common(data)
    assert isinstance(data["chain_code"], str) and data["chain_code"]
    assert data["priority_tier"] in ["TIER_1_STRATEGIC", "TIER_2_PREFERRED", "TIER_3_STANDARD"]
    assert data["credit_status"] in ["GOOD_STANDING", "ON_HOLD"]
    assert data["fill_rate_pct"] is None or isinstance(data["fill_rate_pct"], (int, float))


def assert_supply_agreement(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("customer_id", "")), "customer_id must be a UUID"
    assert is_valid_uuid(data.get("spec_id", "")), "spec_id must be a UUID"
    assert isinstance(data["weekly_contracted_cases"], int) and data["weekly_contracted_cases"] >= 1
    assert isinstance(data["price_per_case_cents"], int) and data["price_per_case_cents"] > 0
    assert data["pinned_spec_version"] is None or isinstance(data["pinned_spec_version"], int)
    assert isinstance(data["spec_stale"], bool)
    assert isinstance(data["under_sla_review"], bool)
    assert data["status"] in ["DRAFT", "ACTIVE", "SUSPENDED", "COMPLETED"]


def assert_production_run(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("line_id", "")), "line_id must be a UUID"
    assert is_valid_uuid(data.get("spec_id", "")), "spec_id must be a UUID"
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert isinstance(data["input_lot_ids"], list) and len(data["input_lot_ids"]) >= 1
    assert data["cut_family"] in ["STRAIGHT", "CRINKLE", "WEDGE", "SHOESTRING"]
    assert isinstance(data["total_input_cwt"], (int, float))
    assert data["actual_cases"] is None or isinstance(data["actual_cases"], int)
    assert isinstance(data["rework_count"], int) and data["rework_count"] >= 0
    assert data["status"] in [
        "SCHEDULED", "CUTTING", "BLANCHING", "COATING", "FREEZING",
        "QA_HOLD", "REWORK", "RELEASED", "REJECTED", "CANCELLED",
    ]


def assert_byproduct_batch(data: dict):
    # PRD §2.4: an immutable system-created record with only id + created_at.
    assert is_valid_uuid(data.get("id", "")), "id must be a UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert "updated_at" not in data, "ByproductBatch must not carry updated_at"
    assert "version" not in data, "ByproductBatch must not carry version"
    assert data["stream"] in ["WHOLE_LOT", "REJECTED_PRODUCT"]
    assert data["routing"] in ["CONDEMNED_WASTE", "CATTLE_FEED", "STARCH_RECOVERY"]
    assert isinstance(data["weight_cwt"], (int, float)) and data["weight_cwt"] > 0
    assert isinstance(data["unit_revenue_cents_per_cwt"], int)
    assert isinstance(data["total_revenue_cents"], int)


def assert_shipment(data: dict):
    _assert_common(data)
    assert is_valid_uuid(data.get("agreement_id", "")), "agreement_id must be a UUID"
    assert data["trailer_setpoint_f"] <= 0.0
    assert data["route_type"] in ["DIRECT_CHAIN", "DISTRIBUTOR"]
    assert isinstance(data["lines"], list) and len(data["lines"]) >= 1
    assert isinstance(data["cases_shipped"], int) and data["cases_shipped"] > 0
    assert isinstance(data["excursion_flag"], bool)
    assert data["status"] in ["IN_TRANSIT", "DELIVERED", "REJECTED_ON_ARRIVAL"]


def assert_shortage_event(data: dict):
    _assert_common(data)
    assert data["scope_variety"] in ["RUSSET_BURBANK", "RANGER_RUSSET", "UMATILLA_RUSSET", "CLEARWATER_RUSSET"]
    assert data["declared_deficit_cwt"] > 0
    assert 1 <= data["available_week_cases"] <= 100000
    assert data["response_mode"] in ["PRO_RATA", "PRIORITY_WATERFALL"]
    assert data["status"] in ["OPEN", "EXECUTED"]
