"""What the server must refuse, and what it must refuse to believe.

Two halves of the same schema contract. Fields the client is required to supply
must be rejected when absent rather than quietly defaulted, and values outside
their declared type or range must be rejected even when the number alone looks
harmless. Fields the server derives must be derived from the real inputs, so a
client that hand-writes a segment tier, a line's allocation or a plan's status
changes nothing at all.
"""
from test_helpers import (
    ADMIN,
    ANALYST,
    BROKER,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    assert_circulation_line,
    assert_circulation_plan,
    assert_drop,
    assert_housefile_segment,
    create_contact_event_payload,
    create_drop_payload,
    create_housefile_line_payload,
    create_page_placement_payload,
    create_plan_payload,
    create_rental_payload,
    create_segment_payload,
    create_presort_batch_payload,
    fetch_plan,
    iso_utc,
    new_drop,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

CLIENT_SUPPLIED_ID = "11111111-1111-1111-1111-111111111111"
CLIENT_SUPPLIED_INSTANT = "2000-01-01T00:00:00.000Z"


def _season_plan_and_drop() -> dict:
    """Season FW26, plan P1 at a 20000000-cent budget, and drop 1 of 64 pages
    landing 2026-09-15."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    return {"season": season, "plan": plan, "drop": drop}


class TestMissingRequiredFields:
    def test_four_creates_each_lose_exactly_one_required_field(self, api):
        """PRD §2.10: "**Request body satisfies its schema** on every write
        endpoint: required fields present, enum values in range, integers inside
        their declared bounds, no negative money or quantities — otherwise
        `ERR_INVALID_REQUEST` (422)."

        Design: Corner/entities/missing_required_fields_are_rejected_with_invalid_request
        """
        world = _season_plan_and_drop()
        season_id = world["season"]["id"]

        segment_payload = create_segment_payload(season_id)
        del segment_payload["segment_code"]
        validate_error(
            api.create_segment(segment_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        rental_payload = create_rental_payload(
            season_id,
            list_source_name="COOP-A",
            requested_gross_names=25000,
            housefile_overlap_bps=2000,
            inter_list_overlap_bps=0,
        )
        del rental_payload["cost_per_thousand_cents"]
        validate_error(
            api.create_rental(rental_payload, BROKER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        placement_payload = create_page_placement_payload(product_name="Wool throw")
        del placement_payload["sq_in_offset"]
        validate_error(
            api.create_page_placement(world["drop"]["id"], placement_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        drop_payload = create_drop_payload(drop_number=2)
        del drop_payload["in_home_date"]
        validate_error(
            api.create_drop(world["plan"]["id"], drop_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

    def test_an_absent_offset_is_never_defaulted_and_nothing_is_stored(self, api):
        """PRD §3.4: "A **page placement** puts one SKU in one rectangle of one
        page, and it carries a `product_sku` that must be unique within the drop
        (a repeat is rejected with `ERR_DUPLICATE_PLACEMENT_SKU`), a
        `product_name` for display, a `unit_price_cents` catalog selling price and
        a `unit_cogs_cents` cost of goods — neither negative — a
        `demand_per_sq_inch_cents` figure recording the historical demand in cents
        this SKU generates per square inch when placed in an ordinary inside
        position, a `page_number`, a `sq_in_offset` measuring the left edge of the
        occupied area in square inches consumed from the page origin, a
        `square_inches` area greater than zero, and a `placement_position` drawn
        from `FRONT_COVER`, `HOT_SPOT`, `INSIDE` and `BACK_COVER`."

        Design: Corner/entities/missing_required_fields_are_rejected_with_invalid_request
        """
        world = _season_plan_and_drop()
        season_id = world["season"]["id"]
        plan_id = world["plan"]["id"]
        drop_id = world["drop"]["id"]

        placement_payload = create_page_placement_payload(product_name="Wool throw")
        del placement_payload["sq_in_offset"]
        validate_error(
            api.create_page_placement(drop_id, placement_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        segment_payload = create_segment_payload(season_id)
        del segment_payload["segment_code"]
        validate_error(
            api.create_segment(segment_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        rental_payload = create_rental_payload(season_id, list_source_name="COOP-A")
        del rental_payload["cost_per_thousand_cents"]
        validate_error(
            api.create_rental(rental_payload, BROKER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        drop_payload = create_drop_payload(drop_number=2)
        del drop_payload["in_home_date"]
        validate_error(
            api.create_drop(plan_id, drop_payload, PLANNER),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        _placements, placement_meta = validate_paginated(
            api.list_page_placements(drop_id, PLANNER)
        )
        assert placement_meta["total_count"] == 0

        _segments, segment_meta = validate_paginated(
            api.list_segments(PLANNER, {"season_id": season_id})
        )
        assert segment_meta["total_count"] == 0

        _rentals, rental_meta = validate_paginated(
            api.list_season_rentals(season_id, BROKER)
        )
        assert rental_meta["total_count"] == 0

        drops, drop_meta = validate_paginated(api.list_plan_drops(plan_id, PLANNER))
        assert drop_meta["total_count"] == 1
        assert [row["drop_number"] for row in drops] == [1]


class TestComputedFieldsIgnoreTheClient:
    def test_a_hand_written_tier_loses_to_the_recency_frequency_monetary_score(
        self, api
    ):
        """PRD §3.1: "The three point awards are added together and the sum is
        multiplied by ten to yield `rfm_score`, an exact integer between 0 and 1000
        that never involves rounding."

        Design: Corner/entities/computed_fields_are_recomputed_when_the_client_sends_an_extra_field
        """
        world = _season_plan_and_drop()

        payload = create_segment_payload(
            world["season"]["id"],
            segment_code="S_A",
            rfm_score=10,
            segment_tier="DORMANT",
            contact_strategy="PREMIUM_FULL",
            fatigue_score=5000,
            rollup_housefile_count=1,
        )
        segment = validate_success(api.create_segment(payload, PLANNER), 201)

        assert_housefile_segment(segment)
        assert segment["rfm_score"] == 1000
        assert segment["segment_tier"] == "BEST"
        assert segment["contact_strategy"] == "PREMIUM_FULL"
        assert segment["fatigue_score"] == 0
        assert segment["rollup_housefile_count"] == 30000
        assert segment["housefile_count"] == 30000
        assert segment["suppressed_at"] is None

    def test_a_hand_written_allocation_loses_to_the_planning_view_of_the_line(
        self, api
    ):
        """PRD §3.5: "The gross order count is `requested_quantity` multiplied by
        `effective_response_bps`, divided by ten thousand, floored to a whole
        number of orders, and `gross_forecast_demand_cents` is that order count
        multiplied by the resolved average order value."

        Design: Corner/entities/computed_fields_are_recomputed_when_the_client_sends_an_extra_field
        """
        world = _season_plan_and_drop()
        plan_id = world["plan"]["id"]
        segment = new_segment(world["season"]["id"], segment_code="S_A")

        line = validate_success(
            api.create_line(
                world["drop"]["id"],
                create_housefile_line_payload(
                    segment["id"],
                    requested_quantity=20000,
                    allocated_quantity=999,
                    committed_cost_cents=777,
                    unit_cost_cents=1,
                    status="ALLOCATED",
                ),
                PLANNER,
            ),
            201,
        )

        assert_circulation_line(line)
        assert line["allocated_quantity"] == 0
        assert line["committed_cost_cents"] == 0
        assert line["unit_cost_cents"] == 0
        assert line["status"] == "PROPOSED"
        assert line["allocation_rank"] == 0
        assert line["effective_response_bps"] == 620
        assert line["gross_forecast_demand_cents"] == 22940000

        plan = fetch_plan(plan_id)
        assert plan["committed_cost_cents"] == 0
        assert plan["uncommitted_budget_cents"] == 20000000


class TestSystemFieldsAreServerMinted:
    def test_a_client_supplied_id_and_version_are_both_discarded(self, api):
        """PRD §2.4: "`updated_at` is refreshed to the current instant on every
        mutation of the row, and `version` is an integer that starts at 1 on
        creation and increments by exactly 1 on every mutation — including
        mutations the row's owner did not request, such as a cascade reaching it
        from another aggregate."

        Design: Corner/entities/system_fields_are_server_minted_and_client_values_are_ignored_input
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)

        plan = validate_success(
            api.create_plan(
                create_plan_payload(
                    season["id"],
                    plan_code="P1",
                    budget_cents=20000000,
                    id=CLIENT_SUPPLIED_ID,
                    version=99,
                    created_at=CLIENT_SUPPLIED_INSTANT,
                    updated_at=CLIENT_SUPPLIED_INSTANT,
                    status="APPROVED",
                    committed_cost_cents=5000,
                ),
                PLANNER,
            ),
            201,
        )

        assert_circulation_plan(plan)
        assert plan["id"] != CLIENT_SUPPLIED_ID
        assert plan["version"] == 1
        assert plan["created_at"] != CLIENT_SUPPLIED_INSTANT
        assert plan["updated_at"] != CLIENT_SUPPLIED_INSTANT

    def test_the_initial_state_and_the_zero_ledger_beat_the_payload(self, api):
        """PRD §3.6: "The plan is born in `DRAFT` with `revision_round` 0,
        `committed_cost_cents` 0, `uncommitted_budget_cents` equal to
        `budget_cents`, all three of `costed_by_user_id`, `submitted_by_user_id`
        and `approved_by_user_id` null, and `planned_cost_cents`,
        `planned_demand_cents` and `planned_contribution_cents` all 0."

        Design: Corner/entities/system_fields_are_server_minted_and_client_values_are_ignored_input
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)

        plan = validate_success(
            api.create_plan(
                create_plan_payload(
                    season["id"],
                    plan_code="P1",
                    budget_cents=20000000,
                    status="APPROVED",
                    committed_cost_cents=5000,
                ),
                PLANNER,
            ),
            201,
        )

        assert plan["status"] == "DRAFT"
        assert plan["committed_cost_cents"] == 0
        assert plan["uncommitted_budget_cents"] == 20000000
        assert plan["revision_round"] == 0
        assert plan["costed_by_user_id"] is None
        assert plan["submitted_by_user_id"] is None
        assert plan["approved_by_user_id"] is None
        assert plan["planned_cost_cents"] == 0
        assert plan["planned_demand_cents"] == 0
        assert plan["planned_contribution_cents"] == 0

    def test_the_two_system_datetimes_start_null_rather_than_echoing_the_payload(
        self, api
    ):
        """PRD §3.4: "Every other computed field on a fresh drop starts at its
        zero value: `requested_quantity_total`, `planned_quantity`,
        `print_rebate_bps`, `printing_cents_per_book`, `paper_cents_per_book`,
        `postage_cents_per_book`, `cost_per_book_cents`,
        `provisional_cost_per_book_cents`, `postage_total_cents` and
        `automation_share_bps` are all 0, `automation_qualified` is false,
        `cost_basis` reads `ESTIMATED_POSTAGE`, and `mailed_at` is null."

        Design: Corner/entities/system_fields_are_server_minted_and_client_values_are_ignored_input
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)
        plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)

        drop = validate_success(
            api.create_drop(
                plan["id"],
                create_drop_payload(
                    drop_number=1,
                    in_home_date=iso_utc("2026-09-15"),
                    page_count=64,
                    id=CLIENT_SUPPLIED_ID,
                    version=99,
                    mailed_at=CLIENT_SUPPLIED_INSTANT,
                    production_status="MAILED",
                ),
                PLANNER,
            ),
            201,
        )
        assert_drop(drop)
        assert drop["id"] != CLIENT_SUPPLIED_ID
        assert drop["version"] == 1
        assert drop["mailed_at"] is None
        assert drop["production_status"] == "PLANNED"
        assert drop["measurement_status"] == "PENDING"

        segment = validate_success(
            api.create_segment(
                create_segment_payload(
                    season["id"],
                    segment_code="S_A",
                    id=CLIENT_SUPPLIED_ID,
                    version=99,
                    suppressed_at=CLIENT_SUPPLIED_INSTANT,
                ),
                PLANNER,
            ),
            201,
        )
        assert segment["id"] != CLIENT_SUPPLIED_ID
        assert segment["version"] == 1
        assert segment["suppressed_at"] is None


