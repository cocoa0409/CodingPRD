"""Tool wear, the four-hop machine-down chain, restoration and reclamation."""

from test_helpers import (
    ApiErrorId,
    api_client,
    complete_machining,
    load_tool,
    log_offset,
    make_machinist_headers,
    make_shop_planner_headers,
    read_bar_lot,
    read_machine,
    read_release,
    read_routing_step,
    read_tool_assignment,
    read_work_order,
    register_machine,
    register_machinist,
    schedule_work_order,
    set_clock,
    setup_held_tool_station,
    setup_interrupted_work_order,
    setup_machine_with_two_alloy_accruals,
    setup_scheduled_work_order,
    setup_shop_floor,
    start_work_order,
    validate_error,
    validate_success,
)

PLANNER = make_shop_planner_headers()


class TestToolStationCycle:
    """IN_SERVICE to OFFSET_HOLD and back, on its own accumulators."""

    def test_offset_log_landing_on_the_drift_limit_holds_the_station(self):
        """PRD 3.7: "Otherwise, if the absolute value of `cumulative_drift_um` is
        greater than or equal to the station's `drift_limit_um`, the station moves
        `IN_SERVICE → OFFSET_HOLD`."
        PRD 3.7: "Both comparisons include their boundary: a station that lands
        exactly on its rated life, or exactly on its drift limit, is held."

        Design: Difficulty/non_linear_state_machine/tool_assignment_offset_hold_index_cycle
        """
        set_clock()
        machinist = register_machinist()
        machine = register_machine()
        tool = load_tool(machine["id"], expected_life_pieces=1500, drift_limit_um=8)
        log_offset(tool["id"], machinist["id"], 40, 3)

        held = validate_success(
            api_client.post_offset_log(
                tool["id"],
                {"pieces_produced": 40, "measured_drift_um": 5},
                make_machinist_headers(machinist["id"]),
            ),
            200,
        )
        assert held["status"] == "OFFSET_HOLD"
        assert held["cumulative_drift_um"] == 8

    def test_indexing_returns_the_station_to_service_but_not_the_machine(self):
        """PRD 3.7: "Without `retire`, a station in `OFFSET_HOLD` or
        `LIFE_EXPIRED` returns to `IN_SERVICE` with `pieces_since_index`,
        `cumulative_drift_um` and `offset_log_count` all reset to 0 — the return
        edge that makes the tool station cyclic."
        PRD 3.7: "Crucially, indexing does **not** bring the machine back — the
        machine is restored by its own separate action and by nothing else."
        PRD 3.7: "A successful restore moves the machine `DOWN → AVAILABLE` and
        increments its `version` by one."

        Design: Difficulty/non_linear_state_machine/tool_assignment_offset_hold_index_cycle
        """
        shop = setup_held_tool_station()

        indexed = validate_success(
            api_client.index_tool_assignment(
                shop.tool_id,
                {"new_tool_code": "T05-OD-B"},
                make_machinist_headers(shop.machinist_id),
            ),
            200,
        )
        assert indexed["status"] == "IN_SERVICE"
        assert indexed["pieces_since_index"] == 0
        assert indexed["cumulative_drift_um"] == 0
        assert indexed["offset_log_count"] == 0
        assert indexed["tool_code"] == "T05-OD-B"

        assert read_machine(shop.machine_id)["status"] == "DOWN", (
            "indexing the station must not restore the machine"
        )
        restored = validate_success(
            api_client.restore_machine(
                shop.machine_id, make_machinist_headers(shop.machinist_id)
            ),
            200,
        )
        assert restored["status"] == "AVAILABLE"


