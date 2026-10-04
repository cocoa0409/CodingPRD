"""Depth tests: resource temporal overlap (half-open slot adjacency,
whole-day training collision) and compensating invariants."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    create_agency,
    create_and_assign_slot,
    create_engineered_bus,
    create_parts_stock_payload,
    create_production_slot_payload,
    create_training_session_payload,
    create_warranty_claim_payload,
    get_success_data,
    make_warranty_admin_headers,
    setup_accepted_bus,
    setup_active_contract,
    validate_error,
    validate_success,
)

PP = TEST_USERS["production_planner_headers"]
WA = TEST_USERS["warranty_admin_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_back_to_back_slots_on_same_line_do_not_conflict(api):
    """PRD section 3.5: "Slot intervals are half-open: a slot occupies from
    its `start_ts` up to but not including its `end_ts`, so back-to-back slots
    where one slot's end equals the next slot's start do not conflict."

    Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency
    """
    resp = api.create_production_slot(
        create_production_slot_payload(
            line_id="LINE_A",
            start_ts="2026-09-01T00:00:00Z",
            end_ts="2026-09-05T00:00:00Z",
        ),
        PP,
    )
    slot_a = get_success_data(resp)

    resp = api.create_production_slot(
        create_production_slot_payload(
            line_id="LINE_A",
            start_ts="2026-09-05T00:00:00Z",
            end_ts="2026-09-08T00:00:00Z",
        ),
        PP,
    )
    slot_b = validate_success(resp, expected_status=201)
    assert slot_b["id"] != slot_a["id"]


def test_one_second_overlap_on_same_line_conflicts(api):
    """PRD section 3.5: "Any new or newly assigned slot whose interval
    overlaps another `OPEN` or `ASSIGNED` slot on the same line is rejected
    with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/production_slot_half_open_adjacency
    """
    resp = api.create_production_slot(
        create_production_slot_payload(
            line_id="LINE_A",
            start_ts="2026-09-01T00:00:00Z",
            end_ts="2026-09-05T00:00:00Z",
        ),
        PP,
    )
    get_success_data(resp)

    resp = api.create_production_slot(
        create_production_slot_payload(
            line_id="LINE_A",
            start_ts="2026-09-04T23:59:59Z",
            end_ts="2026-09-07T00:00:00Z",
        ),
        PP,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_same_agency_same_calendar_date_conflicts(api):
    """PRD section 3.10: "Two sessions for the same agency may not share a
    calendar date — the buffer is a whole day — and a colliding schedule is
    rejected with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/training_session_whole_day_collision
    """
    agency_a = create_agency()
    get_success_data(
        api.create_training_session(
            create_training_session_payload(
                agency_a["id"], scheduled_date="2026-09-10T09:00:00Z"
            ),
            WA,
        ),
    )
    resp = api.create_training_session(
        create_training_session_payload(
            agency_a["id"], propulsion_type="CNG",
            scheduled_date="2026-09-10T15:00:00Z", attendee_count=2,
        ),
        WA,
    )
    validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT)


def test_different_agency_same_date_and_same_agency_next_day_allowed(api):
    """PRD section 3.10: "Two sessions for the same agency may not share a
    calendar date — the buffer is a whole day — and a colliding schedule is
    rejected with `ERR_SCHEDULE_CONFLICT`."

    Design: Difficulty/resource_temporal_overlap/training_session_whole_day_collision
    """
    agency_a = create_agency()
    agency_b = create_agency(federally_funded=False)
    get_success_data(
        api.create_training_session(
            create_training_session_payload(
                agency_a["id"], scheduled_date="2026-09-10T09:00:00Z"
            ),
            WA,
        ),
    )
    # Different agency, same instant: allowed.
    resp = api.create_training_session(
        create_training_session_payload(
            agency_b["id"], scheduled_date="2026-09-10T09:00:00Z"
        ),
        WA,
    )
    validate_success(resp, expected_status=201)
    # Same agency, next calendar date: allowed.
    resp = api.create_training_session(
        create_training_session_payload(
            agency_a["id"], scheduled_date="2026-09-11T09:00:00Z",
            attendee_count=2,
        ),
        WA,
    )
    validate_success(resp, expected_status=201)


def test_slot_cancel_restores_bus_and_releases_occupancy(api):
    """PRD section 3.5: "Cancellation is permitted from `OPEN` without side
    effects, or from `ASSIGNED`, in which case the slot's `bus_unit_id` is
    cleared and the bus remains `ENGINEERED`."

    Design: Difficulty/compensating_invariant/slot_cancel_restores_bus_engineered_invariant
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    slot = create_and_assign_slot(
        bus["id"], start_ts="2026-09-01T00:00:00Z",
        end_ts="2026-09-05T00:00:00Z",
    )
    assert slot["bus_unit_id"] == bus["id"], (
        "assign occupies the slot with the bus"
    )

    resp = api.cancel_slot(slot["id"], PP)
    cancelled = validate_success(resp)
    assert cancelled["status"] == "CANCELLED"

    slot = get_success_data(api.get_production_slot(slot["id"], PP))
    assert slot["bus_unit_id"] is None, (
        f"cancel releases occupancy: bus_unit_id must be null, got "
        f"{slot['bus_unit_id']}"
    )
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "ENGINEERED", (
        f"the bus is unchanged by the assign/cancel round trip; got "
        f"{bus['status']}"
    )


