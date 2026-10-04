"""Compensating invariants: tickets_issued_count conserved through the
call/requeue round trip, and physical chair inventory conserved through the
degrade/recover cycle."""

from test_helpers import (
    TEST_USERS,
    get_success_data,
    run_completed_cycle,
    setup_event_with_operational_sterile_station,
    setup_event_with_queued_ticket,
    validate_paginated,
    validate_success,
)

ED = TEST_USERS["event_director_headers"]
QM = TEST_USERS["queue_marshal_headers"]
SL = TEST_USERS["station_lead_headers"]
ST = TEST_USERS["sterilization_tech_headers"]


class TestTicketCountConservedThroughCallRequeue:
    def test_call_and_requeue_leave_issued_count_unchanged(self, api):
        """PRD §3.6: "A successfully issued ticket enters `QUEUED` status, the
        event's `tickets_issued_count` increments" and "The marshal can
        requeue a `CALLED` ticket back to `QUEUED`, but at most once per
        ticket" — neither the call nor the requeue moves
        `tickets_issued_count`.

        Design: Difficulty/compensating_invariant/ticket_count_conserved_through_call_requeue_cycle
        """
        ctx = setup_event_with_queued_ticket()
        before = validate_success(api.get_event(ctx["id"], ED))
        assert before["tickets_issued_count"] == 1

        get_success_data(api.call_ticket(ctx["id"], ctx["ticket_id"], QM))
        after_call = validate_success(api.get_event(ctx["id"], ED))
        assert after_call["tickets_issued_count"] == 1

        get_success_data(api.requeue_ticket(ctx["id"], ctx["ticket_id"], QM))
        after_requeue = validate_success(api.get_event(ctx["id"], ED))
        assert after_requeue["tickets_issued_count"] == 1

    def test_round_trip_returns_ticket_to_queued(self, api):
        """PRD §3.6: "The marshal can requeue a `CALLED` ticket back to
        `QUEUED`" — after the call/requeue round trip the ticket is QUEUED
        again with a fresh tail-of-queue position.

        Design: Difficulty/compensating_invariant/ticket_count_conserved_through_call_requeue_cycle
        """
        ctx = setup_event_with_queued_ticket()
        get_success_data(api.call_ticket(ctx["id"], ctx["ticket_id"], QM))
        requeued = get_success_data(
            api.requeue_ticket(ctx["id"], ctx["ticket_id"], QM)
        )
        assert requeued["status"] == "QUEUED"
        tickets, _ = validate_paginated(api.list_event_tickets(ctx["id"], QM))
        assert tickets[0]["status"] == "QUEUED"
        assert tickets[0]["queue_position"] == 2


class TestChairCountConservedThroughDegradeRecovery:
    def test_chair_inventory_unchanged_through_cycle(self, api):
        """PRD §3.7: "`dental_chair_count`, `vision_lane_count`, and
        `medical_bay_count` sum the `chair_count` of the event's `OPERATIONAL`
        stations of the corresponding type" and PRD §3.5: "Degradation halves
        a station's effective capacity in the throughput projection, as
        described in §3.7" — the degrade/recover cycle moves the projection
        but the physical chair inventory reported while the station is
        OPERATIONAL is identical before and after.

        Design: Difficulty/compensating_invariant/chair_count_conserved_through_degrade_recovery_cycle
        """
        ctx = setup_event_with_operational_sterile_station(
            station_overrides={"chair_count": 4}
        )
        event_id, station_id = ctx["id"], ctx["station_id"]

        before = validate_success(api.get_event(event_id, ED))
        assert before["dental_chair_count"] == 4

        cycle = get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 7}, ST
            )
        )
        degraded = validate_success(api.get_event(event_id, ED))
        # DEGRADED stations are excluded from the chair-count sum.
        assert degraded["dental_chair_count"] == 0

        get_success_data(api.complete_cycle(event_id, cycle["id"], ST))
        recovered = validate_success(api.get_event(event_id, ED))
        assert recovered["dental_chair_count"] == 4, (
            "physical chair inventory is conserved through degrade/recover"
        )

    def test_station_status_round_trip_degraded_then_operational(self, api):
        """PRD §3.5: "Whenever the backlog for an event with a
        sterilization-requiring `OPERATIONAL` station rises strictly above 6
        pending batches, that station degrades automatically to `DEGRADED`"
        and "A `DEGRADED` station returns to `OPERATIONAL` automatically when
        a cycle completes and the backlog falls back to 6 or fewer."

        Design: Difficulty/compensating_invariant/chair_count_conserved_through_degrade_recovery_cycle
        """
        ctx = setup_event_with_operational_sterile_station(
            station_overrides={"chair_count": 4}
        )
        event_id, station_id = ctx["id"], ctx["station_id"]

        cycle = get_success_data(
            api.start_sterilization_cycle(
                event_id, {"instrument_batch_size": 7}, ST
            )
        )
        stations, _ = validate_paginated(api.list_event_stations(event_id, SL))
        assert stations[0]["status"] == "DEGRADED"

        get_success_data(api.complete_cycle(event_id, cycle["id"], ST))
        stations, _ = validate_paginated(api.list_event_stations(event_id, SL))
        assert stations[0]["status"] == "OPERATIONAL"
