"""Conserved quantities that a forward action and its compensating action must leave alone."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    DCO_HEADERS,
    SOM_HEADERS,
    get_success_data,
    validate_success,
    fixtures,
)



def test_the_bound_store_count_returns_to_its_prior_value_after_a_rollback(api):
    """The forward begin raises the bound-store count and the rollback restores it exactly.

    PRD §3.8: "The rollback is the compensating action for an opening, and the pair is designed
    to be net-neutral on how many stores are bound to a price point: after a rollback, the number
    of stores carrying a non-null `conversion_price_point_id` is the same as it was immediately
    before the matching conversion began."
    PRD §3.8: "On acceptance the store moves to `CONVERTING`, `conversion_price_point_id` is set
    to the target, and `sign_order_filed`, `shelf_tag_filed` and `register_file_locked` are all
    reset to false."
    PRD §3.8: "Rolling back returns the store to `SINGLE_PRICE`, nulls `conversion_price_point_id`,
    moves the project to `ROLLBACK`, and resets all three artefact flags to false."

    Design: Difficulty/compensating_invariant/store_price_binding_count_invariant_across_begin_and_rollback
    """
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store()

    assert fixtures.store_bound_to_point_count(origin["id"]) == 0, "nothing is bound before the begin"

    began = validate_success(api.begin_conversion(store["id"], origin["id"], SOM_HEADERS), 200)
    assert began["status"] == "CONVERTING"
    mid = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert mid["conversion_price_point_id"] == origin["id"]
    assert fixtures.store_bound_to_point_count(origin["id"]) == 1, (
        "the forward begin is the only thing that raised the conserved quantity"
    )

    project = get_success_data(fixtures.open_conversion_project(
        store["id"], origin["id"], target["id"], expected_store_version=began["version"]), 201)
    project = validate_success(
        fixtures.api_client.start_conversion_project(project["id"], SOM_HEADERS), 200)
    assert project["status"] == "IN_PROGRESS"

    rolled = validate_success(
        fixtures.rollback_conversion(store["id"], project["id"]), 200)
    assert rolled["status"] == "SINGLE_PRICE"
    assert rolled["conversion_price_point_id"] is None
    assert rolled["sign_order_filed"] is False
    assert rolled["shelf_tag_filed"] is False
    assert rolled["register_file_locked"] is False

    assert fixtures.store_bound_to_point_count(origin["id"]) == 0, (
        "the compensating action restored the invariant instead of leaving drift behind"
    )


def test_a_reversal_gives_back_the_units_a_release_put_on_hand(api):
    """Releasing 40 units raises on-hand to 40; the reversal driven by deletion returns it to 0.

    PRD §3.9: "Every allocation line whose item is this item and whose status is `ALLOCATED` or
    `SHORTED` is moved to `REVERSED`, and each such line's `released_units` is reset to zero."
    PRD §3.7: "this is the cross-entity hop that matters — adds the same quantity to the item's
    `on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand units
    multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`."
    PRD §3.9: "Deleting an item also gives back the freight that had been absorbed on its behalf.
    This is a container-level invariant that must hold once the cascade settles"
    PRD §3.6: "Once every allocation line on a received container has reached a terminal status —
    `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to
    `ALLOCATED`."

    Design: Difficulty/compensating_invariant/on_hand_units_conserved_by_allocation_line_reversal
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="9501", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=4.0)

    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=40)
    released = fixtures.release_line(line["id"], 20)
    assert released["status"] == "ALLOCATED", "a partial release leaves the line open"

    mid = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert mid["on_hand_units"] == 20

    # A cost that outruns the retail queues the item, and the DELETE decision starts the cascade.
    pushed = fixtures.apply_landed_cost(item["id"], applied_amount_cents=128)
    validate_success(pushed, 201)
    queued = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert queued["status"] == "DELETE_REVIEW"

    deleted = validate_success(
        api.decide_item_deletion(item["id"], "DELETE", BUYER_HEADERS), 200)
    assert deleted["status"] == "DELETED"

    # PRD §3.9's hop 1 declares the reversal's own side effects: the line's status
    # becomes REVERSED and its released_units is reset to zero (it does not say the
    # item's on_hand_units is rewound, so that quantity is not asserted here).
    line_after = validate_success(api.get_allocation_line(line["id"], DCO_HEADERS), 200)
    assert line_after["status"] == "REVERSED"
    assert line_after["released_units"] == 0
    assert line_after["remaining_units"] == 0

    # The reversal is itself what moves the container from ALLOCATED to RECEIVED, since
    # every line on it is now terminal and the recompute is part of hop 2/3 (PRD §3.6/§3.9).
    container_after = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert container_after["status"] == "RECEIVED", (
        "the reversal bubbled the container out of ALLOCATED"
    )

def test_a_partial_release_then_a_partial_reversal_restores_the_original_on_hand(api):
    """Seventeen units released and then given back leave the on-hand exactly where it started.

    PRD §3.9: "Every allocation line whose item is this item and whose status is `ALLOCATED` or
    `SHORTED` is moved to `REVERSED`, and each such line's `released_units` is reset to zero."
    PRD §3.7: "this is the cross-entity hop that matters — adds the same quantity to the item's
    `on_hand_units`, from which the item's `is_shelf_overflow` flag is recomputed as on-hand units
    multiplied by `sqft_per_unit` being greater than `shelf_package_capacity`."
    PRD §3.6: "Once every allocation line on a received container has reached a terminal status —
    `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to
    `ALLOCATED`."

    Design: Difficulty/compensating_invariant/on_hand_units_conserved_by_allocation_line_reversal
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="9601", sqft_per_unit=0.1,
        shelf_package_capacity=4.0)

    container = fixtures.create_received_container(vendor["id"], total_freight_cents=0)
    line = fixtures.allocate(container["id"], store["id"], item["id"],
                             sequence=1, requested_units=30)
    assert line["allocated_units"] == 30

    partial = fixtures.release_line(line["id"], 17)
    assert partial["status"] == "ALLOCATED", "seventeen of thirty released leaves the line open"
    assert partial["remaining_units"] == 13

    mid = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert mid["on_hand_units"] == 17

    validate_success(fixtures.apply_landed_cost(item["id"], applied_amount_cents=128), 201)
    deleted = validate_success(
        api.decide_item_deletion(item["id"], "DELETE", BUYER_HEADERS), 200)
    assert deleted["status"] == "DELETED"

    line_after = validate_success(api.get_allocation_line(line["id"], DCO_HEADERS), 200)
    assert line_after["status"] == "REVERSED"
    assert line_after["released_units"] == 0
    assert line_after["remaining_units"] == 0

    # The reversal is itself what moves the container from ALLOCATED to RECEIVED (hop 3):
    # every line is now terminal, and the container was ALLOCATED before the delete.
    container_after = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert container_after["status"] == "RECEIVED", (
        "the reversal reopened the container instead of leaving it stuck at ALLOCATED"
    )


