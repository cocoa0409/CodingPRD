"""Entity assertions and domain invariant checkers (PRD §2.4 common fields)."""
from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def assert_common_fields(data: dict):
    """PRD §2.4: every resource carries id/created_at/updated_at/version."""
    assert is_valid_uuid(data.get("id", "")), f"id must be a UUID: {data.get('id')}"
    assert is_iso8601_timestamp(data.get("created_at", "")), "created_at must be ISO 8601"
    assert is_iso8601_timestamp(data.get("updated_at", "")), "updated_at must be ISO 8601"
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_part(data: dict):
    assert_common_fields(data)
    assert isinstance(data["part_number"], str) and data["part_number"]
    assert isinstance(data["description"], str)
    assert isinstance(data["package_family"], str)
    assert isinstance(data["process_technology"], str)
    assert isinstance(data["automotive_grade"], bool)
    assert data["lifecycle_status"] in (
        "ACTIVE", "NRND", "EOL_ANNOUNCED", "LAST_TIME_BUY", "DISCONTINUED"
    )
    assert isinstance(data["demand_rate_units_per_week"], int)
    assert isinstance(data["buffer_multiple"], (int, float))
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert data["posture"] in ("NORMAL", "WATCH", "SHORTAGE")


def assert_customer(data: dict):
    assert_common_fields(data)
    assert isinstance(data["name"], str) and data["name"]
    assert data["tier"] in ("STRATEGIC", "KEY", "STANDARD", "SMALL")
    assert data["channel"] in ("DIRECT_ONLINE", "DIRECT_FIELD", "DISTRIBUTOR")
    assert isinstance(data["credit_limit_cents"], int)
    assert isinstance(data["discount_pct"], (int, float))
    assert isinstance(data["open_exposure_cents"], int)
    assert isinstance(data["at_risk_design_win_count"], int)


def assert_pricing_schedule(data: dict):
    assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["effective_from"], str)
    assert isinstance(data["tiers"], list) and len(data["tiers"]) >= 1
    for tier in data["tiers"]:
        assert isinstance(tier["min_qty"], int) and tier["min_qty"] >= 1
        assert isinstance(tier["unit_price_cents"], int)
    assert data["status"] in ("PUBLISHED", "SUPERSEDED")
    assert is_iso8601_timestamp(data.get("published_at", ""))


def assert_sales_order(data: dict):
    assert_common_fields(data)
    assert isinstance(data["customer_id"], str)
    assert data["channel"] in ("DIRECT_ONLINE", "DIRECT_FIELD", "DISTRIBUTOR")
    assert data["status"] in (
        "DRAFT", "ALLOCATED", "BACKORDERED", "SHIPPED", "CANCELLED"
    )
    for field in ("subtotal_cents", "service_fee_cents", "total_cents"):
        assert data[field] is None or isinstance(data[field], int)
    assert data["submitted_at"] is None or is_iso8601_timestamp(data["submitted_at"])


def assert_order_line(data: dict):
    assert_common_fields(data)
    assert isinstance(data["order_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert data["unit_price_cents"] is None or isinstance(data["unit_price_cents"], int)
    assert data["line_total_cents"] is None or isinstance(data["line_total_cents"], int)
    assert isinstance(data["awarded_units"], int) and data["awarded_units"] >= 0
    assert data["allocation_run_id"] is None or isinstance(data["allocation_run_id"], str)
    assert data["allocation_rank"] is None or isinstance(data["allocation_rank"], int)
    assert data["allocation_priority_score"] is None or isinstance(
        data["allocation_priority_score"], int
    )


def assert_capacity_pool(data: dict):
    assert_common_fields(data)
    assert isinstance(data["site_name"], str) and data["site_name"]
    assert isinstance(data["process_technology"], str)
    assert isinstance(data["period_start"], str)
    assert isinstance(data["period_end"], str)
    assert isinstance(data["total_units"], int) and data["total_units"] >= 1
    assert isinstance(data["allocated_units"], int) and data["allocated_units"] >= 0
    assert data["status"] in ("PLANNED", "OPEN", "CLOSED")
    assert isinstance(data["qualified_for_automotive"], bool)


def assert_allocation_run(data: dict):
    assert_common_fields(data)
    assert isinstance(data["period_label"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert isinstance(data["shortage_part_ids"], list)
    assert isinstance(data["awards"], list)
    for award in data["awards"]:
        assert isinstance(award["order_line_id"], str)
        assert isinstance(award["awarded_units"], int)
        assert isinstance(award["priority_score"], int)
        assert isinstance(award["rank"], int) and award["rank"] >= 1


def assert_eol_notice(data: dict):
    assert_common_fields(data)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["notice_date"], str)
    assert isinstance(data["last_order_date"], str)
    assert isinstance(data["last_ship_date"], str)
    assert data["status"] in ("ANNOUNCED", "RESCINDED", "COMPLETED")


def assert_lifetime_buy(data: dict):
    assert_common_fields(data)
    assert isinstance(data["eol_notice_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["quantity"], int) and data["quantity"] >= 1
    assert isinstance(data["unit_price_cents"], int)
    assert isinstance(data["ltb_value_cents"], int)
    assert data["status"] in ("APPROVED", "CANCELLED")


def assert_site_qualification(data: dict):
    assert_common_fields(data)
    assert isinstance(data["site_name"], str)
    assert data["segment"] in ("AUTOMOTIVE", "INDUSTRIAL")
    assert data["status"] in (
        "REQUESTED", "IN_REVIEW", "QUALIFIED", "SUSPENDED", "REJECTED"
    )
    assert data["qualified_at"] is None or is_iso8601_timestamp(data["qualified_at"])
    assert isinstance(data["validity_months"], int)


def assert_reference_design(data: dict):
    assert_common_fields(data)
    assert isinstance(data["title"], str)
    assert isinstance(data["featured_part_number"], str)
    assert data["status"] in ("DRAFT", "PUBLISHED")
    assert data["published_at"] is None or is_iso8601_timestamp(data["published_at"])


def assert_design_win(data: dict):
    assert_common_fields(data)
    assert isinstance(data["reference_design_id"], str)
    assert isinstance(data["customer_id"], str)
    assert isinstance(data["part_id"], str)
    assert isinstance(data["expected_lifetime_revenue_cents"], int)
    assert isinstance(data["annual_volume_units"], int)
    assert isinstance(data["start_date"], str)
    assert data["status"] in ("REGISTERED", "ACTIVE", "COMPLETED")
    assert isinstance(data["at_risk"], bool)
    assert isinstance(data["recognized_ramped_cents"], int)
    assert isinstance(data["recognized_flat_cents"], int)
    assert isinstance(data["recognized_revenue_cents"], int)


def assert_inventory_position(data: dict):
    """Computed read shape from PRD §3.1."""
    assert isinstance(data["part_id"], str)
    assert isinstance(data["on_hand_units"], int)
    assert isinstance(data["reserved_units"], int)
    assert isinstance(data["available_units"], int)
    assert data["available_units"] == data["on_hand_units"] - data["reserved_units"]
    assert isinstance(data["target_trailing_units"], int)
    assert isinstance(data["target_forward_units"], int)
    assert isinstance(data["coverage_trailing"], (int, float))
    assert data["posture"] in ("NORMAL", "WATCH", "SHORTAGE")
