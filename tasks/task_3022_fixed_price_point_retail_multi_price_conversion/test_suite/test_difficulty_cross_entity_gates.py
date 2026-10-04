"""Edges whose precondition reads a different entity's state."""

from test_helpers import (
    ANALYST_HEADERS,
    DCO_HEADERS,
    E,
    PLANNER_HEADERS,
    IMPORT_HEADERS,
    SOM_HEADERS,
    api_client,
    validate_error,
    validate_success,
    fixtures,
)



def test_a_release_is_refused_until_the_container_is_received(api):
    """The line's own ALLOCATED state is never the binding constraint on a release.

    PRD §3.7: "A release is also gated on the container, not merely on the line: the line's
    container must be in `RECEIVED`, and a release attempted against a line whose container has
    not been received is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409."
    PRD §3.7: "When the line's `remaining_units` reaches zero the line becomes `RELEASED` and its
    `released_units` equals its `allocated_units`."
    PRD §3.7: "this is the cross-entity hop that matters — adds the same quantity to the item's
    `on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand units
    multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`."

    Design: Difficulty/cross_entity_state_dependency/release_gated_on_container_receive_state
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_active_item(
        price_point["id"], vendor["id"], sku="9001", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=4.0)

    container = fixtures.create_container_at_port(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=40)
    assert line["status"] == "ALLOCATED"
    assert line["remaining_units"] == 40

    refused = api_client.release_allocation_line(line["id"], 40, DCO_HEADERS)
    validate_error(refused, E.ERR_CONTAINER_NOT_RECEIVED.value)
    untouched = validate_success(api.get_allocation_line(line["id"], ANALYST_HEADERS), 200)
    assert untouched["status"] == "ALLOCATED", "the refused release left the line where it was"
    assert untouched["remaining_units"] == 40
    assert untouched["released_units"] == 0

    fixtures.container_receive(container["id"])
    released = validate_success(fixtures.api_client.release_allocation_line(
        line["id"], 40, DCO_HEADERS), 200)
    assert released["status"] == "RELEASED"
    assert released["released_units"] == 40
    assert released["remaining_units"] == 0

    item_after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert item_after["on_hand_units"] == 40
    # 40 * 0.1 == 4.0, which does not exceed the 4.0 shelf, so the overflow flag stays false.
    assert item_after["is_shelf_overflow"] is False
    assert item_after["price_point_id"] == price_point["id"], (
        "releasing units moves stock, not the price binding"
    )

    second = api_client.release_allocation_line(line["id"], 1, DCO_HEADERS)
    validate_error(second, E.ERR_ALLOCATION_LINE_NOT_ALLOCATED.value)


def test_a_reset_cannot_begin_while_its_window_is_unopened_or_the_clock_has_not_reached_it(api):
    """The begin edge reads both its window's state and the clock against the reset's own start.

    PRD §3.10: "A reset moves from `PLANNED` to `EXECUTING` only when three conditions hold
    together: the reset is currently `PLANNED`, otherwise `ERR_AISLE_RESET_NOT_PLANNED`; its
    season window is `OPEN`, otherwise `ERR_SEASON_WINDOW_NOT_OPEN`; and the logical clock has
    reached the reset's `starts_at`, otherwise `ERR_RESET_OUTSIDE_CALENDAR`."
    PRD §3.10: "The same containment rule is re-checked at the moment the reset begins
    executing, so a reset that was legal at planning time but is being begun outside its window
    is still refused."
    PRD §2.9: "Once the clock reaches `opens_on` and remains at or before `closes_on`, the window
    reads `OPEN`."

    Design: Difficulty/cross_entity_state_dependency/conversion_completion_gated_on_season_window_and_line_states
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    store = fixtures.create_store()
    validate_success(api.begin_conversion(store["id"], price_point["id"], SOM_HEADERS), 200)

    window = fixtures.create_draft_season_window(
        opens_on="2026-10-01T00:00:00Z", closes_on="2026-10-31T00:00:00Z")
    # The reset interval sits inside the calendar but the clock has not reached either bound.
    reset = fixtures.plan_reset_ok(
        store["id"], price_point["id"], window["id"], aisle_code="A11",
        starts_at="2026-10-05T00:00:00Z", ends_at="2026-10-10T00:00:00Z",
        allocated_shelf_sqft=50.0)

    unopened = api.begin_aisle_reset(reset["id"], PLANNER_HEADERS)
    validate_error(unopened, E.ERR_SEASON_WINDOW_NOT_OPEN.value)
    assert validate_success(
        api.get_aisle_reset(reset["id"], ANALYST_HEADERS), 200)["status"] == "PLANNED"

    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["status"] == "CONVERTING"
    assert store_after["conversion_price_point_id"] == price_point["id"]

    # Publish the window and advance the clock past opens_on, but the reset's own start is still
    # days away, so containment fails even though the window now reads OPEN.
    fixtures.set_clock("2026-10-02T00:00:00Z")
    published = validate_success(
        api.schedule_season_window(window["id"], PLANNER_HEADERS), 200)
    assert published["status"] == "OPEN"

    still_early = api.begin_aisle_reset(reset["id"], PLANNER_HEADERS)
    validate_error(still_early, E.ERR_RESET_OUTSIDE_CALENDAR.value)


