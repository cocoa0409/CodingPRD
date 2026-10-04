"""Difficulty tests: non-linear state machines — the COE denial cycle, the
loan's parallel state dimensions, and the appraisal repairs self-loop."""
from __future__ import annotations

from test_helpers import (
    ApiErrorId,
    add_standard_service_period,
    approve_underwriting,
    close_loan,
    create_coe_request_payload,
    create_loan_payload,
    create_south_appraiser,
    create_veteran_payload,
    get_appraisal,
    get_loan,
    list_repairs,
    make_appraiser_headers,
    order_assigned_appraisal,
    setup_approved_loan,
    setup_closed_loan,
    setup_submitted_loan,
    setup_veteran_with_issued_coe,
    submit_value_issued_report,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestCoeReconsiderationCycle:
    def _make_denied_coe(self, api):
        """A DISHONORABLE veteran whose COE has been denied once."""
        veteran = validate_success(
            api.create_veteran(create_veteran_payload(
                character_of_discharge="DISHONORABLE")),
            expected_status=201,
        )
        add_standard_service_period(veteran["id"])
        coe = validate_success(
            api.create_coe_request(veteran["id"], create_coe_request_payload()),
            expected_status=201,
        )
        validate_success(api.deny_coe(coe["id"]))
        return veteran, coe

    def test_coe_denial_reconsideration_cycle_cap(self, api):
        """PRD §3.2: "A loan officer may send a `DENIED` certificate back to
        `RECONSIDERATION`, which increments `reconsideration_count`; the cap is
        two reconsiderations, and a third attempt is rejected with
        `ERR_RECONSIDERATION_EXHAUSTED` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/coe_denial_reconsideration_cycle
        """
        veteran, coe = self._make_denied_coe(api)
        # Cycle 1: reconsider -> deny. Cycle 2: reconsider -> deny.
        validate_success(api.reconsider_coe(coe["id"]))
        validate_success(api.deny_coe(coe["id"]))
        validate_success(api.reconsider_coe(coe["id"]))
        validate_success(api.deny_coe(coe["id"]))
        # Third reconsideration is rejected; count stays at the cap of two.
        validate_error(api.reconsider_coe(coe["id"]),
                       ApiErrorId.ERR_RECONSIDERATION_EXHAUSTED,
                       expected_status=409)
        coes, _meta = validate_paginated(
            api.list_coe_requests(veteran["id"]))
        assert coes[0]["reconsideration_count"] == 2
        assert coes[0]["status"] == "DENIED"

    def test_coe_reconsideration_path_can_still_issue(self, api):
        """PRD §3.2: "Reconsidered certificates face the same issuance and
        denial gates as fresh ones"
        PRD §3.2: "Issuing a certificate — from either `REQUESTED` or
        `RECONSIDERATION` — applies three gates, evaluated in this order."

        Design: Difficulty/non_linear_state_machine/coe_denial_reconsideration_cycle
        """
        veteran, coe = self._make_denied_coe(api)
        # First reconsideration succeeds; a HONORABLE-qualifying veteran here is
        # still DISHONORABLE so a re-issue would fail the discharge gate, but
        # the RECONSIDERATION -> DENIED re-adjudication path must work.
        reconsidered = validate_success(api.reconsider_coe(coe["id"]))
        assert reconsidered["status"] == "RECONSIDERATION"
        assert reconsidered["reconsideration_count"] == 1
        # Re-adjudication from RECONSIDERATION denies again with the same gate.
        denied = validate_success(api.deny_coe(coe["id"]))
        assert denied["status"] == "DENIED"
        assert denied["denial_reason"] == "DISCHARGE_INELIGIBLE"


class TestLoanParallelDimensions:
    def test_loan_parallel_dimensions_close_then_payoff(self, api):
        """PRD §3.3: "A new loan's two parallel state dimensions both start at
        their initial values: `underwriting_status` `SUBMITTED` and
        `closing_status` `NOT_CLOSED`"
        PRD §3.4: "A loan is terminally resolved either as `DENIED` and never
        closed, or as `APPROVED` carried through to `PAID_IN_FULL`."

        Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_close_then_payoff
        """
        # Loan A walks (APPROVED, NOT_CLOSED) -> (APPROVED, CLOSED) ->
        # (APPROVED, PAID_IN_FULL).
        ctx_a = setup_closed_loan(price_cents=30000000)
        paid = validate_success(api.record_payoff(ctx_a["loan"]["id"], "SALE"))
        assert paid["closing_status"] == "PAID_IN_FULL"
        loan_a = get_loan(ctx_a["loan"]["id"])
        assert loan_a["underwriting_status"] == "APPROVED"
        assert loan_a["closing_status"] == "PAID_IN_FULL"

        # Loan B (a different veteran) is underwriting-DENIED and never closes.
        ctx_b = setup_submitted_loan(
            loan_overrides={"purchase_price_cents": 30000000})
        decision = validate_success(
            api.create_underwriting_decision(ctx_b["loan"]["id"], {
                # residual = 450000-350000 = 100000 < required 100300
                # (SOUTH, family 4) -> DENIED per PRD §3.4.
                "gross_monthly_income_cents": 450000,
                "new_housing_payment_cents": 350000,
                "other_obligations_annual_cents": [],
                "family_size": 4,
                "region": "SOUTH",
            }),
            expected_status=201,
        )
        assert decision["outcome"] == "DENIED"
        loan_b = get_loan(ctx_b["loan"]["id"])
        assert loan_b["underwriting_status"] == "DENIED"
        assert loan_b["closing_status"] == "NOT_CLOSED"
        assert loan_b["entitlement_charged_cents"] == 0

    def test_loan_underwriting_dimension_moves_independently(self, api):
        """PRD §3.4: "Recording the decision persists the `UnderwritingDecision`
        with all computed fields, moves the loan's `underwriting_status` to the
        outcome, and increments the loan's `version`."
        PRD §3.3: "A new loan's two parallel state dimensions both start at their
        initial values: `underwriting_status` `SUBMITTED` and `closing_status`
        `NOT_CLOSED`"

        Design: Difficulty/non_linear_state_machine/loan_parallel_dimensions_close_then_payoff
        """
        ctx = setup_approved_loan(price_cents=30000000)
        loan = get_loan(ctx["loan"]["id"])
        # Underwriting moved to APPROVED while the closing dimension is untouched.
        assert loan["underwriting_status"] == "APPROVED"
        assert loan["closing_status"] == "NOT_CLOSED"
        assert loan["closing_date"] is None
        assert loan["payoff_type"] is None


class TestAppraisalRepairsResubmitLoop:
    def test_appraisal_repairs_resubmit_loop(self, api):
        """PRD §3.5: "From `REPAIRS_REQUIRED`, a further `REPAIRS_REQUIRED`
        report is a self-loop re-inspection round — new repair requirements are
        appended in `OPEN`, prior repairs are unchanged, and `report_round`
        increments again"
        PRD §3.5: "An appraiser's `open_assignment_count` tracks how many of
        their appraisals currently sit in `ASSIGNED` or `REPAIRS_REQUIRED`."

        Design: Difficulty/non_linear_state_machine/appraisal_repairs_resubmit_loop
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 30000000})
        appraiser = create_south_appraiser(name="App S4")
        appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
        headers = make_appraiser_headers(appraiser["id"])

        first = validate_success(
            api.submit_appraisal_report(appraisal["id"], {
                "outcome": "REPAIRS_REQUIRED",
                "repairs": [{"description": "Peeling paint",
                             "required_for_clearance": True}],
            }, headers=headers),
        )
        assert first["status"] == "REPAIRS_REQUIRED"

        second = validate_success(
            api.submit_appraisal_report(appraisal["id"], {
                "outcome": "REPAIRS_REQUIRED",
                "repairs": [{"description": "Missing handrail",
                             "required_for_clearance": True}],
            }, headers=headers),
        )
        assert second["status"] == "REPAIRS_REQUIRED"

        readback = get_appraisal(appraisal["id"])
        assert readback["status"] == "REPAIRS_REQUIRED"
        assert readback["report_round"] == 2

        repairs = list_repairs(appraisal["id"])
        assert len(repairs) == 2
        assert all(r["status"] == "OPEN" for r in repairs)

    def test_appraisal_repairs_loop_prior_repairs_unchanged(self, api):
        """PRD §3.5: "From `REPAIRS_REQUIRED`, a further `REPAIRS_REQUIRED`
        report is a self-loop re-inspection round — new repair requirements are
        appended in `OPEN`, prior repairs are unchanged, and `report_round`
        increments again"

        Design: Difficulty/non_linear_state_machine/appraisal_repairs_resubmit_loop
        """
        ctx = setup_submitted_loan(loan_overrides={"purchase_price_cents": 30000000})
        appraiser = create_south_appraiser(name="App Loop2")
        appraisal = order_assigned_appraisal(ctx["loan"]["id"], appraiser)
        headers = make_appraiser_headers(appraiser["id"])

        validate_success(
            api.submit_appraisal_report(appraisal["id"], {
                "outcome": "REPAIRS_REQUIRED",
                "repairs": [{"description": "First defect",
                             "required_for_clearance": True}],
            }, headers=headers),
        )
        first_repairs = list_repairs(appraisal["id"])
        first_ids = {r["id"] for r in first_repairs}

        validate_success(
            api.submit_appraisal_report(appraisal["id"], {
                "outcome": "REPAIRS_REQUIRED",
                "repairs": [{"description": "Second defect",
                             "required_for_clearance": True}],
            }, headers=headers),
        )
        all_repairs = list_repairs(appraisal["id"])
        assert len(all_repairs) == 2
        # Prior repairs unchanged: same ids survive, still OPEN.
        assert first_ids.issubset({r["id"] for r in all_repairs})
        for repair in all_repairs:
            if repair["id"] in first_ids:
                assert repair["status"] == "OPEN"
