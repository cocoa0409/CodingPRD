"""Underwriting cases, validation rounds, eligibility outcomes (PRD §3.4)."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    setup_counterparty_chain,
    create_draft_loan,
    open_underwriting_case,
    add_validation_report,
    complete_report,
    validate_case_round,
    finalize_case,
    underwrite_loan,
    get_case,
    get_loan,
    make_seller_officer_headers,
    validate_error,
    validate_success,
    validate_paginated,
)

ADMIN = TEST_USERS["gse_admin_headers"]
UW_ENGINE = TEST_USERS["uw_engine_headers"]
UNDERWRITER = TEST_USERS["underwriter_headers"]


class TestCaseLifecycle:
    def test_underwriting_case_starts_submitted(self, api):
        """PRD §3.4: "A new case starts with `case_status` of `SUBMITTED`,
        `submission_round` at 1, `recommendation` of `PENDING`, and
        `final_outcome` of `PENDING`."

        Design: Corner/state_machines/underwriting_case_starts_submitted
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-INIT")
        case = open_underwriting_case(loan, seller)
        assert case["case_status"] == "SUBMITTED"
        assert case["submission_round"] == 1
        assert case["recommendation"] == "PENDING"
        assert case["final_outcome"] == "PENDING"

    def test_second_underwriting_case_for_same_loan_rejected(self, api):
        """PRD §3.4: "The loan must be in `DRAFT` status, and no case that has
        not yet reached `FINALIZED` may already exist for it; violating either
        condition yields `ERR_LOAN_NOT_UNDERWRITABLE`."

        Design: Corner/state_machines/second_underwriting_case_for_same_loan_rejected
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-DUP")
        open_underwriting_case(loan, seller)
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_underwriting_case({"loan_id": loan["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_UNDERWRITABLE)

    def test_error_loan_not_underwritable_after_rejection(self, api):
        """PRD §3.4: "The loan must be in `DRAFT` status, and no case that has
        not yet reached `FINALIZED` may already exist for it; violating either
        condition yields `ERR_LOAN_NOT_UNDERWRITABLE`."
        PRD §3.4: "A `FAIL` moves the loan `DRAFT → REJECTED` and sets its
        `au_status` to `INELIGIBLE`."

        Design: Corner/errors/error_loan_not_underwritable_after_rejection
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-FAIL",
                                 credit_score=600)
        underwrite_loan(loan, seller)
        assert get_loan(loan["id"])["status"] == "REJECTED"
        headers = make_seller_officer_headers(seller["id"])
        resp = api.create_underwriting_case({"loan_id": loan["id"]}, headers)
        validate_error(resp, ApiErrorId.ERR_LOAN_NOT_UNDERWRITABLE)


