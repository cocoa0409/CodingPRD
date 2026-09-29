"""Factory capacity: overlap under the changeover buffer and the day ledger.

A production line is a shared resource. These tests exercise the buffered
half-open overlap test, the quarterly day budget, the precedence between an
order's state and the line's budget, and the conservation of committed days when
a build is re-planned.
"""

from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)

from test_helpers import (
    PLANNER,
    ApiErrorId,
    api_client,
    create_build_slot_payload,
    read_line,
    read_order,
    read_slot,
    setup_draft_order,
    setup_engineered_order,
    setup_reference_data,
)


def _reserve(env, order, line, **overrides):
    return api_client.create_build_slot(
        create_build_slot_payload(
            order["id"], line["id"], read_order(order["id"])["version"], **overrides
        ),
        PLANNER,
    )


def test_a_slot_starting_on_an_incumbents_end_date_still_collides():
    """The buffer widens both intervals forward, so the incumbent's guarded edge
    reaches five days past its end date and adjacency is not free.

    PRD: "Adjacency is therefore not free — with any non-zero changeover buffer, a
    slot starting exactly on an incumbent's `end_date` still collides."

    Design: Difficulty/resource_temporal_overlap/line_slot_adjacent_start_collides_under_changeover_buffer_returns_409
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    order_a = env["order"]
    slot_a = validate_success(
        _reserve(env, order_a, env["line"], start_date="2026-08-06", requested_slot_days=20),
        201,
    )
    assert slot_a["end_date"] == "2026-08-26"
    env_b = setup_engineered_order(dict(env))
    order_b = env_b["order"]

    response = _reserve(
        env, order_b, env["line"], start_date="2026-08-26", requested_slot_days=10
    )

    validate_error(response, ApiErrorId.ERR_SLOT_OVERLAP.value, 409)
    assert read_slot(slot_a["id"])["status"] == "RESERVED"
    assert read_slot(slot_a["id"])["end_date"] == "2026-08-26"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20
    _, meta = validate_paginated(
        api_client.list_build_slots(PLANNER, params={"machine_order_id": order_b["id"]})
    )
    assert meta["total_count"] == 0


def test_a_slot_starting_clear_of_the_buffered_edge_is_accepted():
    """Once the candidate starts beyond the incumbent's buffered edge the two
    builds coexist, and the line's ledger carries both.

    PRD: "Each comparison widens *both* intervals forward by the line's
    `changeover_buffer_days`: the candidate collides with an incumbent when the
    candidate's `start_date` falls before the incumbent's `end_date` advanced by the
    buffer **and** the incumbent's `start_date` falls before the candidate's
    `end_date` advanced by the buffer."

    Design: Difficulty/resource_temporal_overlap/line_slot_adjacent_start_collides_under_changeover_buffer_returns_409
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20),
        201,
    )
    env_b = setup_engineered_order(dict(env))

    data = validate_success(
        _reserve(
            env, env_b["order"], env["line"], start_date="2026-08-31", requested_slot_days=10
        ),
        201,
    )

    assert data["status"] == "RESERVED"
    assert data["start_date"] == "2026-08-31"
    assert data["end_date"] == "2026-09-10"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 30


def test_two_individually_legal_slots_may_still_break_the_quarterly_day_budget():
    """Neither slot exceeds the budget on its own and their intervals do not
    collide, so only the aggregate committed days can refuse the second
    reservation.

    PRD: "Last of all the capacity ledger is consulted: the line's
    `committed_slot_days` plus this slot's `slot_days` must not exceed the line's
    `capacity_days_per_quarter`, or the reservation is refused with
    `ERR_LINE_CAPACITY_EXCEEDED`."

    Design: Corner/validations/line_capacity_exceeded_by_aggregate_of_two_orders_returns_409
    """
    env = setup_engineered_order(
        setup_reference_data(
            line={
                "line_code": "LINE-TIGHT",
                "changeover_buffer_days": 0,
                "capacity_days_per_quarter": 25,
            }
        )
    )
    slot_a = validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20),
        201,
    )
    env_b = setup_engineered_order(dict(env))

    response = _reserve(
        env, env_b["order"], env["line"], start_date="2026-09-05", requested_slot_days=15
    )

    validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value, 409)
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20
    assert read_slot(slot_a["id"])["status"] == "RESERVED"
    _, meta = validate_paginated(
        api_client.list_build_slots(PLANNER, params={"machine_order_id": env_b["order"]["id"]})
    )
    assert meta["total_count"] == 0


