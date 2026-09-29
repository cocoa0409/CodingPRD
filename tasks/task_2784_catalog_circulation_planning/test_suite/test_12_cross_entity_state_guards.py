"""Transitions a resource cannot make because of some other resource's state.

In each pair the target row is in a perfectly legal state of its own and every
other precondition is satisfied; the byte-identical call is refused and then
accepted purely because a neighbouring entity moved.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    DIRECTOR_9,
    PLANNER,
    PLANNER_1,
    ApiErrorId,
    allocate,
    approve_plan,
    assert_drop,
    assert_matchback_run,
    cost_plan,
    create_matchback_run_payload,
    fetch_drop,
    fetch_line,
    fetch_plan,
    fetch_rental,
    get_success_data,
    iso_utc,
    mail_drop,
    new_drop,
    new_housefile_line,
    new_plan,
    new_presort_batch,
    new_rental_in_state,
    new_rental_line,
    new_season,
    new_segment,
    presort_drop,
    run_merge_purge,
    set_clock,
    submit_plan,
    validate_error,
    validate_paginated,
)

MAIL_CLOCK = iso_utc("2026-09-20")


def _costed_plan_whose_drop_is_ready_to_presort() -> dict:
    """A drop in PLANNED whose batches already cover its planned quantity
    exactly, under a plan deliberately left in COSTED."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    allocated = allocate(drop["id"])
    new_presort_batch(drop["id"], 20000, "FIVE_DIGIT")
    costed = cost_plan(plan["id"], PLANNER_1)

    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "costed": costed,
        "drop": allocated,
        "line": line,
    }


class TestPresortIsGatedOnTheOwningPlan:
    def test_a_costed_plan_blocks_a_drop_that_is_otherwise_ready(self, api):
        """PRD §3.7: "The drop's owning plan must be in `APPROVED` status,
        otherwise `ERR_INVALID_PLAN_STATE` — presort is the first step that spends
        real money and it is gated on the director's signature."

        Design: Difficulty/cross_entity_state_dependency/presorting_a_drop_requires_its_plan_to_be_approved
        """
        world = _costed_plan_whose_drop_is_ready_to_presort()
        drop_id = world["drop"]["id"]

        assert world["drop"]["planned_quantity"] == 20000
        assert world["drop"]["production_status"] == "PLANNED"
        assert world["costed"]["status"] == "COSTED"

        validate_error(
            api.presort_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )

        drop = fetch_drop(drop_id)
        assert_drop(drop)
        assert drop["production_status"] == "PLANNED"
        assert drop["postage_total_cents"] == 0
        assert drop["cost_basis"] == "ESTIMATED_POSTAGE"

    def test_only_the_directors_approval_unlocks_the_presort(self, api):
        """PRD §3.7: "`printing_cents_per_book` and `paper_cents_per_book` are
        computed exactly as in §3.6, but `postage_cents_per_book` now becomes
        `postage_total_cents` divided by the drop's `planned_quantity`, rounded
        half up to whole cents, and the drop's `cost_basis` is set to
        `PRESORTED_ACTUAL`."

        Design: Difficulty/cross_entity_state_dependency/presorting_a_drop_requires_its_plan_to_be_approved
        """
        world = _costed_plan_whose_drop_is_ready_to_presort()
        drop_id = world["drop"]["id"]
        plan_id = world["plan"]["id"]

        validate_error(
            api.presort_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )

        under_review = submit_plan(plan_id, PLANNER_1)
        assert under_review["status"] == "UNDER_REVIEW"
        validate_error(
            api.presort_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )
        assert fetch_drop(drop_id)["production_status"] == "PLANNED"

        approve_plan(plan_id, DIRECTOR_9)
        presorted = presort_drop(drop_id)
        assert presorted["production_status"] == "PRESORTED"
        assert presorted["cost_basis"] == "PRESORTED_ACTUAL"
        assert presorted["postage_total_cents"] == 800000
        assert presorted["cost_per_book_cents"] == 221

        line = fetch_line(world["line"]["id"])
        assert line["circulation_cost_cents"] == 4420000
        assert line["contribution_cents"] == 5214800

        assert fetch_plan(plan_id)["status"] == "APPROVED"


