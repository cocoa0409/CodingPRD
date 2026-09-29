"""Individual validation gates at their declared boundaries: the refusal, the
row left untouched by the refusal, and the neighbouring call that is admitted.

Each pair of tests pins one rule's own error identity and then shows the
adjacent value passing, so a gate that is too wide and a gate that is too narrow
fail different tests.
"""
from test_helpers import (
    ADMIN,
    DISPATCHER,
    OPERATOR,
    SUPPORT,
    abort_mission,
    add_depot_bay,
    add_order,
    create_bay_reservation_payload,
    create_delivery_mission_payload,
    create_delivery_order_payload,
    create_robot_payload,
    create_route_plan_payload,
    dispatch_mission,
    health_action,
    intervention_action,
    load_payload,
    map_segment,
    mission_action,
    mission_transition_payload,
    open_intervention,
    provision_zone,
    read_bay,
    read_merchant,
    read_mission,
    read_order,
    read_robot,
    read_segment,
    read_zone,
    remedy_payload,
    segment_transition_payload,
    set_clock,
    setup_active_merchant,
    setup_available_robot,
    setup_completed_delivery,
    setup_en_route_mission,
    setup_exception_order,
    setup_handoff_ready_mission,
    setup_loaded_mission,
    setup_other_zone,
    setup_planned_mission,
    setup_received_order,
    setup_second_robot,
    survey_segment,
    validate_error,
    validate_paginated,
    validate_success,
)

CORRIDOR_LENGTH_M = 774.0
#: A nine-minute plan created here would end four minutes past curfew.
PAST_CURFEW_CLOCK_UTC = "2026-08-03T20:55:00.000Z"
#: The same plan created here ends at exactly 21:00.
LAST_LEGAL_CLOCK_UTC = "2026-08-03T20:51:00.000Z"
CHARGE_WINDOW = {
    "window_start_utc": "2026-08-03T10:00:00.000Z",
    "window_end_utc": "2026-08-03T11:00:00.000Z",
}
#: Two hours out from the 09:00 base clock, so `urgency_flag` stays false.
RELAXED_PROMISE_UTC = "2026-08-03T11:00:00.000Z"


class TestOrdinanceSpeedAtRegistration:
    def test_a_robot_faster_than_the_posted_limit_cannot_be_registered(self, api):
        """PRD §3.4: "Registration is also the first of two places where the zone
        ordinance is enforced against the machine: a robot whose `max_speed_cm_s`
        exceeds the zone's `ordinance_max_speed_cm_s` cannot be registered at all
        and the attempt is refused with `ERR_ORDINANCE_SPEED_EXCEEDED` (HTTP 422)."

        Design: Corner/validations/robot_registration_over_the_ordinance_speed_is_refused
        """
        zone = provision_zone()
        assert zone["ordinance_max_speed_cm_s"] == 160

        validate_error(
            api.create_robot(
                create_robot_payload(zone["id"], "RBT-FAST", max_speed_cm_s=200), ADMIN
            ),
            "ERR_ORDINANCE_SPEED_EXCEEDED",
            422,
        )
        validate_error(
            api.create_robot(
                create_robot_payload(zone["id"], "RBT-OVER", max_speed_cm_s=161), ADMIN
            ),
            "ERR_ORDINANCE_SPEED_EXCEEDED",
            422,
        )

        _rows, meta = validate_paginated(api.list_robots(ADMIN, {"zone_id": zone["id"]}))
        assert meta["total_count"] == 0

    def test_a_robot_built_for_exactly_the_posted_limit_is_registered(self, api):
        """PRD §3.4: "The comparison is inclusive in the robot's favour, so a robot
        built for exactly the posted limit is acceptable."
        PRD §3.4: "A newly registered robot has `duty_state` `OFFLINE`,
        `health_state` `NOMINAL`, `battery_pct` 100.0, `odometer_m` 0.0,
        `yield_event_count` 0, `tamper_flag` false, `lifetime_mission_count`,
        `lifetime_intervention_count`, `lifetime_escalation_count` and
        `clean_mission_count` all zero, both `rolling_autonomy_index` and
        `lifetime_autonomy_index` at 100, and `active_mission_id` and
        `current_bay_reservation_id` both null."

        Design: Corner/validations/robot_registration_over_the_ordinance_speed_is_refused
        """
        zone = provision_zone()

        robot = validate_success(
            api.create_robot(
                create_robot_payload(zone["id"], "RBT-EDGE", max_speed_cm_s=160), ADMIN
            ),
            201,
        )

        _rows, meta = validate_paginated(api.list_robots(ADMIN, {"zone_id": zone["id"]}))
        assert robot["max_speed_cm_s"] == 160
        assert robot["duty_state"] == "OFFLINE"
        assert meta["total_count"] == 1


