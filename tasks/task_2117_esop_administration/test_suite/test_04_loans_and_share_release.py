"""Leveraged borrowing and the release of shares from suspense."""
from test_helpers import (
    TEST_USERS,
    ApiErrorId,
    assert_esop_loan,
    assert_loan_payment,
    assert_share_conservation,
    create_loan,
    create_loan_payment_payload,
    create_plan,
    get_loan,
    get_plan,
    record_loan_payment,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

SPONSOR = TEST_USERS["sponsor_headers"]
TRUSTEE = TEST_USERS["trustee_headers"]
ADMIN = TEST_USERS["admin_headers"]


def _levered_plan(name, release_method):
    plan = create_plan(plan_name=name, sponsor_name="Ironwood Manufacturing Inc.")
    loan = create_loan(plan["id"], release_method=release_method)
    return plan, loan


class TestReleaseMethodDivergence:
    def test_release_method_variants_diverge_on_identical_payments(self, api):
        """PRD 3.2: "Under `PRINCIPAL_ONLY`, the released count is the suspense balance before
        the payment multiplied by the fraction whose numerator is the payment's principal
        component and whose denominator is that same principal component added to the
        principal balance remaining after the payment; the product is floored to a whole
        share. Under `PRINCIPAL_AND_INTEREST`, both sides of the fraction grow: the numerator
        is the principal component added to the interest component, and the denominator is the
        principal component, the interest component, the principal balance remaining after the
        payment and the remaining interest after the payment, all four added together; again
        the product is floored to a whole share."
        PRD 3.2: "Take a loan with 600,000 shares in suspense receiving a payment of
        400,000,000 cents of principal and 200,000,000 cents of interest, leaving
        3,600,000,000 cents of principal and 1,400,000,000 cents of interest outstanding
        afterwards: the principal-only method releases 60,000 shares, while the
        principal-and-interest method releases 64,285 — 4,285 more, because front-loaded
        interest inflates the numerator faster than it inflates the denominator."

        Design: Difficulty/dual_variant_calc/loan_share_release_principal_only_vs_principal_and_interest
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        _plan_po, loan_po = _levered_plan("Ironwood PO", "PRINCIPAL_ONLY")
        _plan_pi, loan_pi = _levered_plan("Ironwood PI", "PRINCIPAL_AND_INTEREST")

        payload_po = create_loan_payment_payload(loan_po["id"])
        payload_pi = create_loan_payment_payload(loan_pi["id"])
        payment_po = validate_success(api.create_loan_payment(payload_po, ADMIN), 201)
        payment_pi = validate_success(api.create_loan_payment(payload_pi, ADMIN), 201)

        assert_loan_payment(payment_po)
        assert_loan_payment(payment_pi)
        assert payment_po["released_shares"] == 60_000
        assert payment_pi["released_shares"] == 64_285
        assert payment_po["released_shares"] != payment_pi["released_shares"], (
            "the two methods diverge materially on identical facts"
        )
        assert payment_po["release_method_applied"] == "PRINCIPAL_ONLY"
        assert payment_pi["release_method_applied"] == "PRINCIPAL_AND_INTEREST"
        assert payment_po["suspense_shares_before"] == 600_000
        assert payment_po["suspense_shares_after"] == 540_000
        assert payment_pi["suspense_shares_after"] == 535_715
        assert payment_po["principal_balance_after_cents"] == 3_600_000_000
        assert payment_po["remaining_interest_after_cents"] == 1_400_000_000

    def test_release_method_variants_move_loan_and_plan_counters(self, api):
        """PRD 3.2: "Whatever the released count works out to, the same three counters move on
        every payment. The loan's `released_shares_cumulative` increases by the released count
        and its `suspense_shares` decreases by it; the plan's `suspense_shares` decreases by
        it; and the plan's `unallocated_released_shares` increases by it, which is precisely
        the pool of shares waiting to be handed to participants at the next allocation."

        Design: Difficulty/dual_variant_calc/loan_share_release_principal_only_vs_principal_and_interest
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        plan_po, loan_po = _levered_plan("Ironwood PO", "PRINCIPAL_ONLY")
        plan_pi, loan_pi = _levered_plan("Ironwood PI", "PRINCIPAL_AND_INTEREST")
        record_loan_payment(loan_po["id"])
        record_loan_payment(loan_pi["id"])

        after_po = get_loan(loan_po["id"])
        after_pi = get_loan(loan_pi["id"])
        assert_esop_loan(after_po)
        assert_esop_loan(after_pi)
        assert after_po["suspense_shares"] == 540_000
        assert after_po["released_shares_cumulative"] == 60_000
        assert after_pi["suspense_shares"] == 535_715
        assert after_pi["released_shares_cumulative"] == 64_285

        plan_po = get_plan(plan_po["id"])
        plan_pi = get_plan(plan_pi["id"])
        assert plan_po["unallocated_released_shares"] == 60_000
        assert plan_po["suspense_shares"] == 540_000
        assert plan_pi["unallocated_released_shares"] == 64_285
        assert plan_pi["suspense_shares"] == 535_715
        assert_share_conservation(plan_po)
        assert_share_conservation(plan_pi)


class TestZeroComponentPayment:
    def test_zero_component_payment_releases_no_shares(self, api):
        """PRD 3.2: "A payment names the `loan_id`, a `payment_date`, and its two components,
        `principal_cents` and `interest_cents`, each of which may be 0 but neither of which
        may be negative."
        PRD 3.2: "Under `PRINCIPAL_ONLY`, the released count is the suspense balance before
        the payment multiplied by the fraction whose numerator is the payment's principal
        component and whose denominator is that same principal component added to the
        principal balance remaining after the payment; the product is floored to a whole
        share."

        Design: Difficulty/boundary_precision_check/zero_component_loan_payment_releases_no_shares
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        _plan, loan = _levered_plan("Zero Payment Plan", "PRINCIPAL_ONLY")

        payload = create_loan_payment_payload(loan["id"], principal_cents=0, interest_cents=0)
        payment = validate_success(api.create_loan_payment(payload, ADMIN), 201)

        assert payment["released_shares"] == 0, "a zero numerator releases exactly no shares"
        assert payment["suspense_shares_before"] == 600_000
        assert payment["suspense_shares_after"] == 600_000
        assert payment["principal_balance_after_cents"] == 4_000_000_000
        assert payment["remaining_interest_after_cents"] == 1_600_000_000

    def test_zero_component_payment_leaves_every_suspense_counter_untouched(self, api):
        """PRD 3.2: "One case overrides the proportion entirely. When the payment's principal
        component brings the loan's principal balance exactly to 0, the loan is fully repaid,
        and the release ignores the ratio and releases the entire remaining suspense balance:
        the released count equals the suspense balance before the payment."
        PRD 3.2: "The loan is created `AMORTIZING`, with `principal_balance_cents` starting at
        the original principal, `remaining_interest_cents` starting at the original interest,
        `suspense_shares` starting at the full pledged count and `released_shares_cumulative`
        at 0."

        Design: Difficulty/boundary_precision_check/zero_component_loan_payment_releases_no_shares
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        plan, loan = _levered_plan("Zero Payment Plan", "PRINCIPAL_ONLY")
        record_loan_payment(loan["id"], principal_cents=0, interest_cents=0)

        after = get_loan(loan["id"])
        assert after["status"] == "AMORTIZING", (
            "a zero-principal payment does not bring the balance to 0, so the loan is not repaid"
        )
        assert after["released_shares_cumulative"] == 0
        assert after["suspense_shares"] == 600_000

        plan = get_plan(plan["id"])
        assert plan["unallocated_released_shares"] == 0
        assert plan["suspense_shares"] == 600_000
        assert_share_conservation(plan)


class TestLoanServicing:
    def test_loan_payment_is_immutable_event_without_version_field(self, api):
        """PRD 2.4: "Two record types are exceptions and are deliberately immutable once
        written: loan payments and share allocation lines carry only `id` and `created_at`.
        Neither `updated_at` nor `version` exists on a loan payment, and neither exists on a
        share allocation line."

        Design: Corner/entities/loan_payment_is_immutable_event_without_version_field
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        _plan, loan = _levered_plan("Immutable Plan", "PRINCIPAL_ONLY")
        payment = record_loan_payment(loan["id"])

        fetched = validate_success(api.get_loan_payment(payment["id"], TRUSTEE))
        assert_loan_payment(fetched)
        assert "version" not in fetched, "a loan payment carries no version field"
        assert "updated_at" not in fetched, "a loan payment carries no updated_at field"
        assert fetched["released_shares"] == 60_000
        assert fetched["release_method_applied"] == "PRINCIPAL_ONLY"

    def test_loan_final_payment_releases_all_suspense_and_marks_repaid(self, api):
        """PRD 3.2: "One case overrides the proportion entirely. When the payment's principal
        component brings the loan's principal balance exactly to 0, the loan is fully repaid,
        and the release ignores the ratio and releases the entire remaining suspense balance:
        the released count equals the suspense balance before the payment. The loan's suspense
        balance is set to 0, the loan advances from `AMORTIZING` to `REPAID`, and every
        pledged share has now made its way out of suspense."

        Design: Corner/state_machines/loan_final_payment_releases_all_suspense_and_marks_repaid
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        plan, loan = _levered_plan("Payoff Plan", "PRINCIPAL_ONLY")
        record_loan_payment(loan["id"])

        payoff = record_loan_payment(loan["id"], payment_date="2026-12-31",
                                     principal_cents=3_600_000_000,
                                     interest_cents=1_400_000_000)
        assert payoff["released_shares"] == 540_000, (
            "the payoff releases the whole remaining suspense balance"
        )
        assert payoff["suspense_shares_after"] == 0
        assert payoff["principal_balance_after_cents"] == 0
        assert payoff["remaining_interest_after_cents"] == 0

        after = get_loan(loan["id"])
        assert after["status"] == "REPAID"
        assert after["suspense_shares"] == 0
        assert after["released_shares_cumulative"] == 600_000

        plan = get_plan(plan["id"])
        assert plan["suspense_shares"] == 0
        assert plan["unallocated_released_shares"] == 600_000
        assert plan["total_plan_shares"] == 600_000
        assert_share_conservation(plan)

    def test_loan_payment_exceeding_balance_rejected(self, api):
        """PRD 3.2: "Neither component may exceed what the loan still owes: a `principal_cents`
        larger than the loan's `principal_balance_cents`, or an `interest_cents` larger than
        its `remaining_interest_cents`, is refused with `ERR_PAYMENT_EXCEEDS_BALANCE`."

        Design: Corner/state_machines/loan_payment_exceeding_balance_rejected
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        _plan, loan = _levered_plan("Overpay Plan", "PRINCIPAL_ONLY")

        payload = create_loan_payment_payload(loan["id"], principal_cents=5_000_000_000,
                                              interest_cents=0)
        validate_error(api.create_loan_payment(payload, ADMIN),
                       ApiErrorId.ERR_PAYMENT_EXCEEDS_BALANCE)

        after = get_loan(loan["id"])
        assert after["principal_balance_cents"] == 4_000_000_000
        assert after["suspense_shares"] == 600_000
        _rows, meta = validate_paginated(
            api.list_loan_payments(ADMIN, params={"loan_id": loan["id"]})
        )
        assert meta["total_count"] == 0, "the refused payment persists no servicing record"

    def test_plan_sponsor_cannot_record_loan_payments(self, api):
        """PRD 3.2: "Servicing is the `PlanAdministrator`'s job. A payment names the
        `loan_id`, a `payment_date`, and its two components, `principal_cents` and
        `interest_cents`, each of which may be 0 but neither of which may be negative."
        PRD 2.1: "When the headers are well formed but the named role does not appear in the
        authorized-role list for the endpoint being called, the request is refused with
        `ERR_FORBIDDEN_ROLE` and HTTP 403."

        Design: Corner/rbac/plan_sponsor_cannot_record_loan_payments
        """
        set_clock("2026-06-30T00:00:00Z", ADMIN)
        _plan, loan = _levered_plan("Loan RBAC", "PRINCIPAL_ONLY")

        payload = create_loan_payment_payload(loan["id"])
        validate_error(api.create_loan_payment(payload, SPONSOR), ApiErrorId.ERR_FORBIDDEN_ROLE)

        after = get_loan(loan["id"])
        assert after["suspense_shares"] == 600_000
        assert after["released_shares_cumulative"] == 0
        _rows, meta = validate_paginated(
            api.list_loan_payments(ADMIN, params={"loan_id": loan["id"]})
        )
        assert meta["total_count"] == 0