def _universe_and_drop_ready_for_bad_payloads() -> dict:
    """Season FW26 with segment S_A, plan P1 carrying a COMPLETED housefile-only
    merge-purge run, and drop 1 of 64 pages still in PLANNED."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run = run_merge_purge(plan["id"])
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "run": run,
        "drop": drop,
    }


class TestTypeAndRangeConstraints:
    def test_an_unknown_presort_tier_and_a_negative_rental_cpm_are_both_refused(
        self, api
    ):
        """PRD §3.7: "A planner records the mail stream as a set of **postal
        presort batches** under the drop, each carrying a `declared_tier` — the
        tier the mail shop *claims* for that batch, one of `FIVE_DIGIT`,
        `THREE_DIGIT`, `AADC` or `MIXED_AADC` — and a `piece_count` greater than
        zero."

        Design: Corner/entities/invalid_enum_and_negative_quantity_payloads_are_rejected
        """
        world = _universe_and_drop_ready_for_bad_payloads()
        drop_id = world["drop"]["id"]

        validate_error(
            api.create_presort_batch(
                drop_id, create_presort_batch_payload(20000, "TWO_DIGIT"), PLANNER
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        validate_error(
            api.create_rental(
                create_rental_payload(
                    world["season"]["id"],
                    list_source_name="COOP-A",
                    requested_gross_names=25000,
                    cost_per_thousand_cents=-1,
                    housefile_overlap_bps=2000,
                    inter_list_overlap_bps=0,
                ),
                BROKER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        _batches, batch_meta = validate_paginated(
            api.list_presort_batches(drop_id, PLANNER)
        )
        assert batch_meta["total_count"] == 0

        _rentals, rental_meta = validate_paginated(
            api.list_season_rentals(world["season"]["id"], BROKER)
        )
        assert rental_meta["total_count"] == 0

    def test_a_zero_quantity_and_an_in_range_holdout_share_without_the_flag_fail(
        self, api
    ):
        """PRD §3.5: "A non-zero `holdout_pct_bps` on a line whose `is_holdout` is
        false is a contradiction and is rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/entities/invalid_enum_and_negative_quantity_payloads_are_rejected
        """
        world = _universe_and_drop_ready_for_bad_payloads()
        drop_id = world["drop"]["id"]
        segment_id = world["segment"]["id"]

        validate_error(
            api.create_line(
                drop_id,
                create_housefile_line_payload(segment_id, requested_quantity=0),
                PLANNER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        validate_error(
            api.create_line(
                drop_id,
                create_housefile_line_payload(
                    segment_id,
                    requested_quantity=5000,
                    is_holdout=False,
                    holdout_pct_bps=1000,
                ),
                PLANNER,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        _lines, meta = validate_paginated(api.list_lines(PLANNER, {"drop_id": drop_id}))
        assert meta["total_count"] == 0

        drop = validate_success(api.get_drop(drop_id, PLANNER), 200)
        assert drop["requested_quantity_total"] == 0

    def test_a_contact_channel_outside_the_three_named_ones_is_refused(self, api):
        """PRD §3.8: "A `MarketingAnalyst` logs a **contact event** by naming a
        `housefile_segment_id`, a `channel` of `MAIL`, `EMAIL` or `DIGITAL`, and a
        `contact_date` as an ISO 8601 UTC instant with three fractional digits."

        Design: Corner/entities/invalid_enum_and_negative_quantity_payloads_are_rejected
        """
        world = _universe_and_drop_ready_for_bad_payloads()
        segment_id = world["segment"]["id"]

        validate_error(
            api.create_contact_event(
                create_contact_event_payload(
                    segment_id, iso_utc("2026-08-01"), channel="SMS"
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_REQUEST.value,
            422,
        )

        _events, meta = validate_paginated(
            api.list_segment_contact_events(segment_id, ANALYST)
        )
        assert meta["total_count"] == 0

        segment = validate_success(api.get_segment(segment_id, ADMIN), 200)
        assert segment["fatigue_score"] == 0
        assert segment["version"] == 1
