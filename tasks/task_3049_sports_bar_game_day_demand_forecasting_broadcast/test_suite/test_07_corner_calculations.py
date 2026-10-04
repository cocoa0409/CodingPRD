"""Corner coverage of the calculation rules: forecast input filtering and the
staffing ceiling arithmetic."""

from test_helpers import (
    SCHEDULER_HEADERS,
    SERVER_HEADERS,
    VENUE_MANAGER_HEADERS,
    add_shift,
    create_event,
    create_staffing_plan,
    create_venue,
    event_payload,
    validate_success,
)


class TestWingPrepExcludesCancelledEvents:
    def test_cancelled_events_are_excluded_from_the_base_attendance(self, api):
        """PRD §3.1: "The base attendance is the sum of `expected_attendance` over every event of kind `BASE` whose `status` is `INGESTED` and whose `scheduled_start` falls inside the window; events that have been cancelled are excluded."

        A cancelled 12000-attendee base event in the same window contributes
        nothing; the live 9000-attendee event alone drives the forecast:
        floor(9000 * 0.70) = 6300 dine-in, floor(6300 * 0.40) = 2520 wing
        eaters, 2520 * 15 = 37800 pieces.

        Design: Corner/calculations/wing_prep_excludes_cancelled_events
        """
        venue = create_venue()
        create_event(
            kind="BASE",
            league="FF_NFL",
            title="Live Game",
            expected_attendance=9000,
            scheduled_start="2026-09-13T19:00:00Z",
            scheduled_end="2026-09-13T22:00:00Z",
        )
        dead = create_event(
            kind="BASE",
            league="FF_NFL",
            title="Dead Game",
            expected_attendance=12000,
            scheduled_start="2026-09-14T01:00:00Z",
            scheduled_end="2026-09-14T04:00:00Z",
        )
        validate_success(api.cancel_event(dead["id"], SCHEDULER_HEADERS))

        forecast = validate_success(
            api.get_wing_prep_forecast(
                venue["id"], VENUE_MANAGER_HEADERS, date="2026-09-13"
            )
        )

        assert forecast["base_attendance"] == 9000
        assert forecast["required_pieces"] == 37800


class TestStaffingCeilPrecision:
    def test_thirty_six_hundred_covers_needs_exactly_sixty_foh(self, api):
        """PRD §3.7: "For each shift, regardless of its declared `role`, the front-of-house requirement is the ceiling of forty percent of the shift's `expected_covers` divided by 60 — that is, `expected_covers` times 0.4 divided by 60, rounded up — and the back-of-house requirement is the ceiling of forty percent of `expected_covers` divided by 100."

        3600 covers: ceil(3600 * 0.4 / 60) = 24 FOH heads.

        Design: Corner/calculations/staffing_ceil_precision
        """
        venue = create_venue()
        plan = create_staffing_plan(venue["id"])

        add_shift(plan["id"], role="FOH", expected_covers=3600)
        plan_after = validate_success(
            api.get_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS)
        )

        assert plan_after["foh_required"] == 24
        assert plan_after["boh_required"] == 15  # ceil(3600 * 0.4 / 100) = 15

    def test_one_cover_more_rounds_up(self, api):
        """PRD §3.7: "For each shift, regardless of its declared `role`, the front-of-house requirement is the ceiling of forty percent of the shift's `expected_covers` divided by 60 — that is, `expected_covers` times 0.4 divided by 60, rounded up — and the back-of-house requirement is the ceiling of forty percent of `expected_covers` divided by 100."

        Adding a 3601-cover shift on top of the 3600-cover shift contributes
        ceil(3601 * 0.4 / 60) = 25 more FOH heads, for 49 in total — the
        ceiling rounds the fractional 24.0067 up rather than truncating.

        Design: Corner/calculations/staffing_ceil_precision
        """
        venue = create_venue()
        plan = create_staffing_plan(venue["id"])

        add_shift(plan["id"], role="FOH", expected_covers=3600)
        add_shift(plan["id"], role="FOH", expected_covers=3601)
        plan_after = validate_success(
            api.get_staffing_plan(plan["id"], VENUE_MANAGER_HEADERS)
        )

        # ceil(1440/60) + ceil(1440.4/60) = 24 + 25
        assert plan_after["foh_required"] == 49
        # ceil(1440/100) + ceil(1440.4/100) = 15 + 15
        assert plan_after["boh_required"] == 30