class TestToolHoldCascade:
    """Station held, machine down, job interrupted, steps blocked."""

    def test_tool_hold_sends_the_machine_down_and_interrupts_the_running_job(self):
        """PRD 3.7: "**Hop two**, caused by that station being held, sends the
        station's machine to `DOWN` when the machine was `RUNNING` or `AVAILABLE`,
        and increments the machine's `version` by one."
        PRD 3.7: "**Hop three**, caused by the machine reaching `DOWN`, moves the
        work order on that machine whose `machining_status` is `RUNNING` to
        `INTERRUPTED` and clears the machine's `current_work_order_id`; when no job
        was running, this hop and the next simply have nothing to act on."

        Design: Difficulty/transitive_cascade/tool_offset_hold_to_machine_to_work_order_to_routing_steps
        """
        shop = setup_interrupted_work_order(routing_step_count=2)

        tool = read_tool_assignment(shop.tool_id)
        assert tool["status"] == "OFFSET_HOLD"
        assert tool["cumulative_drift_um"] == 8
        assert tool["pieces_since_index"] == 80

        machine = read_machine(shop.machine_id)
        assert machine["status"] == "DOWN"
        assert machine["current_work_order_id"] is None

        work_order = read_work_order(shop.work_order_id)
        assert work_order["machining_status"] == "INTERRUPTED"
        assert work_order["quality_status"] == "PENDING_INSPECTION"

    def test_interrupted_work_order_blocks_its_pending_routing_steps(self):
        """PRD 3.7: "**Hop four**, caused by that work order reaching
        `INTERRUPTED`, moves every routing step of that work order that is
        `PENDING` to `BLOCKED` and records its `blocked_reason` as
        `UPSTREAM_MACHINE_DOWN`."
        PRD 3.7: "Either hold fires the same four-hop chain, and every hop must be
        applied."

        Design: Difficulty/transitive_cascade/tool_offset_hold_to_machine_to_work_order_to_routing_steps
        """
        shop = setup_interrupted_work_order(routing_step_count=2)
        first, second = shop.routing_steps

        blocked_first = read_routing_step(first["id"])
        assert blocked_first["status"] == "BLOCKED"
        assert blocked_first["blocked_reason"] == "UPSTREAM_MACHINE_DOWN"
        assert read_routing_step(second["id"])["status"] == "BLOCKED"


class TestReclamationSettlement:
    """Per-alloy lines rounded on their own, then summed."""

    def test_each_alloy_line_is_rounded_before_the_lines_are_summed(self):
        """PRD 3.7: "Each line's credit is its kilograms multiplied by the scrap
        rate for that alloy — 118 cents per kilogram for `303SS`, 132 for `316SS`,
        465 for `C360`, 87 for `6061AL` and 41 for `12L14` — rounded half up to a
        whole cent **on that line alone**."
        PRD 3.7: "The chip credit is the sum of those rounded per-line integers;
        summing the unrounded lines and rounding once at the end is not the
        declared order and will differ by whole cents whenever the dropped
        fractions accumulate."
        PRD 3.7: "The net reclamation credit is the chip credit minus the coolant
        cost, and no rounding is ever applied to that grand total."

        Design: Difficulty/combinatorial_formula/reclamation_credit_round_per_alloy_line_then_sum
        """
        shop = setup_machine_with_two_alloy_accruals()
        assert shop.work_order_a["chip_kg"] == 3.504
        assert shop.work_order_b["chip_kg"] == 2.861

        settled = validate_success(
            api_client.reclaim_machine(
                shop.machine_id, {"collected_at": "2026-09-04T00:00:00Z"}, PLANNER
            ),
            200,
        )
        assert settled["last_reclamation_credit_cents"] == 1179
        assert settled["last_reclamation_credit_cents"] != 1180, (
            "summing the unrounded alloy lines first would have produced 1180"
        )
        assert settled["lifetime_reclamation_credit_cents"] == 1179

    def test_settlement_empties_the_chip_map_and_the_coolant_bucket(self):
        """PRD 3.7: "The settlement then writes itself onto the machine:
        `last_reclamation_credit_cents` is set to the net credit — it may be
        negative when the coolant bill outruns the scrap value —
        `lifetime_reclamation_credit_cents` is increased by the same net credit,
        `chip_accrual_by_alloy` is emptied back to an empty map,
        `coolant_makeup_liters` is set to 0, and the machine's `version` is
        incremented by one."
        PRD 3.7: "Because settlement zeroes both buckets, already-settled accrual
        can never be counted twice."

        Design: Difficulty/combinatorial_formula/reclamation_credit_round_per_alloy_line_then_sum
        """
        shop = setup_machine_with_two_alloy_accruals()

        settled = validate_success(
            api_client.reclaim_machine(
                shop.machine_id, {"collected_at": "2026-09-04T00:00:00Z"}, PLANNER
            ),
            200,
        )
        assert settled["coolant_makeup_liters"] == 0
        assert settled["chip_accrual_by_alloy"] == {}
        assert settled["status"] == "AVAILABLE"

        stored = read_machine(shop.machine_id)
        assert stored["chip_accrual_by_alloy"] == {}
        assert stored["coolant_makeup_liters"] == 0


