"""Parts catalog and orders: stock-threshold status flips, the supersession
chain walk, backorder fill ordering, ship/deliver/cancel, the parts-obligation
window for free orders, and validation-ladder precedence.
"""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    create_part,
    create_parts_order,
    create_parts_order_payload,
    create_sale,
    create_sale_payload,
    make_channel_rep_headers,
    model_lifecycle,
    part_transition_payload,
    parts_order_transition_payload,
    set_logical_clock,
    setup_in_season,
    setup_in_season_with_sale,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_admin_headers"]
AGENT = TEST_USERS["service_agent_headers"]


def _order_raw(api, part_id, sale_id, quantity, fulfillment_type):
    return api.create_parts_order(
        create_parts_order_payload(part_id, sale_id, quantity, fulfillment_type), headers=AGENT)


def _legacy_discontinued_sale(api):
    """Season 2018 walked to IN_SEASON with an accepted allocation and one registered
    sale of GX-OLD; the model is discontinued at logical clock 2018-06-01 (obligation
    until 2025-06-01) and the clock parked at 2026-09-01, past the obligation."""
    bundle = setup_in_season(
        allocated_units=2, units_built=5, channel_type="DIRECT",
        in_season_clock="2018-04-01T00:00:00Z",
        season_over={
            "name": "Season 2018", "year": 2018,
            "build_start": "2017-11-01T00:00:00Z", "allocation_open": "2018-01-15T00:00:00Z",
            "in_season_start": "2018-03-01T00:00:00Z", "clearance_start": "2018-07-01T00:00:00Z",
            "season_end": "2018-09-30T00:00:00Z", "demand_forecast_units": 500,
        },
        model_over={"model_code": "GX-OLD", "model_family": "GX", "model_year": 2018,
                    "base_price_cents": 50000, "demand_share_bp": 6000},
        channel_over={"name": "WebDirect"},
    )
    sale = create_sale(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                       quantity=1, proof_of_purchase_token="RCPT-OLD")
    set_logical_clock("2018-06-01T00:00:00Z")
    model_lifecycle(bundle["model"]["id"], "DISCONTINUE")
    set_logical_clock("2026-09-01T00:00:00Z")
    return bundle, sale


def test_supersession_walk_resolves_to_first_stocked_successor(api):
    """PRD 3.8: "Resolution happens synchronously inside the create, walking the
    supersession chain in `chain_position` order."
    PRD 3.8: "Otherwise the walk advances to the chain member with the next higher
    `chain_position` and repeats."
    PRD 3.8: "`total_cost_cents` is computed as the resolved part's `unit_cost_cents`
    times the quantity at resolution time"

    Design: Corner/calculations/supersession_walk_resolves_to_first_stocked_successor
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    p1 = create_part(part_number="GRT-A", component="GRATE", compatible_model_codes=["GX-100"],
                     supersession_chain_id="CH-G", chain_position=1, unit_cost_cents=2400, stock_quantity=0)
    create_part(part_number="GRT-B", component="GRATE", compatible_model_codes=["GX-100"],
                supersession_chain_id="CH-G", chain_position=2, unit_cost_cents=2600, stock_quantity=0)
    p3 = create_part(part_number="GRT-C", component="GRATE", compatible_model_codes=["GX-100"],
                     supersession_chain_id="CH-G", chain_position=3, unit_cost_cents=2800, stock_quantity=4)
    order = validate_success(_order_raw(api, p1["id"], bundle["sale"]["id"], 1, "PAID"), 201)
    assert order["resolved_part_id"] == p3["id"], "the walk skips both exhausted predecessors"
    assert order["status"] == "ALLOCATED"
    assert order["total_cost_cents"] == 2800, "the resolved part's cost, not the requested 2400"
    p3_after = validate_success(api.get_part(p3["id"], headers=AGENT), 200)
    assert p3_after["stock_quantity"] == 3, "stock decrements on the resolved part"


def test_exhausted_part_without_successor_backorders(api):
    """PRD 3.8: "if the requested part is `EXHAUSTED`, the order is born `BACKORDERED`
    with `resolved_part_id` equal to the requested part, waiting for a restock to fill
    it"
    PRD 2.8: "Identifiers carried in a request body are resolved with the same
    discipline: a `channel_account_id` that names no existing channel yields
    `ERR_CHANNEL_NOT_FOUND`, and likewise for any other body-carried reference."

    Design: Corner/calculations/exhausted_part_without_successor_backorders
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    p1 = create_part(part_number="BRN-1", component="BURNER", compatible_model_codes=["GX-100"],
                     supersession_chain_id="CH-B", chain_position=1, unit_cost_cents=3200, stock_quantity=0)
    ghost = _order_raw(api, "00000000-0000-4000-8000-0000000000aa", bundle["sale"]["id"], 1, "PAID")
    validate_error(ghost, ApiErrorId.ERR_PART_NOT_FOUND)
    order = validate_success(_order_raw(api, p1["id"], bundle["sale"]["id"], 2, "PAID"), 201)
    assert order["status"] == "BACKORDERED", "EXHAUSTED with an empty successor chain backorders"
    assert order["resolved_part_id"] == p1["id"], "the fallback pins the requested part for later fill"


