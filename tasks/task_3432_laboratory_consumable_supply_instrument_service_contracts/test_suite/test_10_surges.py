"""Surge events: one-active-per-group, resolve state guard, frozen
allocation scores, and the resolve-time priority waterfall with
skip-not-block promotion and reservation.
"""

from test_helpers import (
    SUPPLY_OPS,
    ApiErrorId,
    api_client,
    create_account,
    create_backordered_order,
    create_catalog_item,
    create_surge_event,
    get_catalog_item_by_sku,
    get_order,
    order_line,
    resolve_surge_event,
    surge_event_payload,
    validate_error,
    validate_success,
)


def _three_priority_accounts():
    """CRITICAL / PRIORITY / STANDARD accounts holding no agreement; their
    allocation scores are the bare priority weights (tier multiplier 1.0)."""
    return (
        create_account(name="Crit Lab", segment="PHARMA",
                       priority_class="CRITICAL"),
        create_account(name="Prio Lab", segment="CLINICAL",
                       priority_class="PRIORITY"),
        create_account(name="Std Lab", segment="ACADEMIC",
                       priority_class="STANDARD"),
    )


def test_second_surge_same_group_rejected(api):
    """PRD section 3.7: "At most one surge may be `ACTIVE` per group: opening
    a second surge on a group that already has an active one is rejected with
    `ERR_SURGE_ALREADY_ACTIVE`."

    Design: Corner/validations/second_surge_same_group_rejected
    """
    create_surge_event(allocation_group="GROUP_C", reason="first")
    response = api_client.create_surge_event(
        surge_event_payload(allocation_group="GROUP_C", reason="second"),
        headers=SUPPLY_OPS,
    )
    validate_error(response, ApiErrorId.ERR_SURGE_ALREADY_ACTIVE)
    other = api_client.create_surge_event(
        surge_event_payload(allocation_group="GROUP_B", reason="other group"),
        headers=SUPPLY_OPS,
    )
    validate_success(other, 201)


def test_surge_resolve_twice_returns_invalid_state(api):
    """PRD section 3.7: "Resolving the surge is a `SupplyOps` action that
    requires the event to be `ACTIVE`, failing with `ERR_INVALID_STATE`
    otherwise."

    Design: Corner/state_machines/surge_resolve_twice_returns_invalid_state
    """
    surge = create_surge_event(allocation_group="GROUP_C", reason="shortage")
    resolve_surge_event(surge)
    response = api_client.resolve_surge_event(surge["id"], headers=SUPPLY_OPS)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE)


def test_surge_score_is_priority_weight_times_tier_multiplier(api):
    """PRD section 3.7: "Each order that backorders carries a frozen
    `allocation_score`: the priority weight of the account's `priority_class`
    multiplied by the tier multiplier of the account's agreement tier as it
    stood at submission. The priority weights are 100 for `CRITICAL`, 50 for
    `PRIORITY`, and 10 for `STANDARD`. The tier multipliers are 2.0 for
    `PLATINUM`, 1.5 for `GOLD`, 1.2 for `SILVER`, and 1.0 for `BASE`, where
    the tier comes from the account's agreement reading `ACTIVE` or `EXPIRING`
    at submit time and is treated as `BASE` when the account has no such
    agreement." and "While a surge reads `ACTIVE` on a group, every order
    submission touching that group goes to `BACKORDERED` regardless of stock".

    Design: Difficulty/combinatorial_formula/surge_score_weight_times_tier_gate
    """
    crit, prio, std = _three_priority_accounts()
    item = create_catalog_item(allocation_group="GROUP_A", base_price_cents=100,
                               stock_on_hand=10)
    create_surge_event(allocation_group="GROUP_A", reason="resin shortage")

    o1 = create_backordered_order(crit, [order_line(item["sku"], 6)])
    o2 = create_backordered_order(prio, [order_line(item["sku"], 5)])
    o3 = create_backordered_order(std, [order_line(item["sku"], 1)])

    assert o1["status"] == o2["status"] == o3["status"] == "BACKORDERED"
    assert o1["allocation_score"] == 100.0, "CRITICAL 100 x BASE 1.0"
    assert o2["allocation_score"] == 50.0, "PRIORITY 50 x BASE 1.0"
    assert o3["allocation_score"] == 10.0, "STANDARD 10 x BASE 1.0"


