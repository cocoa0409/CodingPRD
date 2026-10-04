"""Submission lifecycle: initial state, adjudication gates, the bounded
resubmission loop, frozen accounts, and issuance ordering."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_store, create_account, create_receipt, cash_line,
    create_active_program,
    submit_receipt, approve_submission, reject_submission, resubmit_submission,
    setup_store_with_program, setup_account_with_receipt,
    setup_approved_submission, make_customer_headers,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _instant(text):
    """Parse an ISO 8601 UTC timestamp for instant-level comparison."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
        timezone.utc)


class TestSubmissionCreation:

    def test_submission_created_enters_under_review_in_same_request(self, api):
        """PRD §3.5: "Every submission enters `SUBMITTED` and then, within
        the same request that creates or resubmits it, transitions
        automatically to `UNDER_REVIEW` after fraud screening. At that
        moment the system computes a **provisional award** and records it in
        `provisional_award_cents`."
        PRD §3.5: "The adjudicated variant — computed when guest service
        approves — subtracts the current `returned_quantity`, enforces
        `min_quantity`, and freezes its result into `award_cents`, which is
        null until adjudication."

        Design: Corner/state_machines/submission_created_enters_under_review_in_same_request
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-SM4"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        assert submission["status"] == "UNDER_REVIEW", (
            "the SUBMITTED -> UNDER_REVIEW transition fires inside the "
            "creation request"
        )
        assert submission["resubmit_count"] == 0
        assert submission["provisional_award_cents"] == 1100
        assert submission["award_cents"] is None
        assert submission["rejection_reason"] is None


class TestSubmissionDeadlineBoundary:

    def test_submission_at_exact_deadline_instant_accepted(self, api):
        """PRD §2.6: "A submission deadline is computed from the purchase
        *date* at 00:00:00Z plus a whole number of days, and the deadline
        instant itself is still valid — a submission landing exactly on the
        deadline is accepted."

        Design: Difficulty/boundary_precision_check/submission_deadline_inclusive_at_exact_instant
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-BP1"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        # purchase date 2026-09-08 + 30 days -> deadline 2026-10-08T00:00:00Z
        set_clock("2026-10-08T00:00:00Z")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        assert submission["status"] == "UNDER_REVIEW"
        assert submission["provisional_award_cents"] == 1100

    def test_submission_one_second_past_deadline_rejected(self, api):
        """PRD §3.5: "Creation is rejected with
        `ERR_SUBMISSION_WINDOW_CLOSED` (422) once the logical clock is past
        the deadline — the purchase date at 00:00:00Z plus the store's
        `submission_window_days` days, with the deadline instant itself still
        accepted."

        Design: Difficulty/boundary_precision_check/submission_deadline_inclusive_at_exact_instant
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-BP1"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Bob")
        set_clock("2026-10-08T00:00:01Z")
        resp = api.create_submission(
            base["store"]["id"], {"receipt_id": ctx["receipt"]["id"]},
            make_customer_headers(ctx["account"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED)


class TestAdjudicationStateGate:

    def test_adjudicate_rejected_submission_returns_invalid_state(self, api):
        """PRD §3.5: "Guest service adjudicates a submission in
        `UNDER_REVIEW` with a `decision` of `APPROVE` or `REJECT`;
        adjudicating a submission in any other status is rejected with
        `ERR_INVALID_STATE` (409)."

        Design: Corner/state_machines/adjudicate_rejected_submission_returns_invalid_state
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-SM1"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        submission = reject_submission(
            base["store"]["id"], submission["id"], reason="illegible"
        )
        assert submission["status"] == "REJECTED"
        # clock stays well inside the 30-day window
        set_clock("2026-09-09T00:00:00Z")
        resp = api.adjudicate_submission(
            base["store"]["id"], submission["id"], {"decision": "APPROVE"}, GUEST
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        data = validate_success(api.get_submission(
            base["store"]["id"], submission["id"], GUEST
        ))
        assert data["status"] == "REJECTED"


class TestFrozenAccount:

    def test_account_frozen_blocks_submission_and_adjudication(self, api):
        """PRD §3.3: "Fraud investigation can freeze an account, moving it
        from `ACTIVE` to `FROZEN`; while frozen, submissions, certificate
        issuance, and redemption are all rejected, although accrual reversals
        driven by returns are not blocked."
        PRD §3.5: "A submission on a `FROZEN` account is rejected with
        `ERR_ACCOUNT_FROZEN` (409)."
        PRD §3.5: "Approval is permitted only while the submission window is
        still open — the same deadline rule as creation, evaluated against
        the receipt's purchase date, with `ERR_SUBMISSION_WINDOW_CLOSED`
        (422) past it — and only while the account is not `FROZEN`, with
        `ERR_ACCOUNT_FROZEN` (409) otherwise."

        Design: Corner/errors/account_frozen_blocks_submission_and_adjudication
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-ERR3"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        store = base["store"]
        ctx = setup_account_with_receipt(store, owner_name="Ann")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 5000)],
            purchase_at="2026-09-08T11:00:00Z", receipt_number="R-ERR3-2",
        )
        sub1 = submit_receipt(store["id"], ctx["receipt"]["id"], ctx["account"])
        account = validate_success(api.freeze_account(
            store["id"], ctx["account"]["id"], FRAUD
        ))
        assert account["status"] == "FROZEN"

        resp1 = api.create_submission(
            store["id"], {"receipt_id": r2["id"]},
            make_customer_headers(ctx["account"]["id"]),
        )
        validate_error(resp1, ApiErrorId.ERR_ACCOUNT_FROZEN)

        resp2 = api.adjudicate_submission(
            store["id"], sub1["id"], {"decision": "APPROVE"}, GUEST
        )
        validate_error(resp2, ApiErrorId.ERR_ACCOUNT_FROZEN)

        rejected = reject_submission(
            store["id"], sub1["id"], reason="under fraud review"
        )
        assert rejected["status"] == "REJECTED", (
            "adjudicate-REJECT still works on a frozen account"
        )


class TestResubmissionCycle:

    def test_rejected_submission_resubmits_and_reenters_under_review(self, api):
        """PRD §3.5: "The customer — retail or contractor — may resubmit it,
        cycling `REJECTED` back to `SUBMITTED` and then again automatically
        to `UNDER_REVIEW` within the same request."
        PRD §3.5: "Each resubmission increments `resubmit_count` by 1,
        refreshes `submitted_at` to the current logical clock, clears the
        `rejection_reason`, and recomputes the provisional award."

        Design: Difficulty/non_linear_state_machine/submission_rejected_resubmit_cycle_bounded_by_counter
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-NL2"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        submission = reject_submission(
            base["store"]["id"], submission["id"], reason="illegible receipt"
        )
        assert submission["status"] == "REJECTED"
        assert submission["rejection_reason"] == "illegible receipt"

        resubmitted = resubmit_submission(
            base["store"]["id"], submission["id"], ctx["account"]
        )
        assert resubmitted["status"] == "UNDER_REVIEW"
        assert resubmitted["resubmit_count"] == 1
        assert resubmitted["rejection_reason"] is None
        assert resubmitted["provisional_award_cents"] == 1100

    def test_resubmit_cycle_hard_capped_at_three(self, api):
        """PRD §3.5: "Resubmission requires `resubmit_count` to still be
        below the hard cap of 3 cycles — at the cap, the attempt is rejected
        with `ERR_RESUBMIT_LIMIT_REACHED` (409)"

        Design: Difficulty/non_linear_state_machine/submission_rejected_resubmit_cycle_bounded_by_counter
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-NL2"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        reasons = [
            "illegible receipt", "still illegible", "third strike",
            "final rejection",
        ]
        for reason in reasons:
            submission = reject_submission(
                base["store"]["id"], submission["id"], reason=reason
            )
            assert submission["status"] == "REJECTED"
            if reason != "final rejection":
                submission = resubmit_submission(
                    base["store"]["id"], submission["id"], ctx["account"]
                )
        # after 3 cycles the submission sits REJECTED with resubmit_count 3
        assert submission["resubmit_count"] == 3
        assert submission["rejection_reason"] == "final rejection"

        resp = api.resubmit_submission(
            base["store"]["id"], submission["id"],
            make_customer_headers(ctx["account"]["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_RESUBMIT_LIMIT_REACHED)
        data = validate_success(api.get_submission(
            base["store"]["id"], submission["id"], GUEST
        ))
        assert data["status"] == "REJECTED"
        assert data["resubmit_count"] == 3

    def test_third_resubmit_cycle_still_allowed_below_cap(self, api):
        """PRD §3.5: "Resubmission requires `resubmit_count` to still be
        below the hard cap of 3 cycles — at the cap, the attempt is rejected
        with `ERR_RESUBMIT_LIMIT_REACHED` (409)"
        PRD §3.5: "Each resubmission increments `resubmit_count` by 1,
        refreshes `submitted_at` to the current logical clock, clears the
        `rejection_reason`, and recomputes the provisional award."

        Design: Difficulty/non_linear_state_machine/submission_rejected_resubmit_cycle_bounded_by_counter
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-NL2C"},
            items=[{"sku": "AAA", "rebate_pct": 0.11}],
        )
        ctx = setup_account_with_receipt(base["store"], owner_name="Ann")
        submission = submit_receipt(
            base["store"]["id"], ctx["receipt"]["id"], ctx["account"]
        )
        for _ in range(3):
            submission = reject_submission(
                base["store"]["id"], submission["id"], reason="illegible"
            )
            submission = resubmit_submission(
                base["store"]["id"], submission["id"], ctx["account"]
            )
        # after three REJECTED -> SUBMITTED cycles the submission is back
        # UNDER_REVIEW with resubmit_count exactly at the cap
        assert submission["status"] == "UNDER_REVIEW"
        assert submission["resubmit_count"] == 3, (
            "the loop repeats exactly 3 times; the cap blocks only the "
            "FOURTH resubmit from a REJECTED state"
        )


