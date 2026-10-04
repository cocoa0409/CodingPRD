"""Which rule answers first when one request violates two of them."""

from test_helpers import (
    ANALYST_HEADERS,
    BUYER_HEADERS,
    E,
    SOM_HEADERS,
    validate_error,
    validate_success,
    fixtures,
)





def _store_converting_with_a_planned_reset(api):
    """A store mid-change to 300 cents with one PLANNED reset already occupying aisle A14."""
    fixtures.set_clock()
    origin = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    target = fixtures.create_price_point(300, 0.40, label="THREE_DOLLAR_25")
    store = fixtures.create_store(shelf_facing_capacity_sqft=400.0)
    validate_success(api.begin_conversion(store["id"], target["id"], SOM_HEADERS), 200)
    window = fixtures.create_open_season_window(
        opens_on="2026-09-01T00:00:00Z", closes_on="2026-11-30T00:00:00Z")
    existing = fixtures.plan_reset_ok(
        store["id"], target["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-05T00:00:00Z", ends_at="2026-09-20T00:00:00Z",
        allocated_shelf_sqft=200.0)
    return origin, target, store, window, existing


def test_the_conflicting_activation_request_reports_the_state_error(api):
    """A request violating both the state gate and the contribution gate answers with the state error.

    PRD §2.8: "The full precedence chain, from first to last, is: the two authentication checks
    of §2.1; path-identifier resolution, left to right; body foreign-key resolution, in declared
    order; the acting resource's required source state, checked against the `from` state its
    transition declares and reported with that transition's state error at HTTP 409"
    PRD §2.8: "and finally the endpoint-specific business constraints, each reported with its own
    error id. When several validations could fire on one request, the earlier category in this
    chain wins and its error id is the one returned."
    PRD §3.4: "An item may be cleared to sell only from `COST_PENDING`; an item in any other
    state is rejected with `ERR_ITEM_NOT_COST_PENDING`."
    PRD §3.4: "If no such pack exists, the item is pushed automatically from `COST_PENDING` into
    `DELETE_REVIEW` — this transition is reached from the landed-cost write's own side-effect
    chain and is never triggered by a direct client call."

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_constraint_on_activation
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    covered = fixtures.create_active_item(
        price_point["id"], vendor["id"], sku="8001", base_landed_cost_cents=112)
    losing = fixtures.create_item_in_delete_review(
        price_point["id"], vendor["id"], sku="8002", base_landed_cost_cents=128)
    assert losing["status"] == "DELETE_REVIEW"
    assert losing["net_contribution_cents_per_unit"] == -7

    # The already-ACTIVE item is refused on state alone: ACTIVE is not COST_PENDING.
    validate_error(
        api.activate_item(covered["id"], BUYER_HEADERS), E.ERR_ITEM_NOT_COST_PENDING.value)

    # The losing item violates the state gate and the contribution gate at once.
    refused = api.activate_item(losing["id"], BUYER_HEADERS)
    validate_error(refused, E.ERR_ITEM_NOT_COST_PENDING.value)
    assert refused.json()["data"]["error_id"] != E.ERR_ITEM_NOT_COST_CLEARED.value, (
        "the state check runs before the endpoint-specific contribution constraint"
    )

    still_review = validate_success(api.get_item(losing["id"], ANALYST_HEADERS), 200)
    assert still_review["status"] == "DELETE_REVIEW", "the refused activation moved nothing"


def test_the_contribution_gate_still_refuses_an_item_that_is_in_cost_pending(api):
    """The control: from COST_PENDING the contribution constraint is reached and is still fatal.

    PRD §2.8: "and finally the endpoint-specific business constraints, each reported with its own
    error id. When several validations could fire on one request, the earlier category in this
    chain wins and its error id is the one returned."
    PRD §3.4: "An activation that fails this requirement is rejected with `ERR_ITEM_NOT_COST_CLEARED`
    and HTTP 422."
    PRD §2.8: "The full precedence chain, from first to last, is: the two authentication checks
    of §2.1; path-identifier resolution, left to right; body foreign-key resolution, in declared
    order; the acting resource's required source state, checked against the `from` state its
    transition declares and reported with that transition's state error at HTTP 409"

    Design: Difficulty/priority_pair_validation_conflict/state_versus_business_constraint_on_activation
    """
    fixtures.set_clock()
    price_point = fixtures.create_price_point(125, 0.90, label="DOLLAR_25")
    vendor = fixtures.create_vendor()
    already_active = fixtures.create_active_item(
        price_point["id"], vendor["id"], sku="8101", base_landed_cost_cents=112)
    assert already_active["status"] == "ACTIVE"
    in_pending = fixtures.create_price_assigned_item(
        price_point["id"], vendor["id"], sku="8102", base_landed_cost_cents=112)
    validate_success(fixtures.apply_landed_cost(in_pending["id"], applied_amount_cents=112), 201)

    # A non-negative contribution from COST_PENDING clears the item.
    cleared = validate_success(api.activate_item(in_pending["id"], BUYER_HEADERS), 200)
    assert cleared["status"] == "ACTIVE"
    assert cleared["net_contribution_cents_per_unit"] == 9

    # The negative-contribution item is the one whose gate is deferred behind the state check.
    fixtures.create_item_in_delete_review(
        price_point["id"], vendor["id"], sku="8103", base_landed_cost_cents=128)
    review_rows = validate_success(
        api.list_items(ANALYST_HEADERS, params={"status": "DELETE_REVIEW"}), 200)
    assert len(review_rows) == 1, (
        "only the item whose cost outran its retail is queued, so the state gate is what "
        "answered the other activations"
    )


def test_a_reset_that_both_collides_and_mixes_price_points_answers_with_the_temporal_error(api):
    """Overlap on the aisle wins over the price point foreign to the conversion.

    PRD §3.10: "A same-aisle conflict is rejected with `ERR_AISLE_RESET_OVERLAP` and HTTP 409."
    PRD §3.10: "While a store is `CONVERTING`, every reset opened on it must carry a
    `price_point_id` equal to the store's `conversion_price_point_id`; a mixed price point inside
    a single conversion is rejected with `ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION` and HTTP 409."
    PRD §2.8: "and finally the endpoint-specific business constraints, each reported with its own
    error id. When several validations could fire on one request, the earlier category in this
    chain wins and its error id is the one returned."
    PRD §2.10: "Same-aisle conflict detection treats intervals as half-open: two resets on the
    same aisle of the same store conflict only when one starts strictly before the other ends and
    the other starts strictly before the first ends, so intervals that merely touch at an
    endpoint do not conflict."

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_versus_business_referential_on_aisle_reset
    """
    origin, target, store, window, existing = _store_converting_with_a_planned_reset(api)

    # A14 is still occupied from 09-05 to 09-20, and the candidate runs from 09-15 to 09-25.
    both = fixtures.plan_reset(
        store["id"], origin["id"], window["id"], aisle_code="A14",
        starts_at="2026-09-15T00:00:00Z", ends_at="2026-09-25T00:00:00Z",
        allocated_shelf_sqft=100.0)
    validate_error(both, E.ERR_AISLE_RESET_OVERLAP.value)
    assert both.json()["data"]["error_id"] != E.ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION.value, (
        "the temporal category precedes the referential one"
    )

    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert len(resets) == 1 and resets[0]["id"] == existing["id"], (
        "the rejected request persisted nothing"
    )


def test_moving_to_a_free_aisle_leaves_only_the_mixed_price_point_violation(api):
    """Removing the overlap exposes the referential violation the first request was hiding.

    PRD §3.10: "While a store is `CONVERTING`, every reset opened on it must carry a
    `price_point_id` equal to the store's `conversion_price_point_id`; a mixed price point inside
    a single conversion is rejected with `ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION` and HTTP 409."
    PRD §3.10: "A same-aisle conflict is rejected with `ERR_AISLE_RESET_OVERLAP` and HTTP 409."
    PRD §3.10: "That sum must not exceed the store's `shelf_facing_capacity_sqft`"

    Design: Difficulty/priority_pair_validation_conflict/business_temporal_versus_business_referential_on_aisle_reset
    """
    origin, target, store, window, existing = _store_converting_with_a_planned_reset(api)

    # A15 shares no aisle with A14, so the same-aisle rule passes and only the price point fails.
    referral_only = fixtures.plan_reset(
        store["id"], origin["id"], window["id"], aisle_code="A15",
        starts_at="2026-09-15T00:00:00Z", ends_at="2026-09-25T00:00:00Z",
        allocated_shelf_sqft=100.0)
    validate_error(referral_only, E.ERR_PRICE_POINT_MIXED_WITHIN_CONVERSION.value)

    # The store's committed day is 200.0 of its 400.0 ceiling, so no capacity error can be the
    # reason either request was refused.
    resets = validate_success(api.list_store_aisle_resets(store["id"], ANALYST_HEADERS), 200)
    assert len(resets) == 1
    assert sum(row["allocated_shelf_sqft"] for row in resets) == 200.0
    store_after = validate_success(api.get_store(store["id"], ANALYST_HEADERS), 200)
    assert store_after["shelf_facing_capacity_sqft"] == 400.0