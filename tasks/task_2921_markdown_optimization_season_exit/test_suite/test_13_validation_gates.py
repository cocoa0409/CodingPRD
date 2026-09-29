"""Declared validations whose interest lies in which gate fires, in what order,
and on which side of a boundary the world lands.
"""

from test_helpers import validate_error, validate_paginated, validate_success
from test_helpers import fixtures as fx
from test_helpers.assertions import find_by
from test_helpers.factories import (
    clearance_allocation_payload,
    item_payload,
    markdown_step_payload,
    region_zone_payload,
    sales_week_payload,
    season_payload,
    store_payload,
    submit_payload,
    zone_execution_payload,
)


class TestUniquenessAcrossFiveCollections:
    """One error id, five different keys, one of them composite."""

    def test_five_duplicate_creates_all_report_the_same_error(
        self, api, analyst, director
    ):
        """PRD 2.7 rule 27: "Uniqueness, reported as `ERR_DUPLICATE_RESOURCE` (409),
        over a season's `code`, an item's `sku`, a store's `store_number`, a zone's
        `zone_code`, the pair of `item_id` and `week_ending_date` for a sales week, and
        the pair of `season_id` and `review_type` for an exit review." And: "It guards
        season, item, store, price-zone, sales-week and exit-review creation."

        Design: Corner/validations/uniqueness_keys_reject_duplicates_across_five_collections
        """
        sc = fx.base_scenario(api)

        validate_error(
            api.create_season(season_payload(), director), "ERR_DUPLICATE_RESOURCE", 409
        )
        validate_error(
            api.create_item(item_payload(sc.season["id"]), analyst),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )
        validate_error(
            api.create_store(
                store_payload(
                    sc.west_zone["id"], store_number="0101", clearance_bay_units=250
                ),
                director,
            ),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )
        validate_error(
            api.create_price_zone(region_zone_payload(sc.chain_zone["id"]), director),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )
        validate_error(
            api.post_sales_week(
                sc.item["id"], sales_week_payload("2026-09-05", 10, 4999), analyst
            ),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )

    def test_the_sales_week_key_is_composite_not_a_global_date(self, api, analyst):
        """PRD 3.3: "A week-ending date must be strictly later than the item's
        `first_receipt_date` — an earlier or equal date is an `ERR_VALIDATION` — and the
        pair of item and `week_ending_date` may appear only once, so a re-post is
        refused with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/uniqueness_keys_reject_duplicates_across_five_collections
        """
        sc = fx.base_scenario(api)
        item_b = fx.create_item(
            api,
            sc.season["id"],
            sku="B-2002",
            first_receipt_date="2026-08-18",
            original_retail_cents=3999,
            unit_cost_cents=1500,
            units_received_total=400,
        )

        week = validate_success(
            api.post_sales_week(
                item_b["id"], sales_week_payload("2026-09-05", 40, 3999), analyst
            ),
            201,
        )

        assert week["week_ending_date"] == "2026-09-05"
        assert fx.read_item(api, item_b["id"])["units_sold_total"] == 40
        assert fx.read_item(api, item_b["id"])["sample_weeks"] == 1

    def test_the_refused_duplicates_stored_nothing(self, api, analyst, director):
        """PRD 2.7: "When a request violates more than one rule, the response is decided
        by the lowest-numbered rule in the ordered ladder below." And PRD 3.1: "A newly
        registered season opens in `PLANNING`, with `reserved_clearance_units`,
        `committed_clearance_units` and `projected_exit_units` all at 0, and a duplicate
        `code` is refused with `ERR_DUPLICATE_RESOURCE`."

        Design: Corner/validations/uniqueness_keys_reject_duplicates_across_five_collections
        """
        sc = fx.base_scenario(api)
        fx.create_item(
            api,
            sc.season["id"],
            sku="B-2002",
            first_receipt_date="2026-08-18",
            original_retail_cents=3999,
            unit_cost_cents=1500,
            units_received_total=400,
        )

        validate_error(
            api.create_season(season_payload(), director), "ERR_DUPLICATE_RESOURCE", 409
        )
        validate_error(
            api.create_item(item_payload(sc.season["id"]), analyst),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )
        validate_error(
            api.post_sales_week(
                sc.item["id"], sales_week_payload("2026-09-05", 10, 4999), analyst
            ),
            "ERR_DUPLICATE_RESOURCE",
            409,
        )

        _seasons, season_meta = validate_paginated(api.list_seasons(analyst))
        assert season_meta["total_count"] == 1

        _items, item_meta = validate_paginated(
            api.list_items(analyst, {"season_id": sc.season["id"]})
        )
        assert item_meta["total_count"] == 2

        _zones, zone_meta = validate_paginated(api.list_price_zones(director))
        assert zone_meta["total_count"] == 2

        _stores, store_meta = validate_paginated(
            api.list_stores(director, {"price_zone_id": sc.west_zone["id"]})
        )
        assert store_meta["total_count"] == 3

        _weeks, week_meta = validate_paginated(
            api.list_item_sales_weeks(sc.item["id"], analyst)
        )
        assert week_meta["total_count"] == 4
        assert fx.read_item(api, sc.item["id"])["units_sold_total"] == 257