def test_the_freight_invariant_holds_once_the_deletion_cascade_settles(api):
    """Giving back the freight leaves nothing stranded on the container the item left.

    PRD §3.9: "Deleting an item also gives back the freight that had been absorbed on its behalf.
    This is a container-level invariant that must hold once the cascade settles: for each affected
    container, the sum over all of its non-`REVERSED` allocation lines of the quantity
    `applied_amount_cents` minus the item's `base_landed_cost_cents`, multiplied by the line's
    `allocated_units`, is exactly zero."
    PRD §3.9: "Every allocation line whose item is this item and whose status is `ALLOCATED` or
    `SHORTED` is moved to `REVERSED`, and each such line's `released_units` is reset to zero."
    PRD §3.6: "Once every allocation line on a received container has reached a terminal status —
    `RELEASED`, `SHORTED` or `REVERSED` — the container auto-advances from `RECEIVED` to
    `ALLOCATED`."

    Design: Difficulty/compensating_invariant/on_hand_units_conserved_by_allocation_line_reversal
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    store = fixtures.create_store()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="9701", base_landed_cost_cents=105,
        sqft_per_unit=0.1, shelf_package_capacity=4.0)

    container, lines = fixtures.build_received_container(
        vendor["id"], store["id"],
        [{"item_id": item["id"], "sequence": 1, "requested_units": 40}],
        total_freight_cents=80,
    )
    line = lines[0]
    assert line["allocated_units"] == 40

    absorbed = validate_success(
        api.apply_landed_cost(
            item["id"],
            {"method": "FREIGHT_PASS_THROUGH", "applied_amount_cents": 107,
             "container_id": container["id"]},
            BUYER_HEADERS),
        201,
    )
    assert absorbed["applied_amount_cents"] - item["base_landed_cost_cents"] == 2, (
        "80 // 40 == 2, so the container-wide rate is two cents before the item is reversed"
    )

    validate_success(fixtures.apply_landed_cost(item["id"], applied_amount_cents=128), 201)
    deleted = validate_success(
        api.decide_item_deletion(item["id"], "DELETE", BUYER_HEADERS), 200)
    assert deleted["status"] == "DELETED"

    settled = validate_success(
        api.list_container_allocation_lines(container["id"], DCO_HEADERS), 200)
    surviving_lines = [row for row in settled if row["status"] != "REVERSED"]
    assert surviving_lines == [], "the deleted item's line was reversed by the cascade"

    # PRD §3.9: the per-container invariant sums over the NON-REVERSED lines of
    # (applied_amount_cents - base_landed_cost_cents) * allocated_units and must be
    # exactly zero. Once the item's line is reversed it contributes nothing, so the
    # invariant is satisfied precisely because the reversal rewinds the line.
    total_absorbed = sum(
        (absorbed["applied_amount_cents"] - item["base_landed_cost_cents"]) * row["allocated_units"]
        for row in surviving_lines
    )
    assert total_absorbed == 0, (
        "the pass-through absorbed on the container is given back by the deletion, not stranded"
    )
    read = validate_success(api.get_container(container["id"], ANALYST_HEADERS), 200)
    assert read["status"] == "RECEIVED", "the reversal bubbled the container out of ALLOCATED"