class TestValidationRounds:
    def test_underwriting_case_failure_revision_loop(self, api):
        """PRD §3.4: "If any report for the current round completes as
        `NOT_VALIDATED`, the case instead moves `VALIDATING → FAILED` and its
        `submission_round` increments by one."
        PRD §3.4: "A failed case is not dead: the underwriter may resubmit by
        recording further reports, which moves it `FAILED → VALIDATING` with
        new reports stamped at the incremented round."
        PRD §3.4: "When all three service types — `INCOME`, `ASSET`, and
        `EMPLOYMENT` — hold a report with `result` `VALIDATED` for the current
        round, the case moves `VALIDATING → VALIDATED`."

        Design: Difficulty/non_linear_state_machine/underwriting_case_failure_revision_loop
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-CYC")
        case = open_underwriting_case(loan, seller)

        # Round 1: INCOME validates, ASSET does not -> FAILED, round bumps to 2.
        r1_income = add_validation_report(case, "INCOME", "PR-C1")
        complete_report(r1_income, "VALIDATED")
        r1_asset = add_validation_report(case, "ASSET", "PR-C2")
        complete_report(r1_asset, "NOT_VALIDATED")
        mid = get_case(case["id"])
        assert mid["case_status"] == "FAILED"
        assert mid["submission_round"] == 2

        # Round 2: all three validate -> VALIDATED.
        r2_reports = validate_case_round(mid, ref_prefix="PR-R2")
        assert all(r["round"] == 2 for r in r2_reports.values())
        assert r1_income["round"] == 1 and r1_asset["round"] == 1
        ready = get_case(case["id"])
        assert ready["case_status"] == "VALIDATED"

        finalized = finalize_case(ready)
        assert finalized["final_outcome"] == "PASS"
        assert finalized["recommendation"] == "APPROVE_ELIGIBLE"
        loan_after = get_loan(loan["id"])
        assert loan_after["status"] == "UNDERWRITTEN"
        assert loan_after["au_status"] == "RECOMMEND_APPROVE"

    def test_underwriting_case_stale_round_one_reports_do_not_satisfy_round_two(self, api):
        """PRD §3.4: "When all three service types — `INCOME`, `ASSET`, and
        `EMPLOYMENT` — hold a report with `result` `VALIDATED` for the current
        round, the case moves `VALIDATING → VALIDATED`."

        Design: Difficulty/non_linear_state_machine/underwriting_case_failure_revision_loop
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-CYC2")
        case = open_underwriting_case(loan, seller)

        # Round 1: all three VALIDATED except a late NOT_VALIDATED -> FAILED.
        validate_case_round(case, ref_prefix="PR-A")
        stale_validated = get_case(case["id"])
        assert stale_validated["case_status"] == "VALIDATED"

        # A separate case walks the failure loop and proves the gate looks only
        # at the current round: after the round-1 failure, two VALIDATED
        # reports in round 2 leave the case VALIDATING, not VALIDATED, even
        # though round 1 holds VALIDATED reports of the missing service type.
        loan2 = create_draft_loan(seller, servicer, agreement, loan_number="LN-CYC3")
        case2 = open_underwriting_case(loan2, seller)
        r1 = add_validation_report(case2, "INCOME", "PR-B1")
        complete_report(r1, "VALIDATED")
        r2 = add_validation_report(case2, "ASSET", "PR-B2")
        complete_report(r2, "NOT_VALIDATED")
        assert get_case(case2["id"])["case_status"] == "FAILED"
        mid = get_case(case2["id"])
        r3 = add_validation_report(mid, "INCOME", "PR-B3")
        complete_report(r3, "VALIDATED")
        r4 = add_validation_report(mid, "ASSET", "PR-B4")
        complete_report(r4, "VALIDATED")
        # EMPLOYMENT for round 2 is still missing: the round-1 VALIDATED
        # INCOME report must not satisfy the round-2 gate.
        still = get_case(case2["id"])
        assert still["case_status"] == "VALIDATING"
        assert still["submission_round"] == 2

    def test_validation_reports_filtered_list_reverse_reaches_case(self, api):
        """PRD §3.4: "Each new report belongs to the case's current
        `submission_round`, recorded on the report as `round`, and starts with
        `result` of `PENDING`. Reports may be listed filtered by `case_id` or
        `service_type`."

        Design: Corner/endpoints/validation_reports_filtered_list_reverse_reaches_case
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-VR")
        case = open_underwriting_case(loan, seller)
        for service_type in ("INCOME", "ASSET", "EMPLOYMENT"):
            add_validation_report(case, service_type, f"PR-{service_type}")
        data, meta = validate_paginated(
            api.list_validation_reports(ADMIN, params={"case_id": case["id"]})
        )
        assert len(data) == 3
        assert meta["total_count"] == 3
        assert all(r["round"] == 1 for r in data)
        assert all(r["result"] == "PENDING" for r in data)
        assert {r["service_type"] for r in data} == {"INCOME", "ASSET", "EMPLOYMENT"}


class TestEligibilityOutcomes:
    def test_credit_score_620_inclusive_boundary_vs_619(self, api):
        """PRD §3.4: "The loan is eligible only when its `ltv_bp` is at most
        9500 (the maximum loan-to-value of 95.00 percent — a loan at exactly
        9500 is eligible, one at 9501 is not), its `credit_score` is at least
        620 (exactly 620 is eligible, 619 is not), its `occupancy` is one of
        the three enumerated values, and its `product_type` is one of the three
        enumerated values."
        PRD §3.4: "For an eligible loan, `final_outcome` is `PASS`, and the
        `recommendation` is `REFER_WITH_CAUTION` when the `credit_score` is
        below 680 or the `ltv_bp` is above 9000."

        Design: Corner/calculations/credit_score_620_inclusive_boundary_vs_619
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan620 = create_draft_loan(seller, servicer, agreement, loan_number="LN-620",
                                    credit_score=620)
        case620 = underwrite_loan(loan620, seller)
        assert case620["final_outcome"] == "PASS"
        assert case620["recommendation"] == "REFER_WITH_CAUTION"

        loan619 = create_draft_loan(seller, servicer, agreement, loan_number="LN-619",
                                    credit_score=619)
        case619 = underwrite_loan(loan619, seller)
        assert case619["final_outcome"] == "FAIL"
        loan619_after = get_loan(loan619["id"])
        assert loan619_after["status"] == "REJECTED"
        assert loan619_after["au_status"] == "INELIGIBLE"

    def test_ltv_9500_inclusive_boundary(self, api):
        """PRD §3.4: "The loan is eligible only when its `ltv_bp` is at most
        9500 (the maximum loan-to-value of 95.00 percent — a loan at exactly
        9500 is eligible, one at 9501 is not)."
        PRD §3.4: "For an eligible loan, `final_outcome` is `PASS`, and the
        `recommendation` is `REFER_WITH_CAUTION` when the `credit_score` is
        below 680 or the `ltv_bp` is above 9000."
        PRD §3.4: "A `PASS` with `REFER_WITH_CAUTION` leaves the loan in
        `DRAFT` — a cautionary recommendation does not advance the loan —
        while setting its `au_status` to `RECOMMEND_REFER`. A `FAIL` moves
        the loan `DRAFT → REJECTED` and sets its `au_status` to `INELIGIBLE`."

        Design: Difficulty/boundary_precision_check/ltv_9500_inclusive_boundary
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        # 10000 * 475000000 / 500000000 = 9500 exactly.
        loan95 = create_draft_loan(seller, servicer, agreement, loan_number="LN-B95",
                                   unpaid_principal_balance_cents=475000000)
        # 10000 * 475025000 / 500000000 = 9500.5 -> round-half-up -> 9501.
        loan96 = create_draft_loan(seller, servicer, agreement, loan_number="LN-B96",
                                   unpaid_principal_balance_cents=475025000)
        case95 = underwrite_loan(loan95, seller)
        case96 = underwrite_loan(loan96, seller)
        assert case95["final_outcome"] == "PASS"
        # 9500 > 9000 places the loan in the refer band.
        assert case95["recommendation"] == "REFER_WITH_CAUTION"
        assert case96["final_outcome"] == "FAIL"
        after95 = get_loan(loan95["id"])
        after96 = get_loan(loan96["id"])
        assert after95["ltv_bp"] == 9500
        assert after95["status"] == "DRAFT"
        assert after95["au_status"] == "RECOMMEND_REFER"
        assert after96["ltv_bp"] == 9501
        assert after96["status"] == "REJECTED"
        assert after96["au_status"] == "INELIGIBLE"

    def test_refer_recommendation_keeps_loan_in_draft(self, api):
        """PRD §3.4: "A `PASS` with `REFER_WITH_CAUTION` leaves the loan in
        `DRAFT` — a cautionary recommendation does not advance the loan — while
        setting its `au_status` to `RECOMMEND_REFER`."

        Design: Difficulty/boundary_precision_check/ltv_9500_inclusive_boundary
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-REFB",
                                 credit_score=670)
        case = underwrite_loan(loan, seller)
        assert case["final_outcome"] == "PASS"
        assert case["recommendation"] == "REFER_WITH_CAUTION"
        after = get_loan(loan["id"])
        assert after["status"] == "DRAFT"
        assert after["au_status"] == "RECOMMEND_REFER"


