"""Corner queue — validations (award and audit gates): the good-faith-effort
escape hatch, the empty responsive pool, the audit response window, repayment
bounds, and both segregation-of-duties checkpoints (PRD §3.6, §3.8, §3.9)."""
from test_helpers import (
    TEST_USERS,
    USER_IDS,
    advertise_project,
    api_client,
    authorize_project,
    clear_project,
    create_audit,
    create_bid_entry,
    create_change_order,
    create_line_item,
    determine_project_eligible,
    finalize_audit,
    get_success_data,
    issue_audit_findings,
    open_project_bids,
    record_repayment,
    set_clock,
    setup_project_complete,
    setup_stip_pipeline,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import ApiErrorId

H = TEST_USERS


def _bids_opened(api, bids):
    """One project progressed to BIDS_OPENED with the given bid entries."""
    pipeline = setup_stip_pipeline(
        program_code="NHPP",
        eligible_activity_codes=["ROAD_RESURFACING"],
        state_code="AZ",
        project_specs=[{"total_estimated_cost_cents": 100_000}],
    )
    project = pipeline["projects"][0]
    determine_project_eligible(project["id"])
    clear_project(project["id"])
    authorize_project(project["id"], initial_obligated_cents=80_000,
                      agreement_number="FA-AWD")
    advertise_project(project["id"])
    opened = open_project_bids(project["id"], bids)
    return project, opened


class TestAwardAndAuditGates:
    def test_award_below_goal_with_good_faith_effort_passes(self, api):
        """PRD §3.6: "Independently, the declared `dbe_commitment_pct` must be
        at least the Project's `dbe_goal_pct` — equality passes — unless
        `good_faith_effort_documented` is true, which excuses any shortfall;
        otherwise the award is rejected with `ERR_DBE_GOAL_NOT_MET` (422)."

        A 0.05 commitment against the 0.10 goal is accepted because the
        good-faith-effort flag is an explicit alternative, not a relaxation of
        the >= rule.

        Design: Corner/validations/award_below_goal_with_good_faith_effort_passes
        """
        project, bids = _bids_opened(
            api, [create_bid_entry("Low", 90_000, True)]
        )
        resp = api.award_project(
            project["id"],
            {
                "bid_id": bids[0]["id"],
                "dbe_commitment_pct": 0.05,
                "good_faith_effort_documented": True,
            },
            H["fhwa_reviewer"],
        )
        awarded = validate_success(resp)
        assert awarded["status"] == "UNDER_CONSTRUCTION"
        assert awarded["awarded_bid_id"] == bids[0]["id"]

    def test_award_with_zero_responsive_bids_returns_no_responsive_bids(self, api):
        """PRD §3.6: "the pool must contain at least one responsive bid, else
        `ERR_NO_RESPONSIVE_BIDS` (422), a check evaluated before the named bid
        is inspected".

        The only opened bid is non-responsive, so the pool is empty and the
        pool check fires before the named bid is even inspected.

        Design: Corner/validations/award_with_zero_responsive_bids_returns_no_responsive_bids
        """
        project, bids = _bids_opened(
            api, [create_bid_entry("NR", 90_000, False)]
        )
        resp = api.award_project(
            project["id"],
            {"bid_id": bids[0]["id"], "dbe_commitment_pct": 0.10},
            H["fhwa_reviewer"],
        )
        error = validate_error(resp, ApiErrorId.ERR_NO_RESPONSIVE_BIDS)
        assert resp.status_code == 422, f"expected 422, got {resp.status_code} ({error})"

        reread = get_success_data(api.get_project(project["id"], H["fhwa_reviewer"]))
        assert reread["status"] == "BIDS_OPENED"

    def test_audit_finalize_before_response_window_returns_window_open(self, api):
        """PRD §3.9: "Finalization then waits out the state's response window:
        the logical clock must have reached at least 30 days after
        `findings_issued_at` — exactly 30 days passes — else
        `ERR_AUDIT_RESPONSE_WINDOW_OPEN` (409)."

        Findings are issued at 2026-12-01; finalizing at +14 days
        (2026-12-15) is inside the response window.

        Design: Corner/validations/audit_finalize_before_response_window_returns_window_open
        """
        ctx = setup_project_complete(agreement_number="FA-AW")
        audit = create_audit(ctx["project"]["id"])
        set_clock("2026-12-01T00:00:00Z")
        issue_audit_findings(audit["id"], "Minor", 1_000)

        set_clock("2026-12-15T00:00:00Z")  # findings + 14 days
        resp = api.finalize_audit(audit["id"], H["fhwa_reviewer_alt"])
        error = validate_error(resp, ApiErrorId.ERR_AUDIT_RESPONSE_WINDOW_OPEN)
        assert resp.status_code == 409, f"expected 409, got {resp.status_code} ({error})"

        rows, _meta = validate_paginated(
            api.list_project_audits(ctx["project"]["id"], H["fhwa_reviewer"])
        )
        assert len(rows) == 1
        assert rows[0]["status"] == "FINDINGS_ISSUED"
        assert rows[0]["repayment_due_cents"] is None

    def test_record_repayment_above_due_rejected_then_exact_accepted(self, api):
        """PRD §3.9: "When a repayment is due, the auditor records state
        repayments, each supplying an `amount_cents` no greater than the
        outstanding balance — `repayment_due_cents` minus the `repaid_cents`
        already recorded — with equality allowed; an overpayment is rejected
        with `ERR_REPAYMENT_EXCEEDS_DUE` (422)."
        PRD §3.9: "Each recording adds to `repaid_cents`, and the recording
        that brings `repaid_cents` to exactly `repayment_due_cents` moves the
        Audit from `FINAL` to the terminal `CLOSED` status."

        The audit computes repayment_due 40,000 (reimbursed 400,000 minus
        final eligible round((500,000 - 50,000) x 0.80) = 360,000): 40,001 is
        rejected; the exact 40,000 closes the audit and the project.

        Design: Corner/validations/record_repayment_above_due_rejected_then_exact_accepted
        """
        ctx = setup_project_complete(
            project_cost_cents=700_000,
            apportioned_cents=1_000_000,
            initial_obligated_cents=500_000,
            agreement_number="FA-RP",
            final_voucher_kwargs={
                "line_items": [create_line_item("all", 500_000)],
                "period_start_date": "2027-01-01T00:00:00Z",
                "period_end_date": "2027-04-01T00:00:00Z",
            },
        )
        audit = create_audit(ctx["project"]["id"])
        issue_audit_findings(audit["id"], "50k ineligible", 50_000)
        set_clock("2026-12-07T00:00:00Z")
        finalized = finalize_audit(audit["id"])
        assert finalized["status"] == "FINAL"
        assert finalized["repayment_due_cents"] == 40_000

        over = api.record_repayment(
            audit["id"], {"amount_cents": 40_001}, H["fhwa_reviewer_alt"]
        )
        error = validate_error(over, ApiErrorId.ERR_REPAYMENT_EXCEEDS_DUE)
        assert over.status_code == 422, (
            f"40,001 exceeds the 40,000 due, got {over.status_code} ({error})"
        )
        rows, _meta = validate_paginated(
            api.list_project_audits(ctx["project"]["id"], H["fhwa_reviewer"])
        )
        assert rows[0]["status"] == "FINAL"

        closed = record_repayment(audit["id"], 40_000)
        assert closed["status"] == "CLOSED"
        project = get_success_data(api.get_project(ctx["project"]["id"], H["fhwa_reviewer"]))
        assert project["status"] == "CLOSED_OUT", (
            "the exact repayment closes the audit, cascading the project to "
            f"CLOSED_OUT, got {project['status']}"
        )

    def test_audit_create_by_final_voucher_approver_blocked_by_segregation(self, api):
        """PRD §3.9: "Audit creation is the second segregation-of-duties
        checkpoint: the auditor's `X-User-ID`, recorded as `auditor_user_id`,
        must differ from the `decided_by_user_id` of the project's final
        voucher, else `ERR_SEGREGATION_OF_DUTIES` (422)."

        The reviewer who approved the final voucher cannot initiate the audit
        of the same project; a different reviewer can.

        Design: Corner/validations/audit_create_by_final_voucher_approver_blocked_by_segregation
        """
        # setup_project_complete decides the final voucher with the primary
        # FHWA reviewer.
        ctx = setup_project_complete(agreement_number="FA-SD")

        same = api.create_audit(
            {"project_id": ctx["project"]["id"]}, H["fhwa_reviewer"]
        )
        error = validate_error(same, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert same.status_code == 422, (
            f"the final voucher approver must be barred, got {same.status_code} ({error})"
        )

        other = api.create_audit(
            {"project_id": ctx["project"]["id"]}, H["fhwa_reviewer_alt"]
        )
        audit = validate_success(other, expected_status=201)
        assert audit["status"] == "INITIATED"
        assert audit["auditor_user_id"] == USER_IDS["fhwa_reviewer_alt"]

    def test_change_order_same_user_concur_blocked_by_segregation(self, api):
        """PRD §3.8: "a `StateDOTEngineer` provides state concurrence, moving
        the ChangeOrder from `REQUESTED` to `STATE_CONCURRED`, but the
        concurring operator's `X-User-ID` must differ from
        `requested_by_user_id` — the same operator on both sides is rejected
        with `ERR_SEGREGATION_OF_DUTIES` (422)."

        The requesting engineer cannot concur their own change order; a
        different engineer can.

        Design: Corner/validations/change_order_same_user_concur_blocked_by_segregation
        """
        pipeline = setup_stip_pipeline(
            program_code="NHPP",
            eligible_activity_codes=["ROAD_RESURFACING"],
            state_code="AZ",
            project_specs=[{"total_estimated_cost_cents": 100_000}],
        )
        project = pipeline["projects"][0]
        determine_project_eligible(project["id"])
        clear_project(project["id"])
        authorization = authorize_project(
            project["id"], initial_obligated_cents=80_000, agreement_number="FA-SS"
        )
        advertise_project(project["id"])
        bids = open_project_bids(project["id"], [create_bid_entry("Low", 90_000, True)])
        award_resp = api.award_project(
            project["id"],
            {"bid_id": bids[0]["id"], "dbe_commitment_pct": 0.10},
            H["fhwa_reviewer"],
        )
        assert validate_success(award_resp)["status"] == "UNDER_CONSTRUCTION"

        change_order = create_change_order(authorization["id"], 5_000, "CO")
        assert change_order["requested_by_user_id"] == USER_IDS["state_dot_engineer"]

        self_concur = api.state_concur_change_order(
            change_order["id"], H["state_dot_engineer"]
        )
        error = validate_error(self_concur, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)
        assert self_concur.status_code == 422, (
            f"self-concurrence must be rejected, got {self_concur.status_code} ({error})"
        )

        rows, _meta = validate_paginated(
            api.list_authorization_change_orders(authorization["id"], H["fhwa_reviewer"])
        )
        assert rows[0]["status"] == "REQUESTED"

        concurred = api.state_concur_change_order(
            change_order["id"], H["state_dot_engineer_alt"]
        )
        data = validate_success(concurred)
        assert data["status"] == "STATE_CONCURRED"
        assert data["state_concurred_by_user_id"] == USER_IDS["state_dot_engineer_alt"]
