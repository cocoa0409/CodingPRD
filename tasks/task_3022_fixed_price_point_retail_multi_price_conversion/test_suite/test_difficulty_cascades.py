"""Transitive cascades: a container's receipt gate, and the three hops an item deletion starts."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    E,
    get_success_data,
    SOM_HEADERS,
    validate_error,
    validate_success,
    fixtures,
)



def _item_waiting_on_a_held_container(api):
    """An item at a 125-cent point, an allocation line, and its container on customs hold.

    The container bills 80 cents over the line's 40 allocable units, so the
    container-wide freight rate floors once to 2 cents per unit.
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="6001", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=4.0)
    container = fixtures.create_container_at_port(
        vendor["id"], total_freight_cents=80, on_hold=True)
    fixtures.allocate(container["id"], store["id"], item["id"],
                      sequence=1, requested_units=40)
    return price_point, vendor, store, item, container


def test_the_same_pass_through_is_refused_before_receipt_and_taken_after_it(api):
    """A held container cannot back a charge; once received, the identical write lands.

    PRD §3.2: "The container must be in `RECEIVED`; a pass-through naming a container that is
    not is rejected with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409."
    PRD §3.6: "A customs release is the revert edge: a held container returns to `AT_PORT` once
    the broker clears it, and because `customs_cleared` is set true on arrival at `AT_PORT`, the
    receipt gate is satisfied at that point."
    PRD §3.6: "A received container becomes `RECEIVED`, and that is precisely what makes its
    freight eligible as the container reference of a `FREIGHT_PASS_THROUGH` landed-cost row."
    PRD §3.2: "That sequence is a strictly increasing integer, unique across all landed-cost
    rows, assigned in the order rows are created"

    Design: Difficulty/transitive_cascade/container_hold_cascade_through_item_to_allocation_line
    """
    price_point, vendor, store, item, container = _item_waiting_on_a_held_container(api)

    refused = fixtures.apply_landed_cost(
        item["id"], method="FREIGHT_PASS_THROUGH", applied_amount_cents=107,
        container_id=container["id"])
    validate_error(refused, E.ERR_CONTAINER_NOT_RECEIVED.value)

    waiting = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert waiting["status"] == "PRICE_ASSIGNED", "the refusal wrote no cost row"
    assert waiting["landed_cost_cents"] == 0

    cleared = fixtures.container_customs_release(container["id"])
    assert cleared["status"] == "AT_PORT"
    assert cleared["customs_cleared"] is True, "the release sets customs cleared on the way back"

    received = fixtures.container_receive(container["id"])
    assert received["status"] == "RECEIVED", "receipt is the second gate, satisfied by the release"

    accepted = fixtures.apply_landed_cost(
        item["id"], method="FREIGHT_PASS_THROUGH", applied_amount_cents=107,
        container_id=container["id"])
    history = validate_success(accepted, 201)
    assert history["method"] == "FREIGHT_PASS_THROUGH"
    assert history["applied_amount_cents"] == 107
    assert history["container_id"] == container["id"]
    assert history["effective_sequence"] == 1, "the failed attempt wrote no row"

    item_after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert item_after["landed_cost_cents"] == 107
    assert item_after["status"] == "COST_PENDING"
    # ceil((107 * 4 + 6) / (125 - 4)) == ceil(434 / 121) == 4.
    assert item_after["break_even_units"] == 4


