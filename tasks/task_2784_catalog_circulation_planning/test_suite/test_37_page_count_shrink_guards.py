"""A shrinking book may not strand space that is already committed.

Two independent reasons to refuse the same reduction are separated. A single
40-inch placement parked on page 9 blocks a move to eight pages even though 40 inches
would fit inside the smaller capacity many times over, and a drop carrying 792
allocated inches is refused a capacity of 704 as well. In both cases the identical
PATCH succeeds once the offending placement is removed, and the removal is observed
through the drop the DELETE returns.
"""
from test_helpers import (
    CLOCK_START,
    PLANNER,
    assert_drop_space_conserved,
    fetch_drop,
    iso_utc,
    new_drop,
    new_page_placement,
    new_plan,
    new_season,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _a_ten_page_drop() -> dict:
    """The default season leaves `usable_sq_in_per_page` at 88, so a ten-page book
    has a square-inch capacity of 880."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=10
    )
    assert drop["square_inch_capacity"] == 880
    return {"season": season, "plan": plan, "drop": drop}


def _one_small_placement_parked_on_the_last_page() -> dict:
    """40 inches on page 9 — trivially small, but beyond an eight-page book."""
    world = _a_ten_page_drop()
    world["placement"] = new_page_placement(
        world["drop"]["id"],
        product_sku="SKU-LAST",
        product_name="Cast pan",
        unit_price_cents=8900,
        unit_cogs_cents=3700,
        demand_per_sq_inch_cents=4100,
        page_number=9,
        sq_in_offset=0,
        square_inches=40,
        placement_position="INSIDE",
    )
    return world


def _nine_full_pages_of_placements() -> dict:
    """One 88-inch placement on each of pages 1 through 9, so 792 of the drop's 880
    inches are committed and an eight-page capacity of 704 could not hold them."""
    world = _a_ten_page_drop()
    world["placements"] = [
        new_page_placement(
            world["drop"]["id"],
            product_sku=f"SKU-{page}",
            product_name=f"Item {page}",
            unit_price_cents=8900,
            unit_cogs_cents=3700,
            demand_per_sq_inch_cents=4100,
            page_number=page,
            sq_in_offset=0,
            square_inches=88,
            placement_position="INSIDE",
        )
        for page in range(1, 10)
    ]
    return world


class TestAnOccupiedPageBeyondTheNewCount:
    def test_a_forty_inch_placement_on_page_nine_blocks_an_eight_page_book(self, api):
        """PRD §3.4: "A page-count reduction may never strand space that is already
        committed: shrinking `page_count` below the square inches already allocated, or
        below the highest occupied `page_number`, is rejected with
        `ERR_DROP_SQ_IN_CAPACITY_EXCEEDED` rather than silently producing a negative
        remainder."

        Design: Corner/validations/page_count_may_not_shrink_below_the_space_already_allocated
        """
        world = _one_small_placement_parked_on_the_last_page()
        drop_id = world["drop"]["id"]

        response = api.update_drop(drop_id, {"page_count": 8}, PLANNER)
        validate_error(response, "ERR_DROP_SQ_IN_CAPACITY_EXCEEDED", 422)

        drop = fetch_drop(drop_id)
        assert drop["page_count"] == 10
        assert drop["square_inch_capacity"] == 880
        assert drop["allocated_square_inches"] == 40
        assert drop["unallocated_square_inches"] == 840
        assert_drop_space_conserved(drop)

    def test_the_delete_returns_the_reconciled_drop_and_unblocks_the_shrink(
        self, api
    ):
        """PRD §3.4: "Removing a placement is the exact inverse: its `square_inches`
        return to `unallocated_square_inches` and leave `allocated_square_inches` with
        no drift, and the drop's `version` increments by one. The removal deliberately
        returns the parent drop rather than the deleted placement, so the reconciled
        square-inch figures are directly observable in the response."

        Design: Corner/validations/page_count_may_not_shrink_below_the_space_already_allocated
        """
        world = _one_small_placement_parked_on_the_last_page()
        drop_id = world["drop"]["id"]
        validate_error(
            api.update_drop(drop_id, {"page_count": 8}, PLANNER),
            "ERR_DROP_SQ_IN_CAPACITY_EXCEEDED",
            422,
        )

        after_delete = validate_success(
            api.delete_page_placement(world["placement"]["id"], PLANNER), 200
        )
        assert after_delete["id"] == drop_id
        assert after_delete["allocated_square_inches"] == 0
        assert after_delete["unallocated_square_inches"] == 880
        assert_drop_space_conserved(after_delete)

        _, meta = validate_paginated(api.list_page_placements(drop_id, PLANNER))
        assert meta["total_count"] == 0

        shrunk = validate_success(
            api.update_drop(drop_id, {"page_count": 8}, PLANNER), 200
        )
        assert shrunk["page_count"] == 8
        assert shrunk["square_inch_capacity"] == 704
        assert shrunk["weight_oz_milli"] == 320
        assert shrunk["unallocated_square_inches"] == 704
        assert_drop_space_conserved(shrunk)


class TestAllocatedInchesAboveTheNewCapacity:
    def test_seven_hundred_and_ninety_two_inches_will_not_fit_in_eight_pages(
        self, api
    ):
        """PRD §3.4: "A page-count reduction may never strand space that is already
        committed: shrinking `page_count` below the square inches already allocated, or
        below the highest occupied `page_number`, is rejected with
        `ERR_DROP_SQ_IN_CAPACITY_EXCEEDED` rather than silently producing a negative
        remainder."

        Design: Corner/validations/page_count_may_not_shrink_below_the_space_already_allocated
        """
        world = _nine_full_pages_of_placements()
        drop_id = world["drop"]["id"]

        before = fetch_drop(drop_id)
        assert before["allocated_square_inches"] == 792
        assert before["unallocated_square_inches"] == 88

        validate_error(
            api.update_drop(drop_id, {"page_count": 8}, PLANNER),
            "ERR_DROP_SQ_IN_CAPACITY_EXCEEDED",
            422,
        )
        assert fetch_drop(drop_id)["page_count"] == 10

    def test_removing_the_last_page_lets_the_book_close_exactly(self, api):
        """PRD §3.4: "Changing `page_count` recomputes `weight_oz_milli`,
        `square_inch_capacity` and `unallocated_square_inches`, then re-runs the drop's
        cost per book at the drop's *current* `cost_basis`, then recomputes the owning
        plan's `planned_cost_cents`, `planned_demand_cents` and
        `planned_contribution_cents`; a plan sitting in `COSTED` falls back to `DRAFT` as
        a result.
        The drop's `version` increments by one."

        Design: Corner/validations/page_count_may_not_shrink_below_the_space_already_allocated
        """
        world = _nine_full_pages_of_placements()
        drop_id = world["drop"]["id"]

        after_delete = validate_success(
            api.delete_page_placement(world["placements"][8]["id"], PLANNER), 200
        )
        assert after_delete["allocated_square_inches"] == 704

        shrunk = validate_success(
            api.update_drop(drop_id, {"page_count": 8}, PLANNER), 200
        )
        assert shrunk["page_count"] == 8
        assert shrunk["square_inch_capacity"] == 704
        assert shrunk["allocated_square_inches"] == 704
        assert shrunk["unallocated_square_inches"] == 0
        assert shrunk["weight_oz_milli"] == 320
        assert_drop_space_conserved(shrunk)

        rows, meta = validate_paginated(api.list_page_placements(drop_id, PLANNER))
        assert meta["total_count"] == 8
        assert [row["page_number"] for row in rows] == list(range(1, 9))
