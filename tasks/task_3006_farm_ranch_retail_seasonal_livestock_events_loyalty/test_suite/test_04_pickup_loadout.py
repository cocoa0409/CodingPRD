"""Pickup order parallel fulfillment/loadout dimensions."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_account,
    create_open_store,
    create_pickup_order,
    create_staging_bay,
    make_customer_headers,
    set_clock,
    setup_ready_pickup,
    validate_error,
    validate_success,
)

MGR = TEST_USERS["store_manager_headers"]
ASSOC = TEST_USERS["store_associate_headers"]

FLOOR_NOW = "2026-09-10T09:00:00Z"


def test_loadout_dimension_moves_independently_of_fulfillment(api):
    """PRD §3.8: "The order begins with `fulfillment_status` `PLACED` and `loadout_status` `NOT_REQUIRED` — two parallel dimensions that evolve independently until the fulfillment dimension reaches a terminal state"
    PRD §3.8: "Load-out assistance is requested by the customer on their own order, but only once it is `READY_FOR_PICKUP` ... the request moves it to `ASSISTANCE_REQUESTED`."

    Design: Difficulty/non_linear_state_machine/pickup_order_parallel_fulfillment_and_loadout_dimensions
    """
    ctx = setup_ready_pickup(
        clock=FLOOR_NOW, item_size_class="L", requires_loadout_assistance=True,
        item_sku="GUN-SAFE-72",
    )
    order_id = ctx["order"]["id"]

    requested = validate_success(
        api.request_loadout(order_id, make_customer_headers(ctx["account"]["id"]))
    )
    assert requested["loadout_status"] == "ASSISTANCE_REQUESTED"
    assert requested["fulfillment_status"] == "READY_FOR_PICKUP"


def test_loadout_request_gates_fulfillment_completion(api):
    """PRD §3.8: "Completion, also by an associate, requires the order still `READY_FOR_PICKUP` and respects both dimensions: if the load-out dimension sits at `ASSISTANCE_REQUESTED`, completion is refused with `ERR_LOADOUT_NOT_COMPLETED` until the load-out is done"
    PRD §3.8: "A clean completion moves the order `READY_FOR_PICKUP → COMPLETED` and releases the bay to `AVAILABLE`."

    Design: Difficulty/non_linear_state_machine/pickup_order_parallel_fulfillment_and_loadout_dimensions
    """
    ctx = setup_ready_pickup(
        clock=FLOOR_NOW, item_size_class="L", requires_loadout_assistance=True,
        item_sku="GUN-SAFE-72",
    )
    order_id = ctx["order"]["id"]
    cust = make_customer_headers(ctx["account"]["id"])

    validate_success(api.request_loadout(order_id, cust))
    resp = api.complete_pickup_order(order_id, ASSOC)
    validate_error(resp, ApiErrorId.ERR_LOADOUT_NOT_COMPLETED)

    # Loadout advances without touching fulfillment; then completion succeeds.
    done = validate_success(api.complete_loadout(order_id, ASSOC))
    assert done["loadout_status"] == "LOADOUT_DONE"
    assert done["fulfillment_status"] == "READY_FOR_PICKUP"

    completed = validate_success(api.complete_pickup_order(order_id, ASSOC))
    assert completed["fulfillment_status"] == "COMPLETED"

    bay = validate_success(api.get_staging_bay(ctx["order"]["staging_bay_id"], MGR))
    assert bay["status"] == "AVAILABLE"
