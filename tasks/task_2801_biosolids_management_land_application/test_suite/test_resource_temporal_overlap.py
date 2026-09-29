"""Two scheduling resources with deliberately opposite interval conventions:
half-open site windows and closed loadout-bay occupancy intervals.
"""

from test_helpers import constants as C
from test_helpers import factories as F
from test_helpers.api_errors import ERR_LOADOUT_BAY_CAPACITY, ERR_SITE_WINDOW_CONFLICT
from test_helpers.assertions import assert_dry_tons, assert_instant_equals, assert_wet_tons
from test_helpers.test_users import AGRONOMIST_HEADERS, OFFICER_HEADERS, make_operator_headers
from prd_bench_local_runner.testing import (
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSiteWindowsAreHalfOpen:
    @staticmethod
    def _first_window(world):
        return world.build.event(
            world.site_id,
            world.batch_id,
            world.agreement_id,
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-22T00:00:00Z",
            acres_treated=50.0,
            planned_dry_tons=50.000,
        )

    @staticmethod
    def _payload(world, window_start, window_end):
        return F.event_payload(
            world.site_id,
            world.batch_id,
            world.agreement_id,
            window_start=window_start,
            window_end=window_end,
            acres_treated=50.0,
            planned_dry_tons=50.000,
        )

    def test_window_starting_where_another_ends_is_accepted(self, api, base_world):
        """PRD §2.7: "**Priority 42 — window overlap.** The requested half-open window does not overlap another application event on the same site whose `status` is `SCHEDULED`, `WEATHER_HOLD`, `DEFERRED` or `IN_PROGRESS`, otherwise `ERR_SITE_WINDOW_CONFLICT` (409)."

        The second window opens at the exact instant the first one closes. Under
        half-open semantics the two share no interior time, so the booking is accepted
        and SCHEDULED.

        Design: Difficulty/resource_temporal_overlap/site_windows_touch_at_boundary_but_overlap_is_refused
        """
        first = self._first_window(base_world)

        touching = validate_success(
            api.create_event(
                self._payload(base_world, "2026-08-22T00:00:00Z", "2026-08-24T00:00:00Z"),
                AGRONOMIST_HEADERS,
            ),
            201,
        )

        assert_instant_equals(touching["window_start"], first["window_end"])
        assert touching["status"] == C.EVENT_SCHEDULED

    def test_window_sharing_interior_time_is_refused(self, api, base_world):
        """PRD §2.7: "**Priority 42 — window overlap.** The requested half-open window does not overlap another application event on the same site whose `status` is `SCHEDULED`, `WEATHER_HOLD`, `DEFERRED` or `IN_PROGRESS`, otherwise `ERR_SITE_WINDOW_CONFLICT` (409)."

        A third window from 08-23 to 08-25 shares interior time with the touching
        08-22 to 08-24 booking and is refused for window conflict, leaving the site with
        exactly the two accepted events and reserving none of the batch's tonnage.

        Design: Difficulty/resource_temporal_overlap/site_windows_touch_at_boundary_but_overlap_is_refused
        """
        self._first_window(base_world)
        validate_success(
            api.create_event(
                self._payload(base_world, "2026-08-22T00:00:00Z", "2026-08-24T00:00:00Z"),
                AGRONOMIST_HEADERS,
            ),
            201,
        )

        response = api.create_event(
            self._payload(base_world, "2026-08-23T00:00:00Z", "2026-08-25T00:00:00Z"),
            AGRONOMIST_HEADERS,
        )
        validate_error(response, ERR_SITE_WINDOW_CONFLICT)

        _, meta = validate_paginated(
            api.list_events(OFFICER_HEADERS, {"site_id": base_world.site_id})
        )
        assert meta["total_count"] == 2
        assert_dry_tons(
            base_world.build.read_batch(base_world.batch_id)["unallocated_dry_tons"],
            60.000,
        )


class TestLoadoutBaysAreClosedIntervals:
    @staticmethod
    def _two_touching_tickets(world):
        build = world.build
        event = build.event(
            world.site_id,
            world.batch_id,
            world.agreement_id,
            window_start="2026-08-20T00:00:00Z",
            window_end="2026-08-21T00:00:00Z",
            acres_treated=80.0,
            planned_dry_tons=80.000,
        )
        build.set_clock("2026-08-20T06:00:00Z")
        build.start(event["id"])
        first = build.haul_ticket(
            event["id"],
            truck_id="T-1",
            wet_tons=100.00,
            depart_at="2026-08-20T08:00:00Z",
            return_at="2026-08-20T10:00:00Z",
            odometer_miles=30.0,
        )
        second = build.haul_ticket(
            event["id"],
            truck_id="T-2",
            wet_tons=100.00,
            depart_at="2026-08-20T10:00:00Z",
            return_at="2026-08-20T12:00:00Z",
            odometer_miles=30.0,
        )
        return event, first, second

    def test_third_truck_finds_both_bays_occupied_at_the_touching_instant(
        self, api, base_world
    ):
        """PRD §3.8: "The count of existing tickets across the whole facility whose closed interval shares any instant with the requested interval must be strictly less than the facility's `loadout_bay_count`, otherwise `ERR_LOADOUT_BAY_CAPACITY`."

        The second ticket departs at the exact instant the first returns and is still
        accepted, because closed intervals put only one bay in use at that moment. A
        third truck departing 10:00 then overlaps both of them and is refused: the plant
        has two bays and both are counted as occupied at the shared instant.

        Design: Difficulty/resource_temporal_overlap/loadout_bays_treat_touching_intervals_as_occupied
        """
        event, _, second = self._two_touching_tickets(base_world)
        assert_instant_equals(second["depart_at"], "2026-08-20T10:00:00Z")

        response = api.create_haul_ticket(
            event["id"],
            F.haul_ticket_payload(
                truck_id="T-3",
                wet_tons=100.00,
                depart_at="2026-08-20T10:00:00Z",
                return_at="2026-08-20T11:00:00Z",
                odometer_miles=30.0,
            ),
            make_operator_headers(),
        )
        validate_error(response, ERR_LOADOUT_BAY_CAPACITY)

        _, meta = validate_paginated(
            api.list_haul_tickets(OFFICER_HEADERS, {"event_id": event["id"]})
        )
        assert meta["total_count"] == 2

    def test_a_truck_touching_only_one_ticket_is_accepted(self, api, base_world):
        """PRD §3.8: "Loadout bay occupancy is a **closed** interval from `depart_at` to `return_at` inclusive, so two tickets that merely touch at an endpoint **do** occupy a bay at the same instant."

        A fourth truck departing at 12:00 shares its boundary instant with only the
        second ticket, so one of the two bays is free and the ticket is accepted; the
        refused third ticket left the event IN_PROGRESS with no applied tonnage yet.

        Design: Difficulty/resource_temporal_overlap/loadout_bays_treat_touching_intervals_as_occupied
        """
        event, _, _ = self._two_touching_tickets(base_world)
        api.create_haul_ticket(
            event["id"],
            F.haul_ticket_payload(
                truck_id="T-3",
                wet_tons=100.00,
                depart_at="2026-08-20T10:00:00Z",
                return_at="2026-08-20T11:00:00Z",
                odometer_miles=30.0,
            ),
            make_operator_headers(),
        )

        current_event = base_world.build.read_event(event["id"])
        assert current_event["status"] == C.EVENT_IN_PROGRESS
        assert_wet_tons(current_event["applied_wet_tons"], 0.00)

        fourth = validate_success(
            api.create_haul_ticket(
                event["id"],
                F.haul_ticket_payload(
                    truck_id="T-4",
                    wet_tons=100.00,
                    depart_at="2026-08-20T12:00:00Z",
                    return_at="2026-08-20T13:00:00Z",
                    odometer_miles=30.0,
                ),
                make_operator_headers(),
            ),
            201,
        )
        assert fourth["truck_id"] == "T-4"
