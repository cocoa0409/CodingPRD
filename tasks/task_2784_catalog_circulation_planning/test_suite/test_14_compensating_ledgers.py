"""Undo paths that must return exactly what was taken.

Two different conserved quantities, two different undo mechanics. Retiring an
allocated line credits cents back to a two-part budget identity and drags the
plan's derived status back with the money. Removing a placement is a hard
delete that returns square inches to a two-part capacity identity, and the
freed span has to be immediately re-lettable.
"""
from test_helpers import (
    CLOCK_START,
    PLANNER,
    PLANNER_1,
    allocate,
    assert_drop_space_conserved,
    assert_line_zeroed,
    assert_page_placement,
    assert_plan_budget_conserved,
    cost_plan,
    create_page_placement_payload,
    fetch_drop,
    fetch_line,
    fetch_plan,
    get_success_data,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_page_placement,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    validate_paginated,
)


def _costed_plan_carrying_two_allocated_lines() -> dict:
    """A COSTED plan whose single drop carries an S_A line for 10000 books and
    an S_B line for 8000, a total of 18000 — below the rebate band, so the
    provisional and the final cost per book are both 236."""
    set_clock(CLOCK_START)
    season = new_season()
    seg_a = new_segment(season["id"], segment_code="S_A")
    seg_b = new_segment(season["id"], segment_code="S_B")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line_one = new_housefile_line(drop["id"], seg_a["id"], requested_quantity=10000)
    line_two = new_housefile_line(drop["id"], seg_b["id"], requested_quantity=8000)
    allocated = allocate(drop["id"])
    costed = cost_plan(plan["id"], PLANNER_1)

    return {
        "season": season,
        "seg_a": seg_a,
        "seg_b": seg_b,
        "plan": plan,
        "drop": allocated,
        "costed": costed,
        "line_one": line_one,
        "line_two": line_two,
    }


class TestVoidingALineCreditsTheBudgetExactly:
    def test_the_credit_is_the_frozen_figure_and_the_identity_never_drifts(self, api):
        """PRD §3.5: "Retiring an allocated line takes it `ALLOCATED → VOIDED`
        and credits the plan's `committed_cost_cents` back by *exactly* the
        line's `committed_cost_cents` before zeroing that field on the line,
        then recomputes `uncommitted_budget_cents`; the compensation is exact in
        both directions, so the budget identity of §2.7 holds before and after
        with no drift."

        Design: Difficulty/compensating_invariant/voiding_a_line_restores_the_plan_budget_cents_exactly
        """
        world = _costed_plan_carrying_two_allocated_lines()
        plan_id = world["plan"]["id"]

        assert world["plan"]["budget_cents"] == 20000000
        assert world["drop"]["provisional_cost_per_book_cents"] == 236
        assert world["drop"]["cost_per_book_cents"] == 236

        before_one = fetch_line(world["line_one"]["id"])
        before_two = fetch_line(world["line_two"]["id"])
        assert before_one["committed_cost_cents"] == 2360000
        assert before_two["committed_cost_cents"] == 1888000
        assert before_one["contribution_cents"] == 2457400
        assert before_two["contribution_cents"] == 1965920

        before_plan = world["costed"]
        assert before_plan["status"] == "COSTED"
        assert before_plan["committed_cost_cents"] == 4248000
        assert before_plan["uncommitted_budget_cents"] == 15752000
        assert before_plan["planned_contribution_cents"] == 4423320
        assert_plan_budget_conserved(before_plan)

        voided = get_success_data(
            api.void_line(
                world["line_two"]["id"],
                PLANNER,
                {"reason": "segment pulled from the book"},
            )
        )
        assert voided["status"] == "VOIDED"
        assert voided["committed_cost_cents"] == 0
        assert voided["contribution_cents"] == 0
        assert_line_zeroed(voided)

        after_plan = fetch_plan(plan_id)
        assert after_plan["committed_cost_cents"] == 2360000
        assert after_plan["uncommitted_budget_cents"] == 17640000
        assert_plan_budget_conserved(after_plan)
        assert (
            after_plan["uncommitted_budget_cents"]
            - before_plan["uncommitted_budget_cents"]
            == 1888000
        )

    def test_the_sibling_line_is_untouched_and_the_plan_falls_back_to_draft(self, api):
        """PRD §3.5: "Either way the drop's `requested_quantity_total`, its
        `planned_quantity` and its cost per book are recomputed, then the plan's
        roll-up figures, with a `COSTED` plan falling back to `DRAFT`; the
        line's `version` and the drop's `version` each increment by one."

        Design: Difficulty/compensating_invariant/voiding_a_line_restores_the_plan_budget_cents_exactly
        """
        world = _costed_plan_carrying_two_allocated_lines()
        plan_id = world["plan"]["id"]

        get_success_data(
            api.void_line(
                world["line_two"]["id"],
                PLANNER,
                {"reason": "segment pulled from the book"},
            )
        )

        sibling = fetch_line(world["line_one"]["id"])
        assert sibling["status"] == "ALLOCATED"
        assert sibling["committed_cost_cents"] == 2360000
        assert sibling["unit_cost_cents"] == 236
        assert sibling["allocated_quantity"] == 10000
        assert sibling["contribution_cents"] == 2457400

        drop = fetch_drop(world["drop"]["id"])
        assert drop["requested_quantity_total"] == 10000
        assert drop["planned_quantity"] == 10000
        assert drop["cost_per_book_cents"] == 236

        plan = fetch_plan(plan_id)
        assert plan["planned_cost_cents"] == 2360000
        assert plan["planned_demand_cents"] == 11470000
        assert plan["planned_contribution_cents"] == 2457400
        assert plan["status"] == "DRAFT"


