"""Replaying a completed transition must fail loudly rather than quietly.

Every one of these edges has a side effect that must not run twice: presort
prices the mail stream, mail synthesizes contact events and stamps an instant,
measuring a cell re-scores its siblings, and finalizing a matchback closes a
dimension for good. A handler that treats the second call as a harmless no-op
and answers 200 hides an operator error; one that re-runs the side effect
corrupts the row. Both must be 409 instead.
"""
from test_helpers import (
    ANALYST,
    CLOCK_START,
    PLANNER,
    ApiErrorId,
    api_client,
    approve_plan,
    assert_instant_equals,
    assert_matchback_run,
    assert_test_cell,
    cost_plan,
    create_matchback_run_payload,
    drop_version,
    fetch_drop,
    fetch_line,
    fetch_test_cell,
    iso_utc,
    measure_test_cell_payload,
    new_presort_batch,
    set_clock,
    setup_allocated_drop,
    setup_mailed_drop,
    submit_plan,
    setup_measured_control_and_test_cells,
    validate_error,
    validate_paginated,
    validate_success,
)

MAIL_INSTANT = iso_utc("2026-09-15", 9)


def _approved_drop_with_its_mail_stream_recorded() -> dict:
    """An APPROVED plan whose single 64-page drop has 20000 books allocated and a
    single FIVE_DIGIT presort batch covering them exactly, with the logical clock
    moved to nine in the morning of the in-home date so mailing is permitted."""
    set_clock(CLOCK_START)
    world = setup_allocated_drop()
    assert world["drop"]["planned_quantity"] == 20000
    # PRD §2.10 confines POST /drops/{id}/presort-batches to an editable plan,
    # so the mail stream is recorded before the plan leaves DRAFT.
    world["batch"] = new_presort_batch(world["drop"]["id"], 20000, "FIVE_DIGIT")
    world["plan"] = cost_plan(world["plan"]["id"])
    world["plan"] = submit_plan(world["plan"]["id"])
    world["plan"] = approve_plan(world["plan"]["id"])
    world["drop"] = fetch_drop(world["drop"]["id"])
    world["line"] = fetch_line(world["line"]["id"])
    set_clock(MAIL_INSTANT)
    return world


class TestProductionEdgesRefuseAReplay:
    def test_presort_mail_and_deliver_each_walk_once_and_then_409(self, api):
        """PRD §2.10: "**The requested transition exists from the entity's current
        state**, on every action endpoint — otherwise the matching 409 code:
        `ERR_INVALID_PLAN_STATE`, `ERR_INVALID_DROP_STATE`,
        `ERR_INVALID_MEASUREMENT_STATE`, `ERR_INVALID_RENTAL_STATE`,
        `ERR_INVALID_LINE_STATE`, `ERR_INVALID_TEST_CELL_STATE` or
        `ERR_INVALID_MATCHBACK_STATE`."

        Design: Corner/state_machines/repeating_a_completed_production_transition_is_rejected_not_ignored
        """
        world = _approved_drop_with_its_mail_stream_recorded()
        drop_id = world["drop"]["id"]

        presorted = validate_success(api.presort_drop(drop_id, PLANNER), 200)
        assert presorted["production_status"] == "PRESORTED"
        assert presorted["cost_basis"] == "PRESORTED_ACTUAL"
        validate_error(
            api.presort_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )

        mailed = validate_success(api.mail_drop(drop_id, PLANNER), 200)
        assert mailed["production_status"] == "MAILED"
        validate_error(
            api.mail_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )

        delivered = validate_success(api.deliver_drop(drop_id, PLANNER), 200)
        assert delivered["production_status"] == "DELIVERED"
        validate_error(
            api.deliver_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )

    def test_the_rejected_second_mail_neither_restamps_nor_re_cascades(self, api):
        """PRD §3.7: "Mailing takes the drop `PRESORTED → MAILED`, requires the
        drop's `in_home_date` to be at or before the logical clock's current value
        (an earlier attempt is rejected with `ERR_INVALID_DROP_STATE`), and stamps
        `mailed_at` with the logical clock's current instant."

        Design: Corner/state_machines/repeating_a_completed_production_transition_is_rejected_not_ignored
        """
        world = _approved_drop_with_its_mail_stream_recorded()
        drop_id = world["drop"]["id"]

        validate_success(api.presort_drop(drop_id, PLANNER), 200)
        mailed = validate_success(api.mail_drop(drop_id, PLANNER), 200)
        assert_instant_equals(mailed["mailed_at"], MAIL_INSTANT, "mailed_at")
        mailed_version = mailed["version"]

        validate_error(
            api.mail_drop(drop_id, PLANNER),
            ApiErrorId.ERR_INVALID_DROP_STATE.value,
            409,
        )

        drop = fetch_drop(drop_id)
        assert drop["production_status"] == "MAILED"
        assert_instant_equals(drop["mailed_at"], MAIL_INSTANT, "mailed_at")
        assert drop["version"] == mailed_version

        _events, event_meta = validate_paginated(
            api.list_drop_contact_events(drop_id, ANALYST)
        )
        assert event_meta["total_count"] == 1

        _batches, batch_meta = validate_paginated(
            api.list_presort_batches(drop_id, PLANNER)
        )
        assert batch_meta["total_count"] == 1


