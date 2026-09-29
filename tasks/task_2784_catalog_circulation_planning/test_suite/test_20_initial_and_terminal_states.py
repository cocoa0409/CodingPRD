"""Where every row starts, and the doors that are bolted once it stops.

The interesting initial states are the ones that arrive in pairs or that are
never observable: a drop initialises two independent dimensions inside one
create, and a merge-purge run's declared first state is resolved before the
create response is even written. At the other end of the walk, a cancelled plan
and a cancelled rental must refuse every edge that leaves them — including a
second cancel, which is not idempotent because cancelling credits money back.
"""
from test_helpers import (
    ANALYST,
    BROKER,
    CLOCK_START,
    DIRECTOR,
    PLANNER,
    ApiErrorId,
    allocate,
    assert_drop,
    assert_circulation_line,
    assert_circulation_plan,
    assert_merge_purge_run,
    assert_test_cell,
    create_merge_purge_run_payload,
    create_test_cell_payload,
    fetch_plan,
    fetch_rental,
    iso_utc,
    model_rental_payload,
    new_drop,
    new_housefile_line,
    new_plan,
    new_rental_in_state,
    new_season,
    new_segment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


def _rows_as_they_were_created(api) -> dict:
    """Season FW26, segment S_A, plan P1, one housefile-only merge-purge run, a
    64-page drop landing 2026-09-15 and a 20000-name line — every row captured
    exactly as its own create call reported it."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    segment = new_segment(season["id"], segment_code="S_A")
    plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
    run = validate_success(
        api.create_merge_purge_run(
            plan["id"], create_merge_purge_run_payload(plan["version"], []), BROKER
        ),
        201,
    )
    drop = new_drop(
        plan["id"], drop_number=1, in_home_date=iso_utc("2026-09-15"), page_count=64
    )
    line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
    return {
        "season": season,
        "segment": segment,
        "plan": plan,
        "run": run,
        "drop": drop,
        "line": line,
    }


class TestDeclaredInitialStates:
    def test_a_drop_initialises_two_dimensions_inside_one_create(self, api):
        """PRD §3.4: "The drop is created with `production_status` `PLANNED` and
        `measurement_status` `PENDING`, and the two dimensions advance entirely
        independently of one another thereafter."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        world = _rows_as_they_were_created(api)
        drop = world["drop"]

        assert_drop(drop)
        assert drop["production_status"] == "PLANNED"
        assert drop["measurement_status"] == "PENDING"
        assert drop["cost_basis"] == "ESTIMATED_POSTAGE"
        assert drop["mailed_at"] is None
        assert drop["version"] == 1

    def test_a_plan_opens_in_draft_and_its_first_line_lands_proposed(self, api):
        """PRD §3.5: "A newly created line lands in status `PROPOSED` with
        `allocation_rank` 0 and every allocated, committed, margin and cost field
        at 0."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        world = _rows_as_they_were_created(api)
        line = world["line"]
        plan = world["plan"]

        assert_circulation_line(line)
        assert line["status"] == "PROPOSED"
        assert line["allocation_rank"] == 0
        assert line["allocated_quantity"] == 0
        assert line["committed_cost_cents"] == 0
        assert line["unit_cost_cents"] == 0

        assert_circulation_plan(plan)
        assert plan["status"] == "DRAFT"
        assert plan["revision_round"] == 0

    def test_a_merge_purge_run_is_never_readable_in_its_declared_pending_state(
        self, api
    ):
        """PRD §3.3: "A run is born in `PENDING` and immediately forks on that
        final number."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        world = _rows_as_they_were_created(api)
        run = world["run"]

        assert_merge_purge_run(run)
        assert run["status"] == "COMPLETED"
        assert run["status"] != "PENDING"
        assert run["net_mailable_names"] == 30000

        runs, meta = validate_paginated(
            api.list_merge_purge_runs(world["plan"]["id"], BROKER)
        )
        assert meta["total_count"] == 1
        assert runs[0]["id"] == run["id"]
        assert runs[0]["status"] == "COMPLETED"

    def test_a_fresh_test_cell_is_planned_unmeasured_and_wholly_zeroed(self, api):
        """PRD §3.9: "A new cell lands in status `PLANNED` with `significance`
        `UNMEASURED` and with `responders`, `demand_cents`, `response_rate_bps` and
        `lift_bps` all 0."

        Design: Corner/state_machines/every_entity_starts_in_its_declared_initial_state
        """
        world = _rows_as_they_were_created(api)
        allocate(world["drop"]["id"])

        cell = validate_success(
            api.create_test_cell(
                world["line"]["id"],
                create_test_cell_payload(5000, "CONTROL", cell_code="C1"),
                ANALYST,
            ),
            201,
        )

        assert_test_cell(cell)
        assert cell["status"] == "PLANNED"
        assert cell["significance"] == "UNMEASURED"
        assert cell["responders"] == 0
        assert cell["demand_cents"] == 0
        assert cell["response_rate_bps"] == 0
        assert cell["lift_bps"] == 0
        assert cell["version"] == 1


def _a_cancelled_plan_and_a_cancelled_rental(api) -> dict:
    """Season FW26 holding plan P_DEAD cancelled while still DRAFT and rental
    R_DEAD cancelled while still REQUESTED."""
    set_clock(CLOCK_START)
    season = new_season(season_code="FW26", fiscal_year=2026)
    plan = new_plan(season["id"], plan_code="P_DEAD", budget_cents=20000000)
    dead_plan = validate_success(api.cancel_plan(plan["id"], DIRECTOR), 200)

    rental = new_rental_in_state(
        season["id"], "REQUESTED", list_source_name="COOP-DEAD"
    )
    dead_rental = validate_success(api.cancel_rental(rental["id"], BROKER), 200)
    return {"season": season, "plan": dead_plan, "rental": dead_rental}


class TestTerminalStateLockdown:
    def test_a_cancelled_plan_refuses_cost_approve_revision_and_a_second_cancel(
        self, api
    ):
        """PRD §3.6: "The plan's `uncommitted_budget_cents`, `planned_cost_cents`,
        `planned_demand_cents` and `planned_contribution_cents` are recomputed and
        its `version` increments by one. `CANCELLED` is terminal for a plan."

        Design: Corner/state_machines/terminal_state_transitions_are_rejected_on_cancelled_and_measured_rows
        """
        world = _a_cancelled_plan_and_a_cancelled_rental(api)
        plan_id = world["plan"]["id"]
        cancelled_version = world["plan"]["version"]

        assert world["plan"]["status"] == "CANCELLED"
        assert cancelled_version == 2

        validate_error(
            api.cost_plan(plan_id, PLANNER),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )
        validate_error(
            api.approve_plan(plan_id, DIRECTOR),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )
        validate_error(
            api.request_plan_revision(plan_id, DIRECTOR),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )
        validate_error(
            api.cancel_plan(plan_id, DIRECTOR),
            ApiErrorId.ERR_INVALID_PLAN_STATE.value,
            409,
        )

        plan = fetch_plan(plan_id)
        assert plan["status"] == "CANCELLED"
        assert plan["version"] == cancelled_version
        assert plan["committed_cost_cents"] == 0
        assert plan["uncommitted_budget_cents"] == 20000000

    def test_a_cancelled_rental_refuses_modeling_and_a_second_cancel(self, api):
        """PRD §3.2: "Cancellation is available from every live status —
        `REQUESTED`, `MODELED`, `ORDERED`, `DELIVERED` and `NETTED` all lead to
        `CANCELLED` — and takes an optional free-text `reason`. Attempting it on an
        already-`CANCELLED` rental is rejected with `ERR_INVALID_RENTAL_STATE`."

        Design: Corner/state_machines/terminal_state_transitions_are_rejected_on_cancelled_and_measured_rows
        """
        world = _a_cancelled_plan_and_a_cancelled_rental(api)
        rental_id = world["rental"]["id"]
        cancelled_version = world["rental"]["version"]

        assert world["rental"]["status"] == "CANCELLED"
        assert cancelled_version == 2

        validate_error(
            api.model_rental(rental_id, model_rental_payload(700), BROKER),
            ApiErrorId.ERR_INVALID_RENTAL_STATE.value,
            409,
        )
        validate_error(
            api.cancel_rental(rental_id, BROKER),
            ApiErrorId.ERR_INVALID_RENTAL_STATE.value,
            409,
        )

        rental = fetch_rental(rental_id)
        assert rental["status"] == "CANCELLED"
        assert rental["version"] == cancelled_version
        assert rental["coop_model_score"] == 0
        assert rental["gross_names"] == 0
        assert rental["net_names_delivered"] == 0
