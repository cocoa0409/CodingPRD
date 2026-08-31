"""Running the spindle, closing the production dimension and the secondary route."""

from test_helpers import (
    ApiErrorId,
    add_routing_step,
    api_client,
    certify_bar_lot,
    index_tool,
    make_machinist_headers,
    make_quality_manager_headers,
    make_shop_planner_headers,
    read_bar_lot,
    read_machine,
    read_routing_step,
    read_work_order,
    receive_bar_lot,
    restore_machine,
    schedule_work_order,
    setup_interrupted_work_order,
    setup_running_work_order,
    setup_scheduled_work_order,
    setup_shop_floor,
    validate_error,
    validate_paginated,
    validate_success,
)

PLANNER = make_shop_planner_headers()
QUALITY = make_quality_manager_headers()


class TestRoutingStepPreconditions:
    """A secondary step cannot open while the spindle is still turning."""

    def test_routing_step_cannot_open_while_the_job_is_still_running(self):
        """PRD 3.6: "`PENDING → IN_PROGRESS` requires that the step's work order
        has already reached `machining_status` `MACHINING_COMPLETE` and, when
        `predecessor_step_id` is not null, that the predecessor step is
        `COMPLETE`."
        PRD 2.9: "After those comes the generic state check: the target resource
        must be in a state from which the requested transition is declared,
        otherwise `ERR_INVALID_STATE` (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/routing_step_start_requires_machining_complete
        """
        shop = setup_running_work_order()
        step = add_routing_step(shop.work_order_id, sequence=1, operation="DEBURR")

        response = api_client.advance_routing_step(
            step["id"], {"to_status": "IN_PROGRESS"}, make_machinist_headers(shop.machinist_id)
        )
        validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)

    def test_refused_routing_step_stays_pending_and_the_job_keeps_running(self):
        """PRD 3.6: "A new step opens in `status` `PENDING`, one of `PENDING`,
        `IN_PROGRESS`, `COMPLETE` and `BLOCKED`, with `blocked_reason` null."
        PRD 2.8: "Neither dimension consults the other when it advances, with
        exactly one exception: the quality dimension may not reach `ACCEPTED` or
        `REJECTED` until the production dimension is already at
        `MACHINING_COMPLETE`."

        Design: Difficulty/cross_entity_state_dependency/routing_step_start_requires_machining_complete
        """
        shop = setup_running_work_order()
        step = add_routing_step(shop.work_order_id, sequence=1, operation="DEBURR")
        api_client.advance_routing_step(
            step["id"], {"to_status": "IN_PROGRESS"}, make_machinist_headers(shop.machinist_id)
        )

        assert read_routing_step(step["id"])["status"] == "PENDING"
        assert read_work_order(shop.work_order_id)["machining_status"] == "RUNNING"


def test_start_on_an_uncertified_bar_lot_is_refused():
    """PRD 3.6: "Starting from `SCHEDULED` requires that the machine named by the
    work order is `AVAILABLE`, that the bar lot named by the work order is
    `CERTIFIED`, that no tool station on that machine sits in `OFFSET_HOLD` or
    `LIFE_EXPIRED`, that the operator behind `X-User-ID` exists and is `ACTIVE`,
    and — when the work order's `lights_out_hours` is greater than zero — that the
    operator's `certifications` array contains `LIGHTS_OUT`."

    Design: Corner/state_machines/start_on_uncertified_bar_lot_returns_not_certified
    """
    shop = setup_shop_floor()
    uncertified = receive_bar_lot(heat_number="H-88232")
    work_order = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        uncertified["id"],
        qty_ordered=200,
        lights_out_hours=4,
    )

    response = api_client.start_work_order(
        work_order["id"], make_machinist_headers(shop.machinist_id)
    )
    validate_error(response, ApiErrorId.ERR_BAR_LOT_NOT_CERTIFIED.value)

    assert read_work_order(work_order["id"])["machining_status"] == "SCHEDULED"
    assert read_machine(shop.machine_id)["status"] == "AVAILABLE"
    assert validate_success(
        api_client.get_kanban_release(shop.release_id, PLANNER), 200
    )["status"] == "RELEASED"


