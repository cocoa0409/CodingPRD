"""Two executions competing for the same shelf or the same signage rhythm,
where the window arithmetic decides which one is admitted.
"""

from test_helpers import fixtures as fx
from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers.api_errors import ApiErrorId
from test_helpers.factories import zone_execution_payload


def _two_rung_plan_with_a_store_execution(api):
    sc = fx.planned_scenario(api)
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-12-14", 35.00)
    fx.submit_plan(api, sc.plan["id"])
    sc["plan"] = fx.approve_plan(api, sc.plan["id"])
    sc["exec_s1"] = fx.schedule_execution(
        api,
        sc.plan["id"],
        sc.step1["id"],
        sc.west_zone["id"],
        "STORE",
        "2026-11-16",
        60,
        store_id=sc.store_0101["id"],
    )
    return sc


class TestStoreOccupancyWindows:
    """Touching windows coexist; intersecting ones do not."""

    def test_the_rungs_tile_the_calendar_as_half_open_windows(self, api):
        """PRD 3.5: "Each new rung also fixes the ladder's occupancy calendar: a
        rung's `window_end_date_exclusive` is set to the plan's `exit_date_target`
        when it is the last rung, and appending a further rung rewrites the previous
        rung's `window_end_date_exclusive` to the new rung's `effective_date`, so the
        rungs tile the plan's calendar as half-open windows."

        Design: Difficulty/resource_temporal_overlap/store_occupancy_touching_windows_allowed_then_overlap_rejected
        """
        sc = _two_rung_plan_with_a_store_execution(api)

        assert fx.read_step(api, sc.step1["id"])["window_end_date_exclusive"] == (
            "2026-12-14"
        )
        assert fx.read_step(api, sc.step2["id"])["window_end_date_exclusive"] == (
            "2027-01-15"
        )

    def test_an_execution_starting_where_the_previous_window_ends_is_accepted(
        self, api, analyst
    ):
        """PRD 3.6: "Windows that merely touch do not intersect — a new execution
        starting exactly on the day an existing window ends is accepted."

        Design: Difficulty/resource_temporal_overlap/store_occupancy_touching_windows_allowed_then_overlap_rejected
        """
        sc = _two_rung_plan_with_a_store_execution(api)

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"],
                    sc.step2["id"],
                    sc.west_zone["id"],
                    "STORE",
                    "2026-12-14",
                    60,
                    sc.store_0101["id"],
                ),
                analyst,
            ),
            201,
        )

        assert execution["status"] == "SCHEDULED"
        assert execution["signage_due_date"] == "2026-12-07"

    def test_a_second_execution_inside_the_same_window_is_refused(self, api, analyst):
        """PRD 3.6: "Store-scope executions must not double-book a shelf: a
        store-scope execution occupies the half-open window that runs from its rung's
        `effective_date` up to, but not including, that rung's
        `window_end_date_exclusive`, scoped to the pair of item and store, and a new
        store-scope execution whose window intersects the window of a `SCHEDULED` or
        `APPLIED` execution for the same item and store is refused with
        `ERR_STEP_WINDOW_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/store_occupancy_touching_windows_allowed_then_overlap_rejected
        """
        sc = _two_rung_plan_with_a_store_execution(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "STORE",
            "2026-12-14", 60, store_id=sc.store_0101["id"],
        )

        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step1["id"], sc.west_zone["id"], "STORE",
                "2026-11-16", 60, sc.store_0101["id"],
            ),
            analyst,
        )

        validate_error(response, ApiErrorId.STEP_WINDOW_OVERLAP, 409)

    def test_the_shelf_keeps_exactly_the_two_admitted_executions(self, api, analyst):
        """PRD 2.7 rule 23: "Store-scope occupancy overlap on execution scheduling,
        reported as `ERR_STEP_WINDOW_OVERLAP` (409)."

        Design: Difficulty/resource_temporal_overlap/store_occupancy_touching_windows_allowed_then_overlap_rejected
        """
        sc = _two_rung_plan_with_a_store_execution(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "STORE",
            "2026-12-14", 60, store_id=sc.store_0101["id"],
        )
        api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step1["id"], sc.west_zone["id"], "STORE",
                "2026-11-16", 60, sc.store_0101["id"],
            ),
            analyst,
        )

        rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"store_id": sc.store_0101["id"]})
        )

        assert meta["total_count"] == 2
        assert sum(row["units_in_scope"] for row in rows) == 120
        assert fx.read_item(api, sc.item["id"])["on_hand_units"] == 343


