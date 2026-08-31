"""Replenishment orders: two independent status dimensions, the obsolescence
gate, the backorder promotion sweep and the expediting justification rule."""

from test_helpers import (
    ApiErrorId, add_part_line, allocate_campaign, api_client,
    approve_campaign, assert_replenishment_order, close_campaign,
    create_allocation_request, create_campaign_for, create_forecast, create_part,
    create_replenishment_order_payload, create_work_order, list_ledger,
    phase_out_part, read_allocation_request, read_campaign, read_part,
    read_replenishment_order, setup_catalogue, ship_stock_order,
    submit_campaign, TEST_USERS, validate_error, validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
CONTROLLER = TEST_USERS["controller_headers"]


def _pending_stock_order():
    part = create_part(part_number="PAR-1", description="Track chain link",
                       unit_cost_cents=1000, lead_time_days=30, weight_kg=4.0)
    order = validate_success(api_client.create_replenishment_order(
        create_replenishment_order_payload(part["id"], "STOCK", 50), CONTROLLER), 201)
    return part, order


def test_shipping_before_approval_is_refused(api):
    """PRD 3.7: "Shipping is the one place where the two dimensions touch. Moving
    `logistics_status` from `NOT_STARTED` to `IN_TRANSIT` requires `logistics_status`
    to be `NOT_STARTED` **and** `approval_status` to be `APPROVED`; shipping an
    unapproved order is refused with `ERR_REPLENISHMENT_STATE_INVALID`."
    PRD 3.7: "A newly raised order has `approval_status` `PENDING`,
    `logistics_status` `NOT_STARTED` and `auto_generated` false — the flag is true
    only for the two orders the system raises on its own behalf, described in section
    3.6."

    Design: Difficulty/non_linear_state_machine/replenishment_parallel_dimensions_with_ship_guard
    """
    part, order = _pending_stock_order()
    assert_replenishment_order(order)
    assert order["approval_status"] == "PENDING"
    assert order["logistics_status"] == "NOT_STARTED"
    assert order["auto_generated"] is False

    resp = api.ship_replenishment_order(order["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_REPLENISHMENT_STATE_INVALID.value)

    after = read_replenishment_order(order["id"])
    assert after["logistics_status"] == "NOT_STARTED"
    assert after["approval_status"] == "PENDING"
    assert read_part(part["id"])["in_transit_units"] == 0


def test_approval_and_shipping_advance_independent_dimensions(api):
    """PRD 3.7: "Approving moves `approval_status` from `PENDING` to `APPROVED` and
    deliberately leaves `logistics_status` untouched at `NOT_STARTED`; it requires the
    part not to be `OBSOLETE`, and it advances the order's `version`."
    PRD 3.7: "On shipment the part's `in_transit_units` rises by the order's `qty`,
    the part's `replenishment_status` is set to `ON_ORDER`, and both the part's
    `version` and the order's `version` advance."
    PRD 3.7: "Any approve or reject attempted against a dimension that is not
    `PENDING` is refused with `ERR_REPLENISHMENT_STATE_INVALID`."

    Design: Difficulty/non_linear_state_machine/replenishment_parallel_dimensions_with_ship_guard
    """
    part, order = _pending_stock_order()

    approved = validate_success(api.approve_replenishment_order(order["id"], CONTROLLER))
    assert approved["approval_status"] == "APPROVED"
    assert approved["logistics_status"] == "NOT_STARTED", \
        "approval never touches the logistics dimension"
    assert read_part(part["id"])["in_transit_units"] == 0

    shipped = validate_success(api.ship_replenishment_order(order["id"], CONTROLLER))
    assert shipped["logistics_status"] == "IN_TRANSIT"
    assert shipped["approval_status"] == "APPROVED"
    part_after = read_part(part["id"])
    assert part_after["in_transit_units"] == 50
    assert part_after["replenishment_status"] == "ON_ORDER"

    late_reject = api.reject_replenishment_order(order["id"], CONTROLLER,
                                                 rejection_reason="too late")
    validate_error(late_reject, ApiErrorId.ERR_REPLENISHMENT_STATE_INVALID.value)
    unchanged = read_replenishment_order(order["id"])
    assert unchanged["approval_status"] == "APPROVED"
    assert unchanged["logistics_status"] == "IN_TRANSIT"


def _obsolete_while_in_transit():
    """A 50-unit STOCK order left IN_TRANSIT while the part is walked all the way to
    OBSOLETE through an approved, allocated and closed campaign."""
    scenario = setup_catalogue(
        part_number="OBS-1", unit_cost_cents=1000, lead_time_days=60,
        weight_kg=2.0, dealer_code="D-OBS", dealer_tier="SILVER",
        model_code="EM-F10", serial_prefix="SN-F10", qty_per_unit=50,
        price_rules=())
    part_id = scenario["part"]["id"]
    create_forecast(part_id, 12, "INSTALLED_BASE_RATE")
    scenario["order"] = ship_stock_order(part_id, 50)
    phase_out_part(part_id)
    campaign = create_campaign_for(part_id, "FLAT_RATE", 5)
    submit_campaign(campaign["id"])
    approve_campaign(campaign["id"], 20)
    scenario["allocation_request"] = create_allocation_request(
        campaign["id"], scenario["dealer"]["id"], 10)
    allocate_campaign(campaign["id"])
    close_campaign(campaign["id"])
    validate_success(api_client.obsolete_part(part_id, PLANNER))
    scenario["campaign"] = read_campaign(campaign["id"])
    return scenario


def test_receive_refused_when_the_part_became_obsolete_in_transit(api):
    """PRD 3.7: "Receiving closes the loop. It requires `logistics_status` to be
    `IN_TRANSIT` and the part not to be `OBSOLETE`."
    PRD 2.10: "Otherwise the matching state code (409): `ERR_PART_LIFECYCLE_INVALID`,
    `ERR_CAMPAIGN_STATE_INVALID`, `ERR_ALLOCATION_STATE_INVALID`,
    `ERR_LINE_STATE_INVALID`, `ERR_WORK_ORDER_STATE_INVALID`,
    `ERR_REPLENISHMENT_STATE_INVALID` or `ERR_RETURN_STATE_INVALID`."

    Design: Difficulty/cross_entity_state_dependency/replenishment_receive_gated_by_part_obsolete
    """
    scenario = _obsolete_while_in_transit()

    resp = api.receive_replenishment_order(scenario["order"]["id"], CONTROLLER)
    validate_error(resp, ApiErrorId.ERR_PART_LIFECYCLE_INVALID.value)

    order = read_replenishment_order(scenario["order"]["id"])
    assert order["logistics_status"] == "IN_TRANSIT", \
        "the order's own dimensions never moved"
    assert order["approval_status"] == "APPROVED"


def test_obsolete_part_leaves_the_order_in_transit_and_writes_no_ledger(api):
    """PRD 3.8: "At the far end of the lifecycle, a part moves from `LTB_CLOSED` to
    `OBSOLETE`, and only from `LTB_CLOSED`. Obsoleting sets `stocking_policy` to
    `NO_STOCK` and zeroes both `safety_stock_units` and `reorder_point_units`; every
    replenishment order on the part whose `approval_status` is still `PENDING` is moved
    to `approval_status` `REJECTED`; `current_list_unit_price_cents` is recomputed at
    the fifteen-point `OBSOLETE` scarcity uplift; and the part's `version` advances."
    PRD 3.8: "Closing the campaign moves it from `ALLOCATING` to `CLOSED`. Every
    request on it still in `PENDING` is moved to `DENIED`, and the part moves from
    `LTB_OPEN` to `LTB_CLOSED`"

    Design: Difficulty/cross_entity_state_dependency/replenishment_receive_gated_by_part_obsolete
    """
    scenario = _obsolete_while_in_transit()
    api.receive_replenishment_order(scenario["order"]["id"], CONTROLLER)

    part = read_part(scenario["part"]["id"])
    assert part["lifecycle_state"] == "OBSOLETE"
    assert part["on_hand_units"] == 0
    assert part["in_transit_units"] == 50
    assert part["stocking_policy"] == "NO_STOCK"

    request = read_allocation_request(scenario["allocation_request"]["id"])
    assert request["status"] == "GRANTED"
    assert request["granted_units"] == 10
    campaign = read_campaign(scenario["campaign"]["id"])
    assert campaign["status"] == "CLOSED"
    assert campaign["remaining_qty"] == 10

    _, meta = list_ledger(scenario["part"]["id"])
    assert meta["total_count"] == 0, "nothing was ever booked in"


def test_backorder_promotion_sweep_is_greedy_and_skips_the_oversized_line(api):
    """PRD 3.7: "The candidates are every part line on the received part whose
    `line_status` is `BACKORDERED`. They are sorted by three keys in this order: first
    by the downtime rank of their parent work order's `downtime_priority`, ascending,
    where `MACHINE_DOWN` ranks 0, `DEGRADED` ranks 1 and `PLANNED` ranks 2; then by
    `qty_requested` ascending, so that small jobs clear first; and finally by
    `created_at` ascending as the tie-break."
    PRD 3.7: "The sweep is then a single greedy pass, **not** a best-fit search: the
    sorted list is walked exactly once, and a line is promoted from `BACKORDERED` to
    `RESERVED` only when the part's `available_units` is at least that line's
    `qty_requested` at the moment the line is considered. Each promotion raises
    `allocated_units` by that line's `qty_requested`, which immediately lowers
    `available_units` for every line still to be considered. A line that does not fit
    is simply skipped and the sweep continues to the next one — so a large
    `MACHINE_DOWN` line can be passed over while a smaller `DEGRADED` line behind it is
    promoted."
    PRD 3.7: "Once the sweep completes, any work order that no longer has a line in
    `BACKORDERED` moves from `PARTS_PENDING` back to `OPEN`."

    Design: Corner/state_machines/backorder_promotion_sweep_is_greedy_and_skips_oversized_line
    """
    scenario = setup_catalogue(
        part_number="SWEEP-1", unit_cost_cents=1333, lead_time_days=0,
        weight_kg=1.0, dealer_code="D-SWEEP", model_code="EM-M10",
        serial_prefix="SN-M10", qty_per_unit=1,
        price_rules=(("DESIRABLE", 0.35, 0.60, 0.20),))
    dealer_id = scenario["dealer"]["id"]
    unit_id = scenario["unit"]["id"]
    part_id = scenario["part"]["id"]

    wo_a = create_work_order(unit_id, dealer_id, "BREAKDOWN", "MACHINE_DOWN")
    wo_b = create_work_order(unit_id, dealer_id, "BREAKDOWN", "DEGRADED")
    wo_c = create_work_order(unit_id, dealer_id, "BREAKDOWN", "MACHINE_DOWN")
    line_big = add_part_line(wo_a["id"], dealer_id, part_id, 10)
    line_mid = add_part_line(wo_b["id"], dealer_id, part_id, 3)
    line_small = add_part_line(wo_c["id"], dealer_id, part_id, 2)
    order = ship_stock_order(part_id, 5)

    validate_success(api.receive_replenishment_order(order["id"], CONTROLLER))

    assert validate_success(api.get_part_line(line_small["id"], PLANNER))[
        "line_status"] == "RESERVED", "MACHINE_DOWN with the smallest qty goes first"
    assert validate_success(api.get_part_line(line_big["id"], PLANNER))[
        "line_status"] == "BACKORDERED", "qty 10 does not fit and is skipped"
    assert validate_success(api.get_part_line(line_mid["id"], PLANNER))[
        "line_status"] == "RESERVED", "the sweep continues past the skipped line"

    part = read_part(part_id)
    assert part["on_hand_units"] == 5
    assert part["allocated_units"] == 5
    assert part["available_units"] == 0

    assert validate_success(api.get_work_order(wo_c["id"], PLANNER))["status"] == "OPEN"
    assert validate_success(api.get_work_order(wo_b["id"], PLANNER))["status"] == "OPEN"
    assert validate_success(api.get_work_order(wo_a["id"], PLANNER))["status"] \
        == "PARTS_PENDING"

    entries, meta = list_ledger(part_id)
    assert meta["total_count"] == 1
    assert entries[0]["delta_units"] == 5


def test_operator_emergency_air_order_needs_a_below_reorder_point_part(api):
    """PRD 3.7: "Two rules police operator-raised orders. Expediting must be justified
    by the stock position: an `EMERGENCY_AIR` order raised by an operator is accepted
    only when the part's `replenishment_status` is `BELOW_REORDER_POINT`, and otherwise
    refused with `ERR_AIR_FREIGHT_NOT_JUSTIFIED`."
    PRD 2.8: "A part that has never been classified has a `reorder_point_units` of 0
    and therefore reads `NORMAL` regardless of how empty its shelf is."
    PRD 3.7: "`freight_cost_cents` is 0 for a `STOCK` order"
    PRD 3.7: "`total_landed_cost_cents` is the snapshotted `unit_cost_cents`
    multiplied by `qty` plus `freight_cost_cents`."

    Design: Corner/validations/emergency_air_replenishment_not_justified_when_stock_is_normal
    """
    part = create_part(part_number="JST-1", description="Justification probe",
                       unit_cost_cents=1000, lead_time_days=20, weight_kg=5.0)
    assert part["replenishment_status"] == "NORMAL"

    refused = api.create_replenishment_order(
        create_replenishment_order_payload(part["id"], "EMERGENCY_AIR", 3), CONTROLLER)
    validate_error(refused, ApiErrorId.ERR_AIR_FREIGHT_NOT_JUSTIFIED.value)

    accepted = validate_success(api.create_replenishment_order(
        create_replenishment_order_payload(part["id"], "STOCK", 3), CONTROLLER), 201)
    assert accepted["freight_cost_cents"] == 0
    assert accepted["total_landed_cost_cents"] == 3000

    _, meta = validate_paginated(api.list_replenishment_orders(
        CONTROLLER, params={"part_id": part["id"]}))
    assert meta["total_count"] == 1