def test_quarantine_sentinel_certificate_blocks_the_lot_permanently():
    """PRD 3.2: "One sentinel value inverts the outcome: when the supplied
    `certificate_number` is exactly the literal string `QUARANTINE`, the lot moves
    `RECEIVED → QUARANTINED` instead, and a quarantined lot can never back a work
    order start for the rest of its life."
    PRD 3.6: "`ERR_BAR_LOT_NOT_CERTIFIED` (HTTP 409) when the lot is `RECEIVED`,
    `QUARANTINED` or `DEPLETED`"

    Design: Corner/state_machines/quarantine_sentinel_certificate_blocks_the_lot_permanently
    """
    shop = setup_shop_floor()
    suspect = receive_bar_lot(heat_number="H-88232")
    quarantined = certify_bar_lot(suspect["id"], "QUARANTINE")
    assert quarantined["status"] == "QUARANTINED"

    work_order = schedule_work_order(
        shop.release_id, shop.machine_id, suspect["id"], qty_ordered=200, lights_out_hours=4
    )
    response = api_client.start_work_order(
        work_order["id"], make_machinist_headers(shop.machinist_id)
    )
    validate_error(response, ApiErrorId.ERR_BAR_LOT_NOT_CERTIFIED.value)
    assert read_work_order(work_order["id"])["machining_status"] == "SCHEDULED"


def test_lights_out_start_by_an_uncertified_operator_is_refused():
    """PRD 3.6: "The rejection codes are, in evaluation order,
    `ERR_MACHINE_NOT_AVAILABLE` (HTTP 409) when the machine is `RUNNING` or
    `DOWN`, `ERR_BAR_LOT_NOT_CERTIFIED` (HTTP 409) when the lot is `RECEIVED`,
    `QUARANTINED` or `DEPLETED`, `ERR_TOOL_LIFE_EXPIRED` (HTTP 409) when any
    station on the machine is held, and `ERR_OPERATOR_NOT_CERTIFIED` (HTTP 403)
    when a lights-out job is started by an operator lacking the `LIGHTS_OUT`
    code."
    PRD 3.6: "A successful start writes `machinist_operator_id` from `X-User-ID`
    — on a restart it overwrites whatever operator was recorded before, so the
    last operator to touch the spindle is the one on the record."

    Design: Corner/errors/lights_out_start_by_an_uncertified_operator_is_rejected
    """
    shop = setup_scheduled_work_order(lights_out_hours=4)

    refused = api_client.start_work_order(
        shop.work_order_id, make_machinist_headers(shop.inspector_id)
    )
    validate_error(refused, ApiErrorId.ERR_OPERATOR_NOT_CERTIFIED.value)

    started = validate_success(
        api_client.start_work_order(
            shop.work_order_id, make_machinist_headers(shop.machinist_id)
        ),
        200,
    )
    assert started["machinist_operator_id"] == shop.machinist_id
    assert started["machining_status"] == "RUNNING"


def test_completion_moves_reserved_length_into_consumed_and_accrues_swarf():
    """PRD 3.6: "Completion then performs four things in one operation: it moves
    the work order's `reserved_length_mm` on the bar lot out of
    `reserved_length_mm` and into `consumed_length_mm`, leaving
    `available_length_mm` untouched; it drives the lot `CERTIFIED → DEPLETED` when
    both `available_length_mm` and `reserved_length_mm` have reached exactly 0; it
    computes the job's `chip_kg` and coolant make-up and accrues both onto the
    machine as described in §3.7; and it sets the machine `RUNNING → AVAILABLE`,
    clears `current_work_order_id` and increments the machine's `version` by one."
    PRD 3.7: "The job's `chip_kg` is those consumed metres multiplied by the bar
    lot's `mass_kg_per_meter`, minus the good-piece count multiplied by the part's
    `finished_mass_g` divided by 1,000 to convert grams to kilograms, with the
    result rounded half up to 3 decimal places."

    Design: Corner/state_machines/complete_machining_moves_reserved_length_to_consumed
    """
    shop = setup_running_work_order()

    completed = validate_success(
        api_client.complete_machining(
            shop.work_order_id,
            {"qty_good": 200, "qty_scrap": 0, "actual_run_seconds": 8400},
            make_machinist_headers(shop.machinist_id),
        ),
        200,
    )
    assert completed["machining_status"] == "MACHINING_COMPLETE"
    assert completed["chip_kg"] == 3.504
    assert completed["qty_good"] == 200
    assert completed["quality_status"] == "PENDING_INSPECTION"

    lot = read_bar_lot(shop.lot_id)
    assert lot["reserved_length_mm"] == 0
    assert lot["consumed_length_mm"] == 7200
    assert lot["available_length_mm"] == 64800

    machine = read_machine(shop.machine_id)
    assert machine["coolant_makeup_liters"] == 0.817
    assert machine["status"] == "AVAILABLE"
    assert machine["current_work_order_id"] is None