def _core_item_with_a_certified_estimate(api):
    """Item ``C-3003`` sells exactly 45.00 percent of its receipts, so it stays
    ``CORE`` while still holding a ``CERTIFIED`` (pooled, overridden) estimate.
    """
    sc = fx.certified_scenario(api)
    item_c = fx.create_item(
        api,
        sc.season["id"],
        sku="C-3003",
        original_retail_cents=3999,
        unit_cost_cents=1500,
        units_received_total=400,
    )
    fx.post_history(
        api,
        item_c["id"],
        [
            ("2026-09-05", 45, 3999),
            ("2026-09-12", 45, 3999),
            ("2026-09-19", 45, 3999),
            ("2026-09-26", 45, 3999),
        ],
    )
    fx.set_clock(api, "2026-10-10T00:00:00Z")
    estimate_c = fx.create_estimate(api, item_c["id"])
    sc["estimate_c"] = fx.certify_estimate(
        api, estimate_c["id"], override_low_confidence=True
    )
    sc["item_c"] = item_c
    return sc


class TestEligibilityIsCheckedOnlyAtSubmit:
    """A CORE item may hold a complete, legal ladder and still not be submitted."""

    def test_the_plan_and_the_rung_are_accepted_on_a_core_item(self, api, analyst):
        """PRD 3.3: "Note that opening a plan is not gated on the stage at all — a plan
        may be opened on any item and will still be stamped with a recommended depth —
        the stage is only enforced at submission." PRD 3.5 keys the stamp: "The base
        depth is keyed to the item's `lifecycle_stage`: 0.00 percent for `NEW_ARRIVAL`,
        5.00 for `CORE`, 15.00 for `AGING`, 30.00 for `CLEARANCE`, 50.00 for
        `EXIT_PENDING` and 0.00 for `DISPOSED` — every stage is keyed, because a plan may
        be opened on an item at any stage." And: "Depth is always measured off the
        original ticket, never off the live one, so the rung's `price_cents` is the
        item's `original_retail_cents` less the discount, where the discount is
        `original_retail_cents` multiplied by `depth_pct` divided by 100 and rounded half
        up to a whole cent before the subtraction."

        Design: Corner/validations/core_item_cannot_submit_a_plan_even_with_a_valid_ladder
        """
        sc = _core_item_with_a_certified_estimate(api)

        assert fx.read_item(api, sc.item_c["id"])["lifecycle_stage"] == "CORE"

        plan = fx.create_plan(
            api, sc.season["id"], sc.item_c["id"], sc.estimate_c["id"]
        )
        assert plan["status"] == "DRAFT"
        assert plan["recommended_depth_pct"] == 10.00

        rung = validate_success(
            api.create_markdown_step(
                plan["id"], markdown_step_payload(1, "2026-11-16", 22.57), analyst
            ),
            201,
        )
        assert rung["price_cents"] == 3096
        assert rung["status"] == "PLANNED"

    def test_the_submit_is_the_call_that_is_refused(self, api, analyst):
        """PRD 3.3: "Markdown eligibility, checked when a plan is submitted, is satisfied
        by exactly `AGING`, `CLEARANCE` and `EXIT_PENDING`; a submission on an item still
        in `NEW_ARRIVAL` or `CORE`, or already in `DISPOSED`, is refused with
        `ERR_MARKDOWN_NOT_ELIGIBLE`."

        Design: Corner/validations/core_item_cannot_submit_a_plan_even_with_a_valid_ladder
        """
        sc = _core_item_with_a_certified_estimate(api)
        plan = fx.create_plan(
            api, sc.season["id"], sc.item_c["id"], sc.estimate_c["id"]
        )
        rung = fx.add_rung(api, plan["id"], 1, "2026-11-16", 22.57)

        response = api.submit_markdown_plan(plan["id"], submit_payload(), analyst)
        validate_error(response, "ERR_MARKDOWN_NOT_ELIGIBLE", 422)

        stalled = fx.read_plan(api, plan["id"])
        assert stalled["status"] == "DRAFT"
        assert stalled["ladder_step_count"] == 1
        assert fx.read_step(api, rung["id"])["status"] == "PLANNED"
        assert fx.read_item(api, sc.item_c["id"])["lifecycle_stage"] == "CORE"
        assert sc.estimate_c["status"] == "CERTIFIED"