class TestOccOnFinalize:
    def test_error_stale_version_on_underwriting_finalize(self, api):
        """PRD §2.8: "Finalizing an underwriting case requires the request to
        carry `expected_case_version`, equal to the case's current `version` as
        last observed by the caller; if another writer has advanced the case's
        version since that read — for example through a prior finalize or a
        cascaded mutation — the finalize is rejected with `ERR_STALE_VERSION`
        (HTTP 412), because the caller's view of the case is out of date."

        Design: Corner/errors/error_stale_version_on_underwriting_finalize
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-OCC")
        case = open_underwriting_case(loan, seller)
        validate_case_round(case)
        ready = get_case(case["id"])
        assert ready["case_status"] == "VALIDATED"
        stale = api.finalize_underwriting_case(
            case["id"], {"expected_case_version": ready["version"] - 1}, UW_ENGINE
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)
        assert get_case(case["id"])["case_status"] == "VALIDATED"
        finalized = finalize_case(case)
        assert finalized["final_outcome"] == "PASS"
        assert finalized["case_status"] == "FINALIZED"

    def test_underwriter_cannot_finalize_cases(self, api):
        """PRD §4: "POST /gse/underwriting-cases/{caseId}/finalize —
        GseUnderwritingEngine".
        PRD §2.1: "When a caller attempts an operation outside the permissions
        of their declared role, or fails an ownership check tied to their
        identity, the request is rejected with `ERR_FORBIDDEN_FOR_ROLE`
        (HTTP 403)."

        Design: Corner/roles/underwriter_cannot_finalize_cases
        """
        seller, servicer, agreement, _ = setup_counterparty_chain()
        loan = create_draft_loan(seller, servicer, agreement, loan_number="LN-RB")
        case = open_underwriting_case(loan, seller)
        validate_case_round(case)
        ready = get_case(case["id"])
        resp = api.finalize_underwriting_case(
            case["id"], {"expected_case_version": ready["version"]}, UNDERWRITER
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_case(case["id"])["case_status"] == "VALIDATED"
