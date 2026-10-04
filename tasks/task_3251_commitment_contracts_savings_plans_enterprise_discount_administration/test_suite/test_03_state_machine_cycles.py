"""Tests for non-linear state machines: parallel axes and repeatable cycles."""
from test_helpers import (
    validate_success,
    api_client,
    make_admin_headers,
    make_finance_headers,
    create_org,
    create_active_agreement,
    create_linked_account,
    setup_finalized_invoice,
)

ADMIN = make_admin_headers()
FINANCE = make_finance_headers()


class TestAgreementParallelAxes:
    """Lifecycle and renewal axes evolve independently on one agreement."""

    def test_suspend_resume_cycle_preserves_renewal_review(self, api):
        """PRD section 3.2: "The agreement carries two parallel state dimensions.
        Lifecycle runs `NEGOTIATION → ACTIVE → SUSPENDED → ACTIVE → …` and ends
        at `EXPIRED` or `TERMINATED`. Renewal runs independently — `NONE →
        RENEWAL_REVIEW → RENEWED` or `NONE → RENEWAL_REVIEW → ABANDONED` — and
        every renewal transition requires the lifecycle to be `ACTIVE`, otherwise
        the call fails with `ERR_AGREEMENT_NOT_ACTIVE` (HTTP 409)."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_axes_suspend_resume_cycle_preserves_renewal_review
        """
        org = create_org(name="Par Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(org["id"], committed_spend_cents=1000000)

        data = validate_success(api.open_renewal_review(agr["id"], FINANCE))
        assert data["renewal_status"] == "RENEWAL_REVIEW"
        assert data["lifecycle_status"] == "ACTIVE"

        data = validate_success(api.suspend_agreement(agr["id"], ADMIN))
        assert data["lifecycle_status"] == "SUSPENDED"
        assert data["renewal_status"] == "RENEWAL_REVIEW", (
            "suspend must not touch the renewal axis"
        )

        data = validate_success(api.resume_agreement(agr["id"], ADMIN))
        assert data["lifecycle_status"] == "ACTIVE"
        assert data["renewal_status"] == "RENEWAL_REVIEW"

    def test_close_renewal_review_after_cycle_reaches_renewed(self, api):
        """PRD section 3.2: "Lifecycle transitions never touch the renewal axis,
        with a single exception: terminating an agreement that sits in
        `RENEWAL_REVIEW` forces its renewal status back to `NONE`."
        PRD section 3.10: "A `FinanceAnalyst` opens a renewal review on an
        `ACTIVE` agreement, moving the renewal axis from `NONE` to
        `RENEWAL_REVIEW`, and later closes it with an `outcome` of either
        `RENEWED` or `ABANDONED`."

        Design: Difficulty/non_linear_state_machine/agreement_parallel_axes_suspend_resume_cycle_preserves_renewal_review
        """
        org = create_org(name="Par Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        agr = create_active_agreement(org["id"], committed_spend_cents=1000000)
        validate_success(api.open_renewal_review(agr["id"], FINANCE))
        validate_success(api.suspend_agreement(agr["id"], ADMIN))
        validate_success(api.resume_agreement(agr["id"], ADMIN))

        data = validate_success(
            api.close_renewal_review(agr["id"], {"outcome": "RENEWED"}, FINANCE)
        )
        assert data["renewal_status"] == "RENEWED"
        assert data["lifecycle_status"] == "ACTIVE"


class TestInvoiceDisputeCycle:
    """FINALIZED -> DISPUTED -> FINALIZED cycle repeats before settle."""

    def _setup(self):
        org = create_org(name="Cyc Org", max_hourly_commitment_cents=100000,
                         capacity_quota_units=100)
        acct = create_linked_account(org["id"], name="acct-1", external_ref="ext-1")
        inv = setup_finalized_invoice(org["id"], acct["id"], 10000)
        return org, acct, inv

    def test_dispute_resolve_cycle_is_repeatable(self, api):
        """PRD section 3.9: "After finalize, an invoice may be disputed and
        resolved — `FINALIZED` to `DISPUTED` with a `reason`, then back to
        `FINALIZED` — a cycle that may repeat and increments the invoice's
        `version` each time."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle_allows_repeated_dispute_before_settle
        """
        _, _, inv = self._setup()
        data = validate_success(
            api.dispute_invoice(inv["id"], {"reason": "rate mismatch"}, ADMIN)
        )
        assert data["status"] == "DISPUTED"
        data = validate_success(api.resolve_dispute(inv["id"], ADMIN))
        assert data["status"] == "FINALIZED"
        data = validate_success(
            api.dispute_invoice(inv["id"], {"reason": "second review"}, ADMIN)
        )
        assert data["status"] == "DISPUTED", (
            "the dispute/resolve cycle is repeatable, not one-shot"
        )
        data = validate_success(api.resolve_dispute(inv["id"], ADMIN))
        assert data["status"] == "FINALIZED"

    def test_invoice_settles_for_exact_total_after_repeated_cycle(self, api):
        """PRD section 3.9: "Settlement moves `FINALIZED` to `SETTLED` and is
        exact-amount: the request's `amount_cents` must equal the invoice's
        `total_due_cents` to the cent, otherwise `ERR_SETTLEMENT_AMOUNT_MISMATCH`
        (HTTP 422)."

        Design: Difficulty/non_linear_state_machine/invoice_dispute_resolve_cycle_allows_repeated_dispute_before_settle
        """
        _, _, inv = self._setup()
        validate_success(api.dispute_invoice(inv["id"], {"reason": "r1"}, ADMIN))
        validate_success(api.resolve_dispute(inv["id"], ADMIN))
        validate_success(api.dispute_invoice(inv["id"], {"reason": "r2"}, ADMIN))
        validate_success(api.resolve_dispute(inv["id"], ADMIN))
        data = validate_success(
            api.settle_invoice(inv["id"], {"amount_cents": 10000}, ADMIN)
        )
        assert data["status"] == "SETTLED"
