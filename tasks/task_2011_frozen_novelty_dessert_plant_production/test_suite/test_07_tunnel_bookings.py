"""Tunnel booking window conflict, buffer boundary, throughput (PRD §3.5)."""
from test_helpers import (
    ApiErrorId,
    create_booking,
    create_run,
    setup_completed_run,
    setup_plant,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import PLANNER


class TestTunnelBufferBoundary:
    def test_tunnel_buffer_exact_boundary(self, api):
        """PRD §3.5: "exact adjacency — new start_at equal to an existing
        booking's end_at plus the 30-minute buffer — is allowed. A conflict
        rejects with ERR_TUNNEL_WINDOW_CONFLICT (HTTP 409)."

        Existing booking 10:00-12:00 occupies [10:00, 12:30). A new booking
        starting 12:29 (29-minute gap) conflicts; starting 12:30 (exactly
        the 30-minute buffer) is allowed.

        Design: Difficulty/boundary_precision_check/tunnel_buffer_exact_boundary
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T13:00:00Z")
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T12:29:00Z",
             "end_at": "2026-08-10T13:29:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_WINDOW_CONFLICT)
        ok = validate_success(api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T12:30:00Z",
             "end_at": "2026-08-10T13:30:00Z"}, PLANNER), 201)
        assert ok["status"] == "BOOKED"

    def test_tunnel_buffer_thirty_one_minute_gap_allowed(self, api):
        """PRD §3.5: "exact adjacency — new start_at equal to an existing
        booking's end_at plus the 30-minute buffer — is allowed." A
        31-minute gap is strictly more than the buffer, so it is also
        allowed; the >= boundary and its interior behave identically.

        Design: Difficulty/boundary_precision_check/tunnel_buffer_exact_boundary
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T13:00:00Z")
        ok = validate_success(api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T12:31:00Z",
             "end_at": "2026-08-10T13:31:00Z"}, PLANNER), 201)
        assert ok["status"] == "BOOKED"

    def test_booking_at_exact_end_still_conflicts(self, api):
        """PRD §3.5: "The conflict check treats every existing non-cancelled
        booking on the same tunnel ... as occupying a half-open interval
        that ends 30 minutes after its nominal end_at — a trailing cleanup
        buffer." A new booking starting exactly at the previous booking's
        end (12:00 == 12:00) still conflicts because the buffer extends
        occupancy to 12:30.

        Design: Difficulty/resource_temporal_overlap/tunnel_trailing_buffer_overlap
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T12:30:00Z")
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T12:00:00Z",
             "end_at": "2026-08-10T13:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_WINDOW_CONFLICT)
        bookings, meta = validate_paginated(
            api.list_tunnel_bookings(PLANNER, params={"run_id": run_b["id"]}))
        assert meta["total_count"] == 0

    def test_overlapping_windows_conflict(self, api):
        """PRD §3.5: "A new booking conflicts when its start_at falls
        strictly before an existing booking's buffered end AND that existing
        booking's start_at falls strictly before the new booking's end_at;
        ... A conflict rejects with ERR_TUNNEL_WINDOW_CONFLICT (HTTP 409)."

        Existing 10:00-12:00; new 11:00-13:00 overlaps outright.

        Design: Difficulty/resource_temporal_overlap/tunnel_trailing_buffer_overlap
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T11:30:00Z")
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T11:00:00Z",
             "end_at": "2026-08-10T13:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_WINDOW_CONFLICT)


class TestTunnelThroughput:
    def test_tunnel_capacity_exceeded_rejected(self, api):
        """PRD §3.5: "The throughput check requires the run's planned_units
        to be no greater than the tunnel's max_units_per_hour multiplied by
        the window's length in hours; ... a violation rejects with
        ERR_TUNNEL_CAPACITY_EXCEEDED (HTTP 422)." 50000 planned units in a
        1-hour window on a 20000 u/h tunnel exceeds 20000.

        Design: Corner/validations/tunnel_capacity_exceeded_rejected
        """
        product, line, tunnel, _ = setup_plant(
            line_overrides={"rate_units_per_hour": 60000})
        run = create_run(product["id"], line["id"], run_code="R-CAP",
                         planned_units=50000,
                         scheduled_start="2026-08-10T10:00:00Z")
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run["id"],
             "start_at": "2026-08-10T10:00:00Z",
             "end_at": "2026-08-10T11:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_CAPACITY_EXCEEDED)