class TestCurfewContainmentOfThePlannedRun:
    def test_a_run_that_would_end_past_curfew_is_refused(self, api):
        """PRD §3.6: "The operating-window gate consumes `planned_duration_min`:
        the interval that begins at the current logical-clock instant and ends that
        many minutes later must lie entirely inside the zone's daily window from
        `operating_window_start_utc_hhmm` to `operating_window_end_utc_hhmm` on the
        current UTC date, inclusive at both ends, and a route that would run past
        curfew is refused with `ERR_CURFEW_WINDOW_VIOLATION`."

        Nine minutes from 20:55 reaches 21:04, four minutes beyond the window.

        Design: Corner/validations/route_plan_must_finish_inside_the_operating_window
        """
        ctx = setup_loaded_mission()
        mission = ctx["mission"]
        set_clock(PAST_CURFEW_CLOCK_UTC)

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"],
                    [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]],
                    mission["version"],
                ),
                DISPATCHER,
            ),
            "ERR_CURFEW_WINDOW_VIOLATION",
            422,
        )

        _rows, meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"]})
        )
        assert meta["total_count"] == 0
        assert read_mission(ctx["mi"])["mission_state"] == "LOADED"

    def test_a_run_that_ends_exactly_at_curfew_is_admitted(self, api):
        """PRD §3.6: "The operating-window gate consumes `planned_duration_min`:
        the interval that begins at the current logical-clock instant and ends that
        many minutes later must lie entirely inside the zone's daily window from
        `operating_window_start_utc_hhmm` to `operating_window_end_utc_hhmm` on the
        current UTC date, inclusive at both ends, and a route that would run past
        curfew is refused with `ERR_CURFEW_WINDOW_VIOLATION`."
        PRD §3.6: "Creation is where all the geometry is derived and all the
        geometry gates run; the plan then lands in `plan_state` `DRAFT` and must
        still be validated and activated before the robot may move."

        Design: Corner/validations/route_plan_must_finish_inside_the_operating_window
        """
        ctx = setup_loaded_mission()
        mission = ctx["mission"]
        set_clock(LAST_LEGAL_CLOCK_UTC)

        plan = validate_success(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"],
                    [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]],
                    mission["version"],
                ),
                DISPATCHER,
            ),
            201,
        )

        assert plan["planned_duration_min"] == 9
        assert plan["plan_state"] == "DRAFT"
        assert plan["revision_index"] == 1
        assert read_mission(ctx["mi"])["mission_state"] == "LOADED"


class TestLoadAgainstTheContainerCapacity:
    def test_a_litre_over_the_container_burns_no_lid_code(self, api):
        """PRD §3.7: "The caller must be the merchant that owns the mission's
        order, or the request is refused with `ERR_NOT_RESOURCE_OWNER`, and
        `actual_payload_liters` must not exceed the robot's
        `container_capacity_liters`, or it is refused with
        `ERR_PAYLOAD_CAPACITY_EXCEEDED`."
        PRD §3.7: "Note that the loaded volume is checked independently of the
        ordered volume, so a merchant who overfills the container is caught here
        even though the order passed the same check at dispatch."

        Design: Corner/validations/load_within_container_capacity_is_admitted_at_the_boundary
        """
        ctx = setup_planned_mission()
        assert ctx["robot"]["container_capacity_liters"] == 60.0

        validate_error(
            api.load_delivery_mission(
                ctx["mi"], load_payload(61.0), ctx["merchant_headers"]
            ),
            "ERR_PAYLOAD_CAPACITY_EXCEEDED",
            422,
        )

        mission = read_mission(ctx["mi"])
        assert mission["mission_state"] == "PLANNED"
        assert mission["actual_payload_liters"] is None
        assert read_zone(ctx["z"])["lid_code_sequence"] == 0

    def test_a_load_of_exactly_the_container_volume_mints_the_first_code(self, api):
        """PRD §3.7: "A successful handoff carries the mission from `PLANNED` to
        `LOADED`, stores `actual_payload_liters` and mints the lid access code from
        a per-zone monotonic counter: the zone's `lid_code_sequence` advances by
        one, and `lid_access_code` becomes the six-digit zero-padded decimal
        representation of 100000 plus the new value of that sequence, so the first
        code minted in a zone is 100001."
        PRD §3.7: "The handoff is also timed against the merchant's promise:
        `handoff_late` is set to true when the elapsed time from the mission's
        `created_at` to the current instant strictly exceeds the merchant's
        `handoff_sla_seconds`, and false otherwise, so a handoff at exactly the SLA
        boundary is on time."

        Design: Corner/validations/load_within_container_capacity_is_admitted_at_the_boundary
        """
        ctx = setup_planned_mission()

        loaded = validate_success(
            api.load_delivery_mission(
                ctx["mi"], load_payload(60.0), ctx["merchant_headers"]
            )
        )

        assert loaded["mission_state"] == "LOADED"
        assert loaded["actual_payload_liters"] == 60.0
        assert loaded["lid_access_code"] == "100001"
        assert loaded["handoff_late"] is False
        assert read_zone(ctx["z"])["lid_code_sequence"] == 1