class TestLadderShapeRulesFireInOrder:
    """Four rung-shape errors are reachable from one plan, in a pinned order."""

    def test_cadence_is_checked_before_any_shape_rule(self, api, analyst):
        """PRD 2.7 rule 18: "Cadence on ladder-rung creation: the number of whole days
        between the previous rung's `effective_date` and this rung's must be at least 14;
        exactly 14 days is allowed and 13 is rejected with `ERR_CADENCE_TOO_TIGHT` (422)."
        The ladder is explicit that the order is normative: "The ordering is normative: a
        caller must be able to predict which of several simultaneous problems is reported,
        and a later check may never mask an earlier one."

        Design: Corner/validations/ladder_shape_rules_fire_in_their_declared_inner_order
        """
        sc = fx.planned_scenario(api)
        fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)

        response = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(2, "2026-11-29", 32.50), analyst
        )
        validate_error(response, "ERR_CADENCE_TOO_TIGHT", 422)

        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1

    def test_the_sequence_check_precedes_the_monotonicity_check(self, api, analyst):
        """PRD 2.7 rule 22: "Ladder shape on rung creation: `step_index` must equal the
        plan's current `ladder_step_count` plus 1, else `ERR_STEP_INDEX_OUT_OF_SEQUENCE`
        (422); `ladder_step_count` must be below 4, else `ERR_MAX_LADDER_STEPS` (422); and
        `depth_pct` must be strictly greater than the previous rung's `depth_pct`, else
        `ERR_DEPTH_NOT_MONOTONIC` (422)."

        Design: Corner/validations/ladder_shape_rules_fire_in_their_declared_inner_order
        """
        sc = fx.planned_scenario(api)
        fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)

        equal_depth = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(2, "2026-11-30", 22.57), analyst
        )
        validate_error(equal_depth, "ERR_DEPTH_NOT_MONOTONIC", 422)

        wrong_index = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(3, "2026-11-30", 32.50), analyst
        )
        validate_error(wrong_index, "ERR_STEP_INDEX_OUT_OF_SEQUENCE", 422)

        _rows, meta = validate_paginated(api.list_plan_steps(sc.plan["id"], analyst))
        assert meta["total_count"] == 1

    def test_a_legal_fifth_rung_reports_the_cap(self, api, analyst):
        """PRD 2.7 rule 22: "`ladder_step_count` must be below 4, else
        `ERR_MAX_LADDER_STEPS` (422)". PRD 3.5 records what each accepted rung does:
        "Appending a rung increments the plan's `ladder_step_count`, recomputes the plan's
        `projected_exit_units`, and bumps the plan's `version`."

        Design: Corner/validations/ladder_shape_rules_fire_in_their_declared_inner_order
        """
        sc = fx.planned_scenario(api)
        fx.add_rung(api, sc.plan["id"], 1, "2026-10-12", 10.00)
        fx.add_rung(api, sc.plan["id"], 2, "2026-10-26", 20.00)
        fx.add_rung(api, sc.plan["id"], 3, "2026-11-09", 30.00)
        fx.add_rung(api, sc.plan["id"], 4, "2026-11-23", 40.00)

        fifth = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(5, "2026-12-07", 50.00), analyst
        )
        validate_error(fifth, "ERR_MAX_LADDER_STEPS", 422)

        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 4
        _rows, meta = validate_paginated(api.list_plan_steps(sc.plan["id"], analyst))
        assert meta["total_count"] == 4


