"""Accuracy guarantee claims: lifecycle, cap boundary, and enrollment gate."""
from test_helpers import (
    TEST_USERS,
    GUARANTEE_CAP_CENTS,
    setup_filed_claim,
    setup_under_review_claim,
    unique_email,
    validate_error,
    validate_success,
)
from test_helpers.api_errors import ApiErrorId


class TestClaimReviewCycle:
    def test_partial_approval_reopen_cycle_ends_paid(self, api):
        """PRD §3.8: "A partially approved claim is not final: the adjuster
        may reopen it, moving `PARTIALLY_APPROVED` → `UNDER_REVIEW` provided
        the claim has never reached `PAID`, and the reopening resets
        `reimbursement_cents` to zero pending the new adjudication — the
        review and partial-approval states may loop until payment locks the
        claim."

        Design: Difficulty/non_linear_state_machine/claim_partial_approval_review_cycle
        """
        account, ret, _attempt, claim = setup_under_review_claim(
            claimed_error_amount_cents=8000, email=unique_email("cyc2")
        )
        adjuster = TEST_USERS["claims_adjuster_headers"]
        resp = api.adjudicate_claim(claim["id"], 5000, adjuster)
        partial = validate_success(resp)
        assert partial["status"] == "PARTIALLY_APPROVED"
        assert partial["reimbursement_cents"] == 5000
        resp = api.reopen_claim_review(claim["id"], adjuster)
        reopened = validate_success(resp)
        assert reopened["status"] == "UNDER_REVIEW"
        assert reopened["reimbursement_cents"] == 0
        resp = api.adjudicate_claim(claim["id"], 8000, adjuster)
        approved = validate_success(resp)
        assert approved["status"] == "APPROVED"
        resp = api.pay_claim(claim["id"], adjuster)
        paid = validate_success(resp)
        assert paid["status"] == "PAID"
        assert paid["reimbursement_cents"] == 8000
        assert paid["reviewed_error_amount_cents"] == 8000

    def test_reimbursement_recomputed_after_reopen(self, api):
        """PRD §3.8: "the reopening resets `reimbursement_cents` to zero
        pending the new adjudication — the review and partial-approval states
        may loop until payment locks the claim."

        Design: Difficulty/non_linear_state_machine/claim_partial_approval_review_cycle
        """
        account, ret, _attempt, claim = setup_under_review_claim(
            claimed_error_amount_cents=8000, email=unique_email("cyc2b")
        )
        adjuster = TEST_USERS["claims_adjuster_headers"]
        validate_success(api.adjudicate_claim(claim["id"], 5000, adjuster))
        validate_success(api.reopen_claim_review(claim["id"], adjuster))
        approved = validate_success(api.adjudicate_claim(claim["id"], 8000, adjuster))
        assert approved["reimbursement_cents"] == 8000


class TestCapBoundary:
    def test_claim_above_cap_reimburses_exactly_cap(self, api):
        """PRD §3.8: "Adjudication supplies a `reviewed_error_amount_cents`
        (never negative, else `ERR_INVALID_CLAIM_AMOUNT`) and the outcome
        branches on how it compares to the claimed amount, with the
        reimbursement computed identically on every branch: the lesser of the
        reviewed and claimed amounts, then capped at the $1,000.00 per-return
        guarantee maximum — a claim landing exactly on the cap reimburses
        exactly the cap."

        Design: Corner/calculations/accuracy_reimbursement_cap_boundary
        """
        account, ret, _attempt, claim = setup_under_review_claim(
            claimed_error_amount_cents=150000, email=unique_email("calc2")
        )
        adjuster = TEST_USERS["claims_adjuster_headers"]
        approved = validate_success(api.adjudicate_claim(claim["id"], 150000, adjuster))
        assert approved["status"] == "APPROVED"
        assert approved["reimbursement_cents"] == GUARANTEE_CAP_CENTS

    def test_claim_exactly_at_cap_reimburses_cap(self, api):
        """PRD §3.8: "the reimbursement computed identically on every branch:
        the lesser of the reviewed and claimed amounts, then capped at the
        $1,000.00 per-return guarantee maximum — a claim landing exactly on
        the cap reimburses exactly the cap."

        Design: Corner/calculations/accuracy_reimbursement_cap_boundary
        """
        account, ret, _attempt, claim = setup_under_review_claim(
            claimed_error_amount_cents=100000, email=unique_email("calc2b")
        )
        adjuster = TEST_USERS["claims_adjuster_headers"]
        approved = validate_success(api.adjudicate_claim(claim["id"], 100000, adjuster))
        assert approved["status"] == "APPROVED"
        assert approved["reimbursement_cents"] == 100000