def _rental_line_on_a_universe_that_never_netted_it() -> dict:
    """A PROPOSED rental line under a plan whose only completed merge-purge run
    was executed over an empty rental list, leaving the rental in DELIVERED."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    rental = new_rental_in_state(
        season["id"],
        coop_model_score=640,
        delivered_gross_names=25000,
        list_source_name="COOP-A",
        requested_gross_names=25000,
        cost_per_thousand_cents=8500,
        housefile_overlap_bps=2000,
        inter_list_overlap_bps=0,
    )
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    housefile_only_run = run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_rental_line(drop["id"], rental["id"], requested_quantity=25000)

    return {
        "season": season,
        "segment": segment,
        "rental": rental,
        "plan": plan,
        "housefile_only_run": housefile_only_run,
        "drop": drop,
        "line": line,
    }


class TestAllocationIsGatedOnTheRental:
    def test_a_delivered_rental_blocks_the_whole_allocate_call(self, api):
        """PRD §3.2: "Only a `NETTED` rental may back an allocated circulation
        line."

        Design: Difficulty/cross_entity_state_dependency/allocating_a_rental_line_requires_its_rental_to_be_netted
        """
        world = _rental_line_on_a_universe_that_never_netted_it()
        plan_id = world["plan"]["id"]

        assert world["rental"]["status"] == "DELIVERED"
        assert world["rental"]["net_names_delivered"] == 0
        assert world["rental"]["unit_cost_cents_per_name"] == 9
        assert world["housefile_only_run"]["status"] == "COMPLETED"
        assert world["housefile_only_run"]["net_mailable_names"] == 30000
        assert world["line"]["status"] == "PROPOSED"

        validate_error(
            api.allocate_drop(world["drop"]["id"], PLANNER),
            ApiErrorId.ERR_RENTAL_NOT_NETTED.value,
            409,
        )

        line = fetch_line(world["line"]["id"])
        assert line["status"] == "PROPOSED"
        assert line["allocated_quantity"] == 0
        assert line["committed_cost_cents"] == 0

        plan = fetch_plan(plan_id)
        assert plan["committed_cost_cents"] == 0
        assert plan["uncommitted_budget_cents"] == 20000000

        drop = fetch_drop(world["drop"]["id"])
        assert drop["planned_quantity"] == 0
        assert drop["provisional_cost_per_book_cents"] == 0

    def test_netting_the_rental_unblocks_it_and_caps_it_at_the_net_names(self, api):
        """PRD §3.5: "It computes an audience cap — the segment's
        `housefile_count` for a housefile line, the rental's
        `net_names_delivered` for a rental line — and a budget cap, which is the
        remaining budget divided by the line's `unit_cost_cents` and floored,
        because a partial book cannot be printed."

        Design: Difficulty/cross_entity_state_dependency/allocating_a_rental_line_requires_its_rental_to_be_netted
        """
        world = _rental_line_on_a_universe_that_never_netted_it()
        plan_id = world["plan"]["id"]
        rental_id = world["rental"]["id"]
        drop_id = world["drop"]["id"]

        validate_error(
            api.allocate_drop(drop_id, PLANNER),
            ApiErrorId.ERR_RENTAL_NOT_NETTED.value,
            409,
        )

        second_run = run_merge_purge(plan_id, [rental_id])
        assert second_run["gross_input_names"] == 55000
        assert second_run["duplicates_removed"] == 5000
        assert second_run["net_mailable_names"] == 50000

        rental = fetch_rental(rental_id)
        assert rental["status"] == "NETTED"
        assert rental["net_names_delivered"] == 20000

        runs, _meta = validate_paginated(api.list_merge_purge_runs(plan_id, PLANNER))
        first = next(
            row for row in runs if row["id"] == world["housefile_only_run"]["id"]
        )
        assert first["status"] == "SUPERSEDED"

        allocated_drop = allocate(drop_id)
        assert allocated_drop["provisional_cost_per_book_cents"] == 236
        assert allocated_drop["planned_quantity"] == 20000

        line = fetch_line(world["line"]["id"])
        assert line["status"] == "ALLOCATED"
        assert line["unit_cost_cents"] == 245
        assert line["allocated_quantity"] == 20000
        assert line["committed_cost_cents"] == 4900000

        plan = fetch_plan(plan_id)
        assert plan["committed_cost_cents"] == 4900000
        assert plan["uncommitted_budget_cents"] == 15100000


def _presorted_drop_waiting_for_the_mail_stream() -> dict:
    """A PRESORTED drop whose measurement dimension is still PENDING, with the
    logical clock already past its in-home date."""
    set_clock(CLOCK_START)
    season = new_season()
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run_merge_purge(plan["id"])

    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    allocate(drop["id"])
    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan.
    new_presort_batch(drop["id"], 20000, "FIVE_DIGIT")
    cost_plan(plan["id"], PLANNER_1)
    submit_plan(plan["id"], PLANNER_1)
    approve_plan(plan["id"], DIRECTOR_9)
    presorted = presort_drop(drop["id"])
    set_clock(MAIL_CLOCK)

    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "drop": presorted,
        "line": line,
        "created_measurement_status": drop["measurement_status"],
    }


class TestMatchbackIsGatedOnTheProductionDimension:
    def test_a_presorted_drop_refuses_a_run_even_with_a_fresh_version(self, api):
        """PRD §2.10: "**The requested transition exists from the entity's current
        state**, on every action endpoint — otherwise the matching 409 code:
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DROP_STATE`,
        `ERR_INVALID_MEASUREMENT_STATE`, `ERR_INVALID_RENTAL_STATE`,
        `ERR_INVALID_LINE_STATE`, `ERR_INVALID_TEST_CELL_STATE` or
        `ERR_INVALID_MATCHBACK_STATE`."

        Design: Difficulty/cross_entity_state_dependency/opening_a_matchback_run_requires_its_drop_to_be_mailed
        """
        world = _presorted_drop_waiting_for_the_mail_stream()
        drop_id = world["drop"]["id"]
        presorted_version = world["drop"]["version"]

        assert world["created_measurement_status"] == "PENDING"
        assert world["drop"]["production_status"] == "PRESORTED"

        error = validate_error(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    presorted_version, "LAST_TOUCH_MAIL", 30
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_STALE_DROP_VERSION.value

        drop = fetch_drop(drop_id)
        assert drop["measurement_status"] == "PENDING"
        assert drop["version"] == presorted_version

        _runs, meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        assert meta["total_count"] == 0

    def test_mailing_the_drop_opens_the_measurement_dimension(self, api):
        """PRD §3.9: "On the measurement dimension, a drop in `PENDING` moves
        `PENDING → MATCHBACK_OPEN` and the run is created in status `OPEN`."

        Design: Difficulty/cross_entity_state_dependency/opening_a_matchback_run_requires_its_drop_to_be_mailed
        """
        world = _presorted_drop_waiting_for_the_mail_stream()
        drop_id = world["drop"]["id"]
        presorted_version = world["drop"]["version"]

        validate_error(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    presorted_version, "LAST_TOUCH_MAIL", 30
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )

        mailed = mail_drop(drop_id)
        assert mailed["production_status"] == "MAILED"
        assert mailed["version"] == presorted_version + 1

        run = get_success_data(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    mailed["version"], "LAST_TOUCH_MAIL", 30
                ),
                ANALYST,
            )
        )
        assert_matchback_run(run)
        assert run["status"] == "OPEN"
        assert run["attribution_window_days"] == 30
        assert run["observed_drop_version"] == mailed["version"]
        assert run["matched_order_count"] == 0
        assert run["attributed_order_count"] == 0
        assert run["unmatched_order_count"] == 0
        assert run["attributed_demand_cents"] == 0

        drop = fetch_drop(drop_id)
        assert drop["measurement_status"] == "MATCHBACK_OPEN"
        assert drop["production_status"] == "MAILED"
