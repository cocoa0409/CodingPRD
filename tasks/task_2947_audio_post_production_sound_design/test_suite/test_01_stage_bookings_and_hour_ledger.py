"""Stage reservations, occupancy buffers and the project's stage-hour ledger."""

from prd_bench_local_runner.testing import validate_error, validate_paginated, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import ERR_STAGE_WINDOW_CONFLICT
from test_helpers.assertions import (
    assert_billing_chain,
    assert_decimal,
    assert_hour_ledger,
    assert_hour_ledger_identity,
)
from test_helpers.test_users import SUPERVISOR_HEADERS


class TestProvisionalAndFinalStageCost:
    """The reservation-time and completion-time cost variants of one booking."""

    def test_reservation_pins_the_provisional_cost_from_the_requested_window(self, world, api):
        """A reservation prices the requested window and leaves the final fields null.

        PRD §3.6: "The provisional figure never contains overtime — overtime is a
        completion-time concept only."

        Design: Difficulty/dual_variant_calc/stage_booking_provisional_vs_final_cost_divergence
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(certified_platforms=["THEATRICAL", "STREAMING"], max_daily_hours=10.00)
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)

        version = world.project_version(project["id"])
        booking = validate_success(
            api.create_mix_booking(
                f.mix_booking_payload(
                    version,
                    project["id"],
                    stage["id"],
                    mixer["id"],
                    booking_type="FINAL_MIX",
                    platform="THEATRICAL",
                    window_start_utc="2026-09-14T10:00:00Z",
                    window_end_utc="2026-09-14T13:00:00Z",
                    client_attendance="ONSITE",
                ),
                SUPERVISOR_HEADERS,
            ),
            201,
        )

        assert booking["status"] == "RESERVED"
        assert_decimal(booking["reserved_hours"], 3.00)
        assert booking["provisional_cost_cents"] == 360000
        assert booking["actual_start_utc"] is None
        assert booking["actual_end_utc"] is None
        assert booking["billable_hours_final"] is None
        assert booking["overtime_hours"] is None
        assert booking["final_cost_cents"] is None

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 3.00, 0.00, 37.00)
        assert project_after["stage_cost_subtotal_cents"] == 360000
        assert project_after["billing_total_cents"] == 360000

    def test_completion_charges_the_quarter_hour_overrun_at_time_and_a_half(self, world, api):
        """Closing the stage prices the actual occupation and diverges by 45000 cents.

        PRD §3.6: "Working the earlier example through: a booking that reserved 3.00
        hours at 120000 cents an hour on a `STANDARD` project but actually ran from
        10:00:00Z to 13:10:00Z has an elapsed 3.1667 hours, quantises up to 3.25,
        takes `billable_hours_final` 3.25 and `overtime_hours` 0.25 against
        `regular_hours` 3.00, giving a base of 360000 plus 45000, so
        `final_cost_cents` is 405000 — 45000 cents more than the provisional figure."

        Design: Difficulty/dual_variant_calc/stage_booking_provisional_vs_final_cost_divergence
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(certified_platforms=["THEATRICAL", "STREAMING"], max_daily_hours=10.00)
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)

        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
            client_attendance="ONSITE",
        )
        provisional = booking["provisional_cost_cents"]
        assert provisional == 360000

        world.confirm_booking(booking["id"], mixer["id"])
        world.set_clock("2026-09-14T10:00:00Z")
        world.start_booking(booking["id"], mixer["id"])
        world.set_clock("2026-09-14T13:10:00Z")
        closed = world.complete_booking(booking["id"], mixer["id"])

        assert closed["status"] == "COMPLETED"
        assert_decimal(closed["reserved_hours"], 3.00)
        assert_decimal(closed["billable_hours_final"], 3.25)
        assert_decimal(closed["overtime_hours"], 0.25)
        assert closed["final_cost_cents"] == 405000
        assert closed["final_cost_cents"] - provisional == 45000

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 0.00, 3.25, 36.75)
        assert project_after["stage_cost_subtotal_cents"] == 405000
        assert project_after["billing_total_cents"] == 405000
        # PRD §3.6: "When the closed booking's `booking_type` is `FINAL_MIX` and the
        # project sits at `FINAL_MIX`, `pipeline_stage` advances to `QC`."  This project
        # never conformed a stem package, so it still sits at `EDITORIAL`, and PRD §3.2
        # pins the consequence: "if the triggering event occurs while the project sits at
        # some other stage, `pipeline_stage` is simply left untouched, with no skip and no
        # regression."
        assert project_after["pipeline_stage"] == "EDITORIAL"


