"""Fleet allocation: the tier-ordered waterfall, quantity boundaries, and
cross-entity state gates on proposals."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    commit_allocations,
    create_default_jurisdiction,
    create_lot,
    create_priced_lot,
    create_store,
    create_vendor,
    get_lot,
    get_success_data,
    pass_screening,
    propose_allocation,
    setup_sellable_store,
    validate_error,
    guest_purchase,
)

ADMIN = TEST_USERS["admin_headers"]
ALLOCATOR = TEST_USERS["allocation_manager_headers"]


def test_allocation_exact_pool_then_zero_and_over(api):
    """PRD §3.8: "Each allocation in turn is granted the smaller of its
    `qty_requested` and the remaining pool".
    PRD §3.8: "the requested quantity must not exceed the lot's unallocated
    `qty_pool` at proposal time, else `ERR_INSUFFICIENT_LOT_QUANTITY`".

    Design: Difficulty/boundary_precision_check/allocation_exact_pool_then_zero_and_over
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])

    alloc = propose_allocation(lot["id"], store["id"], 100)
    result = commit_allocations(lot["id"])
    assert result["total_granted_qty"] == 100
    confirmed = get_success_data(api.get_allocation(lot["id"], alloc["id"], ADMIN))
    assert confirmed["qty_granted"] == 100
    assert get_lot(lot["id"])["qty_pool"] == 0
    # One unit against an empty pool fails fiscally.
    over = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 1}, ALLOCATOR)
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_LOT_QUANTITY)


def test_allocation_zero_quantity_request_rejected(api):
    """PRD §2.6: "Request-shape validation (required fields, types, enum
    membership, quantity floors, no unknown fields, and the presence of
    required optimistic-concurrency fields) is enforced as
    `ERR_INVALID_REQUEST`".

    Design: Difficulty/boundary_precision_check/allocation_exact_pool_then_zero_and_over
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_priced_lot(vendor["id"], jur["id"])
    resp = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 0}, ALLOCATOR)
    validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


def test_purchase_exact_on_hand_then_over(api, guest_headers):
    """PRD §3.6: "the store's shelf must hold the goods: `qty` must not exceed
    the `store_on_hand_qty` of the store's received allocation for the lot,
    else `ERR_INSUFFICIENT_STORE_STOCK`."

    Design: Difficulty/boundary_precision_check/purchase_exact_on_hand_then_over
    """
    ctx = setup_sellable_store(qty=10, alloc_qty=4,
                               lot_overrides={"pace_target_units_per_week": 1000})
    purchase = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 4)
    assert purchase["line_total_cents"] == 16000  # guest price 4000 * 4
    over = api.create_purchase(ctx["store"]["id"],
                               {"lot_id": ctx["lot"]["id"], "qty": 1},
                               guest_headers)
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_STORE_STOCK)
    # pool 6 remains, so no CLOSED_SOLD_OUT
    assert get_lot(ctx["lot"]["id"])["commercial_status"] == "ON_SALE"


def test_purchase_exact_on_hand_succeeds_at_boundary(api, guest_headers):
    """PRD §3.6: "the store's shelf must hold the goods: `qty` must not exceed
    the `store_on_hand_qty` of the store's received allocation for the lot,
    else `ERR_INSUFFICIENT_STORE_STOCK`."
    PRD §3.6: "guests (no `member_id`) pay full freight with a percent of zero
    and `pricing_variant` `GUEST`".

    Design: Difficulty/boundary_precision_check/purchase_exact_on_hand_then_over
    """
    ctx = setup_sellable_store(qty=10, alloc_qty=4,
                               lot_overrides={"pace_target_units_per_week": 1000})
    purchase = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 4)
    assert purchase["pricing_variant"] == "GUEST"
    assert purchase["unit_price_cents"] == 4000
    summary = get_success_data(api.get_lot_summary(ctx["lot"]["id"], ADMIN))
    assert summary["qty_sold"] == 4
    assert summary["qty_allocated_outstanding"] == 0
    over = api.create_purchase(ctx["store"]["id"],
                               {"lot_id": ctx["lot"]["id"], "qty": 1},
                               guest_headers)
    validate_error(over, ApiErrorId.ERR_INSUFFICIENT_STORE_STOCK)


def test_allocation_waterfall_tiebreak_by_created_at(api):
    """PRD §3.8: "Candidates are ordered by destination store's
    `performance_tier` — `TIER_1` before `TIER_2` before `TIER_3` — with ties
    broken by allocation creation time, earliest first; the allocation
    identifier is never consulted."

    Design: Corner/calculations/allocation_waterfall_tiebreak_by_created_at
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    s2a = create_store(jur["id"], performance_tier="TIER_2", store_code="S2",
                       name="Store Two")
    s2b = create_store(jur["id"], performance_tier="TIER_2", store_code="S2B",
                       name="Store Two B")
    lot = create_priced_lot(vendor["id"], jur["id"],
                            lot_overrides={"quantity_total": 30,
                                           "est_sellable_qty": 30,
                                           "total_cost_cents": 30000})
    al_a = propose_allocation(lot["id"], s2a["id"], 20)
    al_b = propose_allocation(lot["id"], s2b["id"], 20)
    commit_allocations(lot["id"])
    a = get_success_data(api.get_allocation(lot["id"], al_a["id"], ADMIN))
    b = get_success_data(api.get_allocation(lot["id"], al_b["id"], ADMIN))
    # earlier-created wins the tie; the later one clips to the remaining pool
    assert a["status"] == "CONFIRMED" and a["qty_granted"] == 20
    assert b["status"] == "CONFIRMED" and b["qty_granted"] == 10
    assert get_lot(lot["id"])["qty_pool"] == 0