class TestLidCodeAtCompletion:
    def test_a_wrong_lid_code_leaves_the_whole_delivery_where_it_stood(self, api):
        """PRD §3.7: "Completion is the same dispatcher's action carrying the
        mission from `HANDOFF_READY` to the terminal `COMPLETED`; it repeats the
        same open-takeover gate and additionally requires a `lid_access_code` in
        the request that exactly equals the code minted at handoff, refusing a
        mismatch with `ERR_LID_CODE_MISMATCH` (HTTP 422)."

        Design: Corner/validations/completion_with_the_wrong_lid_code_is_refused
        """
        ctx = setup_handoff_ready_mission()

        validate_error(
            api.mission_transition(
                ctx["mi"],
                mission_transition_payload("COMPLETE", lid_access_code="000000"),
                DISPATCHER,
            ),
            "ERR_LID_CODE_MISMATCH",
            422,
        )

        mission = read_mission(ctx["mi"])
        order = read_order(ctx["o"])
        assert mission["mission_state"] == "HANDOFF_READY"
        assert mission["completed_at_utc"] is None
        assert order["order_state"] == "IN_TRANSIT"
        assert order["settled_fee_cents"] is None
        assert read_robot(ctx["r"])["duty_state"] == "ON_MISSION"

    def test_the_minted_code_completes_the_same_mission(self, api):
        """PRD §3.7: "Completion is the same dispatcher's action carrying the
        mission from `HANDOFF_READY` to the terminal `COMPLETED`; it repeats the
        same open-takeover gate and additionally requires a `lid_access_code` in
        the request that exactly equals the code minted at handoff, refusing a
        mismatch with `ERR_LID_CODE_MISMATCH` (HTTP 422)."
        PRD §3.7: "Finally the robot returns from `ON_MISSION` to `AVAILABLE`, its
        `active_mission_id` is cleared, the zone's `on_mission_robot_count` is
        decremented, and the robot's history absorbs the mission:
        `lifetime_mission_count` advances by one, `lifetime_intervention_count` by
        the mission's `intervention_count`, `lifetime_escalation_count` by its
        `escalation_count`, and `clean_mission_count` by one only when the mission
        recorded no interventions at all, after which both autonomy index variants
        of §3.5 are recomputed."

        Eight 100-metre units of the 774.0 m haul at 22 plus 349 plus 120 plus 180
        plus one crossing at 35 is 860 gross, and 5 percent off rounds to 817.

        Design: Corner/validations/completion_with_the_wrong_lid_code_is_refused
        """
        ctx = setup_handoff_ready_mission()
        validate_error(
            api.mission_transition(
                ctx["mi"],
                mission_transition_payload("COMPLETE", lid_access_code="000000"),
                DISPATCHER,
            ),
            "ERR_LID_CODE_MISMATCH",
        )

        completed = mission_action(ctx["mi"], "COMPLETE", lid_access_code=ctx["lid"])

        order = read_order(ctx["o"])
        robot = read_robot(ctx["r"])
        assert completed["mission_state"] == "COMPLETED"
        assert order["order_state"] == "DELIVERED"
        assert order["settled_fee_cents"] == 817
        assert robot["duty_state"] == "AVAILABLE"
        assert robot["lifetime_mission_count"] == 1


def _zone_at_its_concurrency_cap() -> dict:
    """Three available robots and three received orders in a zone whose
    `max_concurrent_robots` is 2, with two of the robots already on missions."""
    ctx = setup_received_order()
    second_robot = setup_second_robot(ctx, asset_tag="RBT-002")
    third_robot = setup_second_robot(ctx, asset_tag="RBT-003")
    ctx["r2"] = second_robot["id"]
    ctx["r3"] = third_robot["id"]
    ctx["order2"] = add_order(ctx["m"], ctx["s5"], customer_ref="C-2")
    ctx["order3"] = add_order(ctx["m"], ctx["s5"], customer_ref="C-3")
    ctx["o3"] = ctx["order3"]["id"]
    ctx["mission1"] = dispatch_mission(ctx["order"], ctx["r"])
    ctx["mission2"] = dispatch_mission(ctx["order2"], ctx["r2"])
    return ctx


class TestZoneConcurrencyCap:
    def test_the_third_concurrent_dispatch_is_refused_by_the_aggregate(self, api):
        """PRD §3.6: "When a robot is taken onto a mission, the zone's
        `on_mission_robot_count` must be strictly below its
        `max_concurrent_robots`; a zone already at its cap refuses the dispatch
        with `ERR_ZONE_ROBOT_CAP_EXCEEDED` (HTTP 409)."
        PRD §3.6: "This is the one rule where each individual dispatch is
        perfectly legal and only the aggregate fails, and it is checked at exactly
        the point where the counter would be incremented."

        Design: Corner/validations/zone_robot_cap_refuses_the_third_concurrent_dispatch
        """
        ctx = _zone_at_its_concurrency_cap()
        assert read_zone(ctx["z"])["max_concurrent_robots"] == 2
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 2

        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o3"], ctx["r3"], ctx["order3"]["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ZONE_ROBOT_CAP_EXCEEDED",
            409,
        )

        order3 = read_order(ctx["o3"])
        assert order3["order_state"] == "RECEIVED"
        assert order3["dispatch_attempt_count"] == 0
        assert read_robot(ctx["r3"])["duty_state"] == "AVAILABLE"
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 2

    def test_an_abort_frees_the_slot_the_third_dispatch_needed(self, api):
        """PRD §3.7: "The robot returns from `ON_MISSION` to `AVAILABLE` with
        exactly the same counter and index recomputation as on completion, because
        an aborted mission is a terminal mission and counts against the fleet just
        as a completed one does."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order
        that is dispatched a second time shows a count of two."
        PRD §3.6: "The zone's `on_mission_robot_count` advances by one."

        Design: Corner/validations/zone_robot_cap_refuses_the_third_concurrent_dispatch
        """
        ctx = _zone_at_its_concurrency_cap()
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o3"], ctx["r3"], ctx["order3"]["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ZONE_ROBOT_CAP_EXCEEDED",
        )

        abort_mission(ctx["mission1"]["id"], "DISPATCH_CANCELLED")
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 1
        mission3 = validate_success(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o3"], ctx["r3"], ctx["order3"]["version"]
                ),
                DISPATCHER,
            ),
            201,
        )

        assert mission3["mission_state"] == "PLANNED"
        assert read_robot(ctx["r3"])["duty_state"] == "ON_MISSION"
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 2
        assert read_order(ctx["o3"])["dispatch_attempt_count"] == 1