def test_derived_ledgers_settle_inside_the_completing_request():
    """PRD 3.7: "In the same operation, the machine's `coolant_makeup_liters` is
    increased by the job's `actual_run_seconds` divided by 3,600 and multiplied by
    0.35 litres of coolant make-up per machine hour, with the running total
    rounded half up to 3 decimal places."
    PRD 2.7: "At every instant, `available_length_mm` plus `reserved_length_mm`
    plus `consumed_length_mm` equals `total_length_mm` exactly."

    Design: Corner/consistency_model/derived_ledgers_are_reconciled_within_the_same_request
    """
    shop = setup_running_work_order()

    response = validate_success(
        api_client.complete_machining(
            shop.work_order_id,
            {"qty_good": 200, "qty_scrap": 0, "actual_run_seconds": 8400},
            make_machinist_headers(shop.machinist_id),
        ),
        200,
    )
    assert response["machining_status"] == "MACHINING_COMPLETE"
    assert response["chip_kg"] == 3.504

    lot = read_bar_lot(shop.lot_id)
    assert lot["available_length_mm"] == 64800
    assert lot["reserved_length_mm"] == 0
    assert lot["consumed_length_mm"] == 7200
    assert (
        lot["available_length_mm"] + lot["reserved_length_mm"] + lot["consumed_length_mm"]
        == 72000
    )

    machine = read_machine(shop.machine_id)
    assert machine["coolant_makeup_liters"] == 0.817
    assert machine["status"] == "AVAILABLE"


def test_completing_with_more_pieces_than_ordered_is_refused():
    """PRD 3.6: "The sum of good and scrap pieces must not exceed the work
    order's `qty_ordered`; a larger sum is rejected with `ERR_QTY_EXCEEDS_ORDERED`
    (HTTP 422)."

    Design: Corner/errors/completing_with_more_pieces_than_ordered_is_rejected
    """
    shop = setup_running_work_order()

    response = api_client.complete_machining(
        shop.work_order_id,
        {"qty_good": 250, "qty_scrap": 0, "actual_run_seconds": 9300},
        make_machinist_headers(shop.machinist_id),
    )
    validate_error(response, ApiErrorId.ERR_QTY_EXCEEDS_ORDERED.value)

    work_order = read_work_order(shop.work_order_id)
    assert work_order["machining_status"] == "RUNNING"
    assert work_order["qty_good"] == 0

    lot = read_bar_lot(shop.lot_id)
    assert lot["reserved_length_mm"] == 7200
    assert lot["consumed_length_mm"] == 0


