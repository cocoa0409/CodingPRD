"""Difficulty-queue tests: deep multi-step scenarios — dual-variant
calculations, posture bands, HOS/crew gates, miss cascades, OCC-free state
dependencies, resource conservation, and service-credit conservation."""
import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assign_trip_legs,
    create_active_plan,
    create_crew_pool,
    create_customer,
    create_locomotive,
    create_shipment,
    create_train_plan,
    create_yard,
    finalize_and_depart,
    get_customer,
    get_locomotive,
    get_pool,
    get_shipment,
    get_success_data,
    get_yard,
    list_exceptions_for_shipment,
    record_car_event,
    set_clock,
    setup_operational_scenario,
    setup_two_shipments_dwelling,
    validate_error,
    validate_paginated,
    validate_success,
    TEST_USERS,
)

NP = TEST_USERS["network_planner_headers"]
CD = TEST_USERS["crew_dispatcher_headers"]
PP = TEST_USERS["power_planner_headers"]
TS = TEST_USERS["terminal_superintendent_headers"]
SM = TEST_USERS["service_manager_headers"]
ANY = TEST_USERS["any_headers"]


def _two_yard_active_plan(prefix, dep="2026-09-01T08:00:00Z", mask=("TUE",),
                          miles=300, cutoff=60):
    yA = create_yard(yard_code=f"{prefix}-A")
    yB = create_yard(yard_code=f"{prefix}-B")
    plan = create_active_plan(
        yA["id"], yB["id"], train_symbol=f"{prefix}-P",
        scheduled_departure_utc=dep, frequency_mask=list(mask),
        route_distance_miles=miles, cutoff_minutes=cutoff,
    )
    return yA, yB, plan


# ===========================================================================
# dual_variant_calc / plan_velocity_vs_actual_velocity_same_shipment
# ===========================================================================

class TestPlanVsActualVelocity:
    def _run_two_leg_delivery(self):
        """DV1 choreography: A->C->D, delivered 34h after first departure,
        well inside the delivery commitment."""
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="DV1A")
        yC = create_yard(yard_code="DV1C")
        yD = create_yard(yard_code="DV1D")
        p1 = create_active_plan(
            yA["id"], yC["id"], train_symbol="DV1-P1",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
            frequency_mask=["TUE"], route_distance_miles=500,
        )
        p2 = create_active_plan(
            yC["id"], yD["id"], train_symbol="DV1-P2",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"], route_distance_miles=600,
        )
        cu = create_customer(customer_code="DV1-CU", name="Dual Variant Shipper")
        s = create_shipment(
            cu["id"], yA["id"], yD["id"], car_count=4,
            first_mile_pickup_by="2026-09-01T07:30:00Z",
            last_mile_delivery_by="2026-09-05T00:00:00Z",
            committed_route_miles=1100,
        )
        set_clock("2026-09-01T07:00:00Z")
        assign_trip_legs(s, [p1["id"], p2["id"]])
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="DV1-UP8801")
        dep = get_success_data(
            api_call_create_departure(p1["id"], pool["id"], loco["id"], 4, 10)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(dep["id"]))
        record_car_event(s["id"], yA["id"], "TRAIN_DEPARTURE",
                         "2026-09-01T08:00:00Z", 4)
        set_clock("2026-09-02T04:00:00Z")
        record_car_event(s["id"], yC["id"], "YARD_ARRIVAL",
                         "2026-09-02T04:00:00Z", 4)
        set_clock("2026-09-02T06:00:00Z")
        record_car_event(s["id"], yC["id"], "CLASSIFICATION_COMPLETE",
                         "2026-09-02T06:00:00Z", 4)
        set_clock("2026-09-02T08:00:00Z")
        record_car_event(s["id"], yD["id"], "YARD_ARRIVAL",
                         "2026-09-02T08:00:00Z", 4)
        set_clock("2026-09-02T18:00:00Z")
        record_car_event(s["id"], yD["id"], "PLACED_DELIVERED",
                         "2026-09-02T18:00:00Z", 4)
        return s

    def test_actual_velocity_computed_from_observed_events(self, api):
        """PRD §3.8: "**actual car velocity** is the shipment's
        `committed_route_miles` divided by the observed elapsed hours from the
        first `TRAIN_DEPARTURE` event's `occurred_at` to the final completing
        `PLACED_DELIVERED` event's `occurred_at`, stored on the shipment as
        `car_velocity_mph` at 4-decimal precision."

        Design: Difficulty/dual_variant_calc/plan_velocity_vs_actual_velocity_same_shipment
        """
        s = self._run_two_leg_delivery()
        final = get_shipment(s["id"])
        assert final["status"] == "DELIVERED"
        # 1100 miles / 34.0 observed hours = 32.3529 (4dp, round-half-up).
        assert final["car_velocity_mph"] == pytest.approx(32.3529, abs=1e-4)

    def test_delivered_on_time_stays_on_plan(self, api):
        """PRD §3.9: "Otherwise the shipment is `ON_PLAN`."
        PRD §3.8: "A delivery whose completing event's `occurred_at` is later
        than the shipment's `last_mile_delivery_by` commitment is a broken
        promise: the shipment's `compliance_status` is set to `OFF_PLAN`".

        Design: Difficulty/dual_variant_calc/plan_velocity_vs_actual_velocity_same_shipment
        """
        s = self._run_two_leg_delivery()
        final = get_shipment(s["id"])
        assert final["compliance_status"] == "ON_PLAN", (
            "delivered before last_mile_delivery_by with zero missed connections"
        )
        assert final["total_missed_connections"] == 0


# ===========================================================================
# dual_variant_calc / dwell_aggregation_vs_posture_threshold_two_car_mix
# ===========================================================================

