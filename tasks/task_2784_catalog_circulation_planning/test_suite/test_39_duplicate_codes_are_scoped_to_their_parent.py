"""Each uniqueness rule binds inside its own scope and nowhere wider.

Every scope is exercised from both sides: the literal value that collides inside
its parent is then accepted verbatim under a sibling parent. `segment_code` S_A
repeats across two seasons, `drop_number` 1 repeats across two plans and `product_sku`
SKU-1 repeats across two drops, so an implementation that made any of these globally
unique fails on the acceptance half rather than on the rejection half. Only the season
code is genuinely service-wide, and it collides even when the fiscal year differs.
"""
from test_helpers import (
    ADMIN,
    CLOCK_START,
    PLANNER,
    assert_circulation_line,
    assert_drop,
    assert_housefile_segment,
    assert_page_placement,
    create_drop_payload,
    create_housefile_line_payload,
    create_page_placement_payload,
    create_plan_payload,
    create_season_payload,
    create_segment_payload,
    create_suppression_rule_payload,
    fetch_line,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_page_placement,
    new_plan,
    new_season,
    new_segment,
    new_suppression_rule,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SCORING = {
    "recency_days": 45,
    "orders_12mo": 7,
    "ltv_cents": 62000,
    "housefile_count": 30000,
    "avg_order_value_cents": 18500,
    "historical_response_rate_bps": 620,
}

RIVAL_SCORING = {
    "recency_days": 90,
    "orders_12mo": 2,
    "ltv_cents": 5000,
    "housefile_count": 1000,
    "avg_order_value_cents": 9000,
    "historical_response_rate_bps": 300,
}


def _two_seasons_two_plans_and_one_stocked_drop() -> dict:
    """FW26 carries segment S_A and plans P1 and P2; P1 carries drop 1, which
    carries placement SKU-1 and a live line for S_A. SS27 is an empty sibling season
    and P2 an empty sibling plan, so every code below has somewhere else to land."""
    set_clock(CLOCK_START)
    first = new_season(season_code="FW26", fiscal_year=2026)
    second = new_season(season_code="SS27", fiscal_year=2027)
    segment = new_segment(first["id"], segment_code="S_A", **SCORING)
    plan_one = new_plan(first["id"], plan_code="P1", budget_cents=20000000)
    plan_two = new_plan(first["id"], plan_code="P2", budget_cents=20000000)
    drop = new_drop(
        plan_one["id"],
        drop_number=1,
        in_home_date=iso_utc("2026-09-15"),
        page_count=64,
    )
    placement = new_page_placement(
        drop["id"],
        product_sku="SKU-1",
        product_name="Wool throw",
        unit_price_cents=12900,
        unit_cogs_cents=5400,
        demand_per_sq_inch_cents=4200,
        page_number=1,
        sq_in_offset=0,
        square_inches=40,
        placement_position="FRONT_COVER",
    )
    line = new_housefile_line(
        drop["id"], segment["id"], requested_quantity=10000
    )
    rule = new_suppression_rule(
        first["id"],
        rule_code="CAP_ALL",
        channel_scope="ALL",
        window_days=30,
        max_contacts_per_window=5,
        priority=20,
    )
    return {
        "first_season": first,
        "second_season": second,
        "segment": segment,
        "plan_one": plan_one,
        "plan_two": plan_two,
        "drop": drop,
        "placement": placement,
        "line": line,
        "rule": rule,
    }


class TestTheOnlyServiceWideCode:
    def test_a_repeated_season_code_collides_even_in_another_fiscal_year(self, api):
        """PRD §2.5: "It is created by a `PlatformAdmin` with a `season_code` — a
        human-readable identifier of 1 to 32 characters such as `FALL2026A`, unique
        across the whole service, with a collision rejected as
        `ERR_DUPLICATE_SEASON_CODE` — and a `fiscal_year` between 2020 and 2100
        inclusive."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        assert world["first_season"]["fiscal_year"] == 2026

        response = api.create_season(
            create_season_payload(season_code="FW26", fiscal_year=2027), ADMIN
        )
        validate_error(response, "ERR_DUPLICATE_SEASON_CODE", 409)


class TestSegmentCodesAreUniquePerSeason:
    def test_the_same_segment_code_collides_at_home_and_passes_in_a_sibling_season(
        self, api
    ):
        """PRD §3.1: "Registering a segment requires the owning `season_id`, a
        `segment_code` such as `HF_BEST_0_90` that must be unique within that season (a
        repeat is rejected with `ERR_DUPLICATE_SEGMENT_CODE`), and six representative
        figures for the names the segment holds: `recency_days`, the whole days since
        the segment's representative most-recent order; `orders_12mo`, the
        representative order count over the trailing twelve months; `ltv_cents`, the
        representative lifetime monetary value in cents; `housefile_count`, the mailable
        name count the segment owns directly, excluding any descendants;
        `avg_order_value_cents`, the average order value used to convert forecast orders
        into forecast demand; and `historical_response_rate_bps`, the observed catalog
        response rate in basis points."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()

        collision = api.create_segment(
            create_segment_payload(
                world["first_season"]["id"], segment_code="S_A", **RIVAL_SCORING
            ),
            PLANNER,
        )
        validate_error(collision, "ERR_DUPLICATE_SEGMENT_CODE", 409)

        sibling = validate_success(
            api.create_segment(
                create_segment_payload(
                    world["second_season"]["id"], segment_code="S_A", **RIVAL_SCORING
                ),
                PLANNER,
            ),
            201,
        )
        assert_housefile_segment(sibling)
        assert sibling["segment_code"] == "S_A"
        assert sibling["season_id"] == world["second_season"]["id"]
        assert sibling["id"] != world["segment"]["id"]
        assert sibling["housefile_count"] == 1000


class TestPlanAndRuleCodesAreUniquePerSeason:
    def test_a_repeated_plan_code_collides_within_its_season(self, api):
        """PRD §3.6: "A `CirculationPlanner` opens a **circulation plan** against a
        `season_id` with a `plan_code` such as `FALL2026A-CIRC-V1`, unique within that
        season — a repeat is rejected with `ERR_DUPLICATE_PLAN_CODE` — and a
        `budget_cents` figure greater than zero."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()

        response = api.create_plan(
            create_plan_payload(
                world["first_season"]["id"], plan_code="P1", budget_cents=999
            ),
            PLANNER,
        )
        validate_error(response, "ERR_DUPLICATE_PLAN_CODE", 409)

    def test_a_repeated_rule_code_collides_despite_a_different_scope_and_window(
        self, api
    ):
        """PRD §3.8: "Each rule carries a `rule_code` such as `CAP_EMAIL_30D`, unique
        within the season with a repeat rejected as
        `ERR_DUPLICATE_SUPPRESSION_RULE_CODE`; a `channel_scope` of `MAIL`, `EMAIL`,
        `DIGITAL` or `ALL`, where `ALL` counts every channel together; a `window_days`
        trailing window between 1 and 365 whole days inclusive; a
        `max_contacts_per_window` ceiling that may not be negative; a `priority` of at
        least 1 that fixes evaluation order among a season's rules, with lower numbers
        evaluated first and `created_at` ascending breaking ties; and an `is_enabled`
        flag that defaults to true and determines whether the rule participates at
        all."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        assert world["rule"]["channel_scope"] == "ALL"

        response = api.create_suppression_rule(
            world["first_season"]["id"],
            create_suppression_rule_payload(
                rule_code="CAP_ALL",
                channel_scope="MAIL",
                window_days=60,
                max_contacts_per_window=1,
                priority=30,
            ),
            ADMIN,
        )
        validate_error(response, "ERR_DUPLICATE_SUPPRESSION_RULE_CODE", 409)


class TestDropNumbersAreUniquePerPlan:
    def test_drop_number_one_collides_at_home_and_passes_under_a_sibling_plan(
        self, api
    ):
        """PRD §3.4: "A `CirculationPlanner` adds a drop to a plan by supplying a
        `drop_number` between 1 and 99 that must be unique within that plan — a repeat
        is rejected with `ERR_DUPLICATE_DROP_NUMBER` — an `in_home_date` as an ISO 8601
        UTC instant with three fractional digits, and a `page_count`."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        payload = create_drop_payload(
            drop_number=1, in_home_date=iso_utc("2026-10-20"), page_count=64
        )

        collision = api.create_drop(world["plan_one"]["id"], payload, PLANNER)
        validate_error(collision, "ERR_DUPLICATE_DROP_NUMBER", 409)

        sibling = validate_success(
            api.create_drop(world["plan_two"]["id"], payload, PLANNER), 201
        )
        assert_drop(sibling)
        assert sibling["drop_number"] == 1
        assert sibling["circulation_plan_id"] == world["plan_two"]["id"]
        assert sibling["id"] != world["drop"]["id"]

        _, first_meta = validate_paginated(
            api.list_plan_drops(world["plan_one"]["id"], PLANNER)
        )
        assert first_meta["total_count"] == 1
        _, second_meta = validate_paginated(
            api.list_plan_drops(world["plan_two"]["id"], PLANNER)
        )
        assert second_meta["total_count"] == 1


class TestPlacementSkusAreUniquePerDrop:
    def test_the_same_sku_collides_at_home_and_passes_on_a_sibling_drop(self, api):
        """PRD §3.4: "A **page placement** puts one SKU in one rectangle of one page,
        and it carries a `product_sku` that must be unique within the drop (a repeat is
        rejected with `ERR_DUPLICATE_PLACEMENT_SKU`), a `product_name` for display, a
        `unit_price_cents` catalog selling price and a `unit_cogs_cents` cost of goods —
        neither negative — a `demand_per_sq_inch_cents` figure recording the historical
        demand in cents this SKU generates per square inch when placed in an ordinary
        inside position, a `page_number`, a `sq_in_offset` measuring the left edge of the
        occupied area in square inches consumed from the page origin, a `square_inches`
        area greater than zero, and a `placement_position` drawn from `FRONT_COVER`,
        `HOT_SPOT`, `INSIDE` and `BACK_COVER`."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        sibling_drop = new_drop(
            world["plan_two"]["id"],
            drop_number=1,
            in_home_date=iso_utc("2026-10-20"),
            page_count=64,
        )
        payload = create_page_placement_payload(
            product_sku="SKU-1",
            product_name="Duplicate sku",
            unit_price_cents=8900,
            unit_cogs_cents=3700,
            demand_per_sq_inch_cents=4100,
            page_number=2,
            sq_in_offset=0,
            square_inches=10,
            placement_position="INSIDE",
        )

        collision = api.create_page_placement(world["drop"]["id"], payload, PLANNER)
        validate_error(collision, "ERR_DUPLICATE_PLACEMENT_SKU", 409)

        accepted = validate_success(
            api.create_page_placement(sibling_drop["id"], payload, PLANNER), 201
        )
        assert_page_placement(accepted)
        assert accepted["product_sku"] == "SKU-1"
        assert accepted["drop_id"] == sibling_drop["id"]
        assert accepted["id"] != world["placement"]["id"]

        _, home_meta = validate_paginated(
            api.list_page_placements(world["drop"]["id"], PLANNER)
        )
        assert home_meta["total_count"] == 1
        _, sibling_meta = validate_paginated(
            api.list_page_placements(sibling_drop["id"], PLANNER)
        )
        assert sibling_meta["total_count"] == 1


