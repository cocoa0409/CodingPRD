"""Cyclic lifecycles: the item's cost-revision loop and the store's conversion-then-rollback loop."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    E,
    SOM_HEADERS,
    get_success_data,
    validate_error,
    validate_success,
    fixtures,
)


BEFORE_COST_QUOTE = "Before an item has taken any cost, that binding may be undone."

def _revised_item(api):
    """A price-assigned item whose first revision round outruns its retail and whose second does not."""
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    item = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="5001", base_landed_cost_cents=115)
    return price_point, vendor, item


def test_a_cost_revision_round_can_queue_an_item_for_deletion_and_the_next_round_clear_it(api):
    """The second revision round walks the item back out of deletion review and activation follows.

    PRD §3.2: "The same branching governs the cyclical `COST_PENDING` re-application path: each
    additional landed-cost write on an already-`COST_PENDING` item re-runs the identical test and
    can push it to `DELETE_REVIEW` on the same terms."
    PRD §3.2: "a `COST_PENDING` item accepts further landed-cost applications that leave it in
    `COST_PENDING`, each one appending a fresh history row and re-deriving the item's cost
    fields"
    PRD §3.2: "The item's `landed_cost_cents` is recomputed from whichever row currently holds
    that highest sequence"
    PRD §3.4: "An item may be cleared to sell only from `COST_PENDING`; an item in any other state
    is rejected with `ERR_ITEM_NOT_COST_PENDING`."

    Design: Difficulty/non_linear_state_machine/item_delete_review_round_trip_and_pristine_release
    """
    price_point, vendor, item = _revised_item(api)

    # Round one: 130 cents of landed cost outruns the retail, so no curing pack exists.
    first_round = fixtures.apply_landed_cost(item["id"], applied_amount_cents=130)
    validate_success(first_round, 201)
    after_first = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert after_first["status"] == "DELETE_REVIEW", (
        "130 minus the 125-cent retail and the 4-cent variable cost is a loss with no pack to cure it"
    )
    assert after_first["break_even_units"] == 0

    # Round two: the vendor revises down to a non-negative contribution. The item has
    # left COST_PENDING for DELETE_REVIEW, and PRD §3.4 gives DELETE_REVIEW → ACTIVE as
    # its only forward edge, so the landed-cost write moves the item to ACTIVE with the
    # fresh row as its current cost.
    second_round = fixtures.apply_landed_cost(item["id"], applied_amount_cents=115)
    validate_success(second_round, 201)
    after_second = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert after_second["status"] == "ACTIVE", (
        "a recovered contribution clears the item rather than returning it to COST_PENDING"
    )
    assert after_second["landed_cost_cents"] == 115, "the latest sequence row is the current cost"

    history = get_success_data(api.list_item_landed_costs(item["id"], ANALYST_HEADERS))
    assert len(history) == 2, "each revision round appended a row; nothing was overwritten"
    assert {row["applied_amount_cents"] for row in history} == {130, 115}

    cleared = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert cleared["status"] == "ACTIVE"
    assert cleared["landed_cost_cents"] == 115


def test_price_assignment_release_is_legal_only_before_any_cost_row_exists(api):
    """A pristine item may be released; an item carrying a cost row may not.

    PRD §3.1: "Before an item has taken any cost, that binding may be undone."
    PRD §3.1: "A price-assignment release returns an item from `PRICE_ASSIGNED` to
    `DENOMINATED`, nulls `price_point_id`, and is refused with `ERR_ITEM_NOT_PRICE_ASSIGNED` for
    any item not currently in `PRICE_ASSIGNED`."

    Design: Difficulty/non_linear_state_machine/item_delete_review_round_trip_and_pristine_release
    """
    price_point, vendor, item = _revised_item(api)

    pristine = fixtures.price_assign_item(
        fixtures.create_item(vendor["id"], sku="5003")["id"], price_point["id"])
    released = validate_success(
        api.release_item_price_assignment(pristine["id"], BUYER_HEADERS), 200)
    assert released["status"] == "DENOMINATED"
    assert released["price_point_id"] is None, "the release clears the binding"

    # Once the item has taken a cost row it is no longer PRICE_ASSIGNED, so the release is refused.
    validate_success(fixtures.apply_landed_cost(item["id"], applied_amount_cents=115), 201)
    assert validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)["status"] == "COST_PENDING"
    validate_error(
        api.release_item_price_assignment(item["id"], BUYER_HEADERS),
        E.ERR_ITEM_NOT_PRICE_ASSIGNED.value,
    )
    after = validate_success(api.get_item(item["id"], ANALYST_HEADERS), 200)
    assert after["status"] == "COST_PENDING"
    assert after["price_point_id"] == price_point["id"], "the refused release nulled nothing"


def _converting_store(api):
    """A store mid-change toward a 300-cent point, plus its 125-cent origin point."""
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store()
    return origin, target, store


def test_a_second_begin_is_refused_and_a_rollback_needs_a_real_project(api):
    """CONVERTING has no edge back to itself, and the rollback resolves its project first.

    PRD §3.8: "The first call begins the change: a store currently in `SINGLE_PRICE` may be
    converted to a target price point, and if it is not in `SINGLE_PRICE` the attempt is rejected
    with `ERR_STORE_NOT_SINGLE_PRICE`"
    PRD §2.8: "The rejection carries an HTTP 404 and an error id specific to the resource type
    that failed"
    PRD §3.8: "A rollback is permitted while the store is in `CONVERTING` or in `REVERTING`, and
    is refused from any other state with `ERR_STORE_NOT_CONVERTING`"

    Design: Difficulty/non_linear_state_machine/store_conversion_reverts_through_a_rollback_edge
    """
    origin, target, store = _converting_store(api)

    began = validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    assert began["status"] == "CONVERTING"
    assert began["conversion_price_point_id"] == target["id"]

    second = api.begin_conversion(store["id"], origin["id"], SOM_HEADERS)
    validate_error(second, E.ERR_STORE_NOT_SINGLE_PRICE.value)

    unknown_project = api.rollback_conversion(
        store["id"], "00000000-0000-4000-8000-000000000000", SOM_HEADERS)
    validate_error(unknown_project, E.ERR_CONVERSION_PROJECT_NOT_FOUND.value)

    state = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert state["status"] == "CONVERTING", "neither refusal moved the store"
    assert state["status"] != "MULTI_PRICE", "the completion branch was never taken"
    assert state["conversion_price_point_id"] == target["id"]
    assert state["sign_order_filed"] is False
    assert state["shelf_tag_filed"] is False
    assert state["register_file_locked"] is False


def test_the_rollback_branch_returns_the_store_to_its_own_start_state(api):
    """A real project's rollback lands the store back in SINGLE_PRICE with the binding cleared.

    PRD §3.8: "Rolling back returns the store to `SINGLE_PRICE`, nulls
    `conversion_price_point_id`, moves the project to `ROLLBACK`, and resets all three artefact
    flags to false."
    PRD §3.8: "A project is started into execution only from `DRAFT` — a start from any other
    state is rejected with `ERR_CONVERSION_NOT_DRAFT`"
    PRD §3.8: "the number of stores carrying a non-null `conversion_price_point_id` is the same
    as it was immediately before the matching conversion began."

    Design: Difficulty/non_linear_state_machine/store_conversion_reverts_through_a_rollback_edge
    """
    origin, target, store = _converting_store(api)

    state = fixtures.conversion_in_progress(store["id"], origin["id"], target["id"])
    assert state["project"]["status"] == "IN_PROGRESS"

    rolled_back = validate_success(
        api.rollback_conversion(store["id"], state["conversion_id"], SOM_HEADERS), 200)
    assert rolled_back["status"] == "SINGLE_PRICE"
    assert rolled_back["conversion_price_point_id"] is None
    assert rolled_back["sign_order_filed"] is False

    project = validate_success(
        api.get_conversion_project(state["conversion_id"], ANALYST_HEADERS), 200)
    assert project["status"] == "ROLLBACK"

    assert fixtures.store_bound_to_point_count(origin["id"]) == 0, (
        "the compensating rollback leaves no store bound to the outgoing price point"
    )