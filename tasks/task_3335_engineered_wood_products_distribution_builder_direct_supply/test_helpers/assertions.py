"""Entity assertions and domain invariant checkers."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _assert_common_fields(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a valid UUID"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        "created_at must be ISO 8601"
    )
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        "updated_at must be ISO 8601"
    )
    assert isinstance(data.get("version"), int) and data["version"] >= 1, (
        "version must be a positive integer"
    )


def assert_mill_capacity_week(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["mill_code"], str) and data["mill_code"]
    assert isinstance(data["week_start_date"], str) and data["week_start_date"]
    assert isinstance(data["total_capacity_mbf"], int)
    assert isinstance(data["internal_alloc_mbf"], int)
    assert isinstance(data["market_alloc_mbf"], int)
    assert data["week_status"] in ("OPEN", "CLOSED")


def assert_product(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sku_code"], str) and data["sku_code"]
    assert data["product_family"] in (
        "I_JOIST", "LVL_BEAM", "GLULAM_BEAM", "STRUCTURAL_PANEL",
    )
    assert data["species"] in (
        "DOUGLAS_FIR", "SOUTHERN_PINE", "SPRUCE_PINE_FIR",
    )
    assert isinstance(data["dimension_label"], str)
    assert isinstance(data["specialty_flag"], bool)
    assert isinstance(data["requires_code_report"], bool)
    assert isinstance(data["requires_design_support"], bool)
    assert isinstance(data["index_premium_cents"], int)


def assert_price_index_entry(data: dict):
    _assert_common_fields(data)
    assert data["product_family"] in (
        "I_JOIST", "LVL_BEAM", "GLULAM_BEAM", "STRUCTURAL_PANEL",
    )
    assert data["species"] in (
        "DOUGLAS_FIR", "SOUTHERN_PINE", "SPRUCE_PINE_FIR",
    )
    assert isinstance(data["effective_week_start"], str)
    assert isinstance(data["index_price_cents_per_mbf"], int)


def assert_branch(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["branch_code"], str) and data["branch_code"]
    assert isinstance(data["region_code"], str)
    assert data["species_preference"] in (
        "DOUGLAS_FIR", "SOUTHERN_PINE", "SPRUCE_PINE_FIR",
    )
    assert isinstance(data["target_stock_mbf"], int)
    assert isinstance(data["activity_score"], int)
    assert isinstance(data["replenishment_enabled"], bool)


def assert_inventory_lot(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["branch_id"], str)
    assert isinstance(data["product_id"], str)
    assert isinstance(data["qty_received_mbf"], int)
    assert isinstance(data["unit_cost_cents_per_mbf"], int)
    assert is_iso8601_timestamp(data.get("received_at", "")), (
        "received_at must be ISO 8601"
    )
    assert isinstance(data["qty_available_mbf"], int)
    assert isinstance(data["qty_reserved_mbf"], int)
    assert isinstance(data["qty_sold_mbf"], int)
    assert data["lot_status"] in ("ON_HAND", "DEPLETED", "SOLD_OUT")


def assert_builder(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["legal_name"], str) and data["legal_name"]
    assert isinstance(data["lien_rights_state_code"], str)
    assert data["credit_status"] in (
        "PROVISIONAL", "ACTIVE", "SUSPENDED", "CLOSED",
    )
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["exposure_committed_cents"], int)
    assert isinstance(data["exposure_settled_cents"], int)


def assert_builder_job(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["builder_id"], str)
    assert isinstance(data["job_name"], str) and data["job_name"]
    assert is_iso8601_timestamp(data.get("access_window_start", ""))
    assert is_iso8601_timestamp(data.get("access_window_end", ""))
    assert data["placement_difficulty"] in (
        "STANDARD", "TIGHT_ACCESS", "CRANE_ASSIST",
    )
    assert isinstance(data["job_exposure_cap_cents"], int)
    assert isinstance(data["exposure_committed_cents"], int)
    assert isinstance(data["exposure_settled_cents"], int)


def assert_takeoff_request(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["plan_reference"], str)
    assert isinstance(data["includes_floor_system_design"], bool)
    assert data["takeoff_status"] in (
        "SUBMITTED", "QUOTED", "REVISION_REQUESTED", "ACCEPTED", "EXPIRED",
    )
    assert isinstance(data["revision_count"], int)


def assert_sales_order(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_id"], str)
    assert isinstance(data["branch_id"], str)
    assert data["pricing_week_mode"] in ("LOCK_AT_ACCEPT", "FLOAT_TO_SHIP")
    assert isinstance(data["lines"], list)
    assert data["order_status"] in (
        "DRAFT", "CONFIRMED", "ON_HOLD", "DELIVERED", "CANCELLED",
    )
    assert isinstance(data["order_total_cents"], int)
    assert isinstance(data["delivered_total_cents"], int)


def assert_delivery(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["sales_order_id"], str)
    assert isinstance(data["boom_required"], bool)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert data["delivery_status"] in (
        "REQUESTED", "SCHEDULED", "COMPLETED", "FAILED_ACCESS", "CANCELLED",
    )
    assert isinstance(data["fail_count"], int)


def assert_truck_shift(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["fleet_code"], str) and data["fleet_code"]
    assert isinstance(data["shift_date"], str)
    assert is_iso8601_timestamp(data.get("window_start", ""))
    assert is_iso8601_timestamp(data.get("window_end", ""))
    assert isinstance(data["boom_capable"], bool)
    assert isinstance(data["max_drops"], int)
    assert isinstance(data["booked_drops"], int)
    assert data["shift_status"] in ("OPEN", "CLOSED")


def assert_lien_filing(data: dict):
    _assert_common_fields(data)
    assert isinstance(data["job_id"], str)
    assert data["lien_status"] in ("FILED", "RELEASED", "EXPIRED")
    assert isinstance(data["amount_cents"], int)
    assert is_iso8601_timestamp(data.get("filed_at", ""))
    assert isinstance(data["deadline_date"], str)


def assert_lot_quantity_conservation(lot: dict):
    """Per-lot conservation: available + reserved + sold == received."""
    total = (
        lot["qty_available_mbf"] + lot["qty_reserved_mbf"] + lot["qty_sold_mbf"]
    )
    assert total == lot["qty_received_mbf"], (
        f"lot {lot['id']} conserves mbf: {lot['qty_available_mbf']} available + "
        f"{lot['qty_reserved_mbf']} reserved + {lot['qty_sold_mbf']} sold != "
        f"received {lot['qty_received_mbf']}"
    )
