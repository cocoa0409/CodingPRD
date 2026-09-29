"""The two optimistic-concurrency guards, the cumulative threshold that decides
whether a cascade hop fires at all, and the immediacy of the whole cascade.
"""

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.factories import (
    apply_payload,
    clearance_allocation_payload,
    markdown_plan_payload,
    season_transition_payload,
)


class TestStaleItemVersionBlocksThePlanCreate:
    """A fifth sales week invalidates the version the client is holding."""

    def test_the_plan_create_is_refused_on_the_stale_version(self, api, analyst):
        """PRD 2.6: "If that value does not equal the item's current `version` — because a
        sales week was posted, an execution was applied or rolled back, a disposition order
        was created, cancelled or settled, or an earlier plan create already bumped it —
        the create is rejected with `ERR_STALE_ITEM_VERSION` (HTTP 412) and no plan is
        written."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_item_version_blocks_the_plan_create
        """
        sc = fx.certified_scenario(api)
        stale_version = fx.read_item(api, sc.item["id"])["version"]

        fx.post_sales_week(api, sc.item["id"], "2026-10-03", 20, 4499)
        item = fx.read_item(api, sc.item["id"])
        assert item["version"] == stale_version + 1
        assert item["sample_weeks"] == 5
        assert item["units_sold_total"] == 277

        response = api.create_markdown_plan(
            markdown_plan_payload(
                sc.season["id"], sc.item["id"], sc.estimate["id"], stale_version
            ),
            analyst,
        )
        validate_error(response, "ERR_STALE_ITEM_VERSION", 412)

        _rows, meta = validate_paginated(
            api.list_markdown_plans(analyst, {"item_id": sc.item["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_refreshed_version_carries_the_new_aggregates_into_the_plan(
        self, api, analyst
    ):
        """The fifth week lifts sell-through past the slow-seller line, so the item is no
        longer `AGING` and the base depth drops from 15.00 to 5.00. PRD 3.3: "An item counts
        as a slow seller when its `sell_through_pct` is strictly below 45.00 percent and it
        has been on hand for at least six weeks." PRD 3.4: "The inventory-pressure addend
        charges 1.50 percent for each week of supply above a four-week target: take the
        item's `weeks_of_supply` less 4.00, floor that difference at zero so a well-covered
        item contributes nothing, multiply by 1.50, round half up to two decimals, and cap
        the result at 15.00 percent."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_item_version_blocks_the_plan_create
        """
        sc = fx.certified_scenario(api)
        stale_version = fx.read_item(api, sc.item["id"])["version"]
        fx.post_sales_week(api, sc.item["id"], "2026-10-03", 20, 4499)
        validate_error(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], stale_version
                ),
                analyst,
            ),
            "ERR_STALE_ITEM_VERSION",
            412,
        )

        item = fx.read_item(api, sc.item["id"])
        assert item["sell_through_pct"] == 46.17
        assert item["weeks_of_supply"] == 5.83
        assert item["lifecycle_stage"] == "CORE"

        plan = validate_success(
            api.create_markdown_plan(
                markdown_plan_payload(
                    sc.season["id"], sc.item["id"], sc.estimate["id"], item["version"]
                ),
                analyst,
            ),
            201,
        )

        assert plan["status"] == "DRAFT"
        assert plan["ladder_step_count"] == 0
        assert plan["recommended_depth_pct"] == 10.28