class TestOnlyLiveLinesOccupyTheAudienceSlot:
    def test_a_second_line_for_the_same_segment_is_refused_while_the_first_lives(
        self, api
    ):
        """PRD §3.5: "A drop may not carry two live lines for the same audience —
        where "live" means status `PROPOSED` or `ALLOCATED` — and a second such line is
        rejected with `ERR_DUPLICATE_AUDIENCE_LINE`."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        assert world["line"]["status"] == "PROPOSED"

        response = api.create_line(
            world["drop"]["id"],
            create_housefile_line_payload(
                world["segment"]["id"], requested_quantity=500
            ),
            PLANNER,
        )
        validate_error(response, "ERR_DUPLICATE_AUDIENCE_LINE", 409)

        _, meta = validate_paginated(
            api.list_lines(PLANNER, params={"drop_id": world["drop"]["id"]})
        )
        assert meta["total_count"] == 1

    def test_voiding_the_first_line_frees_the_slot_for_the_same_segment(self, api):
        """PRD §3.5: "A drop may not carry two live lines for the same audience —
        where "live" means status `PROPOSED` or `ALLOCATED` — and a second such line is
        rejected with `ERR_DUPLICATE_AUDIENCE_LINE`."

        Design: Corner/validations/duplicate_codes_are_rejected_only_inside_their_own_parent_scope
        """
        world = _two_seasons_two_plans_and_one_stocked_drop()
        payload = create_housefile_line_payload(
            world["segment"]["id"], requested_quantity=500
        )
        validate_error(
            api.create_line(world["drop"]["id"], payload, PLANNER),
            "ERR_DUPLICATE_AUDIENCE_LINE",
            409,
        )

        validate_success(
            api.void_line(world["line"]["id"], PLANNER, {"reason": "make room"}), 200
        )
        assert fetch_line(world["line"]["id"])["status"] == "VOIDED"

        relisted = validate_success(
            api.create_line(world["drop"]["id"], payload, PLANNER), 201
        )
        assert_circulation_line(relisted)
        assert relisted["status"] == "PROPOSED"
        assert relisted["housefile_segment_id"] == world["segment"]["id"]
        assert relisted["requested_quantity"] == 500
        assert relisted["id"] != world["line"]["id"]