def _one_open_and_one_out_of_service_charge_bay() -> dict:
    """Two charge bays in the robot's own zone, one `OPEN` and one
    `OUT_OF_SERVICE`, both with an empty minutes ledger."""
    ctx = setup_available_robot()
    ctx["open_bay"] = add_depot_bay(
        ctx["z"], "B1", bay_type="CHARGE", power_kw=22.0, state="OPEN"
    )
    ctx["closed_bay"] = add_depot_bay(
        ctx["z"], "B2", bay_type="CHARGE", power_kw=22.0, state="OUT_OF_SERVICE"
    )
    return ctx


class TestBayReservationConsistencyGates:
    def test_the_wrong_type_and_the_wrong_service_state_have_their_own_errors(self, api):
        """PRD §3.4: "Three consistency gates then apply in order of the rejection
        ladder: the bay's `state` must be `OPEN`, or the request is refused with
        `ERR_BAY_OUT_OF_SERVICE` (HTTP 409); the requested `reservation_type` must
        be exactly equal to the bay's `bay_type`, so a `CHARGE` reservation on a
        `SERVICE` bay is refused with `ERR_BAY_TYPE_MISMATCH` (HTTP 422); and the
        bay's `zone_id` must equal the robot's `zone_id`, or the request is refused
        with `ERR_ZONE_MISMATCH`, because a robot may never be parked in another
        zone's depot."

        Design: Corner/validations/bay_reservation_checks_type_then_service_state
        """
        ctx = _one_open_and_one_out_of_service_charge_bay()

        validate_error(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["open_bay"]["id"],
                    ctx["r"],
                    ctx["open_bay"]["version"],
                    reservation_type="SERVICE",
                    **CHARGE_WINDOW,
                ),
                DISPATCHER,
            ),
            "ERR_BAY_TYPE_MISMATCH",
            422,
        )
        validate_error(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["closed_bay"]["id"],
                    ctx["r"],
                    ctx["closed_bay"]["version"],
                    reservation_type="CHARGE",
                    **CHARGE_WINDOW,
                ),
                DISPATCHER,
            ),
            "ERR_BAY_OUT_OF_SERVICE",
            409,
        )

        assert read_bay(ctx["open_bay"]["id"])["committed_minutes"] == 0
        assert read_bay(ctx["closed_bay"]["id"])["committed_minutes"] == 0

    def test_only_the_call_that_satisfies_both_gates_books_the_minutes(self, api):
        """PRD §3.4: "From that window the server derives `window_minutes` as the
        number of whole minutes from start to end, discarding any partial minute,
        and that value is frozen for the life of the reservation even though the
        window fields themselves are also immutable."
        PRD §3.4: "Creating a reservation books its minutes into two denormalized
        ledgers at once: the bay's `committed_minutes` increases by
        `window_minutes` and the zone's `reserved_bay_minutes` increases by the same
        amount, with the `version` of the bay, the zone and the new reservation each
        advancing by one."

        Design: Corner/validations/bay_reservation_checks_type_then_service_state
        """
        ctx = _one_open_and_one_out_of_service_charge_bay()
        validate_error(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["open_bay"]["id"],
                    ctx["r"],
                    ctx["open_bay"]["version"],
                    reservation_type="SERVICE",
                    **CHARGE_WINDOW,
                ),
                DISPATCHER,
            ),
            "ERR_BAY_TYPE_MISMATCH",
        )

        reservation = validate_success(
            api.create_bay_reservation(
                create_bay_reservation_payload(
                    ctx["open_bay"]["id"],
                    ctx["r"],
                    ctx["open_bay"]["version"],
                    reservation_type="CHARGE",
                    **CHARGE_WINDOW,
                ),
                DISPATCHER,
            ),
            201,
        )

        bay = read_bay(ctx["open_bay"]["id"])
        assert reservation["state"] == "HELD"
        assert reservation["window_minutes"] == 60
        assert bay["committed_minutes"] == 60
        assert bay["version"] == 2
        assert read_zone(ctx["z"])["reserved_bay_minutes"] == 60


