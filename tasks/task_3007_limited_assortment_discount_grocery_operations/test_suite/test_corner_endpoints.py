"""Endpoint behaviors: labor window confirm/cancel and conditional clearance."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import fixtures, make_store_manager_headers
from test_helpers.factories import labor_window_payload


def _manager(store):
    return make_store_manager_headers(store["id"])


def test_labor_window_confirm_then_confirm_after_cancel_rejected(api):
    """Confirm moves PLANNED -> CONFIRMED; confirming a CANCELLED window fails.

    PRD §3.8: "Confirmation moves a `PLANNED` window `PLANNED → CONFIRMED`; it is a `StoreManager` action restricted to the manager's own store. Cancellation is available from either `PLANNED` or `CONFIRMED` and moves the window to the terminal `CANCELLED` state, removing its cost from the weekly spend aggregation so the budget re-aggregates without it."

    Design: Corner/endpoints/labor_window_confirm_action_endpoint
    """
    store = fixtures.create_store(api)
    window = validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", role="STOCKER",
                                 starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            _manager(store),
        ),
        201,
    )

    confirmed = validate_success(api.confirm_labor_window(window["id"], _manager(store)))
    assert confirmed["status"] == "CONFIRMED"

    validate_success(api.cancel_labor_window(window["id"], _manager(store)))

    response = api.confirm_labor_window(window["id"], _manager(store))
    validate_error(response, "ERR_INVALID_STATE", 409)


def test_labor_window_cancel_from_planned(api):
    """Cancellation is available directly from PLANNED.

    PRD §3.8: "Confirmation moves a `PLANNED` window `PLANNED → CONFIRMED`; it is a `StoreManager` action restricted to the manager's own store. Cancellation is available from either `PLANNED` or `CONFIRMED` and moves the window to the terminal `CANCELLED` state, removing its cost from the weekly spend aggregation so the budget re-aggregates without it."

    Design: Corner/endpoints/labor_window_confirm_action_endpoint
    """
    store = fixtures.create_store(api)
    window = validate_success(
        api.create_labor_window(
            store["id"],
            labor_window_payload(aisle_zone="Z1", role="STOCKER",
                                 starts_at="2026-09-07T06:00:00Z", ends_at="2026-09-07T08:00:00Z"),
            _manager(store),
        ),
        201,
    )
    assert window["status"] == "PLANNED"

    cancelled = validate_success(api.cancel_labor_window(window["id"], _manager(store)))
    assert cancelled["status"] == "CANCELLED"


def test_clearance_on_sold_out_allocation_rejected(api):
    """Clearance requires an ON_SALE allocation with stock; SOLD_OUT fails ERR_INVALID_STATE.

    PRD §3.5: "A `StoreManager` may move an `ON_SALE` allocation with `remaining_quantity` above zero into `CLEARANCE`, supplying a `clearance_markdown_pct` — a markdown fraction strictly between 0 and 1, such as 0.30 — plus a `clearance_start_date` and `clearance_end_date`."

    Design: Corner/endpoints/conditional_action_clearance_only_with_stock
    """
    category = fixtures.create_category(api)
    product = fixtures.active_finds_product(api, category)
    store = fixtures.create_store(api)
    world = fixtures.finds_buy_on_sale(
        api, product["id"], total_quantity=1,
        week_start_date="2026-09-07", week_end_date="2026-09-13",
    )
    alloc = world["allocations"][0]
    manager = _manager(store)

    fixtures.set_clock(api, "2026-09-08T10:00:00Z")
    sold = validate_success(api.sell_allocation(alloc["id"], {"quantity": 1}, manager))
    assert sold["status"] == "SOLD_OUT"

    response = api.clearance_allocation(
        alloc["id"],
        {
            "clearance_markdown_pct": 0.30,
            "clearance_start_date": "2026-09-14",
            "clearance_end_date": "2026-09-20",
        },
        manager,
    )
    validate_error(response, "ERR_INVALID_STATE", 409)