def test_restock_fills_backorders_in_creation_order(api):
    """PRD 3.8: "Restocking also drains the backorder queue: every `BACKORDERED` parts
    order resolved to this part is allocated in `created_at` ascending order — ties
    broken by the order's `seq_no`, never by identifier — each one moving to
    `ALLOCATED` with its quantity deducted from stock, until either the stock or the
    backorders run out."
    PRD 3.8: "at exactly zero it is `EXHAUSTED`. These flips fire on every stock
    movement"

    Design: Corner/state_machines/restock_fills_backorders_in_creation_order
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")  # clock 2026-04-01
    part = create_part(part_number="GRT-7", component="GRATE", compatible_model_codes=["GX-100"],
                       supersession_chain_id="CH-R", chain_position=1, unit_cost_cents=2400, stock_quantity=1)
    first = validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 1, "PAID"), 201)
    assert first["status"] == "ALLOCATED"  # drains stock to 0 -> part EXHAUSTED
    second = validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 1, "PAID"), 201)
    assert second["status"] == "BACKORDERED"
    set_logical_clock("2026-04-01T00:01:00Z")
    third = validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 1, "PAID"), 201)
    assert third["status"] == "BACKORDERED"
    restocked = validate_success(api.transition_part(
        part["id"], part_transition_payload("RESTOCK", quantity=1), headers=PLANNER), 200)
    assert restocked["stock_quantity"] == 0, "the single restocked unit fills exactly one backorder"
    assert restocked["status"] == "EXHAUSTED"
    second_after = validate_success(api.get_parts_order(second["id"], headers=AGENT), 200)
    third_after = validate_success(api.get_parts_order(third["id"], headers=AGENT), 200)
    assert second_after["status"] == "ALLOCATED", "the earliest-created backorder wins the unit"
    assert third_after["status"] == "BACKORDERED"


def test_parts_order_ship_deliver_and_cancel_restores_stock(api):
    """PRD 3.8: "From `ALLOCATED`, a `ServiceAgent` ships the order (`ALLOCATED →
    SHIPPED`) and later marks it delivered (`SHIPPED → DELIVERED`, terminal).
    Cancellation is possible from `REQUESTED`, `BACKORDERED`, or `ALLOCATED`;
    cancelling an allocated order is compensating — the resolved part's
    `stock_quantity` is credited back by the order's `quantity`"

    Design: Corner/state_machines/parts_order_ship_deliver_and_cancel_restores_stock
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    part = create_part(part_number="BRN-5", component="BURNER", compatible_model_codes=["GX-100"],
                       supersession_chain_id="CH-B5", chain_position=1, unit_cost_cents=3200, stock_quantity=5)
    o1 = validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 2, "PAID"), 201)  # stock 5 -> 3
    o2 = validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 1, "PAID"), 201)  # stock 3 -> 2
    shipped = validate_success(api.transition_parts_order(
        o1["id"], parts_order_transition_payload("SHIP"), headers=AGENT), 200)
    assert shipped["status"] == "SHIPPED"
    delivered = validate_success(api.transition_parts_order(
        o1["id"], parts_order_transition_payload("DELIVER"), headers=AGENT), 200)
    assert delivered["status"] == "DELIVERED"
    cancelled = validate_success(api.transition_parts_order(
        o2["id"], parts_order_transition_payload("CANCEL"), headers=AGENT), 200)
    assert cancelled["status"] == "CANCELLED"
    part_after = validate_success(api.get_part(part["id"], headers=AGENT), 200)
    assert part_after["stock_quantity"] == 3, "5 - 2 delivered - 1 credited back = 3"


def test_supersede_with_successor_outside_chain_rejected(api):
    """PRD 3.8: "the caller names a `successor_part_id` which must exist, share the
    part's `supersession_chain_id`, and hold a strictly higher `chain_position`, else
    `ERR_VALIDATION`"
    PRD 3.8: "if the requested part was `SUPERSEDED` with no fulfiller downstream, the
    create fails with `ERR_PART_UNAVAILABLE`."

    Design: Corner/cross_cutting_complexity_layers/supersede_with_successor_outside_chain_rejected
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    p_a = create_part(part_number="BRN-A", component="BURNER", compatible_model_codes=["GX-100"],
                      supersession_chain_id="CH-S", chain_position=1, unit_cost_cents=3200, stock_quantity=5)
    p_z = create_part(part_number="GRT-Z", component="GRATE", compatible_model_codes=["GX-100"],
                      supersession_chain_id="CH-OTHER", chain_position=1, unit_cost_cents=2400, stock_quantity=5)
    p_b = create_part(part_number="BRN-B", component="BURNER", compatible_model_codes=["GX-100"],
                      supersession_chain_id="CH-S", chain_position=2, unit_cost_cents=3400, stock_quantity=0)
    cross_chain = api.transition_part(
        p_a["id"], part_transition_payload("SUPERSEDE", successor_part_id=p_z["id"]), headers=PLANNER)
    validate_error(cross_chain, ApiErrorId.ERR_VALIDATION)
    superseded = validate_success(api.transition_part(
        p_a["id"], part_transition_payload("SUPERSEDE", successor_part_id=p_b["id"]), headers=PLANNER), 200)
    assert superseded["status"] == "SUPERSEDED"
    # The walk finds BRN-B EXHAUSTED, the chain ends, and a SUPERSEDED requested part
    # has no backorder fallback.
    order = _order_raw(api, p_a["id"], bundle["sale"]["id"], 1, "PAID")
    validate_error(order, ApiErrorId.ERR_PART_UNAVAILABLE)


def test_stock_threshold_ten_is_low_stock_zero_is_exhausted(api):
    """PRD 3.8: "A part with more than 10 units on hand — the low-stock threshold — is
    `AVAILABLE`; at 10 units or fewer but above zero it is `LOW_STOCK`; at exactly
    zero it is `EXHAUSTED`."
    PRD 2.8: "the system validates the existence of each identifier in strict
    left-to-right order and rejects the request immediately with the 404 code of the
    first identifier that does not resolve"

    Design: Corner/cross_cutting_complexity_layers/stock_threshold_ten_is_low_stock_zero_is_exhausted
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    part = create_part(part_number="BRN-3", component="BURNER", compatible_model_codes=["GX-100"],
                       supersession_chain_id="CH-B3", chain_position=1, unit_cost_cents=3200, stock_quantity=11)
    ghost = api.transition_parts_order(
        "00000000-0000-4000-8000-0000000000ff", parts_order_transition_payload("SHIP"), headers=AGENT)
    validate_error(ghost, ApiErrorId.ERR_PARTS_ORDER_NOT_FOUND)
    validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 1, "PAID"), 201)  # stock 11 -> 10
    mid = validate_success(api.get_part(part["id"], headers=AGENT), 200)
    assert mid["stock_quantity"] == 10
    assert mid["status"] == "LOW_STOCK", "10 units is at the threshold: LOW_STOCK (boundary inclusive)"
    validate_success(_order_raw(api, part["id"], bundle["sale"]["id"], 10, "PAID"), 201)  # stock 10 -> 0
    end = validate_success(api.get_part(part["id"], headers=AGENT), 200)
    assert end["stock_quantity"] == 0
    assert end["status"] == "EXHAUSTED"


def test_free_parts_order_after_obligation_rejected_paid_passes(api):
    """PRD 3.8: "Warranty and goodwill orders are free of charge — `free_of_charge` is
    true exactly when the fulfillment type is `WARRANTY` or `GOODWILL` — and free
    orders respect the model's parts obligation: the logical clock must be at or
    before the model's `support_obligation_until`, else the order is rejected with
    `ERR_PARTS_OBLIGATION_EXPIRED`."
    PRD 3.2: "a sale may only be recorded against a model that is `ACTIVE` or
    `CLEARANCE_ELIGIBLE`, and an allocation offer may only target an `ACTIVE` model;
    anything else is `ERR_MODEL_NOT_SELLABLE`."

    Design: Corner/validations/free_parts_order_after_obligation_rejected_paid_passes
    """
    bundle, sale = _legacy_discontinued_sale(api)  # obligation ended 2025-06-01; clock 2026-09-01
    part = create_part(part_number="VLV-2", component="BURNER", compatible_model_codes=["GX-OLD"],
                       supersession_chain_id="CH-V", chain_position=1, unit_cost_cents=3200, stock_quantity=5)
    sale_resp = api.create_sale(
        create_sale_payload(bundle["season"]["id"], bundle["model"]["id"], bundle["channel"]["id"],
                            quantity=1, proof_of_purchase_token="RCPT-LATE"),
        headers=make_channel_rep_headers(bundle["channel"]["id"]))
    validate_error(sale_resp, ApiErrorId.ERR_MODEL_NOT_SELLABLE)
    free = _order_raw(api, part["id"], sale["id"], 1, "WARRANTY")
    validate_error(free, ApiErrorId.ERR_PARTS_OBLIGATION_EXPIRED)
    paid = validate_success(_order_raw(api, part["id"], sale["id"], 1, "PAID"), 201)
    assert paid["status"] == "ALLOCATED"
    assert paid["free_of_charge"] is False, "paid parts remain orderable while stock lasts"


def test_incompatible_part_error_precedes_obligation_error(api):
    """PRD 2.9: "When a single request violates several rules at once, the category
    with the lowest priority number wins and alone determines the response; later
    violations are masked until the earlier one is fixed."
    PRD 2.9 rung 7: "the part fits the sale's model (`ERR_PART_INCOMPATIBLE`, 422)"
    PRD 2.9 rung 8: "a free parts order must fall within the model's support
    obligation (`ERR_PARTS_OBLIGATION_EXPIRED`, 422)"

    Design: Difficulty/priority_pair_validation_conflict/incompatible_part_error_precedes_obligation_error
    """
    bundle, sale = _legacy_discontinued_sale(api)  # clock 2026-09-01 > obligation until 2025-06-01
    part = create_part(part_number="VLV-1", component="BURNER", compatible_model_codes=["OTHER-X"],
                       supersession_chain_id="CH-VLV", chain_position=1, unit_cost_cents=3200, stock_quantity=10)
    # Both rung 7 (incompatible with GX-OLD) and rung 8 (obligation expired) are
    # violated; the referential check is earlier on the ladder.
    resp = _order_raw(api, part["id"], sale["id"], 1, "WARRANTY")
    validate_error(resp, ApiErrorId.ERR_PART_INCOMPATIBLE)
    _orders, meta = validate_paginated(api.list_parts_orders(headers=AGENT))
    assert meta["total_count"] == 0, "no parts order may be persisted by the rejected create"


def test_parts_orders_filter_by_part(api):
    """PRD 4: "List parts orders; filters `part_id`, `sale_id`, `status`".
    PRD 2.3: "Paginated and non-paginated list-based responses include the following
    fields in the `meta` object of the response envelope: `limit`, `offset`,
    `total_count`, and `has_more`."

    Design: Corner/endpoints/parts_orders_filter_by_part
    """
    bundle = setup_in_season_with_sale(registered=False, channel_type="DIRECT")
    p1 = create_part(part_number="BRN-1", component="BURNER", compatible_model_codes=["GX-100"],
                     supersession_chain_id="CH-B", chain_position=1, unit_cost_cents=3200, stock_quantity=5)
    p2 = create_part(part_number="GRT-9", component="GRATE", compatible_model_codes=["GX-100"],
                     supersession_chain_id="CH-G2", chain_position=1, unit_cost_cents=2400, stock_quantity=3)
    create_parts_order(p1["id"], bundle["sale"]["id"], quantity=1, fulfillment_type="PAID")
    create_parts_order(p1["id"], bundle["sale"]["id"], quantity=2, fulfillment_type="PAID")
    _d1, meta_p1 = validate_paginated(api.list_parts_orders(headers=AGENT, params={"part_id": p1["id"]}))
    assert meta_p1["total_count"] == 2, "both orders were placed against BRN-1"
    data_p2, meta_p2 = validate_paginated(api.list_parts_orders(headers=AGENT, params={"part_id": p2["id"]}))
    assert meta_p2["total_count"] == 0
    assert data_p2 == [], "an untouched part lists an empty page, not an error"