class TestRemedyNeedsALatchedException:
    def test_a_delivery_inside_its_promise_cannot_be_remedied(self, api):
        """PRD §3.8: "The order must be in `order_state` `EXCEPTION` or
        `DELIVERED`, and its `exception_reason` must not be null, since a null
        reason selects no policy row and is refused with
        `ERR_INVALID_STATE_TRANSITION`; that is why a delivered order qualifies only
        when the `LATE` latch of §3.7 was applied to it."
        PRD §3.8: "A `REDELIVER` touches neither `remedy_spent_cents` nor the
        remaining budget and therefore can never be refused for budget reasons."

        Design: Corner/validations/remedy_on_a_clean_delivered_order_is_refused
        """
        ctx = setup_completed_delivery()
        assert ctx["order"]["order_state"] == "DELIVERED"
        assert ctx["order"]["exception_reason"] is None

        validate_error(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT),
            "ERR_INVALID_STATE_TRANSITION",
            409,
        )

        order = read_order(ctx["o"])
        zone = read_zone(ctx["z"])
        assert order["order_state"] == "DELIVERED"
        assert order["remedy_kind"] is None
        assert order["remedy_reason_code"] is None
        assert order["remedy_amount_cents"] is None
        assert order["settled_fee_cents"] == 817
        assert zone["remedy_spent_cents"] == 0
        assert zone["remedy_budget_remaining_cents"] == 50000


class TestOneRemedyPerOrder:
    def test_the_robot_fault_waterfall_pays_all_three_buckets_once(self, api):
        """PRD §3.8: "A `ROBOT_FAULT` failure refunds 35 percent of the fee,
        compensates 60 percent of the capped declared value and adds 250 cents."
        PRD §3.8: "The second bucket is the declared-value compensation: the
        order's `declared_value_cents` is first capped at 15000 cents, whichever of
        the two is smaller being the compensable value, that value is multiplied by
        the policy's declared-value fraction, and the product is rounded half up to
        whole cents on its own."
        PRD §3.8: "The remedy amount is the sum of the three rounded buckets."
        PRD §3.7: "`ZONE_REVOKED` maps to `BLOCKED_ROUTE`, `DISPATCH_CANCELLED`
        maps to `ROBOT_FAULT`, and `UNRECOVERABLE_BLOCKAGE` maps to
        `BLOCKED_ROUTE`."

        A 35 percent refund of the 850-cent quote rounds to 298, 60 percent of the
        9000-cent declared value is 5400 and the goodwill is 250, so the sum is
        5948.

        Design: Corner/validations/a_second_remedy_on_the_same_order_is_refused
        """
        ctx = setup_exception_order("DISPATCH_CANCELLED")
        assert ctx["order"]["exception_reason"] == "ROBOT_FAULT"

        remedied = validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        zone = read_zone(ctx["z"])
        assert remedied["remedy_amount_cents"] == 5948
        assert remedied["order_state"] == "REFUNDED"
        assert remedied["remedy_kind"] == "REFUND"
        assert zone["remedy_spent_cents"] == 5948
        assert zone["remedy_budget_remaining_cents"] == 44052

    def test_no_second_remedy_of_any_kind_reaches_the_same_order(self, api):
        """PRD §3.8: "Exactly one remedy may ever be issued against an order: a
        second attempt, whatever kind it names, is refused with
        `ERR_REMEDY_ALREADY_ISSUED` (HTTP 409) because `remedy_kind` is no longer
        null."

        Design: Corner/validations/a_second_remedy_on_the_same_order_is_refused
        """
        ctx = setup_exception_order("DISPATCH_CANCELLED")
        validate_success(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT)
        )

        validate_error(
            api.issue_order_remedy(ctx["o"], remedy_payload("REFUND"), SUPPORT),
            "ERR_REMEDY_ALREADY_ISSUED",
            409,
        )
        validate_error(
            api.issue_order_remedy(ctx["o"], remedy_payload("GOODWILL_CREDIT"), SUPPORT),
            "ERR_REMEDY_ALREADY_ISSUED",
            409,
        )

        assert read_order(ctx["o"])["remedy_amount_cents"] == 5948
        assert read_zone(ctx["z"])["remedy_spent_cents"] == 5948