def _two_zones_with_different_leads(api):
    sc = fx.planned_scenario(api)
    sc["north_zone"] = fx.create_region_zone(
        api,
        sc.chain_zone["id"],
        zone_code="REGION-NORTH",
        region_code="NORTH",
        signage_lead_days=15,
    )
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-11-30", 35.00)
    fx.submit_plan(api, sc.plan["id"])
    sc["plan"] = fx.approve_plan(api, sc.plan["id"])
    sc["exec_w1"] = fx.schedule_execution(
        api, sc.plan["id"], sc.step1["id"], sc.west_zone["id"], "ZONE",
        "2026-11-16", 60,
    )
    sc["exec_n2"] = fx.schedule_execution(
        api, sc.plan["id"], sc.step2["id"], sc.north_zone["id"], "ZONE",
        "2026-11-30", 60,
    )
    return sc


class TestZoneSignageConflictIsScopedToOneZone:
    """The same 14-day gap clears one zone's lead and misses another's."""

    def test_the_same_gap_clears_the_shorter_lead(self, api, analyst):
        """PRD 3.1: "When `signage_lead_days` is omitted it defaults by breadth —
        ten days for a `CHAIN` zone, one week for a `REGION` zone, three days for a
        `STORE` zone — because signage takes longer to reach every door of the chain
        than to reach one region or one shop."

        Design: Difficulty/resource_temporal_overlap/zone_signage_window_conflict_is_scoped_to_one_zone
        """
        sc = _two_zones_with_different_leads(api)

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "ZONE",
                    "2026-11-30", 60,
                ),
                analyst,
            ),
            201,
        )

        assert execution["status"] == "SCHEDULED"
        assert execution["signage_due_date"] == "2026-11-23"

    def test_the_same_gap_misses_the_longer_lead(self, api, analyst):
        """PRD 3.6: "Executions on one item in one zone must also respect the signage
        rhythm: for any two executions on the same `price_zone_id` and item that are
        `SCHEDULED` or `APPLIED`, the gap between their effective dates, measured in
        whole days and ignoring direction, must be at least the zone's
        `signage_lead_days`; a gap exactly equal to that lead is allowed and one day
        less is refused with `ERR_ZONE_SIGNAGE_WINDOW_CONFLICT`."

        Design: Difficulty/resource_temporal_overlap/zone_signage_window_conflict_is_scoped_to_one_zone
        """
        sc = _two_zones_with_different_leads(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "ZONE",
            "2026-11-30", 60,
        )

        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step1["id"], sc.north_zone["id"], "ZONE",
                "2026-11-16", 60,
            ),
            analyst,
        )

        validate_error(response, ApiErrorId.ZONE_SIGNAGE_WINDOW_CONFLICT, 409)

    def test_each_zone_carries_its_own_signage_due_date(self, api):
        """PRD 3.1: "That same number does double duty: it is both the lead time
        required before an execution's effective date in the zone and the minimum
        spacing between two executions on the same item in the zone."

        Design: Difficulty/resource_temporal_overlap/zone_signage_window_conflict_is_scoped_to_one_zone
        """
        sc = _two_zones_with_different_leads(api)

        assert sc.exec_w1["signage_due_date"] == "2026-11-09"
        assert sc.exec_n2["signage_due_date"] == "2026-11-15"

    def test_the_cross_zone_pair_coexists_at_the_same_fourteen_day_gap(
        self, api, analyst
    ):
        """PRD 2.7 rule 24: "Zone spacing on execution scheduling, reported as
        `ERR_ZONE_SIGNAGE_WINDOW_CONFLICT` (409)."

        Design: Difficulty/resource_temporal_overlap/zone_signage_window_conflict_is_scoped_to_one_zone
        """
        sc = _two_zones_with_different_leads(api)
        fx.schedule_execution(
            api, sc.plan["id"], sc.step2["id"], sc.west_zone["id"], "ZONE",
            "2026-11-30", 60,
        )
        api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"], sc.step1["id"], sc.north_zone["id"], "ZONE",
                "2026-11-16", 60,
            ),
            analyst,
        )

        _, west_meta = validate_paginated(
            api.list_zone_executions(analyst, {"price_zone_id": sc.west_zone["id"]})
        )
        _, north_meta = validate_paginated(
            api.list_zone_executions(analyst, {"price_zone_id": sc.north_zone["id"]})
        )

        assert west_meta["total_count"] == 2
        assert north_meta["total_count"] == 1