class TestEffectiveDateWindowIsTwoSided:
    """One field, two boundaries, two different error ids."""

    def test_both_sides_of_the_window_are_refused(self, api, analyst):
        """PRD 2.7 rule 19: "Exit-date framing on ladder-rung creation: the rung's
        `effective_date` must be no later than the plan's `exit_date_target` minus 7 days,
        else `ERR_EXIT_DATE_MISSED` (422); and it must be no earlier than the logical
        clock's current date, else `ERR_EFFECTIVE_DATE_IN_PAST` (422)."

        Design: Corner/validations/effective_date_must_sit_inside_the_clock_and_exit_buffer_window
        """
        sc = fx.planned_scenario(api)

        in_past = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(1, "2026-10-09", 22.57), analyst
        )
        validate_error(in_past, "ERR_EFFECTIVE_DATE_IN_PAST", 422)

        too_late = api.create_markdown_step(
            sc.plan["id"], markdown_step_payload(1, "2027-01-09", 22.57), analyst
        )
        validate_error(too_late, "ERR_EXIT_DATE_MISSED", 422)

        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 0

    def test_the_buffer_boundary_date_itself_is_accepted(self, api, analyst):
        """PRD 3.5: "Each new rung also fixes the ladder's occupancy calendar: a rung's
        `window_end_date_exclusive` is set to the plan's `exit_date_target` when it is the
        last rung, and appending a further rung rewrites the previous rung's
        `window_end_date_exclusive` to the new rung's `effective_date`, so the rungs tile
        the plan's calendar as half-open windows."

        Design: Corner/validations/effective_date_must_sit_inside_the_clock_and_exit_buffer_window
        """
        sc = fx.planned_scenario(api)

        rung = validate_success(
            api.create_markdown_step(
                sc.plan["id"], markdown_step_payload(1, "2027-01-08", 22.57), analyst
            ),
            201,
        )

        assert rung["effective_date"] == "2027-01-08"
        assert rung["window_end_date_exclusive"] == "2027-01-15"
        assert rung["price_cents"] == 3871
        assert fx.read_plan(api, sc.plan["id"])["ladder_step_count"] == 1


class TestFiscalCapAndPhysicalCapacityAreSeparate:
    """The 900-unit budget and the 800 bays of OPEN stores are two gates."""

    def test_the_chain_ceiling_is_tested_first(self, api, analyst):
        """PRD 3.7: "Only then is the chain ceiling tested, against the post-release
        figures: the season's `reserved_clearance_units` plus its
        `committed_clearance_units` plus the requested `total_units` may not exceed
        `clearance_space_units`, and a breach is refused with
        `ERR_SEASON_CLEARANCE_CAP_EXCEEDED`."

        Design: Corner/validations/chain_cap_and_store_capacity_are_two_separate_gates
        """
        sc = fx.approved_plan_scenario(api)
        version = fx.read_season(api, sc.season["id"])["version"]

        response = api.create_clearance_allocation(
            sc.season["id"],
            clearance_allocation_payload(sc.plan["id"], 950, version),
            analyst,
        )
        validate_error(response, "ERR_SEASON_CLEARANCE_CAP_EXCEEDED", 409)

        season = fx.read_season(api, sc.season["id"])
        assert season["reserved_clearance_units"] == 0
        assert season["committed_clearance_units"] == 0

    def test_a_request_inside_the_cap_can_still_exceed_the_open_bays(
        self, api, analyst
    ):
        """PRD 3.7: "Next the candidate stores are drawn — every store whose `status` is
        `OPEN` and whose `available_clearance_units` is at least 1, which deliberately
        excludes stores in `REMODEL` or `CLOSING` even when their bays are empty." And:
        "Allocation is all-or-nothing: if the ordered candidates cannot absorb the whole
        `total_units`, the request is refused with `ERR_CLEARANCE_SPACE_EXCEEDED` and not
        a single reservation is written."

        Design: Corner/validations/chain_cap_and_store_capacity_are_two_separate_gates
        """
        sc = fx.approved_plan_scenario(api)
        version = fx.read_season(api, sc.season["id"])["version"]

        response = api.create_clearance_allocation(
            sc.season["id"],
            clearance_allocation_payload(sc.plan["id"], 850, version),
            analyst,
        )
        validate_error(response, "ERR_CLEARANCE_SPACE_EXCEEDED", 409)

        _rows, meta = validate_paginated(
            api.list_clearance_reservations(analyst, {"season_id": sc.season["id"]})
        )
        assert meta["total_count"] == 0
        assert fx.read_store(api, sc.store_0303["id"])["available_clearance_units"] == 120

    def test_eight_hundred_units_fill_both_open_stores_exactly(self, api, analyst):
        """PRD 3.7: "Those candidates are ordered by `available_clearance_units`
        descending, then by `store_number` ascending, then by `created_at` ascending, so
        the largest free bay is filled first and ties resolve deterministically." And: "On
        success each filled store's `committed_clearance_units` grows by its
        `reserved_units` with `available_clearance_units` recomputed, the season's
        `reserved_clearance_units` grows by `total_units`, and the season's `version` is
        incremented."

        Design: Corner/validations/chain_cap_and_store_capacity_are_two_separate_gates
        """
        sc = fx.approved_plan_scenario(api)

        reservations = fx.allocate_clearance(api, sc.season["id"], sc.plan["id"], 800)

        assert len(reservations) == 2
        rank_one = find_by(reservations, allocation_rank=1)
        rank_two = find_by(reservations, allocation_rank=2)
        assert rank_one["store_id"] == sc.store_0202["id"]
        assert rank_one["reserved_units"] == 500
        assert rank_one["status"] == "RESERVED"
        assert rank_two["store_id"] == sc.store_0101["id"]
        assert rank_two["reserved_units"] == 300

        assert fx.read_season(api, sc.season["id"])["reserved_clearance_units"] == 800
        assert fx.read_store(api, sc.store_0202["id"])["available_clearance_units"] == 0
        assert fx.read_store(api, sc.store_0303["id"])["available_clearance_units"] == 120