class TestStageChangeoverBuffer:
    """Room occupancy excludes a window wider than the booked window itself."""

    def _facility(self, world):
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(max_daily_hours=10.00)
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)
        first = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="PREMIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
            client_attendance="ONSITE",
        )
        return stage, mixer, project, first

    def test_a_window_inside_the_changeover_buffer_conflicts(self, world, api):
        """A start one minute inside the 45-minute buffer collides with the occupant.

        PRD §3.6: "The requested half-open window, **extended by the stage's
        `changeover_minutes` on both sides**, must not overlap any existing booking on
        the same `mix_stage_id` whose `status` is `RESERVED`, `CONFIRMED`,
        `IN_PROGRESS` or `COMPLETED`; a collision is reported as
        `ERR_STAGE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/stage_changeover_buffer_boundary_one_minute_either_side
        """
        stage, mixer, project, first = self._facility(world)

        version = world.project_version(project["id"])
        response = api.create_mix_booking(
            f.mix_booking_payload(
                version,
                project["id"],
                stage["id"],
                mixer["id"],
                booking_type="FINAL_MIX",
                platform="THEATRICAL",
                window_start_utc="2026-09-14T13:44:00Z",
                window_end_utc="2026-09-14T15:44:00Z",
                client_attendance="ONSITE",
            ),
            SUPERVISOR_HEADERS,
        )
        validate_error(response, ERR_STAGE_WINDOW_CONFLICT, 409)

        project_after = world.get_project(project["id"])
        assert_decimal(project_after["stage_hours_reserved"], 3.00)
        assert world.get_booking(first["id"])["status"] == "RESERVED"

    def test_a_window_exactly_at_the_buffer_edge_reserves_the_room(self, world, api):
        """A start exactly at end plus changeover is accepted and books real hours.

        PRD §3.6: "Comparison remains half-open at the boundary, so a new window that
        begins at exactly the existing window's `window_end_utc` plus that stage's
        changeover minutes does **not** conflict."

        Design: Difficulty/resource_temporal_overlap/stage_changeover_buffer_boundary_one_minute_either_side
        """
        stage, mixer, project, first = self._facility(world)

        version = world.project_version(project["id"])
        edge = validate_success(
            api.create_mix_booking(
                f.mix_booking_payload(
                    version,
                    project["id"],
                    stage["id"],
                    mixer["id"],
                    booking_type="FINAL_MIX",
                    platform="THEATRICAL",
                    window_start_utc="2026-09-14T13:45:00Z",
                    window_end_utc="2026-09-14T15:45:00Z",
                    client_attendance="ONSITE",
                ),
                SUPERVISOR_HEADERS,
            ),
            201,
        )

        assert edge["status"] == "RESERVED"
        assert_decimal(edge["reserved_hours"], 2.00)
        assert edge["provisional_cost_cents"] == 240000
        assert world.get_booking(first["id"])["status"] == "RESERVED"

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 5.00, 0.00, 35.00)

        ledger = world.ledger(project["id"])
        assert ledger["stage_cost_subtotal_cents"] == 600000
        assert ledger["volume_discount_cents"] == 30000
        assert ledger["billing_total_cents"] == 570000
        assert_billing_chain(ledger)

        listed, meta = validate_paginated(
            api.list_mix_bookings(SUPERVISOR_HEADERS, {"mix_stage_id": stage["id"]})
        )
        assert meta["total_count"] == 2
        assert len(listed) == 2


class TestBookingReleaseIsExactlyInverse:
    """Releasing a slot must undo the reservation with no residue."""

    def test_release_returns_the_hour_and_cost_ledger_to_its_pre_booking_values(self, world):
        """Reserve then release leaves the project exactly where it started.

        PRD §3.6: "Releasing a booking must return `stage_hours_available` to exactly
        the value it held before that booking was created — no drift — and completing a
        booking moves hours from the reserved term to the consumed term rather than
        adding them a second time."

        Design: Difficulty/compensating_invariant/booking_release_restores_hour_and_cost_ledger_without_drift
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(max_daily_hours=10.00)
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)
        available_at_rest = world.get_project(project["id"])["stage_hours_available"]
        assert world.ledger(project["id"])["billing_total_cents"] == 0

        booking = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            window_start_utc="2026-09-14T10:00:00Z",
            window_end_utc="2026-09-14T13:00:00Z",
            client_attendance="ONSITE",
        )
        reserved_state = world.get_project(project["id"])
        assert_hour_ledger(reserved_state, 3.00, 0.00, 37.00)
        assert reserved_state["stage_cost_subtotal_cents"] == 360000
        assert reserved_state["billing_total_cents"] == 360000

        released = world.release_booking(booking["id"], release_reason="client postponed the mix")
        assert released["status"] == "RELEASED"
        assert released["release_reason"] == "client postponed the mix"

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 0.00, 0.00, available_at_rest)
        assert project_after["stage_cost_subtotal_cents"] == 0
        assert project_after["billing_total_cents"] == 0

    def test_the_released_window_is_rebookable_and_two_cycles_leave_no_drift(self, world, api):
        """A released booking leaves the occupancy set, and the second cycle also reverses.

        PRD §3.6: "The booking also leaves the stage occupancy set, freeing that window
        for a new reservation."

        Design: Difficulty/compensating_invariant/booking_release_restores_hour_and_cost_ledger_without_drift
        """
        world.set_clock("2026-09-01T00:00:00Z")
        stage = world.mix_stage(hourly_rate_cents=120000, changeover_minutes=45)
        mixer = world.mixer(max_daily_hours=10.00)
        project = world.locked_project(turnaround_class="STANDARD", stage_hours_authorized=40.00)

        window = {
            "window_start_utc": "2026-09-14T10:00:00Z",
            "window_end_utc": "2026-09-14T13:00:00Z",
        }
        first = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            client_attendance="ONSITE",
            **window,
        )
        world.release_booking(first["id"], release_reason="client postponed the mix")

        second = world.booking(
            project["id"],
            stage["id"],
            mixer["id"],
            booking_type="FINAL_MIX",
            platform="THEATRICAL",
            client_attendance="ONSITE",
            **window,
        )
        assert_decimal(second["reserved_hours"], 3.00)
        world.release_booking(second["id"], release_reason="client postponed again")
        assert world.get_booking(second["id"])["status"] == "RELEASED"

        project_after = world.get_project(project["id"])
        assert_hour_ledger(project_after, 0.00, 0.00, 40.00)
        assert_hour_ledger_identity(project_after)

        ledger = world.ledger(project["id"])
        assert ledger["stage_cost_subtotal_cents"] == 0
        assert ledger["billing_total_cents"] == 0

        listed, meta = validate_paginated(
            api.list_mix_bookings(
                SUPERVISOR_HEADERS, {"project_id": project["id"], "status": "RELEASED"}
            )
        )
        assert meta["total_count"] == 2
        assert {record["id"] for record in listed} == {first["id"], second["id"]}