class TestIssuanceOrdering:

    def test_issuance_cascade_visible_atomically_in_same_request(self, api):
        """PRD §3.5: "Issuance mints a `RebateCertificate` in `ACTIVE` status
        with `issued_amount_cents` equal to the submission's `award_cents`,
        `remaining_balance_cents` equal to the issued amount, `issued_at` set
        to the logical clock"
        PRD §3.5: "The account's balances update in a pinned order:
        `pending_award_cents` is decremented *before*
        `credit_balance_cents` is incremented, so a certificate never
        double-counts within the same request."
        PRD §3.6: "A certificate's `expires_at` is projected at issuance:
        the `issued_at` instant advanced by the store's
        `certificate_validity_months` whole calendar months, snapped to
        00:00:00Z of the resulting calendar day."

        Design: Corner/consistency_model/issuance_cascade_visible_atomically_in_same_request
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CM1"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_account_with_receipt(store, owner_name="Ann")
        submission = approve_submission(
            store["id"],
            submit_receipt(store["id"], ctx["receipt"]["id"], ctx["account"])["id"],
        )
        set_clock("2026-09-08T12:00:00Z")
        cert = validate_success(
            api.issue_certificate(store["id"], submission["id"], GUEST)
        )
        assert cert["status"] == "ACTIVE"
        assert cert["issued_amount_cents"] == 1000
        assert cert["remaining_balance_cents"] == 1000
        # issued 2026-09-08T12:00:00Z + 1 whole month -> 2026-10-08T00:00:00Z
        # compare instants: the PRD pins the instant, not the fractional-
        # second wire spelling
        assert _instant(cert["expires_at"]) == _instant("2026-10-08T00:00:00Z")
        assert cert["submission_id"] == submission["id"]
        assert cert["store_id"] == store["id"]

        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 1000
        assert account["pending_award_cents"] == 0

    def test_issue_certificate_from_non_approved_submission_rejected(self, api):
        """PRD §3.5: "Once a submission is `APPROVED`, guest service issues
        the certificate that settles it."
        PRD §3.5: "adjudicating a submission in any other status is rejected
        with `ERR_INVALID_STATE` (409)."

        Design: Corner/endpoints/issue_certificate_from_non_approved_submission_rejected
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-EP3"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_account_with_receipt(store, owner_name="Ann")
        submission = submit_receipt(
            store["id"], ctx["receipt"]["id"], ctx["account"]
        )
        assert submission["status"] == "UNDER_REVIEW"
        resp = api.issue_certificate(store["id"], submission["id"], GUEST)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0
        ledger = get_success_data(
            api.list_ledger(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert ledger == [], "no certificate or ledger entry may be created"


class TestDerivedFieldReconciliation:

    def test_derived_fields_reconcile_across_full_certificate_lifecycle(self, api):
        """PRD §3.3: "`pending_award_cents`, the sum of `award_cents` over
        the account's submissions in `APPROVED` status"
        PRD §3.7: "plus the `award_cents` of every submission of the store in
        `APPROVED` status, covering awards that are approved but not yet
        settled by a certificate."
        PRD §3.7: "The net liability, `net_liability_cents`, is the gross
        figure multiplied by one minus the store's `expected_breakage_rate`,
        with a single round-half-up to whole cents applied at the very end."

        Design: Corner/cross_cutting_layers/derived_fields_reconcile_across_full_certificate_lifecycle
        """
        from test_helpers import redeem_certificate
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CC2"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_account_with_receipt(store, owner_name="Ann")
        submission = submit_receipt(
            store["id"], ctx["receipt"]["id"], ctx["account"]
        )
        submission = approve_submission(store["id"], submission["id"])
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["pending_award_cents"] == 1000
        assert account["credit_balance_cents"] == 0

        cert = validate_success(
            api.issue_certificate(store["id"], submission["id"], GUEST)
        )
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["pending_award_cents"] == 0
        assert account["credit_balance_cents"] == 1000, (
            "no double-count inside the issuance request"
        )

        set_clock("2026-09-12T00:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 250)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-CC2-2",
        )
        redeem_certificate(store["id"], cert["id"], r2["id"], 250)

        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 750
        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 750
        assert store_read["net_liability_cents"] == 563, (
            f"round_half_up(750 * 0.75) = 563, got "
            f"{store_read['net_liability_cents']}"
        )
