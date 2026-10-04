"""Auxiliary assistance: floors, caps, surge window, relief ledger, suspend cascade."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    adjustment_in_state,
    approve_auxiliary,
    create_auxiliary,
    evaluation_consulted,
    get_auxiliary,
    get_route,
    get_success_data,
    make_carrier_headers,
    reset_clock,
    set_clock,
    setup_route_with_active_points,
    setup_unit_with_route,
    validate_error,
    validate_success,
    create_carrier,
    create_point,
    activate_point,
)

SUP = TEST_USERS["supervisor_headers"]
PM = TEST_USERS["postmaster_headers"]
AMS = TEST_USERS["ams_headers"]

COUNTS = dict(letters_count_total=3600, flats_count_total=900, parcels_count_total=40,
              actual_street_minutes_total=2160, office_minutes_total=1440)


class TestOverrunFloor:

    def test_overrun_29_rejected_below_threshold(self, api):
        """PRD §3.8: "The projected overrun must be at least 30 minutes — below
        that floor no assistance is authorized and approval of such a request is
        rejected with `ERR_OVERRUN_BELOW_THRESHOLD`".

        Design: Difficulty/boundary_precision_check/auxiliary_overrun_29_vs_30_minutes_floor
        """
        reset_clock()
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        resp = api.create_auxiliary(
            ctx["unit"]["id"], ctx["route"]["id"],
            {"helper_carrier_id": aux_car["id"], "service_date": "2026-09-02",
             "projected_overrun_minutes": 29, "seasonal_surge_flag": False}, SUP)
        validate_error(resp, ApiErrorId.ERR_OVERRUN_BELOW_THRESHOLD)
        rows = get_success_data(api.list_auxiliary(ctx["unit"]["id"],
                                                   ctx["route"]["id"], SUP,
                                                   params={"limit": 100}))
        assert len(rows) == 0

    def test_overrun_30_accepted_and_schedules_exactly_30(self, api):
        """PRD §3.8: "an overrun of exactly 30 qualifies. The base assistance
        equals the projected overrun."
        PRD §3.8: "the route's `auxiliary_relief_minutes` increases by that
        amount."

        Design: Difficulty/boundary_precision_check/auxiliary_overrun_29_vs_30_minutes_floor
        """
        reset_clock()
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-09-02", 30, seasonal_surge_flag=False)
        approved = approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert approved["scheduled_minutes"] == 30
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 30


class TestApproveSideEffects:

    def test_approve_computes_minutes_and_accrues_relief(self, api):
        """PRD §3.8: "The result is capped at a hard maximum of 240 minutes (four
        hours) per assignment, and stored as `scheduled_minutes`; the route's
        `auxiliary_relief_minutes` increases by that amount."

        Design: Corner/state_machines/auxiliary_approve_side_effect_accrues_relief
        """
        reset_clock()
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-09-02", 60, seasonal_surge_flag=False)
        approved = approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert approved["status"] == "APPROVED"
        assert approved["scheduled_minutes"] == 60
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 60


class TestSurgeKickerAndCap:

    def _overburdened_route_ctx(self, api):
        """Route with current_evaluated_minutes 545 (post-adjustment), clock in
        the Nov 15 – Jan 2 surge window."""
        set_clock("2026-11-16T00:00:00Z")
        ctx = setup_unit_with_route()
        ctx = evaluation_consulted(ctx, outcome="CONCURRED", counts=COUNTS,
                                   kind="MINI_SURVEY")
        ctx = adjustment_in_state(ctx, state="APPROVED", proposed_minutes=545,
                                  effective_date="2026-11-24")
        set_clock("2026-11-24T00:00:00Z")
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["current_evaluated_minutes"] == 545
        ctx["route"] = route
        return ctx

    def test_cap_at_240_minutes(self, api):
        """PRD §3.8: "The result is capped at a hard maximum of 240 minutes (four
        hours) per assignment".

        Design: Corner/calculations/auxiliary_surge_kicker_and_cap_arithmetic
        """
        reset_clock()
        ctx = self._overburdened_route_ctx(api)
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-11-25", 300, seasonal_surge_flag=False)
        approved = approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert approved["scheduled_minutes"] == 240

    def test_surge_multiplier_then_kicker_order(self, api):
        """PRD §3.8: "Under the surge flag the base is multiplied by 1.25 and
        rounded half-up to whole minutes. If the route is already overburdened —
        its `current_evaluated_minutes` exceed its 480-minute
        `base_evaluated_minutes` — a fixed kicker of 15 minutes is added."

        Design: Corner/calculations/auxiliary_surge_kicker_and_cap_arithmetic
        """
        reset_clock()
        ctx = self._overburdened_route_ctx(api)
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-11-26", 100, seasonal_surge_flag=True)
        approved = approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        # round_half_up(100 * 1.25) + 15 = 125 + 15 = 140
        assert approved["scheduled_minutes"] == 140

    def test_relief_accrues_sum_of_approvals(self, api):
        """PRD §3.8: "the route's `auxiliary_relief_minutes` increases by that
        amount."

        Design: Corner/calculations/auxiliary_surge_kicker_and_cap_arithmetic
        """
        reset_clock()
        ctx = self._overburdened_route_ctx(api)
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux_cap = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                                   aux_car["id"], "2026-11-25", 300,
                                   seasonal_surge_flag=False)
        aux_kick = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                                    aux_car["id"], "2026-11-26", 100,
                                    seasonal_surge_flag=True)
        approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_cap["id"])
        approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_kick["id"])
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 380


class TestReliefNetZero:

    def test_relief_returns_to_zero_after_complete(self, api):
        """PRD §3.8: "A `RouteSupervisor` then either completes the assignment
        (`ACTIVE → COMPLETED`) when the work is done or curtails it (`ACTIVE →
        CURTAILED`); both release the accrued relief by subtracting
        `scheduled_minutes` from the route's `auxiliary_relief_minutes`."

        Design: Difficulty/compensating_invariant/auxiliary_relief_minutes_net_zero_after_complete
        """
        set_clock("2026-11-30T00:00:00Z")
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-12-01", 120, seasonal_surge_flag=True)
        approved = approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        # round_half_up(120 * 1.25) = 150; route at baseline 480, no kicker → wait:
        # 480 is not > 480, so no kicker. scheduled == 150.
        assert approved["scheduled_minutes"] == 150
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 150
        set_clock("2026-12-01T00:00:00Z")
        active = get_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert active["status"] == "ACTIVE"
        get_success_data(api.complete_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                                                aux["id"], SUP))
        done = get_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert done["status"] == "COMPLETED"
        route = get_route(ctx["unit"]["id"], ctx["route"]["id"])
        assert route["auxiliary_relief_minutes"] == 0


class TestSurgeWindow:

    def test_surge_flag_outside_window_rejected(self, api):
        """PRD §3.8: "when the surge flag is set, requires the current logical date
        to fall within the seasonal window running from November 15 through
        January 2 (else `ERR_TEMPORAL_WINDOW`)".

        Design: Corner/validations/surge_flag_outside_window_rejected
        """
        reset_clock()
        ctx = setup_unit_with_route()
        aux_car = create_carrier(ctx["unit"]["id"], carrier_class="AUXILIARY")
        aux = create_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux_car["id"],
                               "2026-09-02", 60, seasonal_surge_flag=True)
        resp = api.approve_auxiliary(ctx["unit"]["id"], ctx["route"]["id"],
                                     aux["id"], PM)
        validate_error(resp, ApiErrorId.ERR_TEMPORAL_WINDOW)
        after = get_auxiliary(ctx["unit"]["id"], ctx["route"]["id"], aux["id"])
        assert after["status"] == "REQUESTED"


class TestRouteLifecycle:

    def test_suspend_requires_empty_route_and_curtails_auxiliary(self, api):
        """PRD §3.3: "suspension requires `active_delivery_point_count` to be zero,
        because the universal service obligation forbids stranding addresses; a
        violation is rejected with `ERR_USO_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/state_gates_before_uso_safety_on_route_suspend
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        # Route carries one active point AND is UNDER_EVALUATION — both fail;
        # state (priority 5) beats USO safety (priority 7) per PRD §2.9 ordering.
        from test_helpers import open_evaluation
        open_evaluation(ctx["unit"]["id"], ctx["route"]["id"], kind="MINI_SURVEY")
        resp = api.suspend_route(ctx["unit"]["id"], ctx["route"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_suspend_with_active_points_rejected_uso(self, api):
        """PRD §3.3: "suspension requires `active_delivery_point_count` to be zero,
        because the universal service obligation forbids stranding addresses; a
        violation is rejected with `ERR_USO_VIOLATION`."

        Design: Difficulty/priority_pair_validation_conflict/state_gates_before_uso_safety_on_route_suspend
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        resp = api.suspend_route(ctx["unit"]["id"], ctx["route"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_USO_VIOLATION)

    def test_suspend_cascades_through_auxiliary_relief(self, api):
        """PRD §3.3: "Suspending a route moves it `STANDARD → SUSPENDED`, curtails
        every open auxiliary assignment on it (any assignment in `REQUESTED`,
        `APPROVED`, or `ACTIVE` moves to `CURTAILED` and the route's
        `auxiliary_relief_minutes` returns to zero)".

        Design: Difficulty/transitive_cascade/route_suspend_cascades_through_auxiliary_relief
        """
        reset_clock()
        ctx = setup_route_with_active_points(1)
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        point = ctx["points"][0]
        aux_car = create_carrier(unit_id, carrier_class="AUXILIARY")
        get_success_data(api.mark_vacant(unit_id, point["id"],
                                         make_carrier_headers(ctx["carrier"]["id"])))
        set_clock("2026-11-30T00:00:00Z")
        aux = create_auxiliary(unit_id, route_id, aux_car["id"], "2026-12-01", 120,
                               seasonal_surge_flag=True)
        approve_auxiliary(unit_id, route_id, aux["id"])
        set_clock("2026-12-01T00:00:00Z")
        assert get_auxiliary(unit_id, route_id, aux["id"])["status"] == "ACTIVE"
        # Hop 1: discontinue the 91-day-vacant point, emptying the route.
        get_success_data(api.discontinue_point(unit_id, point["id"], AMS))
        route = get_route(unit_id, route_id)
        assert route["active_delivery_point_count"] == 0
        # Hop 2: suspend; Hop 3: aux curtailed; Hop 4: relief zeroed.
        data = get_success_data(api.suspend_route(unit_id, route_id, PM))
        assert data["status"] == "SUSPENDED"
        assert get_auxiliary(unit_id, route_id, aux["id"])["status"] == "CURTAILED"
        route_after = get_route(unit_id, route_id)
        assert route_after["auxiliary_relief_minutes"] == 0

    def test_suspend_then_reactivate_cycle(self, api):
        """PRD §3.3: "`SUSPENDED` is a transitional lock rather than a terminal
        state: a `Postmaster` may reactivate the route by supplying an
        `assigned_carrier_id` naming an `AVAILABLE` carrier of the unit — the
        prior carrier may have been detailed away — which moves the route back to
        `STANDARD`, replaces its carrier, and restores the unit's
        `active_route_count`."

        Design: Corner/state_machines/route_suspend_then_reactivate_cycle
        """
        reset_clock()
        ctx = setup_unit_with_route()
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        car2 = create_carrier(unit_id)
        suspended = get_success_data(api.suspend_route(unit_id, route_id, PM))
        assert suspended["status"] == "SUSPENDED"
        unit = get_success_data(api.get_unit(unit_id, TEST_USERS["platform_admin_headers"]))
        assert unit["active_route_count"] == 0
        data = get_success_data(api.reactivate_route(
            unit_id, route_id, {"assigned_carrier_id": car2["id"]}, PM))
        assert data["status"] == "STANDARD"
        assert data["assigned_carrier_id"] == car2["id"]
        unit_after = get_success_data(
            api.get_unit(unit_id, TEST_USERS["platform_admin_headers"]))
        assert unit_after["active_route_count"] == 1
        assert data["version"] == ctx["route"]["version"] + 2


class TestImmediateConsistency:

    def test_cascade_changes_visible_in_same_request(self, api):
        """PRD §1 ¶9: "Every state change described here is atomic within the
        request that triggers it".
        PRD §3.3: "Suspending a route moves it `STANDARD → SUSPENDED`, curtails
        every open auxiliary assignment on it (any assignment in `REQUESTED`,
        `APPROVED`, or `ACTIVE` moves to `CURTAILED` and the route's
        `auxiliary_relief_minutes` returns to zero)".

        Design: Corner/consistency_model/cascade_changes_visible_in_same_request
        """
        set_clock("2026-11-30T00:00:00Z")
        ctx = setup_unit_with_route()
        unit_id, route_id = ctx["unit"]["id"], ctx["route"]["id"]
        aux_car = create_carrier(unit_id, carrier_class="AUXILIARY")
        aux = create_auxiliary(unit_id, route_id, aux_car["id"], "2026-12-01", 50,
                               seasonal_surge_flag=True)
        approve_auxiliary(unit_id, route_id, aux["id"])
        set_clock("2026-12-01T00:00:00Z")
        data = get_success_data(api.suspend_route(unit_id, route_id, PM))
        assert data["status"] == "SUSPENDED"
        assert get_auxiliary(unit_id, route_id, aux["id"])["status"] == "CURTAILED"
        route = get_route(unit_id, route_id)
        assert route["auxiliary_relief_minutes"] == 0
