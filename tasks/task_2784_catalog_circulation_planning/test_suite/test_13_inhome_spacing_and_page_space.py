"""Two exclusion zones with deliberately different interval semantics.

A segment's mailbox is guarded by a symmetric whole-day buffer around an
in-home date, where exactly the gap is permitted and the buffer is released
when the anchoring line is retired. A page of a book is guarded by half-open
square-inch spans, where touching spans are legal and the exclusion is scoped
to one page number.
"""
from test_helpers import (
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    assert_drop_space_conserved,
    assert_page_placement,
    create_housefile_line_payload,
    create_page_placement_payload,
    fetch_drop,
    fetch_line,
    fetch_season,
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
    validate_error,
    validate_paginated,
)


def _four_drops_around_one_anchored_segment() -> dict:
    """Four future drops on one DRAFT plan, with segment S_A's buffer anchored
    by a PROPOSED line on the 2026-09-15 drop."""
    set_clock(CLOCK_START)
    season = new_season()
    seg_a = new_segment(season["id"], segment_code="S_A")
    seg_b = new_segment(season["id"], segment_code="S_B")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    anchor_drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    edge_drop = new_drop(
        plan["id"], drop_number=2, in_home_date=iso_utc("2026-10-06"), page_count=64
    )
    later_inside_drop = new_drop(
        plan["id"], drop_number=3, in_home_date=iso_utc("2026-09-30"), page_count=64
    )
    earlier_inside_drop = new_drop(
        plan["id"], drop_number=4, in_home_date=iso_utc("2026-08-30"), page_count=64
    )
    anchor_line = new_housefile_line(
        anchor_drop["id"], seg_a["id"], requested_quantity=10000
    )

    return {
        "season": season,
        "seg_a": seg_a,
        "seg_b": seg_b,
        "plan": plan,
        "anchor_drop": anchor_drop,
        "edge_drop": edge_drop,
        "later_inside_drop": later_inside_drop,
        "earlier_inside_drop": earlier_inside_drop,
        "anchor_line": anchor_line,
    }