def test_purchase_requires_active_aisle_assignment(api, guest_headers):
    """PRD §3.6: "Fourth, the deal-dependent layout gate: an `ACTIVE` aisle
    assignment covering the current instant must exist for the store and lot —
    `valid_from` at or before now, and either no `valid_to` or `valid_to` at
    or after now — else `ERR_NO_ACTIVE_ASSIGNMENT`."

    Design: Difficulty/cross_entity_state_dependency/purchase_requires_active_aisle_assignment
    """
    from test_helpers import setup_on_sale_lot, assign_aisle

    ctx = setup_on_sale_lot(receive=True)
    resp = api.create_purchase(ctx["store"]["id"],
                               {"lot_id": ctx["lot"]["id"], "qty": 1},
                               guest_headers)
    validate_error(resp, ApiErrorId.ERR_NO_ACTIVE_ASSIGNMENT)
    assign_aisle(ctx["store"]["id"], ctx["lot"]["id"], daily_unit_limit=4)
    ok = guest_purchase(ctx["store"]["id"], ctx["lot"]["id"], 1)
    assert ok["line_total_cents"] == 4000


def test_purchase_succeeds_only_while_assignment_covers_now(api,
                                                            guest_headers,
                                                            floor_headers):
    """PRD §3.6: "an `ACTIVE` aisle assignment covering the current instant
    must exist for the store and lot — `valid_from` at or before now, and
    either no `valid_to` or `valid_to` at or after now — else
    `ERR_NO_ACTIVE_ASSIGNMENT`."

    Design: Difficulty/cross_entity_state_dependency/purchase_requires_active_aisle_assignment
    """
    from test_helpers import (
        create_aisle_assignment_payload,
        get_store,
        set_clock,
        setup_on_sale_lot,
    )

    ctx = setup_on_sale_lot(receive=True)
    store = ctx["store"]
    lot = ctx["lot"]
    version = get_store(store["id"])["version"]
    # Window opens on 2026-09-03; purchases before that have no covering
    # assignment, purchases once it opens succeed.
    assignment = get_success_data(api.create_aisle_assignment(
        store["id"],
        create_aisle_assignment_payload(
            lot["id"], version, daily_unit_limit=4,
            valid_from="2026-09-03T00:00:00Z", valid_to="2026-09-05T00:00:00Z"),
        floor_headers))
    assert assignment["status"] == "ACTIVE"
    early = api.create_purchase(store["id"], {"lot_id": lot["id"], "qty": 1},
                                guest_headers)
    validate_error(early, ApiErrorId.ERR_NO_ACTIVE_ASSIGNMENT)
    set_clock("2026-09-03T12:00:00Z")
    ok = guest_purchase(store["id"], lot["id"], 1)
    assert ok["line_total_cents"] == 4000


def test_allocation_proposal_on_sourced_lot_rejected(api):
    """PRD §2.6: "Lifecycle-state checks (`ERR_INVALID_STATE`) follow".
    PRD §3.2: "The lot is created directly in `commercial_status` `SOURCED`
    with `safety_status` `PENDING_SCREEN`".
    PRD §3.8: "Units move from the warehouse pool to stores through
    **Allocation** records managed by an `AllocationManager`."

    Design: Difficulty/cross_entity_state_dependency/allocation_proposal_requires_priced_lot
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_lot(vendor["id"], jur["id"])  # SOURCED, never screened
    resp = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 10}, ALLOCATOR)
    # A lot that has never passed screening is also not sellable; either the
    # lifecycle gate or the safety gate may surface.
    from test_helpers import validate_error_is_one_of
    validate_error_is_one_of(resp, [ApiErrorId.ERR_INVALID_STATE,
                                    ApiErrorId.ERR_LOT_SAFETY_BLOCKED])


def test_allocation_proposal_on_unscreened_lot_safety_blocked(api):
    """PRD §2.10: "Three operations — selling units of a lot at a store,
    assigning a lot to an aisle, and proposing a warehouse allocation from a
    lot — all require the lot's `safety_status` to be `CLEARED`. A lot that is
    `BLOCKED`, or one that has never passed a screening, is rejected from all
    three with `ERR_LOT_SAFETY_BLOCKED`."

    Design: Difficulty/cross_entity_state_dependency/purchase_requires_active_aisle_assignment
    """
    jur = create_default_jurisdiction()
    vendor = create_vendor()
    store = create_store(jur["id"])
    lot = create_lot(vendor["id"], jur["id"])  # SOURCED, never screened
    resp = api.create_allocation(lot["id"], {"store_id": store["id"],
                                             "qty_requested": 10}, ALLOCATOR)
    validate_error(resp, ApiErrorId.ERR_LOT_SAFETY_BLOCKED)
