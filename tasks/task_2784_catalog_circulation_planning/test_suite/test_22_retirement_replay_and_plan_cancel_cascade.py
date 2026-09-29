"""Retiring circulation once, and retiring a whole plan's worth of it at once.

Both halves turn on the same hazard: the credit that follows a line out of
`ALLOCATED` is an exact compensation, so anything that replays it corrupts the
plan ledger. A second void must therefore be refused rather than absorbed, and
the plan-wide cancel must credit only the lines that were still holding money —
an already-retired child has to be left exactly where it was.
"""
from test_helpers import (
    BROKER,
    CLOCK_START,
    DIRECTOR,
    PLANNER,
    ApiErrorId,
    allocate,
    assert_line_zeroed,
    assert_plan_budget_conserved,
    cost_plan,
    fetch_drop,
    fetch_line,
    fetch_plan,
    iso_utc,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    run_merge_purge,
    set_clock,
    setup_allocated_drop,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestVoidingATwiceRetiredLine:
    def test_the_second_void_is_refused_and_the_budget_is_credited_once(self, api):
        """PRD §3.5: "Retiring a line whose status is neither `PROPOSED` nor
        `ALLOCATED` is rejected with `ERR_INVALID_LINE_STATE`, and doing so on a
        drop that has moved past `PLANNED` is rejected with
        `ERR_INVALID_DROP_STATE`. `SUPPRESSED` and `VOIDED` are both terminal for a
        line."

        Design: Corner/state_machines/voiding_a_line_that_is_already_voided_is_rejected
        """
        set_clock(CLOCK_START)
        world = setup_allocated_drop()
        line_id = world["line"]["id"]
        plan_id = world["plan"]["id"]

        assert world["line"]["status"] == "ALLOCATED"
        assert world["line"]["committed_cost_cents"] == 4720000
        assert world["plan"]["committed_cost_cents"] == 4720000
        assert world["plan"]["uncommitted_budget_cents"] == 15280000

        voided = validate_success(api.void_line(line_id, PLANNER), 200)
        assert voided["status"] == "VOIDED"
        assert voided["committed_cost_cents"] == 0

        credited = fetch_plan(plan_id)
        assert credited["committed_cost_cents"] == 0
        assert credited["uncommitted_budget_cents"] == 20000000
        assert_plan_budget_conserved(credited)

        validate_error(
            api.void_line(line_id, PLANNER),
            ApiErrorId.ERR_INVALID_LINE_STATE.value,
            409,
        )

        after = fetch_plan(plan_id)
        assert after["committed_cost_cents"] == 0
        assert after["uncommitted_budget_cents"] == 20000000
        assert after["version"] == credited["version"]
        assert_plan_budget_conserved(after)

    def test_the_rejected_replay_leaves_the_retired_row_and_its_drop_alone(
        self, api
    ):
        """PRD §2.7: "At every observable moment, `budget_cents` equals
        `committed_cost_cents` plus `uncommitted_budget_cents` with no drift
        whatsoever. Allocation debits `committed_cost_cents`; voiding a line,
        suppressing a line through the fatigue cascade, and cancelling a plan each
        credit back *exactly* the amount that line froze, never a recomputed
        approximation of it."

        Design: Corner/state_machines/voiding_a_line_that_is_already_voided_is_rejected
        """
        set_clock(CLOCK_START)
        world = setup_allocated_drop()
        line_id = world["line"]["id"]
        drop_id = world["drop"]["id"]

        voided = validate_success(api.void_line(line_id, PLANNER), 200)
        voided_version = voided["version"]
        drop_after_void = fetch_drop(drop_id)

        validate_error(
            api.void_line(line_id, PLANNER),
            ApiErrorId.ERR_INVALID_LINE_STATE.value,
            409,
        )

        line = fetch_line(line_id)
        assert line["status"] == "VOIDED"
        assert line["version"] == voided_version
        assert_line_zeroed(line)

        drop = fetch_drop(drop_id)
        assert drop["requested_quantity_total"] == 0
        assert drop["planned_quantity"] == 0
        assert drop["version"] == drop_after_void["version"]

        lines, meta = validate_paginated(api.list_lines(PLANNER, {"drop_id": drop_id}))
        assert meta["total_count"] == 1
        assert lines[0]["status"] == "VOIDED"


def _costed_plan_with_one_live_and_one_already_retired_line(api) -> dict:
    """Season FW26 holding segments S_A and S_B, plan P1 at a 20000000-cent
    budget with one COMPLETED merge-purge run, and a single 64-page drop
    carrying a 20000-name S_A line and a 10000-name S_B line. Both lines are
    allocated, the S_B line is then retired by hand, and the plan is costed so
    its roll-ups hold real money before anything is cancelled."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment_a = new_segment(season["id"], segment_code="S_A")
    segment_b = new_segment(season["id"], segment_code="S_B")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run = run_merge_purge(plan["id"])
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line_a = new_housefile_line(drop["id"], segment_a["id"], requested_quantity=20000)
    line_b = new_housefile_line(drop["id"], segment_b["id"], requested_quantity=10000)
    allocate(drop["id"])

    retired_b = validate_success(api.void_line(line_b["id"], PLANNER), 200)
    costed = cost_plan(plan["id"])
    return {
        "season": season,
        "plan": costed,
        "run": run,
        "drop": fetch_drop(drop["id"]),
        "live_line": fetch_line(line_a["id"]),
        "retired_line": retired_b,
    }


class TestCancellingAPlanCascadesDownward:
    def test_the_cancel_voids_the_live_line_and_spares_the_retired_one(self, api):
        """PRD §3.6: "Every circulation line of the plan in status `PROPOSED` or
        `ALLOCATED` moves to `VOIDED` with `allocated_quantity`,
        `holdout_quantity`, `mailable_quantity`, `forecast_demand_cents`,
        `gross_margin_cents`, `circulation_cost_cents` and `contribution_cents` all
        set to 0, and each such line credits its `committed_cost_cents` back to the
        plan's `committed_cost_cents` before that field is zeroed on the line."

        Design: Corner/state_machines/cancelling_a_plan_cascades_down_to_lines_drops_and_merge_purge_runs
        """
        world = _costed_plan_with_one_live_and_one_already_retired_line(api)
        plan_id = world["plan"]["id"]
        live_id = world["live_line"]["id"]
        retired = world["retired_line"]

        assert world["live_line"]["status"] == "ALLOCATED"
        assert world["live_line"]["committed_cost_cents"] == 4720000
        assert retired["status"] == "VOIDED"
        assert world["plan"]["committed_cost_cents"] == 4720000
        assert world["plan"]["uncommitted_budget_cents"] == 15280000

        cancelled = validate_success(api.cancel_plan(plan_id, DIRECTOR), 200)
        assert cancelled["status"] == "CANCELLED"

        live = fetch_line(live_id)
        assert live["status"] == "VOIDED"
        assert_line_zeroed(live)
        assert live["version"] == world["live_line"]["version"] + 1

        untouched = fetch_line(retired["id"])
        assert untouched["status"] == "VOIDED"
        assert untouched["version"] == retired["version"]
        assert_line_zeroed(untouched)

    def test_the_drop_the_universe_and_the_budget_all_follow_the_plan_down(self, api):
        """PRD §3.6: "Every drop of the plan whose `production_status` is `PLANNED`
        or `PRESORTED` moves to `CANCELLED`, and a drop cancelled out of `PRESORTED`
        also has its presort batch rows deleted; each such drop's `version`
        increments by one. Every merge-purge run of the plan in `COMPLETED` status
        moves to `SUPERSEDED`."

        Design: Corner/state_machines/cancelling_a_plan_cascades_down_to_lines_drops_and_merge_purge_runs
        """
        world = _costed_plan_with_one_live_and_one_already_retired_line(api)
        plan_id = world["plan"]["id"]
        drop_id = world["drop"]["id"]

        assert world["drop"]["production_status"] == "PLANNED"
        assert world["run"]["status"] == "COMPLETED"
        assert world["plan"]["status"] == "COSTED"
        assert world["plan"]["planned_cost_cents"] > 0
        assert world["plan"]["planned_demand_cents"] > 0
        drop_version_before = world["drop"]["version"]

        cancelled = validate_success(api.cancel_plan(plan_id, DIRECTOR), 200)

        assert cancelled["committed_cost_cents"] == 0
        assert cancelled["uncommitted_budget_cents"] == 20000000
        assert cancelled["planned_cost_cents"] == 0
        assert cancelled["planned_demand_cents"] == 0
        assert cancelled["planned_contribution_cents"] == 0
        assert cancelled["version"] == world["plan"]["version"] + 1
        assert_plan_budget_conserved(cancelled)

        drop = fetch_drop(drop_id)
        assert drop["production_status"] == "CANCELLED"
        assert drop["measurement_status"] == "PENDING"
        assert drop["version"] == drop_version_before + 1

        runs, meta = validate_paginated(api.list_merge_purge_runs(plan_id, BROKER))
        assert meta["total_count"] == 1
        assert runs[0]["id"] == world["run"]["id"]
        assert runs[0]["status"] == "SUPERSEDED"