def test_a_conversion_completion_needs_the_filed_artefacts_before_it_reaches_the_store(api):
    """The completion edge is refused while the artefact flags are still false.

    PRD §3.8: "A `StoreOperationsManager` cannot complete the conversion until all three
    booleans are true; completing while any one of them is false is rejected with
    `ERR_CONVERSION_PREREQUISITES_UNMET`."
    PRD §3.8: "The store must still be in `CONVERTING` — a completion attempted elsewhere,
    including on a `REVERTING` store through the wrong path, is rejected with
    `ERR_STORE_NOT_CONVERTING`."
    PRD §3.8: "The conversion project for the change must be `IN_PROGRESS`, and a project in any
    other state is rejected with `ERR_CONVERSION_NOT_IN_PROGRESS`."

    Design: Difficulty/cross_entity_state_dependency/conversion_completion_gated_on_season_window_and_line_states
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store()

    state = fixtures.conversion_in_progress(store["id"], origin["id"], target["id"])
    mid = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert mid["sign_order_filed"] is False
    assert mid["shelf_tag_filed"] is False
    assert mid["register_file_locked"] is False

    refused = api_client.complete_conversion(store["id"], state["conversion_id"], SOM_HEADERS)
    validate_error(refused, E.ERR_CONVERSION_PREREQUISITES_UNMET.value)

    stayed = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert stayed["status"] == "CONVERTING"
    assert stayed["conversion_price_point_id"] == target["id"], (
        "neither refusal moved the store off its conversion binding"
    )
    project = validate_success(
        api.get_conversion_project(state["conversion_id"], ANALYST_HEADERS), 200)
    assert project["status"] == "IN_PROGRESS"

def test_a_release_against_a_still_customs_held_container_is_refused(api):
    """The gate reads the container's live status, so a hold blocks a release the line permits.

    PRD §3.7: "A release is also gated on the container, not merely on the line: the line's
    container must be in `RECEIVED`, and a release attempted against a line whose container has
    not been received is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409."
    PRD §3.6: "A customs hold moves the container to `CUSTOMS_HOLD` and clears `customs_cleared`
    back to false; it is refused from any status other than `AT_PORT` with `ERR_CONTAINER_NOT_AT_PORT`."
    PRD §3.7: "This gate is the reason a line's own status is never sufficient authority to
    release."

    Design: Difficulty/cross_entity_state_dependency/release_gated_on_container_receive_state
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_active_item(
        price_point["id"], vendor["id"], sku="9101", base_landed_cost_cents=105)

    container = fixtures.create_container_at_port(vendor["id"], total_freight_cents=0, on_hold=True)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=40)
    assert line["status"] == "ALLOCATED"
    assert container["customs_cleared"] is False

    validate_error(
        api_client.release_allocation_line(line["id"], 40, DCO_HEADERS),
        E.ERR_CONTAINER_NOT_RECEIVED.value,
    )
    untouched = validate_success(api.get_allocation_line(line["id"], ANALYST_HEADERS), 200)
    assert untouched["status"] == "ALLOCATED"
    assert untouched["remaining_units"] == 40
    assert validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)["on_hand_units"] == 0

    # The customs hold itself cannot be followed by a receipt, because the status is not AT_PORT.
    validate_error(
        api_client.container_receive(container["id"], IMPORT_HEADERS),
        E.ERR_CONTAINER_NOT_AT_PORT.value,
    )

    fixtures.container_customs_release(container["id"])
    fixtures.container_receive(container["id"])

    released = validate_success(
        api_client.release_allocation_line(line["id"], 40, DCO_HEADERS), 200)
    assert released["status"] == "RELEASED"
    assert validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)["on_hand_units"] == 40