class TestStartBlockedByMachineState:
    """A job whose own state is startable is still refused on a DOWN machine."""

    def test_start_is_refused_while_the_machine_is_down(self):
        """PRD 3.6: "The rejection codes are, in evaluation order,
        `ERR_MACHINE_NOT_AVAILABLE` (HTTP 409) when the machine is `RUNNING` or
        `DOWN`, `ERR_BAR_LOT_NOT_CERTIFIED` (HTTP 409) when the lot is `RECEIVED`,
        `QUARANTINED` or `DEPLETED`, `ERR_TOOL_LIFE_EXPIRED` (HTTP 409) when any
        station on the machine is held, and `ERR_OPERATOR_NOT_CERTIFIED` (HTTP
        403) when a lights-out job is started by an operator lacking the
        `LIGHTS_OUT` code."
        PRD 3.7: "and from `AVAILABLE`, when a tool hold lands on an idle machine,
        in which case no work order is affected because none is running."

        Design: Difficulty/cross_entity_state_dependency/work_order_start_blocked_by_machine_down
        """
        shop = setup_scheduled_work_order()
        tool = load_tool(shop.machine_id, expected_life_pieces=1500, drift_limit_um=8)
        log_offset(tool["id"], shop.machinist_id, 40, 3)
        log_offset(tool["id"], shop.machinist_id, 40, 5)
        assert read_machine(shop.machine_id)["status"] == "DOWN"

        response = api_client.start_work_order(
            shop.work_order_id, make_machinist_headers(shop.machinist_id)
        )
        validate_error(response, ApiErrorId.ERR_MACHINE_NOT_AVAILABLE.value)

    def test_refused_start_leaves_the_job_scheduled_and_the_release_released(self):
        """PRD 3.6: "A successful start writes `machinist_operator_id` from
        `X-User-ID` — on a restart it overwrites whatever operator was recorded
        before, so the last operator to touch the spindle is the one on the
        record."
        PRD 3.6: "It moves the work order's kanban release `RELEASED →
        IN_PRODUCTION` when the release is still `RELEASED`; no quantity moves on
        the blanket order at this point, because the pieces were already shifted
        into `open_released_qty` when the release was cut."

        Design: Difficulty/cross_entity_state_dependency/work_order_start_blocked_by_machine_down
        """
        shop = setup_scheduled_work_order()
        tool = load_tool(shop.machine_id, expected_life_pieces=1500, drift_limit_um=8)
        log_offset(tool["id"], shop.machinist_id, 40, 3)
        log_offset(tool["id"], shop.machinist_id, 40, 5)

        api_client.start_work_order(
            shop.work_order_id, make_machinist_headers(shop.machinist_id)
        )

        work_order = read_work_order(shop.work_order_id)
        assert work_order["machining_status"] == "SCHEDULED"
        assert work_order["machinist_operator_id"] is None
        assert read_machine(shop.machine_id)["status"] == "DOWN"
        assert read_release(shop.release_id)["status"] == "RELEASED"