class TestRouteTerminatesAtTheDropoff:
    def test_a_route_that_stops_short_of_the_dropoff_is_refused(self, api):
        """PRD §3.6: "The termination gate requires the last element of the
        sequence to be exactly the order's `dropoff_segment_id`, refusing anything
        else with `ERR_ROUTE_DROPOFF_MISMATCH`."

        The order's dropoff is S5, so a contiguous S1-S2-S3 prefix is a legal walk
        that simply ends in the wrong place.

        Design: Corner/validations/route_must_terminate_at_the_order_dropoff_segment
        """
        ctx = setup_loaded_mission()
        assert read_order(ctx["o"])["dropoff_segment_id"] == ctx["s5"]

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"],
                    [ctx["s1"], ctx["s2"], ctx["s3"]],
                    ctx["mission"]["version"],
                ),
                DISPATCHER,
            ),
            "ERR_ROUTE_DROPOFF_MISMATCH",
            422,
        )

        _rows, meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"]})
        )
        assert meta["total_count"] == 0

    def test_the_same_walk_extended_to_the_dropoff_is_admitted(self, api):
        """PRD §3.6: "The termination gate requires the last element of the
        sequence to be exactly the order's `dropoff_segment_id`, refusing anything
        else with `ERR_ROUTE_DROPOFF_MISMATCH`."
        PRD §3.6: "`total_length_m` is the sum of `length_m` over the sequence in
        the given order, carried to one decimal place."
        PRD §3.6: "Creation is where all the geometry is derived and all the
        geometry gates run; the plan then lands in `plan_state` `DRAFT` and must
        still be validated and activated before the robot may move."

        Design: Corner/validations/route_must_terminate_at_the_order_dropoff_segment
        """
        ctx = setup_loaded_mission()

        plan = validate_success(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"],
                    [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]],
                    ctx["mission"]["version"],
                ),
                DISPATCHER,
            ),
            201,
        )

        assert plan["total_length_m"] == CORRIDOR_LENGTH_M
        assert plan["revision_index"] == 1
        assert plan["plan_state"] == "DRAFT"
        assert read_mission(ctx["mi"])["active_route_plan_id"] is None


class TestSegmentApprovalAgainstTheOrdinanceClearance:
    def test_a_segment_narrower_than_the_ordinance_stays_surveyed(self, api):
        """PRD §3.1: "If the element's `measured_clearance_cm` is below the zone's
        `ordinance_min_clearance_cm` the approval is refused with
        `ERR_CLEARANCE_INSUFFICIENT`; the comparison is inclusive, so a clearance
        exactly equal to the ordinance minimum passes."
        PRD §3.1: "Surveying is the act that turns a mapped element into a scored
        one, moving `status` from `MAPPED` to `SURVEYED`."

        Design: Corner/validations/segment_approval_below_the_ordinance_clearance_is_refused
        """
        zone = provision_zone()
        assert zone["ordinance_min_clearance_cm"] == 90.0
        narrow = map_segment(zone["id"], "N1", measured_clearance_cm=88.0)
        survey_segment(narrow["id"])

        validate_error(
            api.segment_transition(
                narrow["id"], segment_transition_payload("APPROVE"), ADMIN
            ),
            "ERR_CLEARANCE_INSUFFICIENT",
            422,
        )

        segment = read_segment(narrow["id"])
        assert segment["status"] == "SURVEYED"
        assert segment["version"] == 2

    def test_a_segment_at_exactly_the_ordinance_minimum_is_approved(self, api):
        """PRD §3.1: "If the element's `measured_clearance_cm` is below the zone's
        `ordinance_min_clearance_cm` the approval is refused with
        `ERR_CLEARANCE_INSUFFICIENT`; the comparison is inclusive, so a clearance
        exactly equal to the ordinance minimum passes."
        PRD §3.1: "Approval is the gate that admits a segment to routing, moving
        `status` from `SURVEYED` to `APPROVED`, and it enforces exactly two
        compliance findings."

        Design: Corner/validations/segment_approval_below_the_ordinance_clearance_is_refused
        """
        zone = provision_zone()
        edge = map_segment(zone["id"], "E1", measured_clearance_cm=90.0)
        survey_segment(edge["id"])

        approved = validate_success(
            api.segment_transition(
                edge["id"], segment_transition_payload("APPROVE"), ADMIN
            )
        )

        _rows, meta = validate_paginated(
            api.list_sidewalk_segments(
                ADMIN, {"zone_id": zone["id"], "status": "APPROVED"}
            )
        )
        assert approved["status"] == "APPROVED"
        assert approved["version"] == 3
        assert meta["total_count"] == 1


def _en_route_mission_under_active_control() -> dict:
    """A live mission with one intervention event carried to `ACTIVE` by ro-1."""
    ctx = setup_en_route_mission()
    event = open_intervention(ctx["mi"], 30)
    intervention_action(event["id"], "ACKNOWLEDGE")
    ctx["event"] = intervention_action(event["id"], "ASSUME")
    ctx["ev"] = event["id"]
    return ctx