class TestExecutionScopeCouplings:
    """One error id guards four different scope couplings."""

    def test_all_four_disagreements_report_one_error(self, api, analyst):
        """PRD 3.6: "A `CHAIN` execution requires the named zone's `zone_type` to be
        `CHAIN` and forbids a `store_id`." And: "A `ZONE` execution requires the zone's
        `zone_type` to be `REGION` and likewise forbids a `store_id`." And: "A `STORE`
        execution requires the zone's `zone_type` to be either `STORE` or `REGION`,
        requires a `store_id`, and requires that store's `price_zone_id` to equal the
        execution's `price_zone_id`." And: "The execution's `effective_date` must also
        equal the referenced rung's own `effective_date`, and the rung must genuinely
        belong to the named plan." And: "Any of these disagreements is refused with
        `ERR_ZONE_SCOPE_MISMATCH`."

        Design: Corner/validations/execution_scope_must_match_the_zone_type_and_the_step
        """
        sc = fx.approved_plan_scenario(api, effective_date="2026-11-16")

        chain_on_region = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step1["id"],
                sc.west_zone["id"],
                "CHAIN",
                "2026-11-16",
                200,
            ),
            analyst,
        )
        validate_error(chain_on_region, "ERR_ZONE_SCOPE_MISMATCH", 422)

        zone_on_chain = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step1["id"],
                sc.chain_zone["id"],
                "ZONE",
                "2026-11-16",
                200,
            ),
            analyst,
        )
        validate_error(zone_on_chain, "ERR_ZONE_SCOPE_MISMATCH", 422)

        store_without_store_id = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step1["id"],
                sc.west_zone["id"],
                "STORE",
                "2026-11-16",
                200,
            ),
            analyst,
        )
        validate_error(store_without_store_id, "ERR_ZONE_SCOPE_MISMATCH", 422)

        wrong_date = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step1["id"],
                sc.west_zone["id"],
                "ZONE",
                "2026-11-17",
                200,
            ),
            analyst,
        )
        validate_error(wrong_date, "ERR_ZONE_SCOPE_MISMATCH", 422)

        _rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 0

    def test_a_store_scope_execution_on_a_region_zone_is_legal(self, api, analyst):
        """PRD 3.6: "The new execution opens with `status` `SCHEDULED` and
        `signage_status` `PENDING`, computes its `signage_due_date` as the
        `effective_date` less the zone's `signage_lead_days`, leaves
        `per_unit_markdown_cents`, `line_markdown_cents` and `price_cents_applied` at 0
        and `applied_at`, `posted_at`, `posted_by_user_id` and `verified_by_user_id`
        null, moves the referenced rung `PLANNED → SCHEDULED`, adds its `units_in_scope`
        to the plan's `projected_exit_units`, and bumps the plan's `version`."

        Design: Corner/validations/execution_scope_must_match_the_zone_type_and_the_step
        """
        sc = fx.approved_plan_scenario(api, effective_date="2026-11-16")

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"],
                    sc.step1["id"],
                    sc.west_zone["id"],
                    "STORE",
                    "2026-11-16",
                    200,
                    store_id=sc.store_0101["id"],
                ),
                analyst,
            ),
            201,
        )

        assert execution["execution_scope"] == "STORE"
        assert execution["store_id"] == sc.store_0101["id"]
        assert execution["signage_status"] == "PENDING"
        assert execution["signage_due_date"] == "2026-11-09"

        _rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 1