def _drop_with_two_adjacent_placements() -> dict:
    """A 64-page drop — 5632 square inches of capacity — whose page 1 carries
    two touching 44-square-inch placements, [0, 44) and [44, 88)."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    first = new_page_placement(
        drop["id"],
        product_sku="SKU-1",
        product_name="Wool throw",
        unit_price_cents=12900,
        unit_cogs_cents=5400,
        demand_per_sq_inch_cents=4200,
        page_number=1,
        sq_in_offset=0,
        square_inches=44,
        placement_position="FRONT_COVER",
    )
    second = new_page_placement(
        drop["id"],
        product_sku="SKU-2",
        product_name="Cast iron pan",
        unit_price_cents=8900,
        unit_cogs_cents=3900,
        demand_per_sq_inch_cents=3100,
        page_number=1,
        sq_in_offset=44,
        square_inches=44,
        placement_position="INSIDE",
    )
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop": drop,
        "line": line,
        "first": first,
        "second": second,
    }


class TestRemovingAPlacementRestoresTheSquareInches:
    def test_the_delete_returns_the_drop_with_the_space_moved_back(self, api):
        """PRD §3.4: "Removing a placement is the exact inverse: its
        `square_inches` return to `unallocated_square_inches` and leave
        `allocated_square_inches` with no drift, and the drop's `version`
        increments by one."

        Design: Difficulty/compensating_invariant/deleting_a_placement_restores_the_drop_square_inches
        """
        world = _drop_with_two_adjacent_placements()
        drop_id = world["drop"]["id"]
        first_id = world["first"]["id"]

        assert world["drop"]["square_inch_capacity"] == 5632
        assert world["first"]["forecast_space_demand_cents"] == 332640
        assert world["first"]["space_productivity_cents_per_sq_in"] == 7560
        assert world["second"]["forecast_space_demand_cents"] == 136400
        assert world["second"]["space_productivity_cents_per_sq_in"] == 3100

        before = fetch_drop(drop_id)
        assert before["allocated_square_inches"] == 88
        assert before["unallocated_square_inches"] == 5544
        assert_drop_space_conserved(before)

        after = get_success_data(api.delete_page_placement(first_id, PLANNER))
        assert after["allocated_square_inches"] == 44
        assert after["unallocated_square_inches"] == 5588
        assert_drop_space_conserved(after)
        assert before["allocated_square_inches"] - after["allocated_square_inches"] == 44
        assert (
            after["unallocated_square_inches"] - before["unallocated_square_inches"]
            == 44
        )
        assert after["version"] == before["version"] + 1

        placements, meta = validate_paginated(
            api.list_page_placements(drop_id, PLANNER)
        )
        assert meta["total_count"] == 1
        assert first_id not in [row["id"] for row in placements]

    def test_the_freed_span_is_immediately_re_lettable_to_another_sku(self, api):
        """PRD §3.4: "A successful placement adds its `square_inches` to the
        drop's `allocated_square_inches` and subtracts the same amount from
        `unallocated_square_inches`, and increments the drop's `version` by
        one."

        Design: Difficulty/compensating_invariant/deleting_a_placement_restores_the_drop_square_inches
        """
        world = _drop_with_two_adjacent_placements()
        drop_id = world["drop"]["id"]

        get_success_data(api.delete_page_placement(world["first"]["id"], PLANNER))

        survivor_id = world["second"]["id"]
        placements, _meta = validate_paginated(
            api.list_page_placements(drop_id, PLANNER)
        )
        survivor = next(row for row in placements if row["id"] == survivor_id)
        assert survivor["sq_in_offset"] == 44
        assert survivor["square_inches"] == 44
        assert survivor["forecast_space_demand_cents"] == 136400
        assert survivor["space_productivity_cents_per_sq_in"] == 3100

        re_let = get_success_data(
            api.create_page_placement(
                drop_id,
                create_page_placement_payload(
                    product_sku="SKU-9",
                    product_name="Merino scarf",
                    unit_price_cents=7900,
                    unit_cogs_cents=3100,
                    demand_per_sq_inch_cents=4200,
                    page_number=1,
                    sq_in_offset=0,
                    square_inches=44,
                    placement_position="FRONT_COVER",
                ),
                PLANNER,
            )
        )
        assert_page_placement(re_let)
        assert re_let["page_number"] == 1
        assert re_let["sq_in_offset"] == 0
        assert re_let["square_inches"] == 44
        assert re_let["forecast_space_demand_cents"] == 332640

        drop = fetch_drop(drop_id)
        assert drop["allocated_square_inches"] == 88
        assert drop["unallocated_square_inches"] == 5544
        assert_drop_space_conserved(drop)