class TestArrivalAgainstOpenTakeovers:
    def test_arrival_is_refused_while_an_event_still_holds_control(self, api):
        """PRD §3.7: "Arrival is a `FleetDispatcher` action carrying the mission
        from `EN_ROUTE` to `HANDOFF_READY`, and it is gated on the intervention set:
        no event of this mission may still be in `REQUESTED`, `ACKNOWLEDGED`,
        `ACTIVE` or `ESCALATED`, or the arrival is refused with
        `ERR_TAKEOVER_REQUIRED`."

        Design: Corner/validations/arrival_is_refused_while_a_takeover_is_open
        """
        ctx = _en_route_mission_under_active_control()
        assert ctx["event"]["takeover_state"] == "ACTIVE"

        validate_error(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("ARRIVE"), DISPATCHER
            ),
            "ERR_TAKEOVER_REQUIRED",
            409,
        )

        assert read_mission(ctx["mi"])["mission_state"] == "EN_ROUTE"

    def test_arrival_is_admitted_once_control_is_released(self, api):
        """PRD §3.7: "Releasing control is the only route into the terminal
        `RELEASED` state and has three distinct forms, which differ in who may act
        and what is recorded."
        PRD §3.7: "From `ACTIVE` the operator named in `operator_user_id`
        releases; from `ESCALATED` a `SafetyOfficer` may release regardless of who
        assumed control, while a `RemoteOperator` still needs to be that named
        operator."
        PRD §3.7: "All three forms advance the mission's `intervention_count` by
        one, so even a waived request counts against the robot's autonomy index."

        Design: Corner/validations/arrival_is_refused_while_a_takeover_is_open
        """
        ctx = _en_route_mission_under_active_control()
        released = intervention_action(ctx["ev"], "RELEASE", headers=OPERATOR)

        arrived = validate_success(
            api.mission_transition(
                ctx["mi"], mission_transition_payload("ARRIVE"), DISPATCHER
            )
        )

        assert released["takeover_state"] == "RELEASED"
        assert released["operator_user_id"] == OPERATOR["X-User-ID"]
        assert released["control_seconds"] == 0
        assert arrived["mission_state"] == "HANDOFF_READY"
        assert arrived["intervention_count"] == 1
        assert arrived["escalation_count"] == 0


def _an_impaired_robot_and_a_robot_in_another_zone() -> dict:
    """One received order, one in-zone `IMPAIRED` robot and one healthy robot
    that is available in a different zone."""
    ctx = setup_received_order()
    health_action(ctx["r"], "DOWNGRADE")
    health_action(ctx["r"], "IMPAIR")
    other = setup_other_zone(with_robot=True)
    ctx["other_zone"] = other["z"]
    ctx["stranger"] = other["r"]
    return ctx


class TestDispatchEligibilityClauses:
    def test_impaired_health_and_a_foreign_zone_answer_with_their_own_errors(self, api):
        """PRD §3.6: "Its `health_state` must be `NOMINAL` or `DEGRADED`, or the
        dispatch is refused with `ERR_ROBOT_HEALTH_BLOCKED` (HTTP 409)."
        PRD §3.6: "The robot's `zone_id` must equal the `zone_id` of the order's
        dropoff segment, or the dispatch is refused with `ERR_ZONE_MISMATCH`."
        PRD §3.3: "The order itself lands in `order_state` `RECEIVED`, with
        `settled_fee_cents`, `exception_reason`, `remedy_kind`, `remedy_reason_code`
        and `remedy_amount_cents` all null and `dispatch_attempt_count` at zero."

        Design: Corner/validations/dispatch_gates_report_health_before_zone_mismatch
        """
        ctx = _an_impaired_robot_and_a_robot_in_another_zone()
        assert read_robot(ctx["r"])["health_state"] == "IMPAIRED"

        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o"], ctx["r"], ctx["order"]["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ROBOT_HEALTH_BLOCKED",
            409,
        )
        validate_error(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o"], ctx["stranger"], ctx["order"]["version"]
                ),
                DISPATCHER,
            ),
            "ERR_ZONE_MISMATCH",
            422,
        )

        order = read_order(ctx["o"])
        assert order["order_state"] == "RECEIVED"
        assert order["dispatch_attempt_count"] == 0

    def test_a_healthy_in_zone_robot_carries_the_order_into_dispatch(self, api):
        """PRD §3.6: "A successful dispatch writes four rows."
        PRD §3.6: "The order moves from `RECEIVED` to `DISPATCHED` and its
        `dispatch_attempt_count` advances by one, which is why a redelivered order
        that is dispatched a second time shows a count of two."
        PRD §3.6: "The zone's `on_mission_robot_count` advances by one."

        Design: Corner/validations/dispatch_gates_report_health_before_zone_mismatch
        """
        ctx = _an_impaired_robot_and_a_robot_in_another_zone()
        fresh = setup_second_robot(ctx, asset_tag="RBT-002")

        mission = validate_success(
            api.create_delivery_mission(
                create_delivery_mission_payload(
                    ctx["o"], fresh["id"], ctx["order"]["version"]
                ),
                DISPATCHER,
            ),
            201,
        )

        order = read_order(ctx["o"])
        assert mission["mission_state"] == "PLANNED"
        assert order["order_state"] == "DISPATCHED"
        assert order["dispatch_attempt_count"] == 1
        assert read_zone(ctx["z"])["on_mission_robot_count"] == 1
        assert read_zone(ctx["other_zone"])["on_mission_robot_count"] == 0


