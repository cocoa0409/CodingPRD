"""Transportation claims: dispatch gating, vehicle capacity-overlap, the
failed-no-show recovery loop, and ride state preconditions."""
from test_helpers import (
    ApiErrorId,
    activate_attribution,
    api_client,
    create_appointment,
    create_attribution,
    create_en_route_ride,
    create_patient,
    create_room_payload,
    create_vehicle_payload,
    get_success_data,
    set_clock,
    setup_panel_with_active_patient,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS

NET = TEST_USERS["network_operator_headers"]
DISP = TEST_USERS["transport_dispatcher_headers"]


def _make_vehicle(api, center_id, **overrides):
    return get_success_data(
        api.create_vehicle(center_id, create_vehicle_payload(**overrides), NET)
    )


class TestDispatchStateGates:
    def test_ride_dispatch_requires_requested_state(self, api):
        """PRD §3.6: "A `TransportDispatcher` dispatches a `REQUESTED` ride
        (`ERR_RIDE_NOT_REQUESTED` otherwise) by supplying a `vehicle_id`."

        Design: Corner/state_machines/ride_dispatch_requires_requested_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = _make_vehicle(api, center["id"])
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        en_route = create_en_route_ride(appt["id"], vehicle["id"], "2026-09-10T13:20:00Z")
        assert en_route["status"] == "EN_ROUTE"

        resp = api.dispatch_ride(en_route["id"], {"vehicle_id": vehicle["id"]}, DISP)
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_REQUESTED.value, expected_status=409)

    def test_start_pickup_requires_dispatched(self, api):
        """PRD §3.6: "The ride must be `DISPATCHED` (`ERR_RIDE_NOT_DISPATCHED`) and the
        logical clock must lie within the inclusive pickup window from
        `pickup_window_start` to `pickup_window_end`; a missed window is
        `ERR_PICKUP_WINDOW_MISSED`."

        Design: Corner/state_machines/ride_dispatch_requires_requested_state
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        ride = get_success_data(api.create_ride_request(appt["id"], DISP))
        assert ride["status"] == "REQUESTED"
        # Clock inside the pickup window [13:10, 14:10] so only the state gate can fail.
        set_clock("2026-09-10T13:20:00Z")
        resp = api.start_pickup_ride(ride["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_DISPATCHED.value, expected_status=409)


class TestVehicleCapacityOverlap:
    def _extra_room(self, center_id, label):
        return get_success_data(
            api_client.create_room(center_id, create_room_payload(room_label=label), NET)
        )

    def test_vehicle_capacity_overlap_aggregate_seats(self, api):
        """PRD §2.10: "A candidate vehicle is feasible when, at every instant within the new
        ride's pickup window, the concurrent occupied seats from that vehicle's
        `DISPATCHED` or `EN_ROUTE` rides whose pickup windows overlap the new window with
        a non-zero intersection, plus one, do not exceed the vehicle's `seat_capacity`."
        PRD §2.10: "A violation is rejected with `ERR_VEHICLE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/vehicle_capacity_overlap_aggregate_seats
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        room2 = self._extra_room(center["id"], "R2")
        room3 = self._extra_room(center["id"], "R3")
        p2 = create_patient(full_name="Second")
        p3 = create_patient(full_name="Third")
        for p in (p2, p3):
            a = create_attribution(p["id"], plan["id"], team["id"])
            activate_attribution(a["id"])

        vehicle = _make_vehicle(api, center["id"], seat_capacity=2)
        # All three appointments at 14:40 -> identical pickup windows
        # [13:10, 14:10] for each ride. (Distinct rooms: simultaneous
        # appointments may not share a room.)
        def _ride(patient_id, room_id):
            appt = create_appointment(
                team["id"], patient_id, room_id,
                start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
            )
            return get_success_data(api.create_ride_request(appt["id"], DISP))

        r1 = _ride(patient["id"], room["id"])
        r2 = _ride(p2["id"], room2["id"])
        r3 = _ride(p3["id"], room3["id"])

        validate_success(
            api.dispatch_ride(r1["id"], {"vehicle_id": vehicle["id"]}, DISP), 200
        )
        validate_success(
            api.dispatch_ride(r2["id"], {"vehicle_id": vehicle["id"]}, DISP), 200
        )

        resp = api.dispatch_ride(r3["id"], {"vehicle_id": vehicle["id"]}, DISP)
        validate_error(
            resp, ApiErrorId.ERR_VEHICLE_CAPACITY_EXCEEDED.value, expected_status=409
        )

    def test_vehicle_window_adjacency_is_free(self, api):
        """PRD §2.10: "Windows touching at exactly one endpoint — one window's end equal to
        another's start — do not overlap; adjacency is free and no buffer minute is
        applied."

        Design: Difficulty/resource_temporal_overlap/vehicle_capacity_overlap_aggregate_seats
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        p2 = create_patient(full_name="Second")
        a2 = create_attribution(p2["id"], plan["id"], team["id"])
        activate_attribution(a2["id"])

        vehicle = _make_vehicle(api, center["id"], seat_capacity=1)
        # First appointment at 14:40 -> pickup window [13:10, 14:10].
        appt1 = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        r1 = get_success_data(api.create_ride_request(appt1["id"], DISP))
        # Second appointment at 15:40 -> pickup window [14:10, 15:10]; touches the
        # first window at exactly one endpoint, so the 1-seat vehicle accepts both.
        # (The 40-minute visits, [14:40,15:20] and [15:40,16:20], do not overlap,
        # so the shared room is free.)
        appt2 = create_appointment(
            team["id"], p2["id"], room["id"],
            start_utc="2026-09-10T15:40:00Z", duration_minutes=40,
        )
        r2 = get_success_data(api.create_ride_request(appt2["id"], DISP))

        validate_success(
            api.dispatch_ride(r1["id"], {"vehicle_id": vehicle["id"]}, DISP), 200
        )
        dispatched2 = validate_success(
            api.dispatch_ride(r2["id"], {"vehicle_id": vehicle["id"]}, DISP), 200
        )
        assert dispatched2["status"] == "DISPATCHED"


class TestFailedRecoveryLoop:
    def test_ride_request_failed_recovery_loop(self, api):
        """PRD §3.6: "If the passenger fails to appear, the dispatcher marks the ride
        no-show. The ride must be `EN_ROUTE` (`ERR_RIDE_NOT_EN_ROUTE`); it moves to
        `FAILED_NO_SHOW`, its `failure_count` increments by 1, and transport cost is
        booked at 100 percent of the flat ride cost."
        PRD §3.6: "Recovery passes the ride through a transient `RECOVERED` state and
        returns it to `REQUESTED` under the same id — `RECOVERED` is never a resting
        state; the observable state after recovery is `REQUESTED`, ready for a fresh
        dispatch."

        Design: Difficulty/non_linear_state_machine/ride_request_failed_recovery_loop
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = _make_vehicle(api, center["id"])
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        en_route = create_en_route_ride(appt["id"], vehicle["id"], "2026-09-10T13:20:00Z")

        failed = validate_success(api.mark_no_show_ride(en_route["id"], DISP), 200)
        assert failed["status"] == "FAILED_NO_SHOW"
        assert failed["failure_count"] == 1

        # Recover while the visit could still happen (appointment ends 15:20).
        recovered = validate_success(api.recover_ride(failed["id"], DISP), 200)
        assert recovered["id"] == failed["id"]
        assert recovered["status"] == "REQUESTED"
        assert recovered["failure_count"] == 1

    def test_ride_can_be_dispatched_and_failed_twice(self, api):
        """PRD §3.6: "Recovery passes the ride through a transient `RECOVERED` state and
        returns it to `REQUESTED` under the same id — `RECOVERED` is never a resting
        state; the observable state after recovery is `REQUESTED`, ready for a fresh
        dispatch."
        PRD §3.6: "The ride must be `EN_ROUTE` (`ERR_RIDE_NOT_EN_ROUTE`); it moves to
        `FAILED_NO_SHOW`, its `failure_count` increments by 1, and transport cost is
        booked at 100 percent of the flat ride cost."

        Design: Difficulty/non_linear_state_machine/ride_request_failed_recovery_loop
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = _make_vehicle(api, center["id"])
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        en_route = create_en_route_ride(appt["id"], vehicle["id"], "2026-09-10T13:20:00Z")
        failed = validate_success(api.mark_no_show_ride(en_route["id"], DISP), 200)
        recovered = validate_success(api.recover_ride(failed["id"], DISP), 200)

        # Second dispatch + pickup + failure on the same ride row.
        redispatched = validate_success(
            api.dispatch_ride(recovered["id"], {"vehicle_id": vehicle["id"]}, DISP), 200
        )
        en_route2 = validate_success(api.start_pickup_ride(redispatched["id"], DISP), 200)
        failed2 = validate_success(api.mark_no_show_ride(en_route2["id"], DISP), 200)
        assert failed2["status"] == "FAILED_NO_SHOW"
        assert failed2["failure_count"] == 2

    def test_recover_requires_failed_no_show(self, api):
        """PRD §3.6: "a dispatcher recovers a `FAILED_NO_SHOW` ride (`ERR_RIDE_NOT_FAILED`
        otherwise) as long as the logical clock is still before the appointment's end
        (`ERR_RECOVERY_WINDOW_MISSED` past it)."

        Design: Difficulty/non_linear_state_machine/ride_request_failed_recovery_loop
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        ride = get_success_data(api.create_ride_request(appt["id"], DISP))
        resp = api.recover_ride(ride["id"], DISP)
        validate_error(resp, ApiErrorId.ERR_RIDE_NOT_FAILED.value, expected_status=409)