def test_cancelling_a_work_order_blocks_its_pending_routing_steps():
    """PRD 3.6: "Cancellation is a `ShopPlanner` act, declared from `SCHEDULED`
    and from `INTERRUPTED`, and carries a `reason` that is stored as the work
    order's `cancel_reason`."
    PRD 3.6: "Every routing step on the cancelled work order that is `PENDING`,
    `BLOCKED` or `IN_PROGRESS` is moved to `BLOCKED` with `blocked_reason`
    recorded as `WORK_ORDER_CANCELLED`."

    Design: Corner/state_machines/cancel_work_order_blocks_its_pending_routing_steps
    """
    shop = setup_scheduled_work_order()
    first = add_routing_step(shop.work_order_id, sequence=1, operation="DEBURR")
    second = add_routing_step(
        shop.work_order_id, sequence=2, operation="WASH", predecessor_step_id=first["id"]
    )

    cancelled = validate_success(
        api_client.cancel_work_order(
            shop.work_order_id, {"reason": "CUSTOMER_PULL_IN"}, PLANNER
        ),
        200,
    )
    assert cancelled["machining_status"] == "CANCELLED"
    assert cancelled["cancel_reason"] == "CUSTOMER_PULL_IN"

    assert read_routing_step(first["id"])["status"] == "BLOCKED"
    assert read_routing_step(first["id"])["blocked_reason"] == "WORK_ORDER_CANCELLED"
    assert read_routing_step(second["id"])["status"] == "BLOCKED"

    lot = read_bar_lot(shop.lot_id)
    assert lot["available_length_mm"] == 72000
    assert lot["reserved_length_mm"] == 0


def test_restarting_an_interrupted_job_returns_its_blocked_steps_to_pending():
    """PRD 3.6: "A restart out of `INTERRUPTED` carries one extra effect: every
    routing step on this work order sitting in `BLOCKED` is returned to `PENDING`
    and its `blocked_reason` is cleared."
    PRD 3.6: "It sets the machine `AVAILABLE → RUNNING`, points the machine's
    `current_work_order_id` at this work order, and increments the machine's
    `version` by one."

    Design: Corner/state_machines/restart_of_interrupted_work_order_unblocks_its_routing_steps
    """
    shop = setup_interrupted_work_order(routing_step_count=1)
    step = shop.routing_steps[0]
    assert read_routing_step(step["id"])["status"] == "BLOCKED"

    index_tool(shop.tool_id, shop.machinist_id, new_tool_code="T05-OD-B")
    restore_machine(shop.machine_id, shop.machinist_id)

    restarted = validate_success(
        api_client.start_work_order(
            shop.work_order_id, make_machinist_headers(shop.machinist_id)
        ),
        200,
    )
    assert restarted["machining_status"] == "RUNNING"
    assert restarted["machinist_operator_id"] == shop.machinist_id

    machine = read_machine(shop.machine_id)
    assert machine["status"] == "RUNNING"
    assert machine["current_work_order_id"] == shop.work_order_id

    reopened = read_routing_step(step["id"])
    assert reopened["status"] == "PENDING"
    assert reopened["blocked_reason"] is None

    assert validate_success(
        api_client.get_kanban_release(shop.release_id, PLANNER), 200
    )["status"] == "IN_PRODUCTION"


def test_predecessor_step_from_another_work_order_is_refused():
    """PRD 3.6: "When a predecessor is supplied it must belong to the same work
    order and its `sequence` must be strictly lower than the new step's
    `sequence`; violating either condition is rejected with
    `ERR_PREDECESSOR_STEP_INVALID` (HTTP 422)."
    PRD 3.6: "Steps may be listed filtered by `work_order_id` or by
    `predecessor_step_id`."

    Design: Corner/errors/predecessor_step_from_another_work_order_is_rejected
    """
    shop = setup_shop_floor(committed_qty=400, release_qty=400)
    first_job = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-02T06:00:00Z",
        scheduled_end_at="2026-09-02T14:00:00Z",
    )
    second_job = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-04T06:00:00Z",
        scheduled_end_at="2026-09-04T14:00:00Z",
    )
    foreign_step = add_routing_step(first_job["id"], sequence=1, operation="DEBURR")

    response = api_client.create_routing_step(
        {
            "work_order_id": second_job["id"],
            "sequence": 2,
            "operation": "WASH",
            "predecessor_step_id": foreign_step["id"],
        },
        PLANNER,
    )
    validate_error(response, ApiErrorId.ERR_PREDECESSOR_STEP_INVALID.value)

    _, meta = validate_paginated(
        api_client.list_routing_steps(PLANNER, {"work_order_id": second_job["id"]})
    )
    assert meta["total_count"] == 0