def _two_rung_approved_plan(api):
    """An APPROVED plan whose rungs sit on 2026-11-16 and 2026-11-30, both
    authored while the clock stood at 2026-10-10T00:00:00Z.
    """
    sc = fx.planned_scenario(api)
    sc["step1"] = fx.add_rung(api, sc.plan["id"], 1, "2026-11-16", 22.57)
    sc["step2"] = fx.add_rung(api, sc.plan["id"], 2, "2026-11-30", 32.50)
    fx.submit_plan(api, sc.plan["id"])
    sc["plan"] = fx.approve_plan(api, sc.plan["id"])
    return sc


class TestSignageLeadBoundary:
    """Scheduling is legal exactly while the signage window is still open."""

    def test_the_cut_off_date_itself_still_schedules(self, api, analyst):
        """PRD 2.7 rule 20: "Signage lead at scheduling: the scheduled `effective_date`
        minus the zone's `signage_lead_days` must be no earlier than the logical clock's
        current date, so the signage window has not already closed, else
        `ERR_SIGNAGE_LEAD_VIOLATION` (422)."

        Design: Corner/validations/signage_lead_boundary_accepts_the_due_date_and_rejects_the_next_day
        """
        sc = _two_rung_approved_plan(api)
        fx.set_clock(api, "2026-11-09T00:00:00Z")

        execution = validate_success(
            api.create_zone_execution(
                zone_execution_payload(
                    sc.plan["id"],
                    sc.step1["id"],
                    sc.west_zone["id"],
                    "ZONE",
                    "2026-11-16",
                    200,
                ),
                analyst,
            ),
            201,
        )

        assert execution["status"] == "SCHEDULED"
        assert execution["signage_status"] == "PENDING"
        assert execution["signage_due_date"] == "2026-11-09"

    def test_one_day_past_the_cut_off_is_refused(self, api, analyst):
        """PRD 3.6: "The signage window must still be open: the `effective_date` less the
        zone's `signage_lead_days` must not already be in the past relative to the logical
        clock's current date, else the execution could never be posted in time and is
        refused with `ERR_SIGNAGE_LEAD_VIOLATION`."

        Design: Corner/validations/signage_lead_boundary_accepts_the_due_date_and_rejects_the_next_day
        """
        sc = _two_rung_approved_plan(api)
        fx.set_clock(api, "2026-11-09T00:00:00Z")
        fx.schedule_execution(
            api,
            sc.plan["id"],
            sc.step1["id"],
            sc.west_zone["id"],
            "ZONE",
            "2026-11-16",
            200,
        )

        fx.set_clock(api, "2026-11-24T00:00:00Z")
        response = api.create_zone_execution(
            zone_execution_payload(
                sc.plan["id"],
                sc.step2["id"],
                sc.west_zone["id"],
                "ZONE",
                "2026-11-30",
                100,
            ),
            analyst,
        )
        validate_error(response, "ERR_SIGNAGE_LEAD_VIOLATION", 422)

        _rows, meta = validate_paginated(
            api.list_zone_executions(analyst, {"markdown_plan_id": sc.plan["id"]})
        )
        assert meta["total_count"] == 1
        assert fx.read_step(api, sc.step2["id"])["status"] == "PLANNED"
