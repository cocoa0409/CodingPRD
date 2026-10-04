"""Invoices: parallel state dimensions, pay/waive settlement, ledger, clock."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    validate_success,
    validate_error,
    validate_paginated,
    get_success_data,
    setup_shipped_project,
    setup_shipped_project_with_lifetime,
    create_and_submit_report,
    create_and_dispute_report,
    create_and_accept_report,
    create_policy_change_payload,
    review_report,
    get_invoice_for_report,
    set_clock,
)

ADMIN = TEST_USERS["admin_headers"]
FINANCE = TEST_USERS["finance_headers"]
REVIEWER = TEST_USERS["reviewer_headers"]


def _setup_finalized_invoice(api, charity=False, version_string="2022.3.10f1"):
    """PRO org, revenue gate met, SHIPPED project, one ACCEPTED report with a
    FINALIZED/UNPAID invoice of 2,000,000 cents."""
    org, ev, project, _ = setup_shipped_project_with_lifetime(
        1_100_000, version_string=version_string, charity_flag=charity
    )
    return org, project


def _setup_grandfathered_finalized_invoice(api, version_string="2022.3.18f1"):
    """Waive-eligible nonzero invoice without charity_flag (charity zeroes the fee per
    PRD §3.4: 'the amount is zero regardless of the gate'). Eligibility instead comes
    from the PRD §3.4 'grandfathering was applied in error' branch: the project is
    pinned to an ACTIVE GrandfatherCommitment (BASE label) by a retroactive adverse
    policy activation, so the FINALIZED invoice carries fee_schedule_label BASE and is
    waive-eligible but capped at half the final amount."""
    set_clock("2026-01-05T00:00:00Z")
    org, ev, project = setup_shipped_project(
        revenue_cents=160_000_000, version_string=version_string
    )
    policy = get_success_data(
        api.create_policy_change(
            create_policy_change_payload(
                change_code="RETRO-2026",
                announcement_date="2026-02-01",
                effective_date="2026-01-01",
                retroactive_flag=True,
                adverse_flag=True,
                grandfather_window_days=45,
                new_per_install_cents=30,
            ),
            ADMIN,
        ),
        201,
    )
    get_success_data(api.activate_policy_change(policy["id"], ADMIN), 200)
    rep = create_and_accept_report(org, project["id"], "2026-01", 1_100_000)
    return org, project, rep


def _setup_blank_shipped(api, version_string):
    """PRO org, revenue gate met, SHIPPED project with lifetime_installs == 0."""
    org, ev, project = setup_shipped_project(
        revenue_cents=160_000_000, version_string=version_string
    )
    return org, project


# ---------------------------------------------------------------------------
# Queue A — non_linear_state_machine / runtime_invoice_parallel_dimensions_evolve_independently
# ---------------------------------------------------------------------------

class TestParallelInvoiceDimensions:
    def test_finalized_invoice_turns_overdue_via_clock(self, api):
        """PRD §2.8: "A RuntimeFeeInvoice carries two independent status dimensions
        that evolve in parallel: an assessment dimension (assessment_status, one of
        PROVISIONAL, FINALIZED, DISPUTED, ADJUSTED, VOIDED) tracking how firmly the
        amount is established, and a payment dimension (payment_status, one of UNPAID,
        PAID, WAIVED, OVERDUE) tracking collection."
        PRD §3.4: "When the logical clock passes an invoice's due_date with an
        outstanding balance still above zero, the payment dimension flips to OVERDUE
        and the org's standing is recomputed — at least one overdue invoice forces the
        standing to at least REVIEW."

        Design: Difficulty/non_linear_state_machine/runtime_invoice_parallel_dimensions_evolve_independently
        """
        set_clock("2026-09-01T00:00:00Z")
        org, project = _setup_finalized_invoice(api)
        set_clock("2026-10-15T00:00:00Z")

        invoice = get_invoice_for_report(
            validate_paginated(api.list_project_invoices(project["id"], ADMIN))[0][0]["report_id"]
        )
        assert invoice["assessment_status"] == "FINALIZED"
        assert invoice["payment_status"] == "OVERDUE"
        assert invoice["final_amount_cents"] == 2_000_000

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["org_standing"] == "REVIEW"

    def test_overdue_invoice_remains_payable(self, api):
        """PRD §3.4: "A FinanceOps operator pays an invoice by supplying an amount_cents
        that must equal the outstanding balance — final_amount_cents minus paid_cents
        minus waived_cents — exactly; the assessment dimension must be FINALIZED, and
        the payment dimension must be UNPAID or OVERDUE."

        Design: Difficulty/non_linear_state_machine/runtime_invoice_parallel_dimensions_evolve_independently
        """
        set_clock("2026-09-01T00:00:00Z")
        org, project = _setup_finalized_invoice(api)
        invoice = get_invoice_for_report(
            validate_paginated(api.list_project_invoices(project["id"], ADMIN))[0][0]["report_id"]
        )
        set_clock("2026-10-15T00:00:00Z")

        paid = get_success_data(
            api.pay_invoice(invoice["id"], {"amount_cents": 2_000_000}, FINANCE), 200
        )
        assert paid["payment_status"] == "PAID"
        assert paid["assessment_status"] == "FINALIZED"
        assert paid["paid_cents"] == 2_000_000


# ---------------------------------------------------------------------------
# Queue A — priority_pair_validation_conflict / pay_overdue_invoice_state_gate_beats_payment_exactness
# ---------------------------------------------------------------------------

class TestPaymentStateGatePriority:
    def test_pay_on_disputed_invoice_returns_invalid_state(self, api):
        """PRD §2.8: "Payment actions (pay, waive) are only legal once the assessment
        dimension has reached FINALIZED."
        PRD §2.10: "then target-state legality for action endpoints (ERR_INVALID_STATE),
        then org-level standing and migration gates ... then payment exactness
        (ERR_PAYMENT_EXCEEDS_BALANCE)".

        Design: Difficulty/priority_pair_validation_conflict/pay_overdue_invoice_state_gate_beats_payment_exactness
        """
        org, project = _setup_blank_shipped(api, "2022.3.13f1")
        rep = create_and_dispute_report(org, project["id"], "2026-01", 1_150_000, note="check figures")
        invoice = get_invoice_for_report(rep["id"])
        assert invoice["assessment_status"] == "DISPUTED"

        resp = api.pay_invoice(invoice["id"], {"amount_cents": 99_999_999}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)

    def test_disputed_invoice_not_payable_at_exact_amount_either(self, api):
        """PRD §2.8: "Payment actions (pay, waive) are only legal once the assessment
        dimension has reached FINALIZED."

        Design: Difficulty/priority_pair_validation_conflict/pay_overdue_invoice_state_gate_beats_payment_exactness
        """
        org, project = _setup_blank_shipped(api, "2022.3.13f1")
        rep = create_and_dispute_report(org, project["id"], "2026-01", 1_150_000, note="check figures")
        invoice = get_invoice_for_report(rep["id"])
        # 100,000 x 20c + 50,000 x 5c = 2,250,000 provisional, frozen under DISPUTED.
        assert invoice["provisional_amount_cents"] == 2_250_000

        resp = api.pay_invoice(invoice["id"], {"amount_cents": 2_250_000}, FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE.value)


# ---------------------------------------------------------------------------
# Queue A — compensating_invariant / invoice_pay_waive_conserves_balance_due
# ---------------------------------------------------------------------------

class TestPayWaiveCompensatingInvariant:
    def test_partial_waive_then_exact_pay_zeroes_balance(self, api):
        """PRD §2.8: "Every pay and every waive is a compensating entry: the invoice's
        outstanding falls by exactly the amount applied, and the org's balance_due_cents
        falls by the same amount, so that the identity 'final minus paid minus waived
        minus the balance-due delta equals zero' is preserved at every step."
        PRD §3.4: "the requested waiver must respect the waiver cap: half of the final
        amount, computed by multiplying final_amount_cents by 0.5 and rounding half up
        to whole cents before comparison, unless the invoice qualifies for a full
        waiver."

        Design: Difficulty/compensating_invariant/invoice_pay_waive_conserves_balance_due
        """
        org, project, _rep = _setup_grandfathered_finalized_invoice(api, version_string="2022.3.18f1")
        invoice = get_invoice_for_report(
            validate_paginated(api.list_project_invoices(project["id"], ADMIN))[0][0]["report_id"]
        )
        assert invoice["final_amount_cents"] == 2_000_000
        assert invoice["fee_schedule_label"] == "BASE"

        waived = get_success_data(
            api.waive_invoice(
                invoice["id"],
                {"amount_cents": 1_000_000,
                 "reason": "grandfathering applied in error"},
                FINANCE,
            ),
            200,
        )
        assert waived["waived_cents"] == 1_000_000

        paid = get_success_data(
            api.pay_invoice(invoice["id"], {"amount_cents": 1_000_000}, FINANCE), 200
        )
        assert paid["paid_cents"] == 1_000_000
        assert paid["payment_status"] == "PAID"

        ledger = validate_success(api.get_org_ledger(org["id"], FINANCE), 200)
        assert ledger["invoiced_cents"] == 2_000_000
        assert ledger["balance_due_cents"] == 0

        org_now = get_success_data(api.get_org(org["id"], ADMIN), 200)
        assert org_now["balance_due_cents"] == 0

    def test_waive_reduces_balance_by_exact_amount(self, api):
        """PRD §3.4: "A successful waive adds to waived_cents, reduces the org's
        balance by the waived amount (preserving the compensating invariant of §2.8),
        and moves the payment dimension to WAIVED once the outstanding reaches zero."

        Design: Difficulty/compensating_invariant/invoice_pay_waive_conserves_balance_due
        """
        org, project, _rep = _setup_grandfathered_finalized_invoice(api, version_string="2022.3.18f1")
        invoice = get_invoice_for_report(
            validate_paginated(api.list_project_invoices(project["id"], ADMIN))[0][0]["report_id"]
        )

        ledger_before = validate_success(api.get_org_ledger(org["id"], FINANCE), 200)
        assert ledger_before["balance_due_cents"] == 2_000_000

        waived = get_success_data(
            api.waive_invoice(
                invoice["id"],
                {"amount_cents": 1_000_000,
                 "reason": "grandfathering applied in error"},
                FINANCE,
            ),
            200,
        )
        assert waived["waived_cents"] == 1_000_000

        ledger_after = validate_success(api.get_org_ledger(org["id"], FINANCE), 200)
        assert ledger_after["balance_due_cents"] == 1_000_000
        assert ledger_after["waived_cents"] == 1_000_000


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_layers / accept_immediately_visible_in_ledger
# ---------------------------------------------------------------------------

class TestImmediateConsistency:
    def test_accept_side_effects_visible_immediately(self, api):
        """PRD §3.4: "acceptance is the settlement moment and cascades three ways: the
        project's lifetime_installs increases by the report's billable_installs (this is
        the one and only point at which installs are consumed into the lifetime count),
        the invoice's assessment_status becomes FINALIZED with final_amount_cents
        recomputed under the final variant and due_date set to 30 days after
        finalization, and the org's balance_due_cents increases by final_amount_cents."

        Design: Corner/consistency_model/accept_immediately_visible_in_ledger
        """
        org, project = _setup_blank_shipped(api, "2022.3.81f1")
        rep = create_and_submit_report(org, project["id"], "2026-01", 1_100_000)
        review_report(rep["id"], "REVIEW")
        review_report(rep["id"], "ACCEPT")

        ledger = validate_success(api.get_org_ledger(org["id"], FINANCE), 200)
        assert ledger["invoiced_cents"] == 2_000_000
        assert ledger["balance_due_cents"] == 2_000_000

        project_now = get_success_data(api.get_project(project["id"], ADMIN), 200)
        assert project_now["lifetime_installs"] == 1_100_000

        invoice = get_invoice_for_report(rep["id"])
        assert invoice["assessment_status"] == "FINALIZED"
        assert invoice["final_amount_cents"] == 2_000_000


# ---------------------------------------------------------------------------
# Queue B — cross_cutting_layers / default_clock_is_fixed_startup_time
# ---------------------------------------------------------------------------

class TestDefaultClock:
    def test_due_date_from_default_clock(self, api):
        """PRD §2.5: "At server startup the logical clock reads exactly
        2026-09-01T00:00:00Z; before any clock-set call has been made, this default is
        the current time for every rule in the system."
        PRD §3.4: "the invoice's assessment_status becomes FINALIZED with
        final_amount_cents recomputed under the final variant and due_date set to 30
        days after finalization".

        Design: Corner/cross_cutting_layers/default_clock_is_fixed_startup_time
        """
        org, project = _setup_blank_shipped(api, "2022.3.80f1")
        rep = create_and_accept_report(org, project["id"], "2026-08", 1_100_000)
        invoice = get_invoice_for_report(rep["id"])
        assert invoice["due_date"] == "2026-10-01"
