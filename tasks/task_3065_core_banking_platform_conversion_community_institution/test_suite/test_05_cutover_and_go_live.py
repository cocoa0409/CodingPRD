"""Cutover planning, freeze channel exclusion, task windows, and go-live."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    advance_to_mock_conversion, start_mock_run, finalize_run, set_clock,
    plan_cutover, add_task,
    create_ancillary_system, verify_ancillary_system,
    setup_plan_go, setup_project_with_passed_run,
)

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]
OPS = TEST_USERS["ops_headers"]


class TestTaskWindows:
    def test_task_start_before_window_returns_outside_window(self, api):
        """PRD §3.7: "Starting a task (`PENDING → RUNNING`) is performed by the
        role named as the task's `owner_role` — a `ConversionEngineer` for
        engineering tasks, an `OperationsLead` for operations tasks — and
        requires the clock to be at or after `conversion_window_start` and
        strictly before `conversion_window_end`; additionally, if the task
        names a `depends_on_task_id`, the predecessor must be `COMPLETE`."

        Design: Corner/state_machines/cutover_task_start_before_window_returns_outside_window
        """
        ctx = setup_plan_go(
            go_no_go_checkpoint="2026-09-19T18:30:00Z",
            checkpoint_clock="2026-09-19T18:59:00Z",
        )
        task = ctx["tasks"][0]
        # Clock is 18:59, one minute before the 19:00 window start.
        resp = api.start_task(task["id"], CE)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)


class TestFreezeChannel:
    def test_freeze_inside_other_project_window_rejected_then_accepted_after_grace(
            self, api):
        """PRD §2.9: "A conversion weekend consumes a shared operational
        channel: while one institution's cutover tasks are inside their
        conversion windows (plus a thirty-minute completion grace after each
        window's end), no other project may open its file freeze inside that
        span."
        PRD §2.9: "Both the cutover-planning action and the plan-scheduling
        action enforce this rule; a violating `file_freeze_start` is rejected
        with `ERR_FREEZE_CHANNEL_BUSY` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/freeze_channel_aggregate_capacity_conflict
        """
        # Project A: planned cutover, SCHEDULED plan, task 19:00-21:00 (grace
        # until 21:30).
        proj_a = create_project(institution_name="Bank A")
        pt_a = create_product(proj_a["id"], product_code="DDA-STD", rate=0.03)
        gl_a = create_gl(proj_a["id"])
        acct_a = create_account(proj_a["id"], pt_a["id"], legacy_account_number="LA-1")
        map_account(acct_a["id"], gl_a["id"], proj_a["id"])
        advance_to_mock_conversion(proj_a["id"])
        run_a = start_mock_run(proj_a["id"])
        finalize_run(run_a["id"])
        plan_a = plan_cutover(proj_a["id"])
        add_task(plan_a["id"])
        get_success_data(api.schedule_plan(plan_a["id"], PM))
        # Project B: same happy path up to MOCK_CONVERSION with a PASSED run.
        proj_b = create_project(institution_name="Bank B")
        pt_b = create_product(proj_b["id"], product_code="DDA-STD", rate=0.03)
        gl_b = create_gl(proj_b["id"])
        acct_b = create_account(proj_b["id"], pt_b["id"], legacy_account_number="LB-1")
        map_account(acct_b["id"], gl_b["id"], proj_b["id"])
        advance_to_mock_conversion(proj_b["id"])
        run_b = start_mock_run(proj_b["id"])
        finalize_run(run_b["id"])
        # 21:15 falls inside A's window + 30-minute grace -> busy.
        resp = api.plan_cutover(
            proj_b["id"],
            {
                "cutover_scheduled_date": "2026-09-20",
                "file_freeze_start": "2026-09-19T21:15:00Z",
                "go_no_go_checkpoint": "2026-09-19T22:00:00Z",
                "reopen_target": "2026-09-21T06:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_FREEZE_CHANNEL_BUSY)
        # 21:31 is past the grace -> the channel is free.
        plan_b = get_success_data(
            api.plan_cutover(
                proj_b["id"],
                {
                    "cutover_scheduled_date": "2026-09-20",
                    "file_freeze_start": "2026-09-19T21:31:00Z",
                    "go_no_go_checkpoint": "2026-09-19T22:00:00Z",
                    "reopen_target": "2026-09-21T06:00:00Z",
                },
                PM,
            )
        )
        assert plan_b["status"] == "DRAFT"

    def test_freeze_at_grace_edge_boundary(self, api):
        """PRD §2.9: "A conversion weekend consumes a shared operational
        channel: while one institution's cutover tasks are inside their
        conversion windows (plus a thirty-minute completion grace after each
        window's end), no other project may open its file freeze inside that
        span."

        Design: Difficulty/resource_temporal_overlap/freeze_channel_aggregate_capacity_conflict
        """
        proj_a = create_project(institution_name="Bank A")
        pt_a = create_product(proj_a["id"], product_code="DDA-STD", rate=0.03)
        gl_a = create_gl(proj_a["id"])
        acct_a = create_account(proj_a["id"], pt_a["id"], legacy_account_number="LA-1")
        map_account(acct_a["id"], gl_a["id"], proj_a["id"])
        advance_to_mock_conversion(proj_a["id"])
        run_a = start_mock_run(proj_a["id"])
        finalize_run(run_a["id"])
        plan_a = plan_cutover(proj_a["id"])
        add_task(plan_a["id"])
        get_success_data(api.schedule_plan(plan_a["id"], PM))

        proj_b = create_project(institution_name="Bank B")
        pt_b = create_product(proj_b["id"], product_code="DDA-STD", rate=0.03)
        gl_b = create_gl(proj_b["id"])
        acct_b = create_account(proj_b["id"], pt_b["id"], legacy_account_number="LB-1")
        map_account(acct_b["id"], gl_b["id"], proj_b["id"])
        advance_to_mock_conversion(proj_b["id"])
        run_b = start_mock_run(proj_b["id"])
        finalize_run(run_b["id"])
        # Exactly at the grace end (window end 21:00 + 30 min = 21:30) is
        # still inside the excluded span.
        resp = api.plan_cutover(
            proj_b["id"],
            {
                "cutover_scheduled_date": "2026-09-20",
                "file_freeze_start": "2026-09-19T21:30:00Z",
                "go_no_go_checkpoint": "2026-09-19T22:00:00Z",
                "reopen_target": "2026-09-21T06:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_FREEZE_CHANNEL_BUSY)


class TestTaskDependencies:
    def test_forward_and_unresolvable_dependency_rejected(self, api):
        """PRD §3.6: "A dependency must reference a task of the **same plan**
        with a strictly smaller sequence — self-reference and forward reference
        are both rejected with `ERR_INVALID_REFERENCE`."

        Design: Corner/validations/cutover_task_forward_dependency_rejected
        """
        # Build a CUTOVER_PLANNED project with a DRAFT plan.
        ctx2 = setup_project_with_passed_run()
        pid = ctx2["project"]["id"]
        plan = plan_cutover(pid)
        t1 = add_task(plan["id"], task_name="extract", sequence=1,
                      conversion_window_start="2026-09-19T19:00:00Z",
                      conversion_window_end="2026-09-19T21:00:00Z")
        t2 = add_task(plan["id"], task_name="load", sequence=2,
                      conversion_window_start="2026-09-19T21:00:00Z",
                      conversion_window_end="2026-09-19T23:00:00Z",
                      owner_role="OPERATIONS_LEAD",
                      depends_on_task_id=t1["id"])
        t3 = add_task(plan["id"], task_name="bad-self", sequence=3,
                      conversion_window_start="2026-09-19T23:00:00Z",
                      conversion_window_end="2026-09-20T01:00:00Z",
                      owner_role="OPERATIONS_LEAD",
                      depends_on_task_id=t2["id"])
        assert t2["id"]
        assert t3["id"]
        resp = api.create_task(
            {
                "plan_id": plan["id"],
                "task_name": "bad-forward",
                "sequence": 4,
                "conversion_window_start": "2026-09-20T01:00:00Z",
                "conversion_window_end": "2026-09-20T03:00:00Z",
                "owner_role": "OPERATIONS_LEAD",
                "depends_on_task_id": "00000000-0000-4000-8000-000000000000",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REFERENCE)


class TestWindowVsDependencyPriority:
    def test_outside_window_wins_over_unmet_dependency(self, api):
        """PRD §2.8: "then state-machine legality of the requested transition
        (`ERR_INVALID_STATE`); then clock and window geometry rules
        (`ERR_OUTSIDE_WINDOW`); then cross-entity referential validity
        (`ERR_INVALID_REFERENCE`)"
        PRD §3.7: "Starting a task (`PENDING → RUNNING`) is performed by the
        role named as the task's `owner_role` — a `ConversionEngineer` for
        engineering tasks, an `OperationsLead` for operations tasks — and
        requires the clock to be at or after `conversion_window_start` and
        strictly before `conversion_window_end`; additionally, if the task
        names a `depends_on_task_id`, the predecessor must be `COMPLETE`."

        Design: Difficulty/priority_pair_validation_conflict/outside_window_wins_over_invalid_reference_on_task_start
        """
        ctx = setup_project_with_passed_run()
        pid = ctx["project"]["id"]
        sys_row = create_ancillary_system(pid)
        verify_ancillary_system(sys_row["id"])
        plan = plan_cutover(pid)
        t1 = add_task(plan["id"], task_name="extract", sequence=1,
                      conversion_window_start="2026-09-19T19:00:00Z",
                      conversion_window_end="2026-09-19T21:00:00Z",
                      owner_role="CONVERSION_ENGINEER")
        t2 = add_task(plan["id"], task_name="load", sequence=2,
                      conversion_window_start="2026-09-19T21:00:00Z",
                      conversion_window_end="2026-09-19T23:00:00Z",
                      owner_role="OPERATIONS_LEAD",
                      depends_on_task_id=t1["id"])
        get_success_data(api.schedule_plan(plan["id"], PM))
        set_clock("2026-09-19T20:30:00Z")
        get_success_data(api.declare_go(plan["id"], PM))
        set_clock("2026-09-20T01:00:00Z")
        resp2 = api.start_task(t2["id"], OPS)
        validate_error(resp2, ApiErrorId.ERR_OUTSIDE_WINDOW)

    def test_outside_window_reported_when_dependency_also_unmet(self, api):
        """PRD §2.8: "then state-machine legality of the requested transition
        (`ERR_INVALID_STATE`); then clock and window geometry rules
        (`ERR_OUTSIDE_WINDOW`); then cross-entity referential validity
        (`ERR_INVALID_REFERENCE`)"
        PRD §3.7: "Starting too early or too late, or completing outside the
        allowed span, is rejected with `ERR_OUTSIDE_WINDOW`."

        Design: Difficulty/priority_pair_validation_conflict/outside_window_wins_over_invalid_reference_on_task_start
        """
        ctx = setup_project_with_passed_run()
        pid = ctx["project"]["id"]
        sys_row = create_ancillary_system(pid)
        verify_ancillary_system(sys_row["id"])
        plan = plan_cutover(pid)
        t1 = add_task(plan["id"], task_name="extract", sequence=1,
                      conversion_window_start="2026-09-19T19:00:00Z",
                      conversion_window_end="2026-09-19T21:00:00Z",
                      owner_role="CONVERSION_ENGINEER")
        t2 = add_task(plan["id"], task_name="load", sequence=2,
                      conversion_window_start="2026-09-19T21:00:00Z",
                      conversion_window_end="2026-09-19T23:00:00Z",
                      owner_role="OPERATIONS_LEAD",
                      depends_on_task_id=t1["id"])
        get_success_data(api.schedule_plan(plan["id"], PM))
        set_clock("2026-09-19T20:30:00Z")
        get_success_data(api.declare_go(plan["id"], PM))
        # Too early: clock 20:45 is before task B's 21:00 window start, and
        # task A is still PENDING — the window violation is the surfaced error.
        set_clock("2026-09-19T20:45:00Z")
        resp = api.start_task(t2["id"], OPS)
        validate_error(resp, ApiErrorId.ERR_OUTSIDE_WINDOW)


class TestGoLiveGates:
    def test_go_live_blocked_by_failed_task(self, api):
        """PRD §3.7: "Project go-live (`CUTOVER_PLANNED → LIVE`) is the point
        of no return and its gate is exacting: the plan must be in `GO`
        status; every task of the plan must be `COMPLETE` or `SKIPPED`; every
        ancillary system of the project must be `VERIFIED` or `RETEST_PASSED`;
        and no `SEV1` defect may sit in `OPEN`, `TRIAGED`, `IN_FIX`, or
        `REOPENED`."
        PRD §3.1: "A failure of any phase precondition — on advance, on cutover
        planning, on go-live, or on close — is rejected with `ERR_PHASE_GATE`
        (HTTP 409)."

        Design: Corner/endpoints/go_live_blocked_by_failed_task
        """
        ctx = setup_plan_go(go_no_go_checkpoint="2026-09-19T18:30:00Z",
                            checkpoint_clock="2026-09-19T19:00:00Z")
        task = ctx["tasks"][0]
        get_success_data(api.start_task(task["id"], CE))
        get_success_data(api.fail_task(task["id"], CE))
        set_clock("2026-09-20T00:00:00Z")
        resp = api.go_live(ctx["project"]["id"], PM)
        validate_error(resp, ApiErrorId.ERR_PHASE_GATE)

    def test_go_live_flips_uncleared_mapped_accounts_to_exception(self, api):
        """PRD §3.7: "moves the plan `GO → LIVE`; transitions every `CLEARED`
        account to `CONVERTED` and recomputes each such account's accrual
        authoritatively with the computation date set to `cutoff_business_date`
        (this cutover variant writes the final `conversion_balance_cents` and
        accrued interest for day-1 opening, and only `CLEARED` accounts are
        converted); flips every still-`MAPPED` account to `EXCEPTION` with the
        note \"uncleared at go-live\""

        Design: Corner/state_machines/go_live_flips_uncleared_mapped_accounts_to_exception
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"])
        a1 = create_account(project["id"], pt["id"], legacy_account_number="L-A1",
                            opening_principal_cents=1000)
        a2 = create_account(project["id"], pt["id"], legacy_account_number="L-A2",
                            opening_principal_cents=2000)
        map_account(a1["id"], gl["id"], project["id"])
        map_account(a2["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        run = start_mock_run(project["id"])
        finalize_run(run["id"])
        get_success_data(api.flag_exception(a1["id"], {"note": "x"}, CE))
        get_success_data(api.clear_exception(a1["id"], {"resolution_note": "y"}, CE))
        sys_row = create_ancillary_system(project["id"])
        verify_ancillary_system(sys_row["id"])
        plan = plan_cutover(project["id"],
                            go_no_go_checkpoint="2026-09-19T18:30:00Z")
        task = add_task(plan["id"])
        get_success_data(api.schedule_plan(plan["id"], PM))
        set_clock("2026-09-19T19:00:00Z")
        get_success_data(api.declare_go(plan["id"], PM))
        get_success_data(api.start_task(task["id"], CE))
        get_success_data(api.complete_task(task["id"], CE))
        set_clock("2026-09-20T00:00:00Z")
        get_success_data(api.go_live(project["id"], PM))
        a1_row = get_success_data(api.get_account(a1["id"], PM))
        a2_row = get_success_data(api.get_account(a2["id"], PM))
        assert a1_row["status"] == "CONVERTED"
        assert a2_row["status"] == "EXCEPTION"
        assert a2_row["exception_note"] == "uncleared at go-live"