class TestDwellAggregationVsPosture:
    def test_aggregate_overage_sums_open_sessions(self, api):
        """PRD §3.6: "The yard's overage is the sum of these session
        overages, itself floored at zero, expressed at 4-decimal precision."
        PRD §3.2: "overage strictly above B and up to and including twice B
        moves it to `CONGESTED`".

        Design: Difficulty/dual_variant_calc/dwell_aggregation_vs_posture_threshold_two_car_mix
        """
        fx = setup_two_shipments_dwelling("DV2")
        # At 2026-09-02T16:00:00Z: SA age 20h -> 10.0; SB age 19h -> 9.0.
        set_clock("2026-09-02T16:00:00Z")
        yard = get_yard(fx["yC"]["id"])
        assert yard["current_dwell_overage_hours"] == pytest.approx(19.0, abs=1e-4)
        assert yard["posture"] == "CONGESTED"

    def test_closing_one_session_reduces_aggregate(self, api):
        """PRD §3.6: "The yard's `current_dwell_overage_hours` aggregates
        every open dwell session at the yard — shipments with a
        `YARD_ARRIVAL` recorded and no matching outbound or delivery event
        yet."
        PRD §3.6: "the session closes when the first outbound event — a
        `TRAIN_DEPARTURE` or a `CLASSIFICATION_COMPLETE` — is recorded for
        that shipment at that yard, whichever comes first."

        Design: Difficulty/dual_variant_calc/dwell_aggregation_vs_posture_threshold_two_car_mix
        """
        fx = setup_two_shipments_dwelling("DV2B")
        set_clock("2026-09-02T17:00:00Z")
        record_car_event(fx["sA"]["id"], fx["yC"]["id"],
                         "CLASSIFICATION_COMPLETE", "2026-09-02T17:00:00Z", 3)
        # At 2026-09-02T18:00:00Z only SB's session is open: age 21h -> 11.0.
        set_clock("2026-09-02T18:00:00Z")
        yard = get_yard(fx["yC"]["id"])
        assert yard["current_dwell_overage_hours"] == pytest.approx(11.0, abs=1e-4)
        assert yard["posture"] == "CONGESTED"


# ===========================================================================
# combinatorial_formula / posture_band_three_input_nonlinear
# ===========================================================================

class TestPostureBandNonlinear:
    def test_aggregate_above_twice_benchmark_embargoes(self, api):
        """PRD §3.2: "overage strictly above twice B moves it to `EMBARGOED`".

        Design: Difficulty/combinatorial_formula/posture_band_three_input_nonlinear
        """
        fx = setup_two_shipments_dwelling("CB")
        # At 2026-09-02T18:00:00Z: SA age 22h -> 12.0; SB age 21h -> 11.0.
        set_clock("2026-09-02T18:00:00Z")
        yard = get_yard(fx["yC"]["id"])
        assert yard["current_dwell_overage_hours"] == pytest.approx(23.0, abs=1e-4)
        assert yard["posture"] == "EMBARGOED"

    def test_under_benchmark_session_contributes_zero(self, api):
        """PRD §3.6: "For each open session, the session's overage is the
        elapsed hours from its arrival to the current logical-clock instant
        minus the yard's `dwell_benchmark_hours`, floored at zero so a session
        inside its benchmark contributes nothing."
        PRD §3.2: "aggregate overage up to and including B keeps the yard
        `OPEN`".

        Design: Difficulty/combinatorial_formula/posture_band_three_input_nonlinear
        """
        fx = setup_two_shipments_dwelling("CBZ")
        # At 2026-09-02T04:00:00Z: SA age 8h -> 0 (floored); SB age 7h -> 0.
        set_clock("2026-09-02T04:00:00Z")
        yard = get_yard(fx["yC"]["id"])
        assert yard["current_dwell_overage_hours"] == 0
        assert yard["posture"] == "OPEN"


# ===========================================================================
# combinatorial_formula / hos_tiered_gate_with_pool_state_branch
# ===========================================================================

def api_call_create_departure(plan_id, pool_id, loco_id, cars, hours):
    return api_client.create_train_departure(
        {
            "train_plan_id": plan_id, "service_date": "2026-09-01",
            "crew_pool_id": pool_id, "locomotive_id": loco_id,
            "car_count_planned": cars, "crew_hours_estimated": hours,
        },
        TS,
    )


def api_finalize(dep_id):
    return api_client.finalize_train_departure(dep_id, TS)


class TestHosTieredGate:
    def _exhausted_pool_with_pending_departure(self, prefix, d2_hours):
        yA, yB, plan = _two_yard_active_plan(prefix)
        pool = create_crew_pool(yA["id"], crews_available=1)
        l1 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP1")
        l2 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP2")
        d1 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l1["id"], 10, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(d1["id"]))
        d2 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 10, d2_hours)
        )
        return yA, yB, plan, pool, d1, d2

    def test_exhausted_pool_blocks_finalize_even_with_hos_violation(self, api):
        """PRD §3.5: "The crew gate then applies in full: the named pool must
        be in `OPEN` or `REOPENED` with `crews_booked` strictly below
        `crews_available` — an `EXHAUSTED` or `CLOSED` pool, or a fully booked
        one, is rejected with `ERR_NO_CREW_AVAILABLE` (HTTP 422) — and
        `crew_hours_estimated` must not exceed the 12.0-hour hours-of-service
        maximum".

        Design: Difficulty/combinatorial_formula/hos_tiered_gate_with_pool_state_branch
        """
        _yA, _yB, _plan, pool, _d1, d2 = (
            self._exhausted_pool_with_pending_departure("HOS", 12.5)
        )
        resp = api_finalize(d2["id"])
        validate_error(resp, ApiErrorId.ERR_NO_CREW_AVAILABLE.value)
        dep2 = get_success_data(
            api_client.get_train_departure(d2["id"], ANY)
        )
        assert dep2["status"] == "SCHEDULED"
        pool_now = get_pool(pool["id"])
        assert pool_now["crews_booked"] == 1
        assert pool_now["status"] == "EXHAUSTED"

    def test_hos_violation_against_healthy_pool_returns_hos_error(self, api):
        """PRD §3.5: "an estimate of exactly 12.0 hours is allowed, anything
        above it is rejected with `ERR_HOS_EXCEEDED` (HTTP 422)."

        Design: Difficulty/combinatorial_formula/hos_tiered_gate_with_pool_state_branch
        """
        yA, yB, plan = _two_yard_active_plan("HOSOK")
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="HOSOK-UP1")
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 10, 12.5)
        )
        set_clock("2026-09-01T08:00:00Z")
        resp = api_finalize(dep["id"])
        validate_error(resp, ApiErrorId.ERR_HOS_EXCEEDED.value)
        pool_now = get_pool(pool["id"])
        assert pool_now["crews_booked"] == 0