class TestMeasuredTestCellIsTerminal:
    def test_a_second_measure_is_refused_and_the_readout_survives_intact(self, api):
        """PRD §3.9: "A cell already in `MEASURED` cannot be measured again and is
        rejected with `ERR_INVALID_TEST_CELL_STATE`; `MEASURED` is terminal."

        Design: Corner/state_machines/measuring_an_already_measured_test_cell_is_rejected
        """
        set_clock(CLOCK_START)
        world = setup_measured_control_and_test_cells()
        test_cell = world["test_cell"]
        control_cell = world["control_cell"]

        assert_test_cell(test_cell)
        assert test_cell["status"] == "MEASURED"
        assert test_cell["response_rate_bps"] == 600
        assert test_cell["lift_bps"] == 5000
        assert control_cell["response_rate_bps"] == 400
        assert control_cell["lift_bps"] == 0
        measured_version = test_cell["version"]

        validate_error(
            api.measure_test_cell(
                test_cell["id"], measure_test_cell_payload(4000, 74000000), ANALYST
            ),
            ApiErrorId.ERR_INVALID_TEST_CELL_STATE.value,
            409,
        )

        again = fetch_test_cell(test_cell["id"])
        assert again["responders"] == 300
        assert again["response_rate_bps"] == 600
        assert again["lift_bps"] == 5000
        assert again["version"] == measured_version

        control = fetch_test_cell(control_cell["id"])
        assert control["response_rate_bps"] == 400
        assert control["lift_bps"] == 0
        assert control["significance"] == "INSUFFICIENT_CONTROL"


def _open_matchback_run(drop_id, expected_drop_version, variant="LAST_TOUCH_MAIL"):
    """Open a matchback read against the drop's current version."""
    return api_client.create_matchback_run(
        drop_id,
        create_matchback_run_payload(expected_drop_version, variant, 30),
        ANALYST,
    )


def _one_superseded_and_one_finalized_matchback_read() -> dict:
    """A MAILED drop read twice: RUN_A is retired by RUN_B's create, and RUN_B is
    then finalized, closing the drop's measurement dimension."""
    set_clock(CLOCK_START)
    world = setup_mailed_drop()
    drop_id = world["drop"]["id"]

    run_a = validate_success(
        _open_matchback_run(drop_id, drop_version(drop_id)),
        201,
    )
    run_b = validate_success(
        _open_matchback_run(drop_id, drop_version(drop_id)),
        201,
    )
    finalized = validate_success(
        api_client.finalize_matchback_run(run_b["id"], ANALYST), 200
    )
    world["run_a"] = run_a
    world["run_b"] = finalized
    world["drop"] = fetch_drop(drop_id)
    return world


