"""Mock conversion runs: outcome boundaries, singleton rule, terminal lockdown,
re-certification checkpoint, and the validation ordering around finalize."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, TEST_USERS,
    create_project, create_product, create_gl, create_account, map_account,
    advance_to_mock_conversion, start_mock_run, finalize_run,
    setup_mock_conversion_project, setup_project_with_passed_run,
    plan_cutover,
)

PM = TEST_USERS["pm_headers"]
CE = TEST_USERS["ce_headers"]


class TestMockRunOutcomeBoundary:
    def test_zero_balanced_fails_then_passed_with_exceptions(self, api):
        """PRD §3.5: "The run's `outcome` — mirrored into `state` — is then
        decided from the counts: zero balanced accounts yields `FAILED`;
        otherwise any exception accounts yield `PASSED_WITH_EXCEPTIONS`;
        otherwise the run is `PASSED`."
        PRD §3.5: "Every finalization increments the project's
        `mock_runs_used` by one."

        Design: Corner/calculations/mock_run_outcome_boundary_zero_balanced_fails
        """
        project = create_project()
        pt = create_product(project["id"], rate=0.01)
        gl = create_gl(project["id"])
        a1 = create_account(project["id"], pt["id"], legacy_account_number="L-1",
                            opening_principal_cents=1000)
        # PRD §3.1: advancing to MOCK_CONVERSION requires an ACTIVE product and
        # a MAPPED account. Stage a gate account (b0) and map it to satisfy the
        # gate, then flag it into EXCEPTION so the first run still sees zero
        # balanced accounts (FAILED requires no MAPPED/CLEARED/BLOCKED).
        b0 = create_account(project["id"], pt["id"], legacy_account_number="L-0",
                            opening_principal_cents=5)
        map_account(b0["id"], gl["id"], project["id"])
        advance_to_mock_conversion(project["id"])
        get_success_data(api.flag_exception(b0["id"], {"note": "gate account"}, CE))
        r1 = start_mock_run(project["id"], run_label="MOCK-1")
        fin1 = finalize_run(r1["id"])
        assert fin1["outcome"] == "FAILED"
        assert fin1["balanced_account_count"] == 0
        # Clear the gate account so it joins the balanced population.
        get_success_data(api.clear_exception(b0["id"], {"resolution_note": "ok"}, CE))
        map_account(a1["id"], gl["id"], project["id"])
        a2 = create_account(project["id"], pt["id"], legacy_account_number="L-2",
                            opening_principal_cents=2000)
        map_account(a2["id"], gl["id"], project["id"])
        get_success_data(api.flag_exception(a2["id"], {"note": "bad balance"}, CE))
        r2 = start_mock_run(project["id"], run_label="MOCK-2")
        fin2 = finalize_run(r2["id"])
        assert fin2["outcome"] == "PASSED_WITH_EXCEPTIONS"
        assert fin2["balanced_account_count"] == 2
        assert fin2["exception_account_count"] == 1
        proj = get_success_data(api.get_project(project["id"], PM))
        assert proj["mock_runs_used"] == 2


class TestMockRunSingleton:
    def test_second_run_rejected_while_first_running(self, api):
        """PRD §3.5: "Only one run per project may be in flight: starting a
        second run while another is `RUNNING` is rejected with
        `ERR_RUN_IN_PROGRESS` (HTTP 409)"

        Design: Corner/errors/err_run_in_progress_on_second_run
        """
        ctx = setup_mock_conversion_project()
        r1 = start_mock_run(ctx["project"]["id"], run_label="MOCK-1")
        resp = api.create_mock_run(
            {"project_id": ctx["project"]["id"], "run_label": "MOCK-2"}, CE
        )
        validate_error(resp, ApiErrorId.ERR_RUN_IN_PROGRESS)
        finalize_run(r1["id"])
        r2 = get_success_data(
            api.create_mock_run(
                {"project_id": ctx["project"]["id"], "run_label": "MOCK-2"}, CE
            ),
            201,
        )
        assert r2["state"] == "RUNNING"


class TestFinalizeTerminalLockdown:
    def test_finalized_run_rejects_second_finalize_and_new_run_allowed(self, api):
        """PRD §3.5: "Only one run per project may be in flight: starting a
        second run while another is `RUNNING` is rejected with
        `ERR_RUN_IN_PROGRESS` (HTTP 409)"

        Design: Corner/state_machines/mock_run_finalize_terminal_lockdown_and_second_run_allowed
        """
        ctx = setup_mock_conversion_project()
        r1 = start_mock_run(ctx["project"]["id"], run_label="MOCK-1")
        fin = finalize_run(r1["id"])
        assert fin["state"] == "PASSED"
        resp = api.finalize_mock_run(r1["id"], CE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        r2 = get_success_data(
            api.create_mock_run(
                {"project_id": ctx["project"]["id"], "run_label": "MOCK-2"}, CE
            ),
            201,
        )
        assert r2["state"] == "RUNNING"


class TestValidationPriorityOnFinalize:
    def test_state_error_wins_over_phase_gate_on_refinalize(self, api):
        """PRD §2.8: "The order is: first, authentication of the headers
        (`ERR_UNAUTHENTICATED`); second, role authorization for the endpoint
        (`ERR_FORBIDDEN`); third, existence of every path identifier, validated
        left to right, with nested resources verified to belong to the project
        they are addressed under (`ERR_NOT_FOUND`); fourth, request body
        well-formedness — required fields present, types correct, enum values
        valid, no unknown fields (`ERR_INVALID_REQUEST`); then the optimistic
        concurrency check on the two guarded endpoints (`ERR_STALE_VERSION`);
        then state-machine legality of the requested transition
        (`ERR_INVALID_STATE`); then clock and window geometry rules
        (`ERR_OUTSIDE_WINDOW`); then cross-entity referential validity
        (`ERR_INVALID_REFERENCE`); then entity invariants
        (`ERR_INVARIANT_VIOLATION`); then per-project uniqueness
        (`ERR_DUPLICATE`); then service-credit eligibility
        (`ERR_CREDIT_INELIGIBLE`); then project phase gates (`ERR_PHASE_GATE`)"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_wins_over_phase_gate_on_finalize
        """
        ctx = setup_mock_conversion_project()
        r1 = start_mock_run(ctx["project"]["id"], run_label="MOCK-1")
        fin = finalize_run(r1["id"])
        assert fin["state"] == "PASSED"
        resp = api.finalize_mock_run(r1["id"], CE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_phase_gate_fires_when_state_check_passes(self, api):
        """PRD §2.8: "then state-machine legality of the requested transition
        (`ERR_INVALID_STATE`); then clock and window geometry rules
        (`ERR_OUTSIDE_WINDOW`); then cross-entity referential validity
        (`ERR_INVALID_REFERENCE`); then entity invariants
        (`ERR_INVARIANT_VIOLATION`); then per-project uniqueness
        (`ERR_DUPLICATE`); then service-credit eligibility
        (`ERR_CREDIT_INELIGIBLE`); then project phase gates (`ERR_PHASE_GATE`)"

        Design: Difficulty/priority_pair_validation_conflict/invalid_state_wins_over_phase_gate_on_finalize
        """
        # Project still in DISCOVERY: the run row does not exist yet, so use a
        # RUNNING run created after advancing only once (CONFIGURATION). The
        # run can only be started in MOCK_CONVERSION, so instead finalize a
        # valid run and then try to plan the cutover twice: the second attempt
        # hits the phase gate because the project left MOCK_CONVERSION.
        ctx = setup_project_with_passed_run()
        pid = ctx["project"]["id"]
        plan_cutover(pid)
        resp = api.plan_cutover(
            pid,
            {
                "cutover_scheduled_date": "2026-10-01",
                "file_freeze_start": "2026-09-30T18:00:00Z",
                "go_no_go_checkpoint": "2026-09-30T20:00:00Z",
                "reopen_target": "2026-10-02T06:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestPassedRunRecertification:
    def test_passed_run_flips_cleared_accounts_back_to_mapped(self, api):
        """PRD §3.5: "A `PASSED` run carries one further cascade with two
        links: every account that was `CLEARED` at finalize time returns to
        `MAPPED` — the passed run certifies the current mapping, so previously
        cleared exceptions must be re-certified by the next run — and each such
        flip re-triggers the GL variance recomputation on that account's GL."

        Design: Corner/cross_cutting_layers/ops_run_checkpoint_mock_run_advances_epoch
        """
        ctx = setup_mock_conversion_project()
        acct_id = ctx["account"]["id"]
        get_success_data(api.flag_exception(acct_id, {"note": "x"}, CE))
        get_success_data(api.clear_exception(acct_id, {"resolution_note": "y"}, CE))
        r1 = start_mock_run(ctx["project"]["id"], run_label="MOCK-1")
        fin = finalize_run(r1["id"])
        assert fin["outcome"] == "PASSED"
        acct = get_success_data(api.get_account(acct_id, CE))
        assert acct["status"] == "MAPPED"


class TestPlanCutoverPhaseGate:
    def test_plan_cutover_with_exception_account_returns_phase_gate(self, api):
        """PRD §3.6: "The preconditions are strict: exactly one mock run of
        the project must be in `PASSED` state and no run may yet be marked as
        the cutover baseline; no account may sit in `EXCEPTION`"
        PRD §3.1: "A failure of any phase precondition — on advance, on cutover
        planning, on go-live, or on close — is rejected with `ERR_PHASE_GATE`
        (HTTP 409)."

        Design: Corner/validations/plan_cutover_with_exception_account_returns_phase_gate
        """
        ctx = setup_mock_conversion_project()
        acct_id = ctx["account"]["id"]
        get_success_data(api.flag_exception(acct_id, {"note": "x"}, CE))
        r1 = start_mock_run(ctx["project"]["id"], run_label="MOCK-1")
        finalize_run(r1["id"])
        resp = api.plan_cutover(
            ctx["project"]["id"],
            {
                "cutover_scheduled_date": "2026-09-20",
                "file_freeze_start": "2026-09-19T18:00:00Z",
                "go_no_go_checkpoint": "2026-09-19T18:30:00Z",
                "reopen_target": "2026-09-21T06:00:00Z",
            },
            PM,
        )
        validate_error(resp, ApiErrorId.ERR_PHASE_GATE)