def test_deleting_an_item_reverses_its_lines_and_retracts_the_container(api):
    """The delete cascade moves the line, the container and the store's completion gate.

    PRD §3.9: "Every allocation line whose item is this item and whose status is `ALLOCATED` or
    `SHORTED` is moved to `REVERSED`, and each such line's `released_units` is reset to zero."
    PRD §3.9: "The third hop retracts containers: any container whose remaining `ALLOCATED` line
    count has fallen to zero and which is currently in `ALLOCATED` is moved back to `RECEIVED`."
    PRD §3.6: "Once every allocation line on a received container has reached a terminal status —
    `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to
    `ALLOCATED`."
    PRD §3.8: "A `StoreOperationsManager` cannot complete the conversion until all three booleans
    are true; completing while any one of them is false is rejected with
    `ERR_CONVERSION_PREREQUISITES_UNMET`."

    Design: Difficulty/transitive_cascade/item_deletion_cascade_through_lines_to_store_and_container
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    origin = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_item_in_delete_review(
        price_point["id"], vendor["id"], sku="7001", sqft_per_unit=0.1,
        shelf_package_capacity=4.0, units_per_case=4)

    container = fixtures.create_received_container(vendor["id"], total_freight_cents=1260)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=40)

    conversion = validate_success(
        api.begin_conversion(store["id"], price_point["id"], SOM_HEADERS), 200)
    assert conversion["status"] == "CONVERTING"

    # A completion names the conversion project, which must be opened against the
    # CONVERTING store with two distinct price points and the observed store version.
    project = get_success_data(fixtures.open_conversion_project(
        store["id"], origin["id"], price_point["id"],
        expected_store_version=conversion["version"]), 201)
    validate_success(api.start_conversion_project(project["id"], SOM_HEADERS), 200)

    deleted = validate_success(api.decide_item_deletion(item["id"], "DELETE", BUYER_HEADERS), 200)
    assert deleted["status"] == "DELETED"
    assert deleted["price_point_id"] is None

    lines = validate_success(
        api.list_container_allocation_lines(container["id"], DCO_HEADERS), 200)
    assert len(lines) == 1, "the reversal keeps the row; it does not remove it"
    assert lines[0]["id"] == line["id"]
    assert lines[0]["status"] == "REVERSED", (
        "hop one: the deleted item's ALLOCATED line is reversed"
    )
    assert lines[0]["released_units"] == 0, "hop one also rewinds the released units"

    container_after = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert container_after["status"] == "RECEIVED", (
        "hop two/three: the reversal is what moves the container back out of ALLOCATED"
    )

    completion = api.complete_conversion(store["id"], project["id"], SOM_HEADERS)
    validate_error(completion, E.ERR_CONVERSION_PREREQUISITES_UNMET.value)
    still_converting = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert still_converting["status"] == "CONVERTING"
    assert still_converting["conversion_price_point_id"] == price_point["id"]

def test_a_second_allocation_line_reopens_a_container_that_already_reached_allocated(api):
    """The revert edge runs the opposite way from the auto-advance, on the same computed count.

    PRD §3.6: "Once every allocation line on a received container has reached a terminal status —
    `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to
    `ALLOCATED`."
    PRD §3.6: "Conversely, when a fresh `ALLOCATED` allocation line is created against a container
    that has already reached `ALLOCATED`, the container reverts from `ALLOCATED` back to
    `RECEIVED`, reopening it for release. `ALLOCATED` is the terminal state of the forward path
    but is not a sink."
    PRD §3.9: "The third hop retracts containers: any container whose remaining `ALLOCATED` line
    count has fallen to zero and which is currently in `ALLOCATED` is moved back to `RECEIVED`."

    Design: Difficulty/transitive_cascade/item_deletion_cascade_through_lines_to_store_and_container
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    first = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="7201", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)
    second = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="7202", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)
    third = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="7203", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)

    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], first["id"],
                             sequence=1, requested_units=40)
    fixtures.release_line(line["id"], 40)
    assert validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)[
        "status"] == "ALLOCATED"

    # A fresh line against an ALLOCATED container is what reopens it.
    reopened = fixtures.allocate(container["id"], store["id"], second["id"],
                                 sequence=2, requested_units=40)
    assert reopened["status"] == "ALLOCATED"
    assert validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)[
        "status"] == "RECEIVED"

    # Terminating the remaining live line reaches ALLOCATED, and a further line reopens it again.
    fixtures.short_line(reopened["id"])
    assert validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)[
        "status"] == "ALLOCATED", "every line is terminal, so the container advances"

    third_line = fixtures.allocate(container["id"], store["id"], third["id"],
                                   sequence=3, requested_units=40)
    assert third_line["status"] == "ALLOCATED"
    assert validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)[
        "status"] == "RECEIVED", "a fresh allocation line reopens the container for release"

    lines = validate_success(
        api.list_container_allocation_lines(container["id"], DCO_HEADERS), 200)
    assert sorted(row["status"] for row in lines) == ["ALLOCATED", "RELEASED", "SHORTED"]


def test_a_cost_row_refused_on_state_still_leaves_the_item_where_it_was(api):
    """The first hop's gate is the container's state; the item's own state is never enough.

    PRD §3.2: "A freight pass-through is subject to two hard gates on the container it draws on.
    The container must be in `RECEIVED`; a pass-through naming a container that is not is rejected
    with `ERR_CONTAINER_NOT_RECEIVED` and HTTP 409."
    PRD §3.2: "A vendor price change is subject to neither gate because it references no container."
    PRD §3.2: "That sequence is a strictly increasing integer, unique across all landed-cost rows,
    assigned in the order rows are created"
    PRD §3.6: "A received container becomes `RECEIVED`, and that is precisely what makes its
    freight eligible as the container reference of a `FREIGHT_PASS_THROUGH` landed-cost row."

    Design: Difficulty/transitive_cascade/container_hold_cascade_through_item_to_allocation_line
    """
    price_point, vendor, store, item, container = _item_waiting_on_a_held_container(api)

    # The very same endpoint accepts a container-free vendor revision while the gate is shut.
    revision = validate_success(
        fixtures.apply_landed_cost(item["id"], applied_amount_cents=104), 201)
    assert revision["container_id"] is None, "a vendor revision references no container"
    assert revision["effective_sequence"] == 1

    still_refused = fixtures.apply_landed_cost(
        item["id"], method="FREIGHT_PASS_THROUGH", applied_amount_cents=107,
        container_id=container["id"])
    validate_error(still_refused, E.ERR_CONTAINER_NOT_RECEIVED.value)

    after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert after["status"] == "COST_PENDING", "the accepted revision moved the lifecycle"
    assert after["landed_cost_cents"] == 104, "the refused pass-through recorded nothing"

    rows = validate_success(api.list_item_landed_costs(item["id"], ANALYST_HEADERS), 200)
    assert len(rows) == 1 and rows[0]["method"] == "VENDOR_PRICE_CHANGE"
