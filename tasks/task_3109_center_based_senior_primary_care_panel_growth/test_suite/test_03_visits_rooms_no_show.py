"""Visit scheduling claims: room half-open overlap, behavioral room gating,
completion cost booking, ride delivery on completion, cancel cascade, no-show
cost precision, and the no-show strike transport suspension boundary."""
import pytest

from test_helpers import (
    ApiErrorId,
    activate_attribution,
    create_appointment,
    create_attribution,
    create_dispatched_ride,
    create_health_plan,
    create_no_show_appointment,
    create_open_center,
    create_patient,
    create_vehicle_payload,
    get_success_data,
    give_patient_no_show_strikes,
    set_clock,
    setup_panel_with_active_patient,
    validate_error,
    validate_success,
)
from test_helpers import TEST_USERS, make_care_team_lead_headers

NET = TEST_USERS["network_operator_headers"]
ENR = TEST_USERS["enrollment_coordinator_headers"]
FRONT = TEST_USERS["front_desk_headers"]
DISP = TEST_USERS["transport_dispatcher_headers"]


def _team_lead(team):
    return make_care_team_lead_headers(team["id"])


class TestRoomHalfOpenOverlap:
    def test_room_adjacency_free_but_overlap_rejected(self, api):
        """PRD §2.10: "Room reservations for appointments follow the same half-open overlap
        discipline: two appointments may not occupy the same room over any shared instant
        of their reserved intervals, and a conflict is rejected with
        `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_free_but_overlap_rejected
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40,
        )
        # Adjacent at exactly the prior appointment's end — half-open, so free.
        adjacent = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:40:00Z", duration_minutes=40,
        )
        assert adjacent["status"] == "SCHEDULED"

        # Overlapping the first appointment (14:20 lies inside [14:00, 14:40)).
        resp = api.create_appointment(
            {
                "care_team_id": team["id"],
                "patient_id": patient["id"],
                "room_id": room["id"],
                "start_utc": "2026-09-10T14:20:00Z",
                "duration_minutes": 40,
                "kind": "PRIMARY",
            },
            FRONT,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)

    def test_room_overlap_one_minute_before_end_rejected(self, api):
        """PRD §2.10: "Room reservations for appointments follow the same half-open overlap
        discipline: two appointments may not occupy the same room over any shared instant
        of their reserved intervals, and a conflict is rejected with
        `ERR_SCHEDULE_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/room_half_open_adjacency_free_but_overlap_rejected
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40,
        )
        # Second appointment ends exactly when the first begins — adjacency, free.
        before = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T13:20:00Z", duration_minutes=40,
        )
        assert before["status"] == "SCHEDULED"

        resp = api.create_appointment(
            {
                "care_team_id": team["id"],
                "patient_id": patient["id"],
                "room_id": room["id"],
                "start_utc": "2026-09-10T14:20:00Z",
                "duration_minutes": 20,
                "kind": "PRIMARY",
            },
            FRONT,
        )
        validate_error(resp, ApiErrorId.ERR_SCHEDULE_CONFLICT.value, expected_status=409)


class TestBehavioralRoomGate:
    def test_behavioral_appointment_requires_behavioral_room(self, api):
        """PRD §3.5: "A `BEHAVIORAL` appointment additionally requires the reserved room's
        `supports_behavioral` to be true (`ERR_CROSS_REFERENCE_MISMATCH` when it is not)."

        Design: Corner/validations/behavioral_appointment_requires_behavioral_room
        """
        center, team, room = create_open_center(supports_behavioral=False)
        plan = create_health_plan()
        patient = create_patient()
        attr = create_attribution(patient["id"], plan["id"], team["id"])
        activate_attribution(attr["id"])
        resp = api.create_appointment(
            {
                "care_team_id": team["id"],
                "patient_id": patient["id"],
                "room_id": room["id"],
                "start_utc": "2026-09-12T10:00:00Z",
                "duration_minutes": 40,
                "kind": "BEHAVIORAL",
            },
            FRONT,
        )
        validate_error(
            resp, ApiErrorId.ERR_CROSS_REFERENCE_MISMATCH.value, expected_status=422
        )

    def test_behavioral_appointment_in_behavioral_room_accepted(self, api):
        """PRD §3.5: "A `BEHAVIORAL` appointment additionally requires the reserved room's
        `supports_behavioral` to be true (`ERR_CROSS_REFERENCE_MISMATCH` when it is not)."

        Design: Corner/validations/behavioral_appointment_requires_behavioral_room
        """
        center, team, room = create_open_center(supports_behavioral=True)
        plan = create_health_plan()
        patient = create_patient()
        attr = create_attribution(patient["id"], plan["id"], team["id"])
        activate_attribution(attr["id"])
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-12T10:00:00Z", duration_minutes=40, kind="BEHAVIORAL",
        )
        assert appt["status"] == "SCHEDULED"


class TestCompletionCostAndRideDelivery:
    def test_appointment_complete_books_cost_and_delivers_ride(self, api):
        """PRD §3.8: "An internal visit books at a base by `kind` — 18000 cents for
        `PRIMARY`, 22000 cents for `BEHAVIORAL`, 9000 cents for `CHW_OUTREACH` — scaled by
        duration as a multiplier of `duration_minutes` over 40 (0.5 for 20 minutes, 1.0
        for 40, 1.5 for 60)."
        PRD §3.6: "A ride in `EN_ROUTE` — or in `DISPATCHED` when pickup never started —
        moves automatically to `DELIVERED` when the linked appointment completes, booking
        transport cost at 100 percent of the flat ride cost."

        Design: Corner/state_machines/appointment_complete_books_cost_and_delivers_ride
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = get_success_data(
            api.create_vehicle(
                center["id"], create_vehicle_payload(seat_capacity=4), NET
            )
        )
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40, kind="PRIMARY",
        )
        _, dispatched = create_dispatched_ride(appt["id"], vehicle["id"])

        set_clock("2026-09-10T13:50:00Z")  # inside [13:30, 14:40] check-in window
        validate_success(api.check_in_appointment(appt["id"], FRONT), 200)
        completed = validate_success(
            api.complete_appointment(appt["id"], _team_lead(team)), 200
        )
        assert completed["status"] == "COMPLETED"
        assert completed["cost_cents"] == 18000

        ride = get_success_data(api.get_ride_request(dispatched["id"], DISP))
        assert ride["status"] == "DELIVERED"

    def test_complete_requires_checked_in(self, api):
        """PRD §3.5: "Completing requires the appointment to be `CHECKED_IN`
        (`ERR_APPOINTMENT_NOT_CHECKED_IN`) and moves it to the terminal `COMPLETED`
        state."

        Design: Corner/state_machines/appointment_complete_books_cost_and_delivers_ride
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40,
        )
        resp = api.complete_appointment(appt["id"], _team_lead(team))
        validate_error(
            resp, ApiErrorId.ERR_APPOINTMENT_NOT_CHECKED_IN.value, expected_status=409
        )


class TestCancelCascade:
    def test_appointment_cancel_cascades_to_requested_ride(self, api):
        """PRD §3.5: "Cancelling moves the appointment to the terminal `CANCELLED` state and
        cascades to transportation: any linked ride in `REQUESTED` or `DISPATCHED` moves
        to `CANCELLED` with no transport cost booked, while an `EN_ROUTE` ride is
        unaffected."

        Design: Corner/state_machines/appointment_cancel_cascades_to_requested_ride
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40,
        )
        ride = get_success_data(api.create_ride_request(appt["id"], DISP))
        assert ride["status"] == "REQUESTED"

        cancelled = validate_success(api.cancel_appointment(appt["id"], FRONT), 200)
        assert cancelled["status"] == "CANCELLED"

        ride_after = get_success_data(api.get_ride_request(ride["id"], DISP))
        assert ride_after["status"] == "CANCELLED"

    def test_appointment_cancel_cascades_to_dispatched_ride(self, api):
        """PRD §3.5: "Cancelling moves the appointment to the terminal `CANCELLED` state and
        cascades to transportation: any linked ride in `REQUESTED` or `DISPATCHED` moves
        to `CANCELLED` with no transport cost booked, while an `EN_ROUTE` ride is
        unaffected."

        Design: Corner/state_machines/appointment_cancel_cascades_to_requested_ride
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        vehicle = get_success_data(
            api.create_vehicle(center["id"], create_vehicle_payload(), NET)
        )
        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-10T14:00:00Z", duration_minutes=40,
        )
        _, dispatched = create_dispatched_ride(appt["id"], vehicle["id"])
        assert dispatched["status"] == "DISPATCHED"

        validate_success(api.cancel_appointment(appt["id"], FRONT), 200)
        ride_after = get_success_data(api.get_ride_request(dispatched["id"], DISP))
        assert ride_after["status"] == "CANCELLED"


class TestNoShowCostAndStrikes:
    def test_no_show_books_half_cost_rounded(self, api):
        """PRD §3.5: "When a `SCHEDULED` appointment's end time passes without check-in, the
        nightly sweep marks it `COMPLETED_NO_SHOW`, terminal. The no-show still books
        cost — at half the full scaled visit cost, rounded half-up to whole cents — and
        increments the patient's `no_show_strikes`."
        PRD §3.8: "An internal visit books at a base by `kind` — 18000 cents for
        `PRIMARY`, 22000 cents for `BEHAVIORAL`, 9000 cents for `CHW_OUTREACH` — scaled by
        duration as a multiplier of `duration_minutes` over 40 (0.5 for 20 minutes, 1.0
        for 40, 1.5 for 60)."

        Design: Corner/calculations/no_show_books_half_cost_rounded
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        appt = create_no_show_appointment(
            team, patient["id"], room["id"],
            sweep_utc="2026-09-11T00:00:00Z",
            start_utc="2026-09-10T14:00:00Z", duration_minutes=20,
            kind="CHW_OUTREACH",
        )
        assert appt["status"] == "COMPLETED_NO_SHOW"
        # round_half_up(9000 * (20/40) * 0.5) == 2250
        assert appt["cost_cents"] == 2250

    def test_no_show_strike_count_exactly_three_suspends_transport(self, api):
        """PRD §3.6: "Creation is rejected with `ERR_TRANSPORT_PRIVILEGE_SUSPENDED` when the
        patient carries 3 or more `no_show_strikes`."
        PRD §2.4: "the **nightly sweep** marks any appointment still in `SCHEDULED` whose
        end time (its `start_utc` plus its `duration_minutes`) has passed as a no-show,
        recomputes each patient's `no_show_strikes` as the count of `COMPLETED_NO_SHOW`
        appointments in the trailing ninety days."

        Design: Difficulty/boundary_precision_check/no_show_strike_count_exactly_three_suspends_transport
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        patient = give_patient_no_show_strikes(center, team, room, patient["id"], 2)
        assert patient["no_show_strikes"] == 2

        # At exactly 2 strikes a ride request still succeeds.
        appt_ok = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-20T14:00:00Z", duration_minutes=40,
        )
        ride = validate_success(api.create_ride_request(appt_ok["id"], DISP), 201)
        assert ride["status"] == "REQUESTED"

        # Cancel the 09-20 appointment so the next nightly sweep does not mark
        # it as an additional no-show (which would inflate the strike count).
        validate_success(api.cancel_appointment(appt_ok["id"], FRONT), 200)

        # Third no-show brings the patient to exactly 3 strikes.
        create_no_show_appointment(
            team, patient["id"], room["id"],
            sweep_utc="2026-09-21T15:00:00Z",
            start_utc="2026-09-21T14:00:00Z", duration_minutes=40,
        )
        patient3 = get_success_data(api.get_patient(patient["id"], ENR))
        assert patient3["no_show_strikes"] == 3

        appt_blocked = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-22T14:00:00Z", duration_minutes=40,
        )
        resp = api.create_ride_request(appt_blocked["id"], DISP)
        validate_error(
            resp, ApiErrorId.ERR_TRANSPORT_PRIVILEGE_SUSPENDED.value, expected_status=409
        )

    def test_two_strikes_do_not_suspend_transport(self, api):
        """PRD §3.6: "Creation is rejected with `ERR_TRANSPORT_PRIVILEGE_SUSPENDED` when the
        patient carries 3 or more `no_show_strikes`."
        PRD §2.4: "the **nightly sweep** marks any appointment still in `SCHEDULED` whose
        end time (its `start_utc` plus its `duration_minutes`) has passed as a no-show,
        recomputes each patient's `no_show_strikes` as the count of `COMPLETED_NO_SHOW`
        appointments in the trailing ninety days."

        Design: Difficulty/boundary_precision_check/no_show_strike_count_exactly_three_suspends_transport
        """
        center, team, room, plan, patient, attr = setup_panel_with_active_patient()
        patient = give_patient_no_show_strikes(center, team, room, patient["id"], 2)
        assert patient["no_show_strikes"] == 2

        appt = create_appointment(
            team["id"], patient["id"], room["id"],
            start_utc="2026-09-20T14:00:00Z", duration_minutes=40,
        )
        ride = validate_success(api.create_ride_request(appt["id"], DISP), 201)
        assert ride["status"] == "REQUESTED"
        assert ride["patient_id"] == patient["id"]