def test_an_unengineered_order_is_reported_before_the_line_budget_problem():
    """The request breaks both the order-state rule and the line's day budget, and
    the fiscal gate is deliberately the lower-priority check.

    PRD: "The last three rungs are the fiscal gates, and they are deliberately the
    lowest-priority checks in the whole ladder, so that a request which is otherwise
    invalid never reports a budget problem: 59 is `ERR_LINE_CAPACITY_EXCEEDED` on
    build-slot reservation, 60 is `ERR_COVERAGE_EXHAUSTED` on visit booking, and 61
    is `ERR_POSTURE_RESTRICTED`, also on visit booking."

    Design: Difficulty/priority_pair_validation_conflict/build_slot_order_state_outranks_line_capacity_returns_409
    """
    env = setup_draft_order(
        setup_reference_data(line={"capacity_days_per_quarter": 10})
    )

    response = _reserve(
        env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20
    )

    error = validate_error(response, ApiErrorId.ERR_ORDER_NOT_ENGINEERED.value, 409)
    assert error["error_id"] != ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value
    assert read_line(env["line"]["id"])["committed_slot_days"] == 0
    assert read_order(env["order"]["id"])["fulfillment_status"] == "DRAFT"
    _, meta = validate_paginated(
        api_client.list_build_slots(PLANNER, params={"machine_order_id": env["order"]["id"]})
    )
    assert meta["total_count"] == 0


def test_once_the_order_is_engineered_the_same_request_reports_the_budget_gate():
    """Removing the higher-priority state violation uncovers the day-budget
    violation the first attempt had masked.

    PRD: "10. `ERR_ORDER_NOT_ENGINEERED` — the order's `fulfillment_status` is
    `ENGINEERED`; guards reserving a build slot."

    Design: Difficulty/priority_pair_validation_conflict/build_slot_order_state_outranks_line_capacity_returns_409
    """
    env = setup_engineered_order(
        setup_reference_data(line={"capacity_days_per_quarter": 10})
    )

    response = _reserve(
        env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20
    )

    validate_error(response, ApiErrorId.ERR_LINE_CAPACITY_EXCEEDED.value, 409)
    assert read_line(env["line"]["id"])["committed_slot_days"] == 0
    assert read_order(env["order"]["id"])["fulfillment_status"] == "ENGINEERED"


def test_re_planning_a_build_credits_the_superseded_slots_days_back_to_the_line():
    """Re-slotting the same order debits the new days and credits the old ones in
    the same request, so the ledger lands on the new slot's length rather than the
    sum of both.

    PRD: "The line's `committed_slot_days` is then re-derived — the new slot enters
    the committed set and the superseded one leaves it."

    Design: Difficulty/compensating_invariant/slot_supersede_credits_line_committed_days_ledger
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    slot_a = validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20),
        201,
    )
    assert read_line(env["line"]["id"])["committed_slot_days"] == 20

    slot_b = validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-09-05", requested_slot_days=15),
        201,
    )

    assert slot_b["status"] == "RESERVED"
    assert slot_b["slot_days"] == 15
    assert slot_b["end_date"] == "2026-09-20"
    assert read_slot(slot_a["id"])["status"] == "RELEASED"
    assert read_line(env["line"]["id"])["committed_slot_days"] == 15


def test_the_superseded_slot_keeps_its_own_history_and_names_its_replacement():
    """The released slot is an audit record, not a blanked row: it keeps the days it
    once held and points at the slot that took its place, leaving exactly one
    reserved slot on the line.

    PRD: "Any slot of the *same order* still sitting in `RESERVED` is moved to
    `RELEASED` with its `superseded_by_slot_id` set to the new slot's `id`, which is
    how re-planning a build reads in the audit trail."

    Design: Difficulty/compensating_invariant/slot_supersede_credits_line_committed_days_ledger
    """
    env = setup_engineered_order(setup_reference_data(line={}))
    slot_a = validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-08-06", requested_slot_days=20),
        201,
    )

    slot_b = validate_success(
        _reserve(env, env["order"], env["line"], start_date="2026-09-05", requested_slot_days=15),
        201,
    )

    released = read_slot(slot_a["id"])
    assert released["status"] == "RELEASED"
    assert released["superseded_by_slot_id"] == slot_b["id"]
    assert released["slot_days"] == 20
    rows, meta = validate_paginated(
        api_client.list_build_slots(
            PLANNER,
            params={"production_line_id": env["line"]["id"], "status": "RESERVED"},
        )
    )
    assert meta["total_count"] == 1
    assert rows[0]["id"] == slot_b["id"]
