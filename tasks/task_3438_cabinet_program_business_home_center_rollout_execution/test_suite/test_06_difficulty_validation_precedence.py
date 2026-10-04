"""Validation-order precedence: state before fiscal, referential before temporal (PRD §2.9)."""

from prd_bench_local_runner.testing import validate_error, validate_paginated

from test_helpers import (
    PLANT_SCHEDULER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
    WEEK_MINUS_1,
    WEEK_NEXT,
    WEEK_PLUS_4,
    factories,
    make_dealer_rep_headers,
    order_line,
)
from test_helpers import fixtures


def test_cancelled_order_schedule_reports_state_not_fiscal(api):
    """A cancelled order that also still sits on CREDIT_HOLD violates both the
    from-state rule and the fiscal gate; the earlier state stage answers.

    PRD §2.9: "When a single request violates several rules, the response is determined by a fixed evaluation order, and a request rejected at an earlier stage never reaches a later one."
    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    PRD §3.4: "Scheduling belongs to the `PlantScheduler` and is gated fiscally: only an order whose `payment_status` is `UNINVOICED` may advance `ACKNOWLEDGED` → `SCHEDULED`; an order sitting on `CREDIT_HOLD` is rejected with `ERR_CREDIT_HOLD`."
    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_fiscal_gate_on_schedule
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=100)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=10)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=1)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    o2_ack = fixtures.acknowledge_order(api, o2["id"])
    assert o2_ack["payment_status"] == "CREDIT_HOLD"
    fixtures.cancel_order(api, o2["id"])

    # From-state CANCELLED is illegal for SCHEDULED (stage 5) and would also be
    # fiscally gated (stage 9): the state stage answers first.
    blocked = api.transition_order(
        o2["id"], {"to_status": "SCHEDULED"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_INVALID_STATE")

    after = fixtures.get_order(api, o2["id"])
    assert after["status"] == "CANCELLED"


def test_credit_hold_gate_blocks_live_schedule(api):
    """Without an earlier-stage violation, the fiscal gate itself answers
    ERR_CREDIT_HOLD for an acknowledged order on hold.

    PRD §3.4: "Scheduling belongs to the `PlantScheduler` and is gated fiscally: only an order whose `payment_status` is `UNINVOICED` may advance `ACKNOWLEDGED` → `SCHEDULED`; an order sitting on `CREDIT_HOLD` is rejected with `ERR_CREDIT_HOLD`."
    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    Design: Difficulty/priority_pair_validation_conflict/state_precondition_beats_fiscal_gate_on_schedule
    """
    world = fixtures.setup_active_program(
        api, account_overrides={"credit_limit_cents": 100000}
    )
    fixtures.create_production_slot(api, week=WEEK_NEXT, capacity_units=100)
    o1 = fixtures.place_order(
        api, world["account"], world["program"], lines=[order_line(quantity=10)]
    )
    o2 = fixtures.place_order(
        api, world["account"], world["program"],
        jobsite_address="2 Job Ln", lines=[order_line(quantity=1)],
    )
    fixtures.acknowledge_order(api, o1["id"])
    o2_ack = fixtures.acknowledge_order(api, o2["id"])
    assert o2_ack["payment_status"] == "CREDIT_HOLD"

    blocked = api.transition_order(
        o2["id"], {"to_status": "SCHEDULED"}, PLANT_SCHEDULER_HEADERS
    )
    validate_error(blocked, "ERR_CREDIT_HOLD")

    after = fixtures.get_order(api, o2["id"])
    assert after["status"] == "ACKNOWLEDGED"
    assert after["payment_status"] == "CREDIT_HOLD"


def test_unknown_family_beats_past_delivery_week(api):
    """One create carrying both an uncovered family and an impossible delivery
    week is answered by the referential stage, before the temporal stage.

    PRD §2.9: "When a single request violates several rules, the response is determined by a fixed evaluation order, and a request rejected at an earlier stage never reaches a later one."
    PRD §2.9: "The stages, from first to last: (1) authentication of the `X-User-ID` and `X-User-Role` headers (`ERR_UNAUTHENTICATED`); (2) authorization — the endpoint's role list, the per-transition role pins described in §3, entity-backed ownership, and claim segregation of duties (`ERR_FORBIDDEN`, `ERR_SEGREGATION_OF_DUTIES`); (3) existence of every path identifier and request-body reference (`ERR_NOT_FOUND`); (4) the optimistic-concurrency check on program-line creation (`ERR_STALE_VERSION`); (5) state legality — the entity's state machine plus the lifecycle gates (`ERR_INVALID_STATE`, `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`, `ERR_PROGRAM_TRANSITIONING`, `ERR_NO_ACTIVE_LINE`, `ERR_QUOTE_STALE`, `ERR_SHIPMENT_NOT_DELIVERED`, `ERR_ORDER_NOT_CANCELLABLE`); (6) referential business rules (`ERR_LINE_NOT_COVERED`, `ERR_STORE_NOT_SERVICED`, `ERR_NO_CURRENT_BATCH`, `ERR_INVALID_REQUEST`, `ERR_CHANNEL_REQUIRES_DESIGN_JOB`); (7) temporal rules (`ERR_DESIGNER_WINDOW_OVERLAP`, `ERR_MEASURE_WINDOW_INVALID`, `ERR_DELIVERY_WEEK_INVALID`, `ERR_CLAIM_WINDOW_EXPIRED`, `ERR_SLOT_WEEK_PAST`, `ERR_DISPOSITION_WINDOW_EXPIRED`); (8) constraint checks (`ERR_SLOT_EXISTS`, `ERR_REVISION_LIMIT_EXCEEDED`, `ERR_CLAIM_QUANTITY_EXCEEDED`, `ERR_COLOR_MISMATCH`, `ERR_NO_CAPACITY`, `ERR_DISPOSITION_OVERAGE`, `ERR_ACCOUNT_HAS_OPEN_ORDERS`); and finally (9) the fiscal gate at order scheduling (`ERR_CREDIT_HOLD`)."
    PRD §3.3: "The caller's `X-User-ID` must equal the order's `account_id` (`ERR_FORBIDDEN`), the account must be `ACTIVE` and the program `ACTIVE` or `TRANSITIONING` (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`), and every `family_code` must be covered by the program's `ACTIVE` line (`ERR_LINE_NOT_COVERED`)."
    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_order_create
    """
    world = fixtures.setup_active_program(api)
    payload = factories.order_payload(
        world["account"]["id"], world["program"]["id"],
        requested_delivery_week=WEEK_MINUS_1,
        lines=[order_line("GHOST", quantity=1)],
    )
    resp = api.create_order(payload, make_dealer_rep_headers(world["account"]["id"]))
    validate_error(resp, "ERR_LINE_NOT_COVERED")

    data, meta = validate_paginated(
        api.list_orders(PROGRAM_MANAGER_HEADERS, params={"account_id": world["account"]["id"]})
    )
    assert meta["total_count"] == 0
    assert data == []


def test_referential_and_temporal_legs_in_isolation(api):
    """Each leg of the pair fires alone: unknown family with a feasible week,
    and a known family with an infeasible week.

    PRD §3.3: "The caller's `X-User-ID` must equal the order's `account_id` (`ERR_FORBIDDEN`), the account must be `ACTIVE` and the program `ACTIVE` or `TRANSITIONING` (`ERR_ACCOUNT_NOT_ACTIVE`, `ERR_PROGRAM_NOT_ACTIVE`), and every `family_code` must be covered by the program's `ACTIVE` line (`ERR_LINE_NOT_COVERED`)."
    PRD §3.3: "The `requested_delivery_week` must be feasible: subtracting the smallest `base_lead_weeks` among the ordered families from it must not land before the current week (`ERR_DELIVERY_WEEK_INVALID`)."
    Design: Difficulty/priority_pair_validation_conflict/referential_beats_temporal_on_order_create
    """
    world = fixtures.setup_active_program(api)
    headers = make_dealer_rep_headers(world["account"]["id"])

    ghost = api.create_order(
        factories.order_payload(
            world["account"]["id"], world["program"]["id"],
            requested_delivery_week=WEEK_PLUS_4,
            lines=[order_line("GHOST", quantity=1)],
        ),
        headers,
    )
    validate_error(ghost, "ERR_LINE_NOT_COVERED")

    too_early = api.create_order(
        factories.order_payload(
            world["account"]["id"], world["program"]["id"],
            requested_delivery_week=WEEK_MINUS_1,
            lines=[order_line(quantity=1)],
        ),
        headers,
    )
    validate_error(too_early, "ERR_DELIVERY_WEEK_INVALID")

    data, meta = validate_paginated(
        api.list_orders(PROGRAM_MANAGER_HEADERS, params={"account_id": world["account"]["id"]})
    )
    assert meta["total_count"] == 0