def test_slot_cancel_then_reassign_keeps_bus_available(api):
    """PRD section 3.5: "Cancellation is permitted from `OPEN` without side
    effects, or from `ASSIGNED`, in which case the slot's `bus_unit_id` is
    cleared and the bus remains `ENGINEERED`."

    Design: Difficulty/compensating_invariant/slot_cancel_restores_bus_engineered_invariant
    """
    setup = setup_active_contract(contract_overrides={"base_quantity": 1})
    bus = create_engineered_bus(
        setup["contract"]["id"], setup["configuration"]["id"]
    )
    slot = create_and_assign_slot(
        bus["id"], start_ts="2026-09-01T00:00:00Z",
        end_ts="2026-09-05T00:00:00Z",
    )
    get_success_data(api.cancel_slot(slot["id"], PP))
    # The bus remains ENGINEERED, so a fresh slot accepts it again.
    slot2 = create_and_assign_slot(
        bus["id"], start_ts="2026-09-06T00:00:00Z",
        end_ts="2026-09-10T00:00:00Z",
    )
    assert slot2["bus_unit_id"] == bus["id"]
    bus = get_success_data(api.get_bus_unit(bus["id"], PP))
    assert bus["status"] == "ENGINEERED"


def _setup_claim_under_review(api, stock_quantity=5, unit_cost_cents=75000,
                              claimed_amount=150000):
    setup = setup_accepted_bus(
        component_overrides={"unit_cost_cents": unit_cost_cents},
    )
    component = setup["components"][0]
    resp = api.create_parts_stock(
        create_parts_stock_payload(
            setup["agency"]["id"], component["id"], quantity=stock_quantity
        ),
        WA,
    )
    stock = get_success_data(resp)
    resp = api.create_warranty_claim(
        create_warranty_claim_payload(
            setup["bus"]["id"], component["id"],
            defect_code="ALT_FAIL", claimed_amount_cents=claimed_amount,
        ),
        WA,
    )
    claim = get_success_data(resp)
    get_success_data(api.start_review_claim(claim["id"], WA))
    return setup, stock, claim


def test_approve_reserves_stock_conserving_available(api):
    """PRD section 3.9: "Approval also reserves physical stock: on the parts
    stock row keyed by the contract's agency and the claim's `component_id`,
    the `reserved_quantity` is increased by the number of units of that
    component the approved amount can fund, computed as the
    `approved_amount_cents` divided by the component's `unit_cost_cents`,
    rounded up to a whole unit."

    Design: Difficulty/compensating_invariant/warranty_reserve_release_stock_invariant
    """
    setup, stock, claim = _setup_claim_under_review(api)
    available_before = stock["quantity"] - stock["reserved_quantity"]

    resp = api.approve_claim(claim["id"], make_warranty_admin_headers("wa-1"))
    claim = validate_success(resp)
    assert claim["approved_amount_cents"] == 150000
    stock = get_success_data(api.get_parts_stock(stock["id"], WA))
    # approved 150000 / unit 75000 = 2 units reserved.
    assert stock["quantity"] == 5
    assert stock["reserved_quantity"] == 2
    assert stock["quantity"] - stock["reserved_quantity"] == 3 == available_before - 2


def test_pay_releases_reservation_conserving_available(api):
    """PRD section 3.9: "Payment releases the stock reservation, decrements
    the stock row's `quantity` by the reserved units consumed, and moves the
    claim `APPROVED` → `PAID`."

    Design: Difficulty/compensating_invariant/warranty_reserve_release_stock_invariant
    """
    setup, stock, claim = _setup_claim_under_review(api)
    resp = api.approve_claim(claim["id"], make_warranty_admin_headers("wa-1"))
    validate_success(resp)
    stock_after_approve = get_success_data(
        api.get_parts_stock(stock["id"], WA)
    )
    available_after_approve = (
        stock_after_approve["quantity"] - stock_after_approve["reserved_quantity"]
    )

    resp = api.pay_claim(claim["id"], make_warranty_admin_headers("wa-2"))
    paid = validate_success(resp)
    assert paid["status"] == "PAID"
    stock = get_success_data(api.get_parts_stock(stock["id"], WA))
    assert stock["quantity"] == 3
    assert stock["reserved_quantity"] == 0
    assert stock["quantity"] - stock["reserved_quantity"] == 3, (
        "the approve/pay pair conserves available stock: 5-2 after approve, "
        f"3-0 after pay; got {stock['quantity']}-{stock['reserved_quantity']}"
    )
    assert stock["quantity"] - stock["reserved_quantity"] == available_after_approve