class TestStaleMissionVersionOutranksTheClearanceGate:
    def test_the_pinned_version_is_checked_before_the_geometry(self, api):
        """PRD §2.10: "The ladder is walked from the top and stops at the first
        violated rule, and its bands are, in order: authentication and
        authorisation; request-payload syntax; existence of referenced rows;
        parent-version pinning; state of the target row and of the rows it depends
        on; safety and ordinance compliance; structural consistency of the submitted
        graph; and finally capacity, caps and budgets."
        PRD §2.5: "A mismatch is rejected with `ERR_STALE_MISSION_VERSION` (HTTP
        412)."

        The same sequence is illegal for this 140-centimetre robot either way, so a
        request carrying the mission's pre-load version can only be answered by the
        higher band.

        Design: Corner/validations/stale_mission_version_is_reported_before_the_clearance_gate
        """
        ctx = setup_loaded_mission(robot_overrides={"width_cm": 140.0})
        assert ctx["mission"]["version"] == 2

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"], [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]], 1
                ),
                DISPATCHER,
            ),
            "ERR_STALE_MISSION_VERSION",
            412,
        )

        _rows, meta = validate_paginated(
            api.list_route_plans(DISPATCHER, {"mission_id": ctx["mi"]})
        )
        assert meta["total_count"] == 0

    def test_the_current_version_exposes_the_negative_clearance_margin(self, api):
        """PRD §3.6: "The clearance gate is inclusive: a `clearance_margin_cm` of
        exactly 0.0 passes and any negative margin is refused with
        `ERR_CLEARANCE_INSUFFICIENT` (HTTP 422)."
        PRD §3.6: "Because the margin is computed against the mission's own robot,
        one identical segment sequence can be perfectly legal for a narrow robot and
        illegal for a wider one."

        Design: Corner/validations/stale_mission_version_is_reported_before_the_clearance_gate
        """
        ctx = setup_loaded_mission(robot_overrides={"width_cm": 140.0})

        validate_error(
            api.create_route_plan(
                create_route_plan_payload(
                    ctx["mi"],
                    [ctx["s1"], ctx["s2"], ctx["s3"], ctx["s5"]],
                    ctx["mission"]["version"],
                ),
                DISPATCHER,
            ),
            "ERR_CLEARANCE_INSUFFICIENT",
            422,
        )

        mission = read_mission(ctx["mi"])
        assert mission["mission_state"] == "LOADED"
        assert mission["active_route_plan_id"] is None
        assert mission["version"] == 2


class TestPayloadTierCeiling:
    def test_forty_five_litres_is_the_last_admitted_volume(self, api):
        """PRD §3.3: "A volume above 45.0 litres has no payload tier and is refused
        with `ERR_INVALID_REQUEST`."
        PRD §3.3: "`payload_tier` is `SMALL` when `payload_liters` is at most 15.0
        litres, `MEDIUM` when it is above 15.0 but at most 30.0, and `LARGE` when it
        is above 30.0 but at most 45.0."

        Design: Corner/validations/payload_tier_ceiling_is_inclusive_at_forty_five_litres
        """
        ctx = setup_active_merchant()

        large = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    payload_liters=45.0,
                    promised_by_utc=RELAXED_PROMISE_UTC,
                ),
                ctx["merchant_headers"],
            ),
            201,
        )
        validate_error(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    customer_ref="C-2",
                    payload_liters=45.01,
                    promised_by_utc=RELAXED_PROMISE_UTC,
                ),
                ctx["merchant_headers"],
            ),
            "ERR_INVALID_REQUEST",
            400,
        )

        assert large["payload_tier"] == "LARGE"
        assert large["quoted_fee_cents"] == 812
        assert large["urgency_flag"] is False

    def test_each_admitted_tier_escrows_its_own_quote(self, api):
        """PRD §3.3: "The distance term first converts distance into whole
        100-metre units, rounding any partial unit up, and charges 22 cents per
        unit."
        PRD §3.3: "To that is added a base fee of 349 cents; the payload-tier
        supplement, which is 0 cents for `SMALL`, 120 cents for `MEDIUM` and 260
        cents for `LARGE`; an urgency surcharge of 180 cents when `urgency_flag` is
        true and nothing when it is false; 35 cents for each crossing traversed; and
        95 cents for each remote intervention counted against the delivery."
        PRD §3.3: "Immediately afterwards the quoted amount is escrowed: the
        merchant's `escrowed_fee_cents` increases by `quoted_fee_cents` and the
        merchant's `version` advances by one."

        An 800-metre haul is eight whole units at 22 cents, so the `LARGE` gross is
        176 + 349 + 260 + 70 and the `MEDIUM` gross is 176 + 349 + 120 + 70, each
        then discounted 5 percent for a `PREFERRED` merchant.

        Design: Corner/validations/payload_tier_ceiling_is_inclusive_at_forty_five_litres
        """
        ctx = setup_active_merchant()
        large = add_order(
            ctx["m"], ctx["s5"], payload_liters=45.0, promised_by_utc=RELAXED_PROMISE_UTC
        )

        medium = validate_success(
            api.create_delivery_order(
                create_delivery_order_payload(
                    ctx["m"],
                    ctx["s5"],
                    customer_ref="C-2",
                    payload_liters=30.0,
                    promised_by_utc=RELAXED_PROMISE_UTC,
                ),
                ctx["merchant_headers"],
            ),
            201,
        )

        _rows, meta = validate_paginated(
            api.list_delivery_orders(DISPATCHER, {"merchant_id": ctx["m"]})
        )
        assert medium["payload_tier"] == "MEDIUM"
        assert medium["quoted_fee_cents"] == 679
        assert medium["urgency_flag"] is False
        assert meta["total_count"] == 2
        assert read_merchant(ctx["m"])["escrowed_fee_cents"] == large[
            "quoted_fee_cents"
        ] + medium["quoted_fee_cents"]