class TestStaleSeasonVersionBlocksTheAllocation:
    """The season's own transition is what makes the caller's view stale."""

    def test_the_allocation_is_refused_on_the_version_not_on_the_status(
        self, api, analyst, director
    ):
        """PRD 2.6: "A request that allocates clearance floor space against a season must
        carry `expected_season_version` holding the `version` of the target `Season` as the
        client last read it, and a mismatch is rejected with `ERR_STALE_SEASON_VERSION`
        (HTTP 412) with no reservation created."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_season_version_blocks_the_clearance_allocation
        """
        sc = fx.approved_plan_scenario(api, effective_date="2026-11-16")
        stale_version = fx.read_season(api, sc.season["id"])["version"]

        moved = validate_success(
            api.transition_season(
                sc.season["id"], season_transition_payload("EXIT_WINDOW"), director
            )
        )
        assert moved["status"] == "EXIT_WINDOW"
        assert moved["version"] == stale_version + 1

        response = api.create_clearance_allocation(
            sc.season["id"],
            clearance_allocation_payload(sc.plan["id"], 600, stale_version),
            analyst,
        )
        validate_error(response, "ERR_STALE_SEASON_VERSION", 412)

        _rows, meta = validate_paginated(
            api.list_clearance_reservations(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 0
        assert fx.read_season(api, sc.season["id"])["reserved_clearance_units"] == 0

    def test_the_retry_with_the_refreshed_version_draws_the_waterfall(
        self, api, analyst, director
    ):
        """PRD 3.7: "The waterfall then walks that order, and for each store in turn takes
        the smaller of the store's `available_clearance_units` and the units still
        unplaced, creating one reservation per filled store with that quantity in
        `reserved_units`, with `allocation_rank` counting 1, 2, 3 and so on in fill order,
        and with `status` `RESERVED`; the walk stops as soon as nothing remains to place."

        Design: Corner/cross_cutting_complexity_layers/stale_expected_season_version_blocks_the_clearance_allocation
        """
        sc = fx.approved_plan_scenario(api, effective_date="2026-11-16")
        stale_version = fx.read_season(api, sc.season["id"])["version"]
        fx.transition_season(api, sc.season["id"], "EXIT_WINDOW")
        validate_error(
            api.create_clearance_allocation(
                sc.season["id"],
                clearance_allocation_payload(sc.plan["id"], 600, stale_version),
                analyst,
            ),
            "ERR_STALE_SEASON_VERSION",
            412,
        )

        fresh_version = fx.read_season(api, sc.season["id"])["version"]
        rows = validate_success(
            api.create_clearance_allocation(
                sc.season["id"],
                clearance_allocation_payload(sc.plan["id"], 600, fresh_version),
                analyst,
            ),
            201,
        )

        assert len(rows) == 2
        assert rows[0]["store_id"] == sc.store_0202["id"]
        assert rows[0]["reserved_units"] == 500
        assert rows[1]["store_id"] == sc.store_0101["id"]
        assert rows[1]["reserved_units"] == 100

        season = fx.read_season(api, sc.season["id"])
        assert season["reserved_clearance_units"] == 600
        assert season["status"] == "EXIT_WINDOW"


class TestOneUnitBelowTheExitWindowTrigger:
    """The threshold hop is the only hop of the cascade that does not fire."""

    def test_committing_599_units_leaves_the_season_active(self, api, analyst):
        """PRD 3.7: "Whenever a reservation entering `COMMITTED` lifts the season's
        `committed_clearance_units` to at least 60 percent of the season's
        `exit_units_target` — that is, to at least the `exit_units_target` multiplied by
        60.00, divided by 100 and rounded half up to a whole unit — a season still in
        `ACTIVE` moves `ACTIVE → EXIT_WINDOW` on the spot."

        Design: Corner/cross_cutting_complexity_layers/committed_units_one_below_the_trigger_leave_the_season_active
        """
        sc = fx.approved_plan_scenario(api)
        reservations = fx.allocate_clearance(api, sc.season["id"], sc.plan["id"], 599)
        assert [row["reserved_units"] for row in reservations] == [500, 99]
        sc = fx.scheduled_execution_scenario(api, sc)
        sc = fx.verified_execution_scenario(api, sc)
        sc = fx.applied_execution_scenario(api, sc)

        for reservation in reservations:
            stored = fx.read_reservation(api, reservation["id"])
            assert stored["status"] == "COMMITTED"

        season = fx.read_season(api, sc.season["id"])
        assert season["committed_clearance_units"] == 599
        assert season["reserved_clearance_units"] == 0
        assert season["status"] == "ACTIVE"

    def test_the_rest_of_the_cascade_ran_in_full(self, api, analyst):
        """PRD 3.6: "Hop three re-runs lifecycle classification, which for a permanently
        marked item carries the lifecycle dimension into `CLEARANCE`."

        Design: Corner/cross_cutting_complexity_layers/committed_units_one_below_the_trigger_leave_the_season_active
        """
        sc = fx.approved_plan_scenario(api)
        fx.allocate_clearance(api, sc.season["id"], sc.plan["id"], 599)
        sc = fx.scheduled_execution_scenario(api, sc)
        sc = fx.verified_execution_scenario(api, sc)
        sc = fx.applied_execution_scenario(api, sc)

        item = fx.read_item(api, sc.item["id"])
        assert item["markdown_state"] == "PERM_MARKED"
        assert item["lifecycle_stage"] == "CLEARANCE"

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["gross_markdown_cents"] == 225600


class TestTheWholeCascadeIsVisibleImmediately:
    """No hop lags behind the request that caused it."""

    def test_the_apply_response_already_carries_the_frozen_money_line(self, api, analyst):
        """PRD 3.6: "The apply itself computes the markdown liability line and freezes it:
        `per_unit_markdown_cents` is the item's `current_retail_cents` less the rung's
        `price_cents`, `line_markdown_cents` is that per-unit amount multiplied by
        `units_in_scope`, and `price_cents_applied` records the rung price written onto the
        item."

        Design: Corner/consistency_model/every_cascade_hop_is_visible_in_the_same_request
        """
        sc = fx.verified_execution_scenario(api)
        fx.set_clock(api, "2026-10-19T00:00:00Z")

        applied = validate_success(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst)
        )

        assert applied["status"] == "APPLIED"
        assert applied["per_unit_markdown_cents"] == 1128
        assert applied["line_markdown_cents"] == 225600
        assert applied["price_cents_applied"] == 3871
        assert applied["applied_at"] == "2026-10-19T00:00:00.000Z"

    def test_every_neighbour_is_correct_on_the_very_next_read(self, api, analyst):
        """PRD 3.6: "Hop one rewrites the item's `current_retail_cents` to the rung's
        `price_cents` and moves the rung `SCHEDULED → EXECUTED`." The plan side is settled
        in the same request: "Alongside the cascade, the plan's `gross_markdown_cents` grows
        by `line_markdown_cents`, its `net_markdown_cents` is recomputed, and the plan moves
        `APPROVED → EXECUTING` on its first applied execution."

        Design: Corner/consistency_model/every_cascade_hop_is_visible_in_the_same_request
        """
        sc = fx.verified_execution_scenario(api)
        fx.set_clock(api, "2026-10-19T00:00:00Z")
        validate_success(
            api.apply_zone_execution(sc.execution["id"], apply_payload(), analyst)
        )

        item = fx.read_item(api, sc.item["id"])
        assert item["current_retail_cents"] == 3871
        assert item["markdown_state"] == "PERM_MARKED"
        assert item["lifecycle_stage"] == "CLEARANCE"
        assert item["permanent_markdown_reserve_cents"] == 225600
        assert item["on_hand_units"] == 343

        plan = fx.read_plan(api, sc.plan["id"])
        assert plan["status"] == "COMPLETED"
        assert plan["gross_markdown_cents"] == 225600
        assert plan["vendor_funded_cents"] == 0
        assert plan["net_markdown_cents"] == 225600

        assert fx.read_step(api, sc.step1["id"])["status"] == "EXECUTED"