# ===========================================================================
# non_linear_state_machine / crew_pool_exhausted_reopened_cycle
# ===========================================================================

class TestCrewPoolCycle:
    def _setup_cycle(self, prefix):
        yA, yB, plan = _two_yard_active_plan(prefix)
        pool = create_crew_pool(yA["id"], crews_available=1)
        l1 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP1")
        l2 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP2")
        dA = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l1["id"], 10, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(dA["id"]))
        return yA, yB, plan, pool, l2

    def test_exhausted_pool_reopens_and_exhausts_again(self, api):
        """PRD §3.3: "When a booking leaves `crews_booked` equal to
        `crews_available`, the system flips the pool to `EXHAUSTED`
        automatically, whether it was `OPEN` or `REOPENED`. A dispatcher
        restores an exhausted pool by replenishing it with `additional_crews`
        ... adds the additional crews to `crews_available`, moves the pool to
        `REOPENED`".

        Design: Difficulty/non_linear_state_machine/crew_pool_exhausted_reopened_cycle
        """
        _yA, _yB, plan, pool, l2 = self._setup_cycle("CYC")
        assert get_pool(pool["id"])["status"] == "EXHAUSTED"

        replenished = validate_success(
            api_client.replenish_crew_pool(
                pool["id"], {"additional_crews": 1}, CD
            )
        )
        assert replenished["status"] == "REOPENED"
        assert replenished["crews_available"] == 2

        dB = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 10, 8)
        )
        set_clock("2026-09-01T09:00:00Z")
        departed = validate_success(api_finalize(dB["id"]))
        assert departed["status"] == "DEPARTED"
        pool_now = get_pool(pool["id"])
        assert pool_now["status"] == "EXHAUSTED", "second exhaustion closes the cycle"
        assert pool_now["crews_available"] == 2
        assert pool_now["crews_booked"] == 2

    def test_departure_stamps_actual_time_and_variance(self, api):
        """PRD §3.5: "A successful finalize stamps `actual_departure_utc`
        from the logical clock, computes `departure_variance_minutes` as
        actual minus scheduled in whole minutes (positive values mean late),
        moves the departure to `DEPARTED`".

        Design: Difficulty/non_linear_state_machine/crew_pool_exhausted_reopened_cycle
        """
        _yA, _yB, plan, pool, l2 = self._setup_cycle("CYC2")
        validate_success(
            api_client.replenish_crew_pool(
                pool["id"], {"additional_crews": 1}, CD
            )
        )
        dB = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 10, 8)
        )
        set_clock("2026-09-01T09:00:00Z")
        departed = validate_success(api_finalize(dB["id"]))
        assert departed["actual_departure_utc"].startswith("2026-09-01T09:00:00")
        assert departed["departure_variance_minutes"] == 60


# ===========================================================================
# non_linear_state_machine / yard_posture_oscillation_across_three_bands
# ===========================================================================

class TestYardPostureOscillation:
    def test_posture_walks_open_congested_embargoed(self, api):
        """PRD §3.2: "aggregate overage up to and including B keeps the yard
        `OPEN`; overage strictly above B and up to and including twice B moves
        it to `CONGESTED`; overage strictly above twice B moves it to
        `EMBARGOED`."

        Design: Difficulty/non_linear_state_machine/yard_posture_oscillation_across_three_bands
        """
        fx = setup_two_shipments_dwelling("OSC")
        yC = fx["yC"]["id"]
        assert get_yard(yC)["posture"] == "OPEN"
        set_clock("2026-09-02T16:00:00Z")
        assert get_yard(yC)["posture"] == "CONGESTED"
        set_clock("2026-09-02T18:00:00Z")
        yard = get_yard(yC)
        assert yard["posture"] == "EMBARGOED"
        assert yard["current_dwell_overage_hours"] == pytest.approx(23.0, abs=1e-4)

    def test_posture_recovers_as_sessions_close(self, api):
        """PRD §3.2: "Recovery is symmetric: an `EMBARGOED` yard returns to
        `CONGESTED` once overage falls back to strictly above B but at most
        twice B, and either congested or embargoed yards return to `OPEN`
        once overage is at most B."

        Design: Difficulty/non_linear_state_machine/yard_posture_oscillation_across_three_bands
        """
        fx = setup_two_shipments_dwelling("OSC2")
        yC = fx["yC"]["id"]
        set_clock("2026-09-02T18:00:00Z")
        record_car_event(fx["sA"]["id"], yC, "CLASSIFICATION_COMPLETE",
                         "2026-09-02T18:00:00Z", 3)
        yard = get_yard(yC)
        assert yard["posture"] == "CONGESTED"
        assert yard["current_dwell_overage_hours"] == pytest.approx(11.0, abs=1e-4)
        set_clock("2026-09-02T20:00:00Z")
        record_car_event(fx["sB"]["id"], yC, "CLASSIFICATION_COMPLETE",
                         "2026-09-02T20:00:00Z", 2)
        yard = get_yard(yC)
        assert yard["posture"] == "OPEN"
        assert yard["current_dwell_overage_hours"] == 0


# ===========================================================================
# transitive_cascade / late_arrival_cascades_miss_across_two_connections
# ===========================================================================

