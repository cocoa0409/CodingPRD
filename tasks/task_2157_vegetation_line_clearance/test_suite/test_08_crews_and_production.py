"""Crew bookings, the travel buffer, daily production and the plan summary."""
import pytest

from test_helpers import (
    ApiErrorId, TEST_USERS, assert_crew_assignment, file_production,
    make_crew_foreman_headers, new_crew, new_work_plan, read_booking, read_crew,
    read_plan, read_production_summary, read_span, setup_circuit, setup_completed_span,
    setup_in_progress_span, setup_released_span, validate_error, validate_paginated,
    validate_success,
)

PLANNER = TEST_USERS["planner_headers"]
FORESTER = TEST_USERS["forester_headers"]


class TestTravelBufferGeometry:
    """A 60-minute buffer is appended to the end of every interval before comparison."""

    def test_a_booking_starting_inside_the_travel_buffer_conflicts(self, api):
        """PRD §3.4: "The requested booking conflicts with an existing one when the requested
        `start_at` is earlier than that booking's `end_at` plus 60 minutes **and** the requested
        `end_at` plus 60 minutes is later than that booking's `start_at`; if any existing
        booking satisfies both conditions the request is rejected with
        `ERR_CREW_SCHEDULE_CONFLICT` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_interval_with_sixty_minute_travel_buffer
        """
        world = setup_released_span()
        crew = new_crew(crew_code="CRW-1")
        first = validate_success(api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": crew["id"],
            "start_at": "2026-08-03T08:00:00Z", "end_at": "2026-08-03T16:00:00Z"},
            PLANNER), 201)

        resp = api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": crew["id"],
            "start_at": "2026-08-03T16:30:00Z", "end_at": "2026-08-03T20:00:00Z"}, PLANNER)

        validate_error(resp, ApiErrorId.ERR_CREW_SCHEDULE_CONFLICT.value)
        assert resp.status_code == 409
        assert read_booking(first["id"])["status"] == "SCHEDULED"

    def test_a_booking_exactly_sixty_minutes_later_does_not_conflict(self, api):
        """PRD §3.4: "Bookings that merely touch — where the gap between them is 60 minutes or
        more — do not conflict."
        PRD §3.4: "A successful booking is created at `SCHEDULED`, moves an `AVAILABLE` crew to
        `ASSIGNED`, and increments the crew's `version` by 1."

        Design: Difficulty/resource_temporal_overlap/crew_booking_half_open_interval_with_sixty_minute_travel_buffer
        """
        world = setup_released_span()
        crew = new_crew(crew_code="CRW-1")
        validate_success(api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": crew["id"],
            "start_at": "2026-08-03T08:00:00Z", "end_at": "2026-08-03T16:00:00Z"},
            PLANNER), 201)

        resp = api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": crew["id"],
            "start_at": "2026-08-03T17:00:00Z", "end_at": "2026-08-03T20:00:00Z"}, PLANNER)
        second = validate_success(resp, 201)

        assert_crew_assignment(second)
        assert second["status"] == "SCHEDULED"
        _, meta = validate_paginated(
            api.list_crew_assignments(PLANNER, params={"crew_id": crew["id"]}))
        assert meta["total_count"] == 2

    def test_releasing_the_only_booking_returns_the_crew_to_available(self, api):
        """PRD §3.4: "A planner may release a booking early from either `SCHEDULED` or
        `ACTIVE`, moving it to the terminal state `RELEASED`, returning the crew
        `ASSIGNED → AVAILABLE` only when that crew holds no other booking in `SCHEDULED` or
        `ACTIVE`, and incrementing the crew's `version` by 1."

        Design: Corner/state_machines/corner_crew_assignment_release_returns_crew_to_available
        """
        world = setup_released_span()
        crew = new_crew(crew_code="CRW-1")
        booking = validate_success(api.create_crew_assignment({
            "work_order_id": world["span"]["id"], "crew_id": crew["id"],
            "start_at": "2026-08-03T08:00:00Z", "end_at": "2026-08-03T16:00:00Z"},
            PLANNER), 201)
        assert read_crew(crew["id"])["status"] == "ASSIGNED"

        released = validate_success(api.release_crew_assignment(booking["id"], PLANNER), 200)

        assert released["status"] == "RELEASED"
        assert read_crew(crew["id"])["status"] == "AVAILABLE"