class TestInHomeSpacingBuffer:
    def test_exactly_the_gap_is_allowed_and_the_buffer_reaches_backwards(self, api):
        """PRD §3.5: "The buffer is symmetric — it applies whether the other drop
        mails before or after this one — and a separation of exactly
        `min_inhome_gap_days` whole days is permitted."

        Design: Difficulty/resource_temporal_overlap/inhome_spacing_is_a_symmetric_day_buffer_around_a_segment
        """
        world = _four_drops_around_one_anchored_segment()
        segment_id = world["seg_a"]["id"]

        season = fetch_season(world["season"]["id"])
        assert season["min_inhome_gap_days"] == 21

        at_the_edge = get_success_data(
            api.create_line(
                world["edge_drop"]["id"],
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            )
        )
        assert at_the_edge["status"] == "PROPOSED"

        validate_error(
            api.create_line(
                world["later_inside_drop"]["id"],
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            ),
            ApiErrorId.ERR_INHOME_SPACING_VIOLATION.value,
            409,
        )

        validate_error(
            api.create_line(
                world["earlier_inside_drop"]["id"],
                create_housefile_line_payload(segment_id, requested_quantity=5000),
                PLANNER,
            ),
            ApiErrorId.ERR_INHOME_SPACING_VIOLATION.value,
            409,
        )

        _lines, meta = validate_paginated(
            api.list_lines(PLANNER, {"drop_id": world["earlier_inside_drop"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_the_buffer_is_per_segment_and_released_by_voiding_the_anchor(self, api):
        """PRD §3.5: "Only lines in status `PROPOSED` or `ALLOCATED`, sitting on
        drops whose `production_status` is not `CANCELLED`, occupy the buffer; a
        `VOIDED` or `SUPPRESSED` line releases it immediately."

        Design: Difficulty/resource_temporal_overlap/inhome_spacing_is_a_symmetric_day_buffer_around_a_segment
        """
        world = _four_drops_around_one_anchored_segment()
        crowded_drop_id = world["later_inside_drop"]["id"]

        validate_error(
            api.create_line(
                crowded_drop_id,
                create_housefile_line_payload(
                    world["seg_a"]["id"], requested_quantity=5000
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_INHOME_SPACING_VIOLATION.value,
            409,
        )

        other_segment_line = get_success_data(
            api.create_line(
                crowded_drop_id,
                create_housefile_line_payload(
                    world["seg_b"]["id"], requested_quantity=5000
                ),
                PLANNER,
            )
        )
        assert other_segment_line["status"] == "PROPOSED"

        get_success_data(
            api.void_line(
                world["anchor_line"]["id"], PLANNER, {"reason": "release the buffer"}
            )
        )
        assert fetch_line(world["anchor_line"]["id"])["status"] == "VOIDED"
        assert fetch_drop(world["anchor_drop"]["id"])["requested_quantity_total"] == 0

        released = get_success_data(
            api.create_line(
                crowded_drop_id,
                create_housefile_line_payload(
                    world["seg_a"]["id"], requested_quantity=5000
                ),
                PLANNER,
            )
        )
        assert released["status"] == "PROPOSED"

        _lines, meta = validate_paginated(
            api.list_lines(PLANNER, {"drop_id": crowded_drop_id})
        )
        assert meta["total_count"] == 2


def _drop_with_a_front_cover_placement() -> dict:
    """A 64-page drop carrying one 44-square-inch front-cover placement in the
    span [0, 44) of page 1."""
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
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop": drop,
        "line": line,
        "first": first,
    }


class TestPageSpaceHalfOpenIntervals:
    def test_a_span_starting_where_the_previous_one_ends_is_accepted(self, api):
        """PRD §3.4: "A placement occupies the half-open interval that begins at
        `sq_in_offset` and extends for `square_inches`, so the interval includes
        its left edge and excludes its right; two live placements on the same
        `page_number` of the same drop may not have overlapping intervals, though
        intervals that merely touch — where one ends exactly where the next begins
        — are permitted."

        Design: Difficulty/resource_temporal_overlap/page_space_is_a_half_open_interval_that_permits_adjacency
        """
        world = _drop_with_a_front_cover_placement()
        drop_id = world["drop"]["id"]

        season = fetch_season(world["season"]["id"])
        assert season["usable_sq_in_per_page"] == 88
        assert world["drop"]["square_inch_capacity"] == 5632
        assert world["drop"]["unallocated_square_inches"] == 5632

        first = world["first"]
        assert_page_placement(first)
        assert first["position_multiplier_bps"] == 18000
        assert first["forecast_space_demand_cents"] == 332640
        assert first["space_productivity_cents_per_sq_in"] == 7560

        adjacent = get_success_data(
            api.create_page_placement(
                drop_id,
                create_page_placement_payload(
                    product_sku="SKU-2",
                    product_name="Cast iron pan",
                    unit_price_cents=8900,
                    unit_cogs_cents=3900,
                    demand_per_sq_inch_cents=3100,
                    page_number=1,
                    sq_in_offset=44,
                    square_inches=44,
                    placement_position="INSIDE",
                ),
                PLANNER,
            )
        )
        assert_page_placement(adjacent)
        assert adjacent["forecast_space_demand_cents"] == 136400
        assert adjacent["space_productivity_cents_per_sq_in"] == 3100

        drop = fetch_drop(drop_id)
        assert drop["allocated_square_inches"] == 88
        assert drop["unallocated_square_inches"] == 5544
        assert_drop_space_conserved(drop)

    def test_a_one_inch_backstep_overlaps_while_the_same_offsets_are_free_elsewhere(
        self, api
    ):
        """PRD §3.4: "A placement must also fit inside a single page:
        `sq_in_offset` plus `square_inches` may not exceed the season's
        `usable_sq_in_per_page`, and `page_number` must lie between 1 and the
        drop's `page_count` inclusive; either violation is rejected with
        `ERR_PAGE_CAPACITY_EXCEEDED`."

        Design: Difficulty/resource_temporal_overlap/page_space_is_a_half_open_interval_that_permits_adjacency
        """
        world = _drop_with_a_front_cover_placement()
        drop_id = world["drop"]["id"]

        new_page_placement(
            drop_id,
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

        overlap = validate_error(
            api.create_page_placement(
                drop_id,
                create_page_placement_payload(
                    product_sku="SKU-3",
                    product_name="Enamel kettle",
                    unit_price_cents=6900,
                    unit_cogs_cents=2900,
                    demand_per_sq_inch_cents=2800,
                    page_number=1,
                    sq_in_offset=43,
                    square_inches=10,
                    placement_position="HOT_SPOT",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_PAGE_SPACE_OVERLAP.value,
            409,
        )
        assert overlap["error_id"] != ApiErrorId.ERR_PAGE_CAPACITY_EXCEEDED.value

        validate_error(
            api.create_page_placement(
                drop_id,
                create_page_placement_payload(
                    product_sku="SKU-4",
                    product_name="Linen apron",
                    unit_price_cents=4900,
                    unit_cogs_cents=1900,
                    demand_per_sq_inch_cents=2600,
                    page_number=2,
                    sq_in_offset=80,
                    square_inches=10,
                    placement_position="INSIDE",
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_PAGE_CAPACITY_EXCEEDED.value,
            422,
        )

        second_page = get_success_data(
            api.create_page_placement(
                drop_id,
                create_page_placement_payload(
                    product_sku="SKU-5",
                    product_name="Stoneware mug",
                    unit_price_cents=2400,
                    unit_cogs_cents=900,
                    demand_per_sq_inch_cents=2600,
                    page_number=2,
                    sq_in_offset=0,
                    square_inches=44,
                    placement_position="INSIDE",
                ),
                PLANNER,
            )
        )
        assert second_page["page_number"] == 2
        assert second_page["sq_in_offset"] == 0
        assert second_page["square_inches"] == 44

        drop = fetch_drop(drop_id)
        assert drop["allocated_square_inches"] == 132
        assert drop["unallocated_square_inches"] == 5500
        assert_drop_space_conserved(drop)

        _placements, meta = validate_paginated(
            api.list_page_placements(drop_id, PLANNER)
        )
        assert meta["total_count"] == 3