def test_restore_is_blocked_while_a_station_remains_held():
    """PRD 3.7: "Restoring a machine is a `Machinist` act declared only from
    `DOWN`. It succeeds only when no tool station on that machine remains in
    `OFFSET_HOLD` or `LIFE_EXPIRED`; if one does, the restore is rejected with
    `ERR_TOOL_LIFE_EXPIRED`."

    Design: Corner/state_machines/machine_restore_blocked_while_a_tool_station_is_held
    """
    shop = setup_held_tool_station()

    refused = api_client.restore_machine(
        shop.machine_id, make_machinist_headers(shop.machinist_id)
    )
    validate_error(refused, ApiErrorId.ERR_TOOL_LIFE_EXPIRED.value)

    validate_success(
        api_client.index_tool_assignment(
            shop.tool_id, {"new_tool_code": "T05-OD-B"}, make_machinist_headers(shop.machinist_id)
        ),
        200,
    )
    restored = validate_success(
        api_client.restore_machine(shop.machine_id, make_machinist_headers(shop.machinist_id)),
        200,
    )
    assert restored["status"] == "AVAILABLE"
    assert read_tool_assignment(shop.tool_id)["status"] == "IN_SERVICE"


def test_retiring_a_station_locks_it_and_clears_the_path_for_a_restore():
    """PRD 3.7: "When `retire` is supplied as true, a station in `OFFSET_HOLD` or
    `LIFE_EXPIRED` moves to `RETIRED` instead, permanently; any further offset log
    or index attempt against a `RETIRED` station is rejected with
    `ERR_INVALID_STATE`."
    PRD 3.7: "A `RETIRED` station does not block a restore, because the guard
    inspects only the two held statuses — retiring a station is therefore a
    legitimate way to clear the path."

    Design: Corner/state_machines/tool_index_with_retire_true_moves_station_to_retired
    """
    shop = setup_held_tool_station()

    retired = validate_success(
        api_client.index_tool_assignment(
            shop.tool_id, {"retire": True}, make_machinist_headers(shop.machinist_id)
        ),
        200,
    )
    assert retired["status"] == "RETIRED"

    refused_log = api_client.post_offset_log(
        shop.tool_id,
        {"pieces_produced": 5, "measured_drift_um": 1},
        make_machinist_headers(shop.machinist_id),
    )
    validate_error(refused_log, ApiErrorId.ERR_INVALID_STATE.value)

    restored = validate_success(
        api_client.restore_machine(shop.machine_id, make_machinist_headers(shop.machinist_id)),
        200,
    )
    assert restored["status"] == "AVAILABLE"


def test_tool_life_expires_exactly_at_the_rated_piece_count():
    """PRD 3.7: "If, after the log has been applied, `pieces_since_index` is
    greater than or equal to the station's `expected_life_pieces`, the station
    moves `IN_SERVICE → LIFE_EXPIRED`."
    PRD 3.7: "Both comparisons include their boundary: a station that lands
    exactly on its rated life, or exactly on its drift limit, is held."

    Design: Corner/calculations/tool_life_threshold_fires_at_exactly_expected_life_pieces
    """
    set_clock()
    machinist = register_machinist(certifications=["SWISS_SETUP"])
    first_machine = register_machine(asset_tag="SW-01")
    second_machine = register_machine(asset_tag="SW-02")
    first_tool = load_tool(
        first_machine["id"], station=5, tool_code="TA", expected_life_pieces=100, drift_limit_um=8
    )
    second_tool = load_tool(
        second_machine["id"], station=5, tool_code="TB", expected_life_pieces=100, drift_limit_um=8
    )

    under = validate_success(
        api_client.post_offset_log(
            second_tool["id"],
            {"pieces_produced": 99, "measured_drift_um": 1},
            make_machinist_headers(machinist["id"]),
        ),
        200,
    )
    assert under["status"] == "IN_SERVICE"
    assert under["pieces_since_index"] == 99

    at_limit = validate_success(
        api_client.post_offset_log(
            first_tool["id"],
            {"pieces_produced": 100, "measured_drift_um": 1},
            make_machinist_headers(machinist["id"]),
        ),
        200,
    )
    assert at_limit["status"] == "LIFE_EXPIRED"
    assert at_limit["pieces_since_index"] == 100

    assert read_machine(first_machine["id"])["status"] == "DOWN"
    assert read_machine(second_machine["id"])["status"] == "AVAILABLE"


