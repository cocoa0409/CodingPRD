"""Interval semantics: half-open labor windows vs inclusive Finds sale windows."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    CATEGORY_MANAGER_HEADERS,
    fixtures,
    make_store_manager_headers,
)
from test_helpers.factories import labor_window_payload


def _manager(store):
    return make_store_manager_headers(store["id"])


def test_labor_window_half_open_overlap_scoped_per_zone(api):
    """07:00-09:00 overlaps 06:00-08:00 in Z1; touching at 08:00 and other zones are fine.

    PRD §3.8: "Within the same store and `aisle_zone`, a new window must not overlap any existing `PLANNED` or `CONFIRMED` window under half-open semantics — back-to-back windows touching at an endpoint are fine — else `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/labor_window_half_open_overlap
    """
    store = fixtures.create_store(api)
    validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            _manager(store),
        ),
        201,
    )

    overlapping = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z1", starts_at="2026-09-07T07:00:00Z", ends_at="2026-09-07T09:00:00Z"),
        _manager(store),
    )
    validate_error(overlapping, "ERR_WINDOW_OVERLAP", 409)

    touching = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z1", starts_at="2026-09-07T08:00:00Z", ends_at="2026-09-07T10:00:00Z"),
        _manager(store),
    )
    validate_success(touching, 201)

    other_zone = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z2", starts_at="2026-09-07T07:00:00Z", ends_at="2026-09-07T09:00:00Z"),
        _manager(store),
    )
    validate_success(other_zone, 201)


def test_labor_window_leading_edge_touching_is_allowed(api):
    """A window ending exactly when another begins does not overlap (half-open).

    PRD §3.8: "Within the same store and `aisle_zone`, a new window must not overlap any existing `PLANNED` or `CONFIRMED` window under half-open semantics — back-to-back windows touching at an endpoint are fine — else `ERR_WINDOW_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/labor_window_half_open_overlap
    """
    store = fixtures.create_store(api)
    validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", starts_at="2026-09-07T08:00:00Z", ends_at="2026-09-07T10:00:00Z"),
            _manager(store),
        ),
        201,
    )
    # New window occupies [06:00, 08:00) — ends exactly at the existing start.
    leading = api.create_labor_window(
        store["id"],
        labor_window_payload(aisle_zone="Z1", starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
        _manager(store),
    )
    validate_success(leading, 201)


def _two_active_finds(api, category):
    """Two ACTIVE FINDS products via separate full tender awards."""
    f1 = fixtures.active_finds_product(api, category, price_cents=199)
    f2 = fixtures.active_finds_product(api, category, price_cents=249)
    return f1, f2


def test_finds_sale_window_inclusive_overlap_and_clearance_gap(api):
    """Sharing the boundary day 2026-09-13 is a conflict; 09-14 start is fine; gap day mandatory.

    PRD §3.5: "Third, sale-window exclusivity: for every store receiving an allocation, no other allocation of that store in `ON_SALE` or `CLEARANCE` status may have an inclusive sale window overlapping the buy's `[week_start_date, week_end_date]` window; a conflict is rejected with `ERR_SALE_WINDOW_CONFLICT`."
    PRD §3.5: "A mandatory gap day separates the programs: the clearance start must be at least one day after the allocation's `sale_end_date`, and an earlier start is rejected with `ERR_CLEARANCE_GAP_VIOLATION`."

    Design: Difficulty/resource_temporal_overlap/finds_sale_window_inclusive_overlap_and_gap
    """
    category = fixtures.create_category(api)
    f1, f2 = _two_active_finds(api, category)
    store = fixtures.create_store(api)

    buy1 = fixtures.finds_buy_on_sale(
        api, f1["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )["buy"]

    buy2 = fixtures.create_finds_buy(
        api, f2["id"], total_quantity=5,
        week_start_date="2026-09-13", week_end_date="2026-09-20",
    )
    buy2 = fixtures.plan_allocations(api, buy2)

    buy3 = fixtures.create_finds_buy(
        api, f2["id"], total_quantity=5,
        week_start_date="2026-09-14", week_end_date="2026-09-20",
    )
    buy3 = fixtures.plan_allocations(api, buy3)

    # Shared boundary day 09-13 counts as overlap under inclusive semantics.
    conflict = api.activate_finds_buy(buy2["id"], CATEGORY_MANAGER_HEADERS)
    validate_error(conflict, "ERR_SALE_WINDOW_CONFLICT", 409)

    # Starting the day after the window ends is fine.
    ok = validate_success(api.activate_finds_buy(buy3["id"], CATEGORY_MANAGER_HEADERS))
    assert ok["status"] == "ON_SALE"

    # Clearance must wait a full gap day after the 09-13 sale end.
    alloc1 = fixtures.buy_allocations(api, buy1["id"])[0]
    gap = api.clearance_allocation(
        alloc1["id"],
        {
            "clearance_markdown_pct": 0.30,
            "clearance_start_date": "2026-09-13",
            "clearance_end_date": "2026-09-19",
        },
        _manager(store),
    )
    validate_error(gap, "ERR_CLEARANCE_GAP_VIOLATION", 409)


def test_finds_sale_window_adjacent_weeks_do_not_conflict(api):
    """A window beginning the day after another ends activates cleanly.

    PRD §3.5: "Third, sale-window exclusivity: for every store receiving an allocation, no other allocation of that store in `ON_SALE` or `CLEARANCE` status may have an inclusive sale window overlapping the buy's `[week_start_date, week_end_date]` window; a conflict is rejected with `ERR_SALE_WINDOW_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/finds_sale_window_inclusive_overlap_and_gap
    """
    category = fixtures.create_category(api)
    f1, f2 = _two_active_finds(api, category)
    fixtures.create_store(api)

    fixtures.finds_buy_on_sale(
        api, f1["id"], total_quantity=5,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    buy2 = fixtures.create_finds_buy(
        api, f2["id"], total_quantity=5,
        week_start_date="2026-09-14", week_end_date="2026-09-20",
    )
    buy2 = fixtures.plan_allocations(api, buy2)

    activated = validate_success(api.activate_finds_buy(buy2["id"], CATEGORY_MANAGER_HEADERS))
    assert activated["status"] == "ON_SALE"