class TestProductionSummary:

    def test_an_empty_plan_reports_zero_ratios_rather_than_an_error(self, api):
        """PRD §3.3: "`production_pct` is 100 multiplied by the numerator, divided by the
        denominator, rounded half-up to two decimal places — and when the denominator is zero
        the answer is exactly 0.00, never an error and never a division by zero."
        PRD §3.4: "When total labor hours across that set are zero — including when the set is
        empty — the rate is exactly 0.00."

        Design: Difficulty/boundary_precision_check/production_summary_on_empty_plan_is_zero_not_error
        """
        world = setup_circuit()
        plan = new_work_plan(world["circuit"]["id"], budget_cents=900_000)

        resp = api.get_production_summary(plan["id"], PLANNER)
        summary = validate_success(resp, 200)

        assert summary["planned_unit_count"] == 0
        assert summary["completed_unit_count"] == 0
        assert summary["production_pct"] == pytest.approx(0.00, abs=0.001)
        assert summary["crew_production_rate"] == pytest.approx(0.00, abs=0.001)

    def test_an_empty_plan_reports_the_full_budget_as_remaining(self, api):
        """PRD §3.3: "It returns the `work_plan_id`, the `planned_unit_count`, the
        `completed_unit_count`, the `production_pct`, the `committed_cents`, a
        `budget_remaining_cents` equal to the plan's `budget_cents` less its `committed_cents`,
        and the `crew_production_rate` described in the next subsection."
        PRD §3.3: "A new plan begins in `DRAFT` with `planned_unit_count` at 0,
        `completed_unit_count` at 0, `committed_cents` at 0 and `production_pct` at 0.00."

        Design: Difficulty/boundary_precision_check/production_summary_on_empty_plan_is_zero_not_error
        """
        world = setup_circuit()
        plan = new_work_plan(world["circuit"]["id"], budget_cents=900_000)

        summary = read_production_summary(plan["id"])

        assert summary["work_plan_id"] == plan["id"]
        assert summary["committed_cents"] == 0
        assert summary["budget_remaining_cents"] == 900_000

    def test_summary_reports_the_production_rate_and_percentage(self, api):
        """PRD §3.4: "Take every production entry reachable through the bookings of every span
        of the plan whose `execution_status` is not `CANCELLED`, sum their `units_trimmed`, sum
        their `labor_hours`, and divide the first sum by the second, rounding half-up to two
        decimal places."
        PRD §3.3: "The numerator, written back to `completed_unit_count`, is the sum of
        `actual_units_completed` over the plan's spans whose `execution_status` is
        `IN_PROGRESS`, `STORM_PREEMPTED` or `COMPLETED`; spans still at `PLANNED`, `MAPPED` or
        `RELEASED` contribute nothing to it."

        Design: Corner/calculations/corner_production_summary_reports_rate_and_pct
        """
        world = setup_completed_span(units_trimmed=180, labor_hours=8)

        summary = validate_success(
            api.get_production_summary(world["plan"]["id"], PLANNER), 200)

        assert summary["planned_unit_count"] == 200
        assert summary["completed_unit_count"] == 180
        assert summary["production_pct"] == pytest.approx(90.00, abs=0.001)
        assert summary["crew_production_rate"] == pytest.approx(22.50, abs=0.001)
        assert summary["committed_cents"] == 0
        assert summary["budget_remaining_cents"] == 5_000_000


class TestProductionFilingGuards:

    def test_production_beyond_the_ten_percent_overrun_cap_is_rejected(self, api):
        """PRD §3.4: "The span's `actual_units_completed` plus the entry's `units_trimmed` may
        not exceed the span's `planned_unit_count` multiplied by 1.10 and then truncated
        downward to a whole number — a ten percent overrun tolerance, with the fractional part
        discarded rather than rounded. Exceeding it is `ERR_UNITS_EXCEED_PLANNED` (HTTP 422)."

        Design: Corner/validations/corner_production_beyond_overrun_cap_is_rejected
        """
        world = setup_in_progress_span()
        booking_id, crew_id = world["booking"]["id"], world["crew"]["id"]
        foreman = make_crew_foreman_headers(crew_id)
        file_production(booking_id, crew_id, work_date="2026-08-03", units_trimmed=180,
                        labor_hours=8, equipment_hours=6, disposal_tons=1)

        over = api.create_production_entry({
            "crew_assignment_id": booking_id, "work_date": "2026-08-03",
            "units_trimmed": 41, "labor_hours": 2, "equipment_hours": 0,
            "disposal_tons": 0}, foreman)
        validate_error(over, ApiErrorId.ERR_UNITS_EXCEED_PLANNED.value)
        assert over.status_code == 422

        at_cap = api.create_production_entry({
            "crew_assignment_id": booking_id, "work_date": "2026-08-03",
            "units_trimmed": 40, "labor_hours": 2, "equipment_hours": 0,
            "disposal_tons": 0}, foreman)
        validate_success(at_cap, 201)

        assert read_span(world["span"]["id"])["actual_units_completed"] == 220
        assert read_plan(world["plan"]["id"])["production_pct"] == pytest.approx(110.00, abs=0.001)

    def test_a_foreman_of_another_crew_may_not_file_against_the_booking(self, api):
        """PRD §2.1: "Concretely, a `CrewForeman` filing production must name a booking whose
        `crew_id` equals its own `X-User-ID`, and a `CrewForeman` recording a hazard-tree
        removal must hold an `ACTIVE` booking, under that crew id, on the span the tree is
        assigned to; a mismatch is `ERR_NOT_CREW_OWNER` (HTTP 403)."
        PRD §3.4: "Production is filed by the `CrewForeman` of the booked crew, one entry per
        crew per day."

        Design: Corner/errors/corner_production_entry_by_other_crew_foreman_returns_forbidden
        """
        world = setup_in_progress_span()
        other_crew = new_crew(crew_code="CRW-2", crew_type="MANUAL", headcount=2,
                              hourly_rate_cents=5000, home_district="SOUTH")

        resp = api.create_production_entry({
            "crew_assignment_id": world["booking"]["id"], "work_date": "2026-08-03",
            "units_trimmed": 10, "labor_hours": 2, "equipment_hours": 0,
            "disposal_tons": 0}, make_crew_foreman_headers(other_crew["id"]))

        validate_error(resp, ApiErrorId.ERR_NOT_CREW_OWNER.value)
        assert resp.status_code == 403
        assert read_span(world["span"]["id"])["actual_units_completed"] == 0
        _, meta = validate_paginated(api.list_production_entries(
            FORESTER, params={"crew_assignment_id": world["booking"]["id"]}))
        assert meta["total_count"] == 0