class TestFinalizingARunThatIsNotOpen:
    def test_refinalizing_a_finalized_run_is_refused(self, api):
        """PRD §3.9: "Finalizing a run takes it `OPEN → FINALIZED`, requires the
        run to be in `OPEN` (otherwise `ERR_INVALID_MATCHBACK_STATE`) and requires
        its drop to be in `MATCHBACK_OPEN` (otherwise
        `ERR_INVALID_MEASUREMENT_STATE`)."

        Design: Corner/state_machines/finalizing_a_matchback_run_that_is_not_open_is_rejected
        """
        world = _one_superseded_and_one_finalized_matchback_read()
        run_b = world["run_b"]

        assert_matchback_run(run_b)
        assert run_b["status"] == "FINALIZED"
        assert run_b["finalized_at"] is not None
        assert_instant_equals(
            run_b["finalized_at"], iso_utc("2026-09-15"), "finalized_at"
        )
        assert world["drop"]["measurement_status"] == "MATCHBACK_CLOSED"

        validate_error(
            api.finalize_matchback_run(run_b["id"], ANALYST),
            ApiErrorId.ERR_INVALID_MATCHBACK_STATE.value,
            409,
        )

        runs, meta = validate_paginated(api.list_matchback_runs(world["drop"]["id"], ANALYST))
        assert meta["total_count"] == 2
        stored = next(row for row in runs if row["id"] == run_b["id"])
        assert stored["status"] == "FINALIZED"
        assert_instant_equals(
            stored["finalized_at"], run_b["finalized_at"], "finalized_at"
        )
        assert stored["version"] == run_b["version"]

    def test_a_run_retired_by_a_later_read_can_never_be_finalized(self, api):
        """PRD §3.9: "A drop already in `MATCHBACK_OPEN` takes a self-loop: every
        existing run of that drop in status `OPEN` or `FINALIZED` moves to
        `SUPERSEDED` with its own `version` incremented by one, and a fresh run is
        created in `OPEN`."

        Design: Corner/state_machines/finalizing_a_matchback_run_that_is_not_open_is_rejected
        """
        world = _one_superseded_and_one_finalized_matchback_read()
        run_a_id = world["run_a"]["id"]
        assert world["run_a"]["status"] == "OPEN"

        runs, _meta = validate_paginated(
            api.list_matchback_runs(world["drop"]["id"], ANALYST)
        )
        retired = next(row for row in runs if row["id"] == run_a_id)
        assert retired["status"] == "SUPERSEDED"
        assert retired["finalized_at"] is None
        assert retired["version"] == world["run_a"]["version"] + 1

        validate_error(
            api.finalize_matchback_run(run_a_id, ANALYST),
            ApiErrorId.ERR_INVALID_MATCHBACK_STATE.value,
            409,
        )

        runs_after, _meta_after = validate_paginated(
            api.list_matchback_runs(world["drop"]["id"], ANALYST)
        )
        still_retired = next(row for row in runs_after if row["id"] == run_a_id)
        assert still_retired["status"] == "SUPERSEDED"
        assert still_retired["finalized_at"] is None
        assert still_retired["version"] == retired["version"]


class TestClosedMeasurementDimensionAcceptsNoNewRun:
    def test_the_measurement_lockdown_is_scoped_to_its_own_dimension(self, api):
        """PRD §3.9: "A drop in `MATCHBACK_CLOSED` accepts no new run at all and is
        rejected with `ERR_INVALID_MEASUREMENT_STATE` — reaching the closed state
        does not unlock a re-read."

        Design: Corner/state_machines/a_new_matchback_run_on_a_closed_drop_is_rejected
        """
        world = _one_superseded_and_one_finalized_matchback_read()
        drop_id = world["drop"]["id"]
        assert world["drop"]["production_status"] == "MAILED"
        assert world["drop"]["measurement_status"] == "MATCHBACK_CLOSED"
        closed_version = world["drop"]["version"]

        error = validate_error(
            api.create_matchback_run(
                drop_id,
                create_matchback_run_payload(
                    closed_version, "FRACTIONAL_MULTI_TOUCH", 30
                ),
                ANALYST,
            ),
            ApiErrorId.ERR_INVALID_MEASUREMENT_STATE.value,
            409,
        )
        assert error["error_id"] != ApiErrorId.ERR_INVALID_DROP_STATE.value
        assert error["error_id"] != ApiErrorId.ERR_STALE_DROP_VERSION.value

        _runs, meta = validate_paginated(api.list_matchback_runs(drop_id, ANALYST))
        assert meta["total_count"] == 2

        unchanged = fetch_drop(drop_id)
        assert unchanged["version"] == closed_version
        assert unchanged["measurement_status"] == "MATCHBACK_CLOSED"

        delivered = validate_success(api.deliver_drop(drop_id, PLANNER), 200)
        assert delivered["production_status"] == "DELIVERED"
        assert delivered["measurement_status"] == "MATCHBACK_CLOSED"