class TestBookingStateGates:
    def test_booking_created_in_booked_state(self, api):
        """PRD §3.5: "Tunnel bookings are made by a ProductionPlanner naming
        tunnel_id, run_id, start_at, and end_at (strictly after start_at)" —
        a newly created booking starts in BOOKED.

        Design: Corner/state_machines/booking_created_in_booked_state
        """
        product, line, tunnel, _ = setup_plant()
        run = create_run(product["id"], line["id"], run_code="R-B0",
                         planned_units=1000,
                         scheduled_start="2026-08-10T10:00:00Z")
        booking = create_booking(tunnel["id"], run["id"],
                                 start_at="2026-08-10T10:00:00Z",
                                 end_at="2026-08-10T11:00:00Z")
        assert booking["status"] == "BOOKED"

    def test_booking_exists_rejected(self, api):
        """PRD §3.5: "A run may hold at most one active booking; a second
        attempt while one is still BOOKED rejects with ERR_BOOKING_EXISTS
        (HTTP 409)."

        Design: Corner/validations/booking_exists_rejected
        """
        product, line, tunnel, _ = setup_plant()
        run = create_run(product["id"], line["id"], run_code="R-BX",
                         planned_units=1000,
                         scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T11:00:00Z")
        # Second, non-overlapping window for the SAME run.
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run["id"],
             "start_at": "2026-08-10T12:30:00Z",
             "end_at": "2026-08-10T13:30:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_BOOKING_EXISTS)

    def test_run_not_schedulable_when_completed(self, api):
        """PRD §3.5: "The referenced run must be in SCHEDULED or
        MIX_ASSIGNED, else ERR_RUN_NOT_SCHEDULABLE."

        Design: Corner/validations/run_not_schedulable_when_completed
        """
        ctx = setup_completed_run(run_code="R-NS", planned_units=1000,
                                  actual_units=1000, mix_metered_litres=50.0)
        resp = api.create_tunnel_booking(
            {"tunnel_id": ctx["tunnel"]["id"], "run_id": ctx["run"]["id"],
             "start_at": "2026-08-10T18:00:00Z",
             "end_at": "2026-08-10T19:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_RUN_NOT_SCHEDULABLE)


class TestBookingVsRunStatePriority:
    def test_booking_temporal_vs_referential_priority(self, api):
        """PRD §2.9: "When a single request violates multiple rules, the
        rejection surfaces the highest-priority violation. The evaluation
        order, from highest priority to lowest, is: ... then the
        domain-specific business, temporal, referential, and fiscal checks
        detailed in §3." The §3.5 booking rules list the conflict check
        before the run-state check ("The referenced run must be in
        SCHEDULED or MIX_ASSIGNED" precedes the one-active-booking rule but
        follows the conflict/throughput checks in the endpoint prose), so a
        booking whose window overlaps an existing one surfaces
        ERR_TUNNEL_WINDOW_CONFLICT even when the referenced run is CANCELED.

        Design: Difficulty/priority_pair_validation_conflict/booking_temporal_vs_referential_priority
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T11:00:00Z")
        validate_success(api.cancel_run(run_b["id"], PLANNER))
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T11:00:00Z",
             "end_at": "2026-08-10T13:00:00Z"}, PLANNER)
        validate_error(resp, ApiErrorId.ERR_TUNNEL_WINDOW_CONFLICT)
        bookings, meta = validate_paginated(
            api.list_tunnel_bookings(PLANNER, params={"run_id": run_b["id"]}))
        assert meta["total_count"] == 0

    def test_temporal_conflict_masks_canceled_run_state(self, api):
        """PRD §2.9: "the rejection surfaces the highest-priority
        violation. The evaluation order, from highest priority to lowest,
        is: ... then the domain-specific business, temporal, referential,
        and fiscal checks detailed in §3." The temporal window conflict is
        named before the referential run-state check, so a booking that
        violates both returns ERR_TUNNEL_WINDOW_CONFLICT and never reports
        ERR_RUN_NOT_SCHEDULABLE.

        Design: Difficulty/priority_pair_validation_conflict/booking_temporal_vs_referential_priority
        """
        product, line, tunnel, _ = setup_plant()
        run_a = create_run(product["id"], line["id"], run_code="R-A",
                           planned_units=1000,
                           scheduled_start="2026-08-10T10:00:00Z")
        create_booking(tunnel["id"], run_a["id"],
                       start_at="2026-08-10T10:00:00Z",
                       end_at="2026-08-10T12:00:00Z")
        run_b = create_run(product["id"], line["id"], run_code="R-B",
                           planned_units=1000,
                           scheduled_start="2026-08-10T11:00:00Z")
        validate_success(api.cancel_run(run_b["id"], PLANNER))
        resp = api.create_tunnel_booking(
            {"tunnel_id": tunnel["id"], "run_id": run_b["id"],
             "start_at": "2026-08-10T11:00:00Z",
             "end_at": "2026-08-10T13:00:00Z"}, PLANNER)
        assert resp.status_code == 409
        assert resp.json()["data"]["error_id"] == "ERR_TUNNEL_WINDOW_CONFLICT"
        assert resp.json()["data"]["error_id"] != "ERR_RUN_NOT_SCHEDULABLE"