class TestClaimGuards:
    def test_claim_on_unfiled_return_rejected(self, api):
        """PRD §3.8: "The claim requires the referenced return to have reached
        `ACCEPTED` at least once — its current status must be `ACCEPTED` or
        `AMENDED`; a claim against a return that never got there is rejected
        with `ERR_RETURN_NOT_FILED` (HTTP 409), a check evaluated before the
        amount check."

        Design: Corner/validations/claim_on_unfiled_return_rejected
        """
        from test_helpers import setup_return_with_forms

        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("val6")
        )
        from test_helpers import make_taxpayer_headers

        resp = api.create_claim(
            ret.id, 5000, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_RETURN_NOT_FILED)

    def test_zero_claimed_amount_rejected(self, api):
        """PRD §3.8: "When the authority assesses a penalty or interest the
        filer attributes to a software miscalculation, the filer files an
        `AccuracyClaim` against the return, supplying a
        `claimed_error_amount_cents` that must be greater than zero (else
        `ERR_INVALID_CLAIM_AMOUNT`, HTTP 422)."

        Design: Corner/errors/invalid_claim_amount_rejected
        """
        from test_helpers import make_taxpayer_headers, setup_accepted_return

        account, ret, _attempt = setup_accepted_return(
            forms=("F1040",), email=unique_email("err2")
        )
        resp = api.create_claim(
            ret.id, 0, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_CLAIM_AMOUNT)

    def test_guarantee_not_enrolled_blocks_start_review(self, api):
        """PRD §3.8: "A `ClaimsAdjuster` then works the claim. Moving it
        `FILED` → `UNDER_REVIEW` requires the owning account to be enrolled in
        the guarantee program — `accuracy_guarantee_enrolled` must be true,
        else `ERR_GUARANTEE_NOT_ENROLLED` (HTTP 409)."

        Design: Corner/validations/guarantee_not_enrolled_blocks_claim_review
        """
        account, ret, _attempt, claim = setup_filed_claim(
            claimed_error_amount_cents=5000,
            email=unique_email("val7"),
            accuracy_guarantee_enrolled=False,
        )
        assert claim["status"] == "FILED"
        resp = api.start_claim_review(
            claim["id"], TEST_USERS["claims_adjuster_headers"]
        )
        validate_error(resp, ApiErrorId.ERR_GUARANTEE_NOT_ENROLLED)
        claims = api.list_claims(ret.id, TEST_USERS["claims_adjuster_headers"])
        assert validate_success(claims)[0]["status"] == "FILED"


class TestTerminalLockdown:
    def test_paid_claim_cannot_be_reopened(self, api):
        """PRD §3.8: "Payment moves a claim from `APPROVED` or
        `PARTIALLY_APPROVED` to the terminal `PAID` state with no further
        amount changes."

        Design: Corner/state_machines/claim_terminal_lockdown_after_pay
        """
        account, ret, _attempt, claim = setup_under_review_claim(
            claimed_error_amount_cents=8000, email=unique_email("sm5")
        )
        adjuster = TEST_USERS["claims_adjuster_headers"]
        validate_success(api.adjudicate_claim(claim["id"], 8000, adjuster))
        paid = validate_success(api.pay_claim(claim["id"], adjuster))
        assert paid["status"] == "PAID"
        resp = api.reopen_claim_review(claim["id"], adjuster)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        claims = api.list_claims(ret.id, TEST_USERS["claims_adjuster_headers"])
        locked = validate_success(claims)[0]
        assert locked["status"] == "PAID"
        assert locked["reimbursement_cents"] == 8000