def test_drift_accumulation_is_signed_and_trips_at_the_absolute_limit():
    """PRD 3.7: "The station's `pieces_since_index` is increased by the pieces
    produced, its `cumulative_drift_um` is increased by the measured drift"
    PRD 3.7: "Otherwise, if the absolute value of `cumulative_drift_um` is greater
    than or equal to the station's `drift_limit_um`, the station moves
    `IN_SERVICE → OFFSET_HOLD`."

    Design: Corner/cross_cutting_complexity_layers/offset_drift_threshold_fires_at_exactly_the_limit
    """
    set_clock()
    machinist = register_machinist(certifications=["SWISS_SETUP"])
    first_machine = register_machine(asset_tag="SW-01")
    second_machine = register_machine(asset_tag="SW-02")
    first_tool = load_tool(
        first_machine["id"], station=5, tool_code="TA", expected_life_pieces=1500, drift_limit_um=8
    )
    second_tool = load_tool(
        second_machine["id"], station=5, tool_code="TB", expected_life_pieces=1500, drift_limit_um=8
    )
    log_offset(first_tool["id"], machinist["id"], 10, 3)
    log_offset(second_tool["id"], machinist["id"], 10, 3)

    climbing = log_offset(first_tool["id"], machinist["id"], 10, 4)
    assert climbing["cumulative_drift_um"] == 7
    assert climbing["status"] == "IN_SERVICE"

    corrected = log_offset(first_tool["id"], machinist["id"], 10, -1)
    assert corrected["cumulative_drift_um"] == 6
    assert corrected["status"] == "IN_SERVICE"

    negative_trip = log_offset(second_tool["id"], machinist["id"], 10, -11)
    assert negative_trip["cumulative_drift_um"] == -8
    assert negative_trip["status"] == "OFFSET_HOLD"

    assert read_tool_assignment(first_tool["id"])["pieces_since_index"] == 30
    assert read_machine(first_machine["id"])["status"] == "AVAILABLE"
    assert read_machine(second_machine["id"])["status"] == "DOWN"


def test_chip_and_coolant_accrue_across_successive_jobs():
    """PRD 3.7: "That chip mass is added to the machine's `chip_accrual_by_alloy`
    map under the part's `alloy_code` — the existing kilograms for that alloy, or
    zero if the alloy has no entry yet, plus the job's chip mass, rounded half up
    to 3 decimal places."
    PRD 3.7: "Work orders that have not reached `MACHINING_COMPLETE` contribute
    nothing to either bucket, because accrual is written only at completion."

    Design: Corner/calculations/chip_and_coolant_accrual_accumulates_across_two_jobs
    """
    shop = setup_shop_floor(committed_qty=400, release_qty=400)
    first = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-02T06:00:00Z",
        scheduled_end_at="2026-09-02T14:00:00Z",
    )
    start_work_order(first["id"], shop.machinist_id)
    first = complete_machining(
        first["id"], shop.machinist_id, qty_good=200, qty_scrap=0, actual_run_seconds=8400
    )

    second = schedule_work_order(
        shop.release_id,
        shop.machine_id,
        shop.lot_id,
        qty_ordered=200,
        lights_out_hours=0,
        scheduled_start_at="2026-09-03T06:00:00Z",
        scheduled_end_at="2026-09-03T12:00:00Z",
    )
    start_work_order(second["id"], shop.machinist_id)
    second = complete_machining(
        second["id"], shop.machinist_id, qty_good=200, qty_scrap=0, actual_run_seconds=5400
    )

    machine = read_machine(shop.machine_id)
    assert machine["chip_accrual_by_alloy"].get("303SS") == 7.008
    assert machine["coolant_makeup_liters"] == 1.342
    assert first["chip_kg"] == 3.504
    assert second["chip_kg"] == 3.504

    lot = read_bar_lot(shop.lot_id)
    assert lot["consumed_length_mm"] == 14400
    assert lot["available_length_mm"] == 57600
    assert lot["reserved_length_mm"] == 0