def test_surge_waterfall_skips_unsatisfiable_and_allocates_rest(api):
    """PRD section 3.7: "Candidates are considered in a pinned order:
    `allocation_score` descending, then `submitted_at` ascending, then
    `total_quantity` ascending, then the account's `name` ascending. Each
    candidate in turn is either fully satisfiable — every line's
    `available_stock` is at least its `quantity` — in which case all of its
    lines reserve stock ... and the order becomes `ALLOCATED` ... or it is
    skipped, staying `BACKORDERED` while the waterfall continues down the
    ranking."

    Design: Difficulty/combinatorial_formula/surge_score_weight_times_tier_gate
    """
    crit, prio, std = _three_priority_accounts()
    item = create_catalog_item(allocation_group="GROUP_A", base_price_cents=100,
                               stock_on_hand=10)
    surge = create_surge_event(allocation_group="GROUP_A",
                               reason="resin shortage")
    o1 = create_backordered_order(crit, [order_line(item["sku"], 6)])
    o2 = create_backordered_order(prio, [order_line(item["sku"], 5)])
    o3 = create_backordered_order(std, [order_line(item["sku"], 1)])

    resolved = resolve_surge_event(surge)
    assert resolved["status"] == "RESOLVED"

    assert get_order(o1)["status"] == "ALLOCATED", "score 100 first, 6 of 10"
    assert get_order(o2)["status"] == "BACKORDERED", (
        "needs 5 of the 4 remaining: skipped, not blocked"
    )
    assert get_order(o3)["status"] == "ALLOCATED", "needs 1 of 4 remaining"
    probe = get_catalog_item_by_sku(item["sku"])
    assert probe["reserved_quantity"] == 7
    assert probe["available_stock"] == 3
    assert probe["stock_on_hand"] == 10


def test_surge_submit_backorders_and_freezes_score(api):
    """PRD section 3.7: "While a surge reads `ACTIVE` on a group, every order
    submission touching that group goes to `BACKORDERED` regardless of stock"
    and "Each order that backorders carries a frozen `allocation_score`".

    Design: Difficulty/transitive_cascade/surge_resolve_promotes_and_reserves
    """
    crit, _, _ = _three_priority_accounts()
    item = create_catalog_item(allocation_group="GROUP_A", base_price_cents=100,
                               stock_on_hand=10)
    create_surge_event(allocation_group="GROUP_A", reason="allocation crunch")
    order = create_backordered_order(crit, [order_line(item["sku"], 6)])
    assert order["status"] == "BACKORDERED", (
        "stock is sufficient (10 >= 6) yet the active surge forces BACKORDERED"
    )
    assert order["allocation_score"] == 100.0, "frozen at submit: 100 x 1.0"


def test_surge_resolve_promotes_order_and_reserves_stock(api):
    """PRD section 3.7: "Resolution ... runs the allocation waterfall for that
    group." with each satisfiable candidate: "all of its lines reserve stock,
    each line adding its `quantity` to its item's `reserved_quantity`, and the
    order becomes `ALLOCATED` with its `version` incremented by 1".

    Design: Difficulty/transitive_cascade/surge_resolve_promotes_and_reserves
    """
    crit, _, _ = _three_priority_accounts()
    item = create_catalog_item(allocation_group="GROUP_A", base_price_cents=100,
                               stock_on_hand=10)
    surge = create_surge_event(allocation_group="GROUP_A",
                               reason="allocation crunch")
    order = create_backordered_order(crit, [order_line(item["sku"], 6)])

    resolved = resolve_surge_event(surge)
    assert resolved["status"] == "RESOLVED"
    assert get_order(order)["status"] == "ALLOCATED", (
        "link 1: the waterfall promotes the top-scored backordered order"
    )
    probe = get_catalog_item_by_sku(item["sku"])
    assert probe["reserved_quantity"] == 6, "link 2: promotion reserved stock"
    assert probe["available_stock"] == 4
