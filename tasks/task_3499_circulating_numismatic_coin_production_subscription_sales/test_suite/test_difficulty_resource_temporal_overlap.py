"""Difficulty rule resource_temporal_overlap (PRD §3.2, §3.3, §3.6): three
distinct interval semantics — half-open overlap on the (facility, press_line)
resource, the >= 24-hour minimum gap between same-family releases, and the
per-UTC-date aggregate capacity budget at a vault."""

from test_helpers import ApiErrorId, TEST_USERS, validate_error
from test_helpers.factories import (
    create_product_payload,
    create_production_run_payload,
)
from test_helpers.fixtures import (
    create_denomination,
    create_fed_order,
    create_metal_lot,
    create_product,
    create_run,
    receive_metal_lot,
    set_clock,
)

PLANNER = TEST_USERS["production_planner_headers"]
MANAGER = TEST_USERS["program_manager_headers"]
PROCUREMENT = TEST_USERS["procurement_officer_headers"]


def test_press_window_half_open_adjacency_allowed_overlap_rejected(api):
    """PRD §3.3: "The press line is a real resource: no two runs in non-terminal
    states on the same facility and press line may occupy overlapping windows,
    where overlap is judged on half-open intervals — an existing run's
    `planned_start` falling before the new run's `planned_end` while the new
    run's `planned_start` falls before the existing run's `planned_end`. Runs
    that merely touch, one ending exactly when the other begins, do not overlap
    and both are accepted."
    PRD §3.3: "A window whose `planned_end` is not after its `planned_start`, or
    any genuine overlap with a non-terminal run, is rejected with
    `ERR_PRESS_WINDOW_OVERLAP` (409)."

    Design: Difficulty/resource_temporal_overlap/press_window_half_open_adjacency_allowed_overlap_rejected
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    create_denomination(api)
    fed_order = create_fed_order(api, quantity_ordered_pieces=500000)
    run1 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P1",
        planned_start="2026-10-05T08:00:00Z", planned_end="2026-10-05T12:00:00Z",
        planned_quantity=100000)
    assert run1["status"] == "PLANNED"

    # Adjacent under half-open semantics: 12:00 start == prior 12:00 end is NOT
    # an overlap.
    run2 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P1",
        planned_start="2026-10-05T12:00:00Z", planned_end="2026-10-05T14:00:00Z",
        planned_quantity=50000)
    assert run2["status"] == "PLANNED"

    # An 11:00-13:00 window straddles run1's 08:00-12:00 window on the same
    # (facility, press_line) resource.
    resp = api.create_production_run(
        create_production_run_payload(
            fed_order_id=fed_order["id"], facility="PHILADELPHIA",
            press_line="P1", planned_start="2026-10-05T11:00:00Z",
            planned_end="2026-10-05T13:00:00Z", planned_quantity=50000),
        PLANNER)
    validate_error(resp, ApiErrorId.ERR_PRESS_WINDOW_OVERLAP)

    # The same straddling window on a different press line does not collide.
    run4 = create_run(
        api, fed_order["id"], facility="PHILADELPHIA", press_line="P2",
        planned_start="2026-10-05T11:00:00Z", planned_end="2026-10-05T13:00:00Z",
        planned_quantity=50000)
    assert run4["status"] == "PLANNED"


def test_release_family_minimum_gap_boundary(api):
    """PRD §3.6: "Releases within a family must stand at least 24 hours apart: a
    new `release_datetime` less than 24 hours away from any non-`WITHDRAWN`
    product in the same `product_family` is rejected with
    `ERR_RELEASE_GAP_VIOLATION` (409), while a gap of exactly 24 hours passes."

    Design: Difficulty/resource_temporal_overlap/release_family_minimum_gap_boundary
    """
    p1 = create_product(
        api, product_code="RG-1", product_family="RGF", product_type="PROOF_SET",
        price_cents=2000, mintage_limit=100, household_order_limit=10,
        release_datetime="2026-10-01T14:00:00Z")
    assert p1["status"] == "SCHEDULED"

    # 20 hours apart (< 24h) is rejected.
    resp = api.create_product(
        create_product_payload(
            product_code="RG-2", product_family="RGF", product_type="PROOF_SET",
            price_cents=2000, mintage_limit=100, household_order_limit=10,
            release_datetime="2026-10-02T10:00:00Z"),
        MANAGER)
    validate_error(resp, ApiErrorId.ERR_RELEASE_GAP_VIOLATION)

    # Exactly 24 hours apart satisfies the >= boundary.
    p3 = create_product(
        api, product_code="RG-3", product_family="RGF", product_type="PROOF_SET",
        price_cents=2000, mintage_limit=100, household_order_limit=10,
        release_datetime="2026-10-02T14:00:00Z")
    assert p3["status"] == "SCHEDULED"


def test_vault_daily_aggregate_capacity_across_lots(api):
    """PRD §3.2: "Vaults impose a daily receiving cap: the sum of
    `quantity_tonnes` over lots delivered at the same vault on the same UTC date
    — per the logical clock — plus the arriving lot's tonnage must not exceed 50
    tonnes, and a receipt that would break the cap is rejected with
    `ERR_VAULT_CAPACITY_EXCEEDED` (422)."
    PRD §3.2: "a `planned_delivery_date` that is metadata only and drives no
    transition."

    Design: Difficulty/resource_temporal_overlap/vault_daily_aggregate_capacity_across_lots
    """
    set_clock(api, "2026-09-10T00:00:00Z", {"COPPER": 800000})
    create_denomination(api)
    lot1 = create_metal_lot(api, quantity_tonnes=30, vault="FORT_KNOX",
                            locked_unit_price_cents_per_tonne=800000,
                            planned_delivery_date="2026-09-10")
    lot2 = create_metal_lot(api, quantity_tonnes=30, vault="FORT_KNOX",
                            locked_unit_price_cents_per_tonne=800000,
                            planned_delivery_date="2026-09-11")

    lot1 = receive_metal_lot(api, lot1["id"])
    assert lot1["status"] == "DELIVERED"  # 30 <= 50 on 2026-09-10

    # The aggregate sums per vault per UTC date: 30 + 30 = 60 > 50 today.
    resp = api.receive_metal_lot(lot2["id"], PROCUREMENT)
    validate_error(resp, ApiErrorId.ERR_VAULT_CAPACITY_EXCEEDED)

    # Rolling the logical clock to the next UTC date resets the aggregate.
    set_clock(api, "2026-09-11T00:00:00Z")
    lot2 = receive_metal_lot(api, lot2["id"])
    assert lot2["status"] == "DELIVERED"
