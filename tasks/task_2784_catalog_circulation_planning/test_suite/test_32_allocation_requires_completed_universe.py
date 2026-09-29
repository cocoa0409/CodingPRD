"""A merge-purge run that exists is not a merge-purge run that succeeded.

The plan's first run is created before any segment exists, so it lands on the
FAILED branch with a universe of nobody. Allocation must still be refused: the guard
reads COMPLETED, not "a run row exists" and not "net names came back". Once the
segment exists a second run completes, and the same allocate call then works — while
the failed run stays FAILED rather than being swept up as SUPERSEDED.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    PLANNER,
    assert_merge_purge_names_conserved,
    create_merge_purge_run_payload,
    fetch_line,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    plan_version,
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


def _a_plan_whose_only_universe_failed(api) -> dict:
    """The run is created against a season with no segments at all, so its housefile
    gross contribution is zero. Only afterwards does S_A appear, along with a drop
    carrying one 20000-book line."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    failed_run = validate_success(
        api.create_merge_purge_run(
            plan["id"], create_merge_purge_run_payload(plan["version"], []), BROKER
        ),
        201,
    )
    segment = new_segment(season["id"], segment_code="S_A", **SCORING)
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    return {
        "season": season,
        "plan": plan,
        "failed_run": failed_run,
        "segment": segment,
        "drop": drop,
        "line": line,
    }


def _the_same_allocate_after_a_completed_run(api) -> dict:
    """The refused allocate, then a second run over the now-populated season, then
    the identical allocate again."""
    world = _a_plan_whose_only_universe_failed(api)
    world["refused"] = api.allocate_drop(world["drop"]["id"], PLANNER)
    validate_error(world["refused"], "ERR_MERGE_PURGE_REQUIRED", 409)

    world["good_run"] = validate_success(
        api.create_merge_purge_run(
            world["plan"]["id"],
            create_merge_purge_run_payload(plan_version(world["plan"]["id"]), []),
            BROKER,
        ),
        201,
    )
    world["allocated"] = validate_success(
        api.allocate_drop(world["drop"]["id"], PLANNER), 200
    )
    return world


class TestTheFailedBranchDoesNotSatisfyTheGuard:
    def test_an_empty_season_sends_the_run_down_the_failed_branch(self, api):
        """PRD §3.3: "When `net_mailable_names` is exactly zero the run takes the
        `PENDING → FAILED` branch instead, and the two branches diverge in ways that
        outlive the status field: the four name aggregates are still persisted for
        audit, but **no** rental moves to `NETTED` and no `net_names_delivered` is
        written, and **no** other merge-purge run of the plan is superseded — a
        previously completed universe survives a failed re-run intact."

        Design: Corner/validations/allocation_requires_a_completed_merge_purge_run_on_the_same_plan
        """
        world = _a_plan_whose_only_universe_failed(api)
        run = world["failed_run"]

        assert run["status"] == "FAILED"
        assert run["gross_input_names"] == 0
        assert run["net_mailable_names"] == 0
        assert run["suppressed_names"] == 0
        assert run["duplicates_removed"] == 0
        assert run["housefile_leaf_segment_count"] == 0
        assert_merge_purge_names_conserved(run)

    def test_allocation_is_refused_while_the_only_run_is_failed(self, api):
        """PRD §3.5: "Allocation only runs when the ground is prepared. The owning
        plan must be editable, the drop must be in `PLANNED` production status, and the
        plan must already have a merge-purge run in `COMPLETED` status — otherwise
        `ERR_MERGE_PURGE_REQUIRED`."

        Design: Corner/validations/allocation_requires_a_completed_merge_purge_run_on_the_same_plan
        """
        world = _a_plan_whose_only_universe_failed(api)

        response = api.allocate_drop(world["drop"]["id"], PLANNER)
        validate_error(response, "ERR_MERGE_PURGE_REQUIRED", 409)

        line = fetch_line(world["line"]["id"])
        assert line["status"] == "PROPOSED"
        assert line["allocated_quantity"] == 0
        assert line["committed_cost_cents"] == 0

        plan = fetch_plan(world["plan"]["id"])
        assert plan["committed_cost_cents"] == 0
        assert plan["uncommitted_budget_cents"] == 20000000


class TestASecondRunRestoresTheUniverse:
    def test_the_second_run_completes_over_the_now_populated_season(self, api):
        """PRD §3.3: "A run is born in `PENDING` and immediately forks on that final
        number. When `net_mailable_names` is greater than zero the run takes the
        `PENDING → COMPLETED` branch: `gross_input_names`, `suppressed_names`,
        `duplicates_removed`, `net_mailable_names`, `processing_order` and
        `housefile_leaf_segment_count` are all persisted; every rental in the input set
        moves `DELIVERED → NETTED` with its `net_names_delivered` written to its
        post-dedup count; every *other* merge-purge run of the same plan sitting in
        `COMPLETED` moves to `SUPERSEDED`; the accepted version is stored as
        `observed_plan_version`; and the plan's `version` increments by one."

        Design: Corner/validations/allocation_requires_a_completed_merge_purge_run_on_the_same_plan
        """
        world = _the_same_allocate_after_a_completed_run(api)
        run = world["good_run"]

        assert run["status"] == "COMPLETED"
        assert run["gross_input_names"] == 30000
        assert run["net_mailable_names"] == 30000
        assert run["housefile_leaf_segment_count"] == 1
        assert_merge_purge_names_conserved(run)

    def test_the_failed_run_is_never_superseded(self, api):
        """PRD §3.3: "A run moves `COMPLETED → SUPERSEDED` when a later run on the
        same plan takes the completed branch, or when the plan itself is cancelled;
        nothing happens beyond the status change and the row's `updated_at` refresh."

        Design: Corner/validations/allocation_requires_a_completed_merge_purge_run_on_the_same_plan
        """
        world = _the_same_allocate_after_a_completed_run(api)

        rows, meta = validate_paginated(
            api.list_merge_purge_runs(world["plan"]["id"], BROKER)
        )
        assert meta["total_count"] == 2
        by_id = {row["id"]: row for row in rows}
        assert by_id[world["failed_run"]["id"]]["status"] == "FAILED"
        assert by_id[world["good_run"]["id"]]["status"] == "COMPLETED"

    def test_the_identical_allocate_now_funds_the_line(self, api):
        """PRD §3.5: "The line's `allocated_quantity` is the smallest of its
        `requested_quantity`, its audience cap and its budget cap."

        Design: Corner/validations/allocation_requires_a_completed_merge_purge_run_on_the_same_plan
        """
        world = _the_same_allocate_after_a_completed_run(api)

        assert world["allocated"]["planned_quantity"] == 20000
        line = fetch_line(world["line"]["id"])
        assert line["status"] == "ALLOCATED"
        assert line["allocated_quantity"] == 20000