class TestMissCascadeAcrossConnections:
    def _run_cascade(self):
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="TC-A")
        yC = create_yard(yard_code="TC-C")
        yD = create_yard(yard_code="TC-D")
        yE = create_yard(yard_code="TC-E")
        p1 = create_active_plan(
            yA["id"], yC["id"], train_symbol="TC-P1",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
            frequency_mask=["TUE"], route_distance_miles=500, cutoff_minutes=60,
        )
        p2 = create_active_plan(
            yC["id"], yD["id"], train_symbol="TC-P2",
            scheduled_departure_utc="2026-09-02T08:30:00Z",
            frequency_mask=["WED"], route_distance_miles=500, cutoff_minutes=600,
        )
        p3 = create_active_plan(
            yD["id"], yE["id"], train_symbol="TC-P3",
            scheduled_departure_utc="2026-09-03T10:00:00Z",
            frequency_mask=["THU"], route_distance_miles=400, cutoff_minutes=120,
        )
        cu = create_customer(customer_code="TC-CU", name="Cascade Shipper")
        s = create_shipment(
            cu["id"], yA["id"], yE["id"], car_count=3,
            first_mile_pickup_by="2026-09-01T07:30:00Z",
            last_mile_delivery_by="2026-09-06T00:00:00Z",
            committed_route_miles=1400,
        )
        set_clock("2026-09-01T07:00:00Z")
        assign_trip_legs(s, [p1["id"], p2["id"], p3["id"]])
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="TC-UP9301")
        dep = get_success_data(
            api_call_create_departure(p1["id"], pool["id"], loco["id"], 3, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(dep["id"]))
        record_car_event(s["id"], yA["id"], "TRAIN_DEPARTURE",
                         "2026-09-01T08:00:00Z", 3)
        # Arrive at C with 540 min slack to p2's 08:30 departure (< cutoff 600).
        set_clock("2026-09-01T23:20:00Z")
        record_car_event(s["id"], yC["id"], "YARD_ARRIVAL",
                         "2026-09-01T23:20:00Z", 3)
        return s

    def test_late_arrival_misses_downstream_legs(self, api):
        """PRD §3.7: "If the slack is strictly less than the next leg's train
        plan's `cutoff_minutes`, the next leg misses" and "every later leg of
        the same shipment still in `PLANNED` moves to `MISSED` as well, each
        with `connection_status` `MISSED` by the same induction".

        Design: Difficulty/transitive_cascade/late_arrival_cascades_miss_across_two_connections
        """
        s = self._run_cascade()
        legs, meta = validate_paginated(
            api_client.list_shipment_trip_legs(s["id"], ANY)
        )
        legs.sort(key=lambda l: l["leg_sequence"])
        assert legs[0]["status"] == "COMPLETED"
        assert legs[1]["status"] == "MISSED"
        assert legs[1]["connection_status"] == "MISSED"
        assert legs[2]["status"] == "MISSED", "cascade reaches legs with no arrival"
        shipment = get_shipment(s["id"])
        assert shipment["total_missed_connections"] == 2
        assert shipment["trip_plan_status"] == "MISSED_CONNECTION"

    def test_cascade_raises_exception_and_off_plan_compliance(self, api):
        """PRD §3.7: "The system raises a `ServiceException` of type
        `MISSED_CONNECTION` for the shipment with `detected_at` stamped from
        the logical clock."
        PRD §3.9: "A shipment is `OFF_PLAN` when any of three conditions
        holds: ... or its `total_missed_connections` has reached 2 or more."

        Design: Difficulty/transitive_cascade/late_arrival_cascades_miss_across_two_connections
        """
        s = self._run_cascade()
        exceptions = list_exceptions_for_shipment(s["id"])
        mc = [e for e in exceptions if e["exception_type"] == "MISSED_CONNECTION"]
        assert len(mc) == 2, "one MISSED_CONNECTION exception per missed leg"
        assert all(e["status"] == "OPEN" for e in mc)
        shipment = get_shipment(s["id"])
        assert shipment["compliance_status"] == "OFF_PLAN"


# ===========================================================================
# transitive_cascade / departure_cancel_releases_power_and_misses_slot_legs
# ===========================================================================

class TestDepartureCancelCascade:
    def test_cancel_releases_locomotive_at_origin(self, api):
        """PRD §3.5: "Cancellation of a `SCHEDULED` departure ... releases
        the locomotive back to `AVAILABLE` at the origin yard, and leaves the
        crew pool untouched — no booking was ever consumed."

        Design: Difficulty/transitive_cascade/departure_cancel_releases_power_and_misses_slot_legs
        """
        sc = setup_operational_scenario(
            "DC", shipment_car_count=2, delivery_by="2026-09-04T00:00:00Z",
        )
        cancelled = validate_success(
            api_client.cancel_train_departure(
                sc["departure"]["id"], TS
            )
        )
        assert cancelled["status"] == "CANCELLED"
        loco = get_locomotive(sc["loco"]["id"])
        assert loco["status"] == "AVAILABLE"
        assert loco["current_yard_id"] == sc["yA"]["id"], (
            "released at origin, not repositioned"
        )
        pool = get_pool(sc["pool"]["id"])
        assert pool["crews_booked"] == 0, "cancel consumes no crew"

    def test_cancel_misses_legs_and_marks_shipment_at_risk(self, api):
        """PRD §3.5: "Every `PLANNED` trip leg whose `planned_departure_utc`
        matches this departure's slot instead misses: each such leg moves to
        `MISSED` and the full missed-connection cascade of §3.7 fires per leg."
        PRD §3.9: "a shipment is `AT_RISK` when it has exactly one missed
        connection or any open `DEPARTURE_DELAY` exception against it".

        Design: Difficulty/transitive_cascade/departure_cancel_releases_power_and_misses_slot_legs
        """
        sc = setup_operational_scenario(
            "DC2", shipment_car_count=2, delivery_by="2026-09-04T00:00:00Z",
        )
        validate_success(
            api_client.cancel_train_departure(
                sc["departure"]["id"], TS
            )
        )
        shipment = get_shipment(sc["shipment"]["id"])
        assert shipment["total_missed_connections"] == 1
        assert shipment["trip_plan_status"] == "MISSED_CONNECTION"
        assert shipment["compliance_status"] == "AT_RISK"
        exceptions = list_exceptions_for_shipment(sc["shipment"]["id"])
        mc = [e for e in exceptions if e["exception_type"] == "MISSED_CONNECTION"]
        assert len(mc) == 1
        legs, _meta = validate_paginated(
            api_client.list_shipment_trip_legs(
                sc["shipment"]["id"], ANY
            )
        )
        assert legs[0]["status"] == "MISSED"


# ===========================================================================
# priority_pair_validation_conflict / state_vs_business_safety_on_finalize
# ===========================================================================

class TestStateBeforeSafetyOnFinalize:
    def test_cancelled_departure_finalize_reports_state_error(self, api):
        """PRD §2.9: "fifth, source-state legality of the transition; ...
        eighth, hours-of-service and crew availability at finalize" and "the
        client observes only the earliest failing check".
        PRD §3.5: "Finalizing a departure not in `SCHEDULED` is rejected with
        `ERR_DEPARTURE_NOT_FINALIZABLE` (HTTP 409)".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        yA, yB, plan = _two_yard_active_plan("PP")
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="PP-UP9501")
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 10, 12.5)
        )
        validate_success(
            api_client.cancel_train_departure(dep["id"], TS)
        )
        set_clock("2026-09-01T08:00:00Z")
        resp = api_finalize(dep["id"])
        validate_error(resp, ApiErrorId.ERR_DEPARTURE_NOT_FINALIZABLE.value)

    def test_state_error_leaves_departure_unchanged(self, api):
        """PRD §3.5: "Cancellation of a `SCHEDULED` departure (a
        non-`SCHEDULED` one is again `ERR_DEPARTURE_NOT_FINALIZABLE`) moves it
        to `CANCELLED`".

        Design: Difficulty/priority_pair_validation_conflict/state_vs_business_safety_on_finalize
        """
        yA, yB, plan = _two_yard_active_plan("PP2")
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="PP2-UP9501")
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 10, 12.5)
        )
        validate_success(
            api_client.cancel_train_departure(dep["id"], TS)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_error(api_finalize(dep["id"]),
                       ApiErrorId.ERR_DEPARTURE_NOT_FINALIZABLE.value)
        reread = get_success_data(
            api_client.get_train_departure(dep["id"], ANY)
        )
        assert reread["status"] == "CANCELLED", (
            "rejected finalize leaves the departure unchanged"
        )


# ===========================================================================
# boundary_precision_check / posture_thresholds_strictly_greater_boundaries
# ===========================================================================

class TestPostureBoundaryPrecision:
    def _setup_single_open_session(self, prefix):
        """One shipment dwelling at yard C since 2026-09-01T06:00:00Z."""
        set_clock("2026-09-01T03:00:00Z")
        yA = create_yard(yard_code=f"{prefix}-A")
        yC = create_yard(yard_code=f"{prefix}-C")
        plan = create_active_plan(
            yA["id"], yC["id"], train_symbol=f"{prefix}-P",
            scheduled_departure_utc="2026-09-01T05:00:00Z",
            frequency_mask=["TUE"], route_distance_miles=100, cutoff_minutes=30,
        )
        cu = create_customer(customer_code=f"{prefix}-CU")
        s = create_shipment(
            cu["id"], yA["id"], yC["id"], car_count=3,
            first_mile_pickup_by="2026-09-01T04:30:00Z",
            committed_route_miles=100,
        )
        assign_trip_legs(s, [plan["id"]])
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number=f"{prefix}-UP9601")
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 3, 4)
        )
        set_clock("2026-09-01T05:00:00Z")
        validate_success(api_finalize(dep["id"]))
        record_car_event(s["id"], yA["id"], "TRAIN_DEPARTURE",
                         "2026-09-01T05:00:00Z", 3)
        set_clock("2026-09-01T06:00:00Z")
        record_car_event(s["id"], yC["id"], "YARD_ARRIVAL",
                         "2026-09-01T06:00:00Z", 3)
        return yC["id"]

    def test_overage_equal_to_benchmark_stays_open(self, api):
        """PRD §3.2: "The exact boundary semantics matter: overage equal to
        the benchmark exactly stays `OPEN`, and overage equal to twice the
        benchmark exactly stays `CONGESTED`."

        Design: Difficulty/boundary_precision_check/posture_thresholds_strictly_greater_boundaries
        """
        yC_id = self._setup_single_open_session("BN")
        # At 2026-09-02T02:00:00Z the session age is exactly 20h: overage == 10.0 == B.
        set_clock("2026-09-02T02:00:00Z")
        yard = get_yard(yC_id)
        assert yard["current_dwell_overage_hours"] == pytest.approx(10.0, abs=1e-4)
        assert yard["posture"] == "OPEN", "equality does NOT congest"

    def test_overage_equal_to_twice_benchmark_stays_congested(self, api):
        """PRD §3.2: "The exact boundary semantics matter: overage equal to
        the benchmark exactly stays `OPEN`, and overage equal to twice the
        benchmark exactly stays `CONGESTED`."

        Design: Difficulty/boundary_precision_check/posture_thresholds_strictly_greater_boundaries
        """
        yC_id = self._setup_single_open_session("BN2")
        # At 2026-09-02T12:00:00Z the session age is exactly 30h: overage == 20.0 == 2B.
        set_clock("2026-09-02T12:00:00Z")
        yard = get_yard(yC_id)
        assert yard["current_dwell_overage_hours"] == pytest.approx(20.0, abs=1e-4)
        assert yard["posture"] == "CONGESTED", "equality does NOT embargo"


# ===========================================================================
# boundary_precision_check / connection_cutoff_exact_equality_makes
# ===========================================================================

class TestConnectionCutoffBoundary:
    def _run_exact_slack(self):
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="CW-A")
        yB = create_yard(yard_code="CW-B")
        yC = create_yard(yard_code="CW-C")
        p1 = create_active_plan(
            yA["id"], yB["id"], train_symbol="CW-P1",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
            frequency_mask=["TUE"], cutoff_minutes=30,
        )
        p2 = create_active_plan(
            yB["id"], yC["id"], train_symbol="CW-P2",
            scheduled_departure_utc="2026-09-01T21:00:00Z",
            frequency_mask=["TUE"], cutoff_minutes=60,
        )
        cu = create_customer(customer_code="CW-CU", name="Cutoff Shipper")
        s = create_shipment(
            cu["id"], yA["id"], yC["id"], car_count=1,
            first_mile_pickup_by="2026-09-01T07:30:00Z",
            last_mile_delivery_by="2026-09-04T00:00:00Z",
            committed_route_miles=600,
        )
        set_clock("2026-09-01T07:00:00Z")
        assign_trip_legs(s, [p1["id"], p2["id"]])
        pool = create_crew_pool(yA["id"], crews_available=2)
        loco = create_locomotive(yA["id"], unit_number="CW-UP9701")
        dep = get_success_data(
            api_call_create_departure(p1["id"], pool["id"], loco["id"], 1, 6)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(dep["id"]))
        record_car_event(s["id"], yA["id"], "TRAIN_DEPARTURE",
                         "2026-09-01T08:00:00Z", 1)
        # Arrival at B exactly 60 minutes before p2's 21:00 departure.
        set_clock("2026-09-01T20:00:00Z")
        record_car_event(s["id"], yB["id"], "YARD_ARRIVAL",
                         "2026-09-01T20:00:00Z", 1)
        return s

    def test_slack_equal_to_cutoff_makes_connection(self, api):
        """PRD §3.7: "slack exactly equal to the cutoff still makes the
        connection, and the next leg's `connection_status` is set to `MADE`."

        Design: Difficulty/boundary_precision_check/connection_cutoff_exact_equality_makes
        """
        s = self._run_exact_slack()
        legs, _meta = validate_paginated(
            api_client.list_shipment_trip_legs(s["id"], ANY)
        )
        legs.sort(key=lambda l: l["leg_sequence"])
        assert legs[1]["connection_status"] == "MADE", "60 == 60 makes the train"
        assert legs[1]["status"] == "PLANNED"

    def test_exact_cutoff_keeps_miss_tally_at_zero(self, api):
        """PRD §3.7: "If the slack is strictly less than the next leg's train
        plan's `cutoff_minutes`, the next leg misses; slack exactly equal to
        the cutoff still makes the connection".

        Design: Difficulty/boundary_precision_check/connection_cutoff_exact_equality_makes
        """
        s = self._run_exact_slack()
        shipment = get_shipment(s["id"])
        assert shipment["total_missed_connections"] == 0
        legs, _meta = validate_paginated(
            api_client.list_shipment_trip_legs(s["id"], ANY)
        )
        legs.sort(key=lambda l: l["leg_sequence"])
        assert legs[0]["status"] == "COMPLETED"


# ===========================================================================
# cross_entity_state_dependency / finalize_gated_by_crew_pool_state
# ===========================================================================

class TestFinalizeGatedByPoolState:
    def _setup_blocked_departure(self, prefix):
        yA, yB, plan = _two_yard_active_plan(prefix)
        pool = create_crew_pool(yA["id"], crews_available=1)
        l1 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP1")
        l2 = create_locomotive(yA["id"], unit_number=f"{prefix}-UP2")
        d1 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l1["id"], 5, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(d1["id"]))
        d2 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 5, 8)
        )
        return pool, d2

    def test_exhausted_pool_blocks_finalize(self, api):
        """PRD §3.5: "an `EXHAUSTED` or `CLOSED` pool, or a fully booked one,
        is rejected with `ERR_NO_CREW_AVAILABLE` (HTTP 422)".

        Design: Difficulty/cross_entity_state_dependency/finalize_gated_by_crew_pool_state
        """
        pool, d2 = self._setup_blocked_departure("CG")
        resp = api_finalize(d2["id"])
        validate_error(resp, ApiErrorId.ERR_NO_CREW_AVAILABLE.value)
        dep2 = get_success_data(
            api_client.get_train_departure(d2["id"], ANY)
        )
        assert dep2["status"] == "SCHEDULED"

    def test_replenish_unblocks_same_departure(self, api):
        """PRD §3.3: "A dispatcher restores an exhausted pool by replenishing
        it with `additional_crews` ... adds the additional crews to
        `crews_available`, moves the pool to `REOPENED`".

        Design: Difficulty/cross_entity_state_dependency/finalize_gated_by_crew_pool_state
        """
        pool, d2 = self._setup_blocked_departure("CG2")
        validate_error(api_finalize(d2["id"]),
                       ApiErrorId.ERR_NO_CREW_AVAILABLE.value)
        validate_success(
            api_client.replenish_crew_pool(
                pool["id"], {"additional_crews": 1}, CD
            )
        )
        departed = validate_success(api_finalize(d2["id"]))
        assert departed["status"] == "DEPARTED"
        pool_now = get_pool(pool["id"])
        assert pool_now["crews_booked"] == 2
        assert pool_now["crews_available"] == 2
        assert pool_now["status"] == "EXHAUSTED"


# ===========================================================================
# cross_entity_state_dependency / plan_retirement_gated_by_trip_leg_state
# ===========================================================================

class TestPlanRetirementGatedByLegs:
    def _setup_plan_with_planned_leg(self, prefix):
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code=f"{prefix}-A")
        yB = create_yard(yard_code=f"{prefix}-B")
        plan = create_active_plan(
            yA["id"], yB["id"], train_symbol=f"{prefix}-P",
            scheduled_departure_utc="2026-09-02T08:00:00Z",
            frequency_mask=["WED"],
        )
        cu = create_customer(customer_code=f"{prefix}-CU")
        s = create_shipment(
            cu["id"], yA["id"], yB["id"], car_count=2,
            first_mile_pickup_by="2026-09-02T06:00:00Z",
        )
        assign_trip_legs(s, [plan["id"]])
        return plan, s

    def test_retire_blocked_by_planned_leg(self, api):
        """PRD §3.1: "Retirement is refused ... with `ERR_PLAN_IN_USE`
        (HTTP 409) if any trip leg in `PLANNED` or `EN_ROUTE` status still
        rides it".

        Design: Difficulty/cross_entity_state_dependency/plan_retirement_gated_by_trip_leg_state
        """
        plan, _s = self._setup_plan_with_planned_leg("RG")
        resp = api_client.retire_train_plan(
            plan["id"], {"expected_train_plan_version": plan["version"]}, NP
        )
        validate_error(resp, ApiErrorId.ERR_PLAN_IN_USE.value)
        reread = get_success_data(
            api_client.get_train_plan(plan["id"], ANY)
        )
        assert reread["status"] == "ACTIVE"

    def test_retire_succeeds_after_shipment_cancel_replaces_legs(self, api):
        """PRD §3.9: "Cancellation moves the shipment to `CANCELLED`,
        increments its `version`, and supersedes every one of its trip legs
        to `REPLACED`".
        PRD §3.1: "Retirement moves an `ACTIVE` plan to its terminal state
        `RETIRED`." and "it too carries the OCC version field and increments
        `version` by one on success."

        Design: Difficulty/cross_entity_state_dependency/plan_retirement_gated_by_trip_leg_state
        """
        plan, s = self._setup_plan_with_planned_leg("RG2")
        validate_error(
            api_client.retire_train_plan(
                plan["id"], {"expected_train_plan_version": plan["version"]}, NP
            ),
            ApiErrorId.ERR_PLAN_IN_USE.value,
        )
        validate_success(
            api_client.cancel_shipment(s["id"], SM)
        )
        retired = validate_success(
            api_client.retire_train_plan(
                plan["id"], {"expected_train_plan_version": plan["version"]}, NP
            )
        )
        assert retired["status"] == "RETIRED"
        assert retired["version"] == plan["version"] + 1


# ===========================================================================
# resource_temporal_overlap / crew_pool_epoch_capacity_gate
# ===========================================================================

class TestCrewPoolEpochCapacity:
    def test_second_finalize_rejected_at_epoch_capacity(self, api):
        """PRD §3.3: "When a booking leaves `crews_booked` equal to
        `crews_available`, the system flips the pool to `EXHAUSTED`
        automatically" and PRD §3.5: "an `EXHAUSTED` or `CLOSED` pool, or a
        fully booked one, is rejected with `ERR_NO_CREW_AVAILABLE`
        (HTTP 422)".

        Design: Difficulty/resource_temporal_overlap/crew_pool_epoch_capacity_gate
        """
        yA, yB, plan = _two_yard_active_plan("OL")
        pool = create_crew_pool(yA["id"], crews_available=1)
        l1 = create_locomotive(yA["id"], unit_number="OL-UP9901")
        l2 = create_locomotive(yA["id"], unit_number="OL-UP9902")
        d1 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l1["id"], 5, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(d1["id"]))
        d2 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 5, 8)
        )
        resp = api_finalize(d2["id"])
        validate_error(resp, ApiErrorId.ERR_NO_CREW_AVAILABLE.value)
        pool_now = get_pool(pool["id"])
        assert pool_now["crews_booked"] == 1
        assert pool_now["crews_available"] == 1
        assert pool_now["status"] == "EXHAUSTED"

    def test_rejected_finalize_records_no_partial_booking(self, api):
        """PRD §3.5: "A successful finalize ... books one crew from the pool
        (`crews_booked` increases by one, which may flip the pool `OPEN` or
        `REOPENED` to `EXHAUSTED`)."

        Design: Difficulty/resource_temporal_overlap/crew_pool_epoch_capacity_gate
        """
        yA, yB, plan = _two_yard_active_plan("OL2")
        pool = create_crew_pool(yA["id"], crews_available=1)
        l1 = create_locomotive(yA["id"], unit_number="OL2-UP9901")
        l2 = create_locomotive(yA["id"], unit_number="OL2-UP9902")
        d1 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l1["id"], 5, 8)
        )
        set_clock("2026-09-01T08:00:00Z")
        validate_success(api_finalize(d1["id"]))
        d2 = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], l2["id"], 5, 8)
        )
        validate_error(api_finalize(d2["id"]),
                       ApiErrorId.ERR_NO_CREW_AVAILABLE.value)
        dep2 = get_success_data(
            api_client.get_train_departure(d2["id"], ANY)
        )
        assert dep2["status"] == "SCHEDULED", "no partial booking recorded"


# ===========================================================================
# resource_temporal_overlap / locomotive_single_assignment_overlap_and_reposition
# ===========================================================================

class TestLocomotiveOverlapAndReposition:
    def _setup_two_plans(self):
        set_clock("2026-09-01T06:00:00Z")
        yA = create_yard(yard_code="LP-A")
        yB = create_yard(yard_code="LP-B")
        p1 = create_active_plan(
            yA["id"], yB["id"], train_symbol="LP-P",
            scheduled_departure_utc="2026-09-01T08:00:00Z",
        )
        p2 = create_active_plan(
            yA["id"], yB["id"], train_symbol="LP-P2",
            scheduled_departure_utc="2026-09-01T09:00:00Z",
        )
        pool = create_crew_pool(yA["id"], crews_available=3)
        l1 = create_locomotive(yA["id"], unit_number="LP-UP0001")
        l2 = create_locomotive(yA["id"], unit_number="LP-UP0002")
        d1 = get_success_data(
            api_call_create_departure(p1["id"], pool["id"], l1["id"], 5, 6)
        )
        d2 = get_success_data(
            api_call_create_departure(p2["id"], pool["id"], l2["id"], 5, 6)
        )
        set_clock("2026-09-01T09:00:00Z")
        validate_success(api_finalize(d2["id"]))
        return yA, yB, p1, pool, l1, l2

    def test_assigned_unit_rejected_for_second_schedule(self, api):
        """PRD §3.5: "the locomotive must be `AVAILABLE` (otherwise
        `ERR_UNIT_NOT_AVAILABLE`)".

        Design: Difficulty/resource_temporal_overlap/locomotive_single_assignment_overlap_and_reposition
        """
        _yA, _yB, p1, pool, l1, _l2 = self._setup_two_plans()
        resp = api_call_create_departure(p1["id"], pool["id"], l1["id"], 5, 6)
        validate_error(resp, ApiErrorId.ERR_UNIT_NOT_AVAILABLE.value)

    def test_repositioned_unit_fails_origin_positioning(self, api):
        """PRD §3.5: "finalization of that departure repositions the unit by
        setting its `current_yard_id` to the train plan's destination yard"
        and "positioned at the plan's origin yard, meaning the unit's
        `current_yard_id` equals the plan's `origin_yard_id` (otherwise
        `ERR_UNIT_WRONG_YARD`, HTTP 409)".

        Design: Difficulty/resource_temporal_overlap/locomotive_single_assignment_overlap_and_reposition
        """
        yA, yB, p1, pool, _l1, l2 = self._setup_two_plans()
        loco_now = get_locomotive(l2["id"])
        assert loco_now["status"] == "AVAILABLE"
        assert loco_now["current_yard_id"] == yB["id"]
        resp = api_call_create_departure(p1["id"], pool["id"], l2["id"], 5, 6)
        validate_error(resp, ApiErrorId.ERR_UNIT_WRONG_YARD.value)


# ===========================================================================
# compensating_invariant / locomotive_book_release_rebook_lock_conservation
# ===========================================================================

class TestLocomotiveLockConservation:
    def _available_count_at(self, api, yard_id):
        data, meta = validate_paginated(
            api_client.list_locomotives(
                ANY, params={"current_yard_id": yard_id, "status": "AVAILABLE"}
            )
        )
        return meta["total_count"]

    def test_cancel_releases_the_lock(self, api):
        """PRD §3.5: "Cancellation of a `SCHEDULED` departure ... releases
        the locomotive back to `AVAILABLE` at the origin yard".

        Design: Difficulty/compensating_invariant/locomotive_book_release_rebook_lock_conservation
        """
        yA, yB, plan = _two_yard_active_plan("CI")
        pool = create_crew_pool(yA["id"], crews_available=3)
        loco = create_locomotive(yA["id"], unit_number="CI-UP0101")
        assert self._available_count_at(api, yA["id"]) == 1
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 5, 6)
        )
        assert get_locomotive(loco["id"])["status"] == "ASSIGNED"
        validate_success(
            api_client.cancel_train_departure(dep["id"], TS)
        )
        loco_now = get_locomotive(loco["id"])
        assert loco_now["status"] == "AVAILABLE"
        assert loco_now["current_yard_id"] == yA["id"]
        assert self._available_count_at(api, yA["id"]) == 1, (
            "lock count returns to exactly its pre-book value"
        )

    def test_rebook_same_unit_succeeds_after_cancel(self, api):
        """PRD §3.4: "Scheduling a departure consumes the unit into
        `ASSIGNED`; ... cancelling the departure returns it to `AVAILABLE`
        still at the origin."

        Design: Difficulty/compensating_invariant/locomotive_book_release_rebook_lock_conservation
        """
        yA, yB, plan = _two_yard_active_plan("CI2")
        pool = create_crew_pool(yA["id"], crews_available=3)
        loco = create_locomotive(yA["id"], unit_number="CI2-UP0101")
        dep = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 5, 6)
        )
        validate_success(
            api_client.cancel_train_departure(dep["id"], TS)
        )
        rebooked = get_success_data(
            api_call_create_departure(plan["id"], pool["id"], loco["id"], 5, 6)
        )
        assert rebooked["status"] == "SCHEDULED"
        assert get_locomotive(loco["id"])["status"] == "ASSIGNED", (
            "lock re-acquired; no phantom units created by the cycle"
        )


# ===========================================================================
# compensating_invariant / service_credit_accrual_and_adjustment_conservation
# ===========================================================================

class TestServiceCreditConservation:
    def _run_late_delivery(self):
        sc = setup_operational_scenario(
            "SC", shipment_car_count=4, committed_miles=300,
            delivery_by="2026-09-02T00:00:00Z",
        )
        finalize_and_depart(sc, "2026-09-01T08:00:00Z")
        set_clock("2026-09-01T20:00:00Z")
        record_car_event(sc["shipment"]["id"], sc["yB"]["id"], "YARD_ARRIVAL",
                         "2026-09-01T20:00:00Z", 4)
        set_clock("2026-09-02T06:00:00Z")
        record_car_event(sc["shipment"]["id"], sc["yB"]["id"], "PLACED_DELIVERED",
                         "2026-09-02T06:00:00Z", 4)
        return sc

    def test_late_delivery_accrues_credits_equal_to_car_count(self, api):
        """PRD §3.8: "the customer's `service_credit_balance` increases by the
        shipment's `car_count`" and "the shipment's `compliance_status` is set
        to `OFF_PLAN`, a `ServiceException` of type `DELIVERY_MISS` is
        raised".

        Design: Difficulty/compensating_invariant/service_credit_accrual_and_adjustment_conservation
        """
        sc = self._run_late_delivery()
        cu = get_customer(sc["customer"]["id"])
        assert cu["service_credit_balance"] == 4
        shipment = get_shipment(sc["shipment"]["id"])
        assert shipment["status"] == "DELIVERED"
        assert shipment["compliance_status"] == "OFF_PLAN"
        exceptions = list_exceptions_for_shipment(sc["shipment"]["id"])
        dm = [e for e in exceptions if e["exception_type"] == "DELIVERY_MISS"]
        assert len(dm) == 1

    def test_adjustment_reverses_accrual_and_floor_is_enforced(self, api):
        """PRD §3.8: "A `ServiceManager` may also adjust a customer's balance
        directly by a signed `delta` — added to `service_credit_balance` —
        but no adjustment may drive the balance below zero; one that would is
        rejected with `ERR_CREDIT_BALANCE_NEGATIVE` (HTTP 422)."

        Design: Difficulty/compensating_invariant/service_credit_accrual_and_adjustment_conservation
        """
        sc = self._run_late_delivery()
        adjusted = validate_success(
            api_client.adjust_service_credits(
                sc["customer"]["id"], {"delta": -4}, SM
            )
        )
        assert adjusted["service_credit_balance"] == 0, (
            "accrual and compensating adjustment cancel exactly"
        )
        resp = api_client.adjust_service_credits(
            sc["customer"]["id"], {"delta": -1}, SM
        )
        validate_error(resp, ApiErrorId.ERR_CREDIT_BALANCE_NEGATIVE.value)
        assert get_customer(sc["customer"]["id"])["service_credit_balance"] == 0
