"""Structural assertions for every response shape the tests read back."""

from prd_bench_local_runner.testing import is_iso8601_timestamp, is_valid_uuid


def _created(data: dict):
    assert is_valid_uuid(data.get("id", "")), f"id must be a plain UUID, got {data.get('id')!r}"
    assert is_iso8601_timestamp(data.get("created_at", "")), (
        f"created_at must be an ISO 8601 UTC timestamp, got {data.get('created_at')!r}"
    )


def _common(data: dict):
    _created(data)
    assert is_iso8601_timestamp(data.get("updated_at", "")), (
        f"updated_at must be an ISO 8601 UTC timestamp, got {data.get('updated_at')!r}"
    )
    assert isinstance(data.get("version"), int), "version must be an integer"


def assert_price_point(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "ACTIVE"), data["status"]
    assert isinstance(data["shelf_price_cents"], int) and data["shelf_price_cents"] > 0
    assert isinstance(data["issued_store_count"], int) and data["issued_store_count"] >= 0


def assert_season_window(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "SCHEDULED", "OPEN", "CLOSED"), data["status"]
    assert isinstance(data["overlapping_reset_count"], int)
    assert is_iso8601_timestamp(data["opens_on"]) and is_iso8601_timestamp(data["closes_on"])


def assert_pack_program(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "PENDING_ACTIVATION", "ACTIVE", "TERMINATED"), data["status"]
    assert isinstance(data["pack_qty"], int) and data["pack_qty"] >= 1
    assert isinstance(data["case_pack_qty"], int) and data["case_pack_qty"] >= 1
    assert isinstance(data["quoted_landed_cost_cents"], int)
    assert isinstance(data["target_landed_cost_cents"], int)


def assert_item(data: dict):
    _common(data)
    assert data["status"] in (
        "DENOMINATED", "PRICE_ASSIGNED", "COST_PENDING", "DELETE_REVIEW", "ACTIVE", "DELETED",
    ), data["status"]
    for field in (
        "unit_retail_cents", "units_per_case", "base_landed_cost_cents",
        "fixed_store_handling_cents", "variable_store_cost_cents", "on_hand_units",
        "landed_cost_cents", "break_even_units", "net_contribution_cents_per_unit",
    ):
        assert isinstance(data[field], int), f"{field} must be an integer, got {data[field]!r}"
    assert isinstance(data["broken_case_allowance"], bool)
    assert isinstance(data["is_shelf_overflow"], bool)
    assert isinstance(data["sqft_per_unit"], (int, float))
    assert isinstance(data["shelf_package_capacity"], (int, float))
    assert data["price_point_id"] is None or is_valid_uuid(data["price_point_id"])


def assert_vendor(data: dict):
    _common(data)
    assert isinstance(data["import_flag"], bool)
    assert isinstance(data["exclusivity_program_count"], int)


def assert_container(data: dict):
    _common(data)
    assert data["status"] in (
        "BOOKED", "IN_TRANSIT", "AT_PORT", "CUSTOMS_HOLD", "RECEIVED", "ALLOCATED",
    ), data["status"]
    assert isinstance(data["customs_cleared"], bool)
    assert isinstance(data["total_freight_cents"], int)


def assert_store(data: dict):
    _common(data)
    assert data["status"] in ("SINGLE_PRICE", "CONVERTING", "MULTI_PRICE", "REVERTING"), data["status"]
    for field in ("sign_order_filed", "shelf_tag_filed", "register_file_locked"):
        assert isinstance(data[field], bool), f"{field} must be a boolean"
    assert isinstance(data["shelf_facing_capacity_sqft"], (int, float))
    assert isinstance(data["price_integrity_audit_count"], int)
    assert isinstance(data["open_violation_count"], int)
    assert data["conversion_price_point_id"] is None or is_valid_uuid(data["conversion_price_point_id"])


def assert_aisle_reset(data: dict):
    _common(data)
    assert data["status"] in ("PLANNED", "EXECUTING", "EXECUTED", "ABANDONED"), data["status"]
    assert isinstance(data["allocated_shelf_sqft"], (int, float))
    assert isinstance(data["seasonal_changeover"], bool)
    assert is_iso8601_timestamp(data["starts_at"]) and is_iso8601_timestamp(data["ends_at"])


def assert_conversion_project(data: dict):
    _common(data)
    assert data["status"] in ("DRAFT", "IN_PROGRESS", "COMPLETED", "ROLLBACK"), data["status"]
    assert isinstance(data["coverage_delta_pct"], (int, float))


def assert_price_integrity_audit(data: dict):
    """The audit is an append-only row: id and created_at only."""
    _created(data)
    assert "updated_at" not in data, "a price integrity audit must not report updated_at"
    assert "version" not in data, "a price integrity audit must not report version"
    assert data["result"] in ("WITHIN_TOLERANCE", "VIOLATION"), data["result"]
    assert data["status"] in ("OPEN", "RESOLVED"), data["status"]
    assert isinstance(data["mismatch_ratio"], (int, float))
    assert isinstance(data["observed_item_count"], int)
    assert isinstance(data["mismatched_item_count"], int)


def assert_landed_cost_history(data: dict):
    assert is_valid_uuid(data.get("id", "")), "id must be a plain UUID"
    assert is_iso8601_timestamp(data.get("created_at", ""))
    assert data["method"] in ("FREIGHT_PASS_THROUGH", "VENDOR_PRICE_CHANGE"), data["method"]
    assert isinstance(data["applied_amount_cents"], int)
    assert isinstance(data["effective_sequence"], int)


def assert_allocation_line(data: dict):
    _common(data)
    assert data["status"] in ("ALLOCATED", "OVERFLOW", "RELEASED", "SHORTED", "REVERSED"), data["status"]
    for field in ("sequence", "requested_units", "allocated_units", "overflow_units",
                  "released_units", "remaining_units"):
        assert isinstance(data[field], int), f"{field} must be an integer"
    assert data["remaining_units"] == data["allocated_units"] - data["released_units"]
    assert data["overflow_units"] == data["requested_units"] - data["allocated_units"]


# ─── Domain invariant checkers ────────────────────────────────────────────────

def assert_item_cost_invariants(data: dict):
    """net_contribution and the divergence sentinel, checked on any item read."""
    expected_net = (
        data["unit_retail_cents"] - data["landed_cost_cents"] - data["variable_store_cost_cents"]
    )
    assert data["net_contribution_cents_per_unit"] == expected_net, (
        f"net contribution {data['net_contribution_cents_per_unit']} != {expected_net}"
    )
    if data["net_contribution_cents_per_unit"] < 0:
        assert data["break_even_units"] == 0, (
            "break_even_units must be the zero sentinel when the unit margin is non-positive"
        )
    else:
        assert data["break_even_units"] >= 0


def assert_waterfall_invariants(line: dict):
    """allocated + overflow == requested, and released never exceeds allocated."""
    assert line["allocated_units"] + line["overflow_units"] == line["requested_units"]
    assert line["released_units"] <= line["allocated_units"]


def assert_coverage_projection(data: dict):
    completed = data["completed_aisle_count"]
    projected = data["projected_convertible_aisle_count"]
    baseline = data["adjusted_baseline"]
    assert baseline == max(projected, 1), f"adjusted_baseline must be max({projected}, 1)"
    expected_delta = round((completed - baseline) / baseline, 3)
    assert abs(data["coverage_delta_pct"] - expected_delta) < 1e-9, (
        f"coverage_delta_pct {data['coverage_delta_pct']} != {expected_delta}"
    )
    assert data["shortfall"] is (data["coverage_delta_pct"] < -0.50)