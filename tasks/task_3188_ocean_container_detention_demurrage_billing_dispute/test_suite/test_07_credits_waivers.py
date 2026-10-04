"""Credit machinery: waterfall, authority tiers, waiver lifecycle, reversals,
write-off cascade to account unsuspension."""
from test_helpers import (
    ApiErrorId,
    api_client,
    attach_evidence,
    file_dispute,
    make_billing_agent_headers,
    make_credit_director_headers,
    make_credit_supervisor_headers,
    make_customer_rep_headers,
    set_clock,
    setup_dispute_under_review,
    setup_issued_invoice,
    validate_error,
    validate_success,
)

BA = {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}
SUP = {"X-User-ID": "sup-1", "X-User-Role": "CreditSupervisor"}
DIR = {"X-User-ID": "dir-1", "X-User-Role": "CreditDirector"}


def _big_invoice_ctx(account_code, contract_ref, container_number):
    """159000-cent invoice: demurrage 105000 + detention 54000."""
    return setup_issued_invoice(
        account_overrides={"account_code": account_code, "legal_name": f"{account_code} Co"},
        contract_overrides={
            "contract_ref": contract_ref,
            "demurrage_free_days": 4,
            "detention_free_days": 5,
            "saturday_counts_as_free_day": False,
        },
        container_overrides={"container_number": container_number},
        gate_out_clock="2026-09-15T12:00:00Z",
        return_clock="2026-09-29T12:00:00Z",
    )


class TestCreditWaterfallEvaluationOrder:
    def test_waterfall_offsets_detention_first_then_rejects_oversized_second_credit(self):
        """PRD §3.8: "A credit offsets the invoice's detention component first,
        then demurrage: the credited detention portion is the smaller of the
        credit amount and the remaining detention total after credits already
        applied, and the credited demurrage portion is the smaller of whatever
        remains of the credit and the remaining demurrage total after credits
        already applied."
        PRD §3.8: "If the two portions together fall short of the credit amount
        — meaning the credit would exceed the creditable balance or push
        `balance_due_cents` negative — the credit is rejected outright with
        `ERR_CREDIT_EXCEEDS_BALANCE`".

        Design: Difficulty/combinatorial_formula/credit_waterfall_evaluation_order_and_component_offset
        """
        ctx = _big_invoice_ctx("ACCT-D", "CTR-D", "MATU0000052")
        invoice = ctx["invoice"]
        assert invoice["gross_amount_cents"] == 159000

        wv1 = validate_success(api_client.propose_credit_waiver(
            invoice["id"],
            {"amount_cents": 60000, "justification": "goodwill for gate congestion delay"},
            make_credit_supervisor_headers("sup-1"),
        ), 201)
        assert wv1["authority_tier"] == "TIER_2_SUPERVISOR"
        assert wv1["status"] == "PROPOSED"

        wv2 = validate_success(api_client.propose_credit_waiver(
            invoice["id"],
            {"amount_cents": 100000, "justification": "second goodwill, oversized"},
            make_credit_director_headers("dir-1"),
        ), 201)

        approved = validate_success(api_client.approve_credit_waiver(
            wv1["id"], {"expected_waiver_version": wv1["version"]},
            make_credit_director_headers("dir-1"),
        ))
        assert approved["status"] == "APPLIED"

        rejected = api_client.approve_credit_waiver(
            wv2["id"], {"expected_waiver_version": wv2["version"]},
            make_credit_director_headers("dir-1"),
        )
        validate_error(rejected, ApiErrorId.ERR_CREDIT_EXCEEDS_BALANCE)

        inv = validate_success(api_client.get_invoice(invoice["id"], DIR))
        assert inv["credit_total_cents"] == 60000
        assert inv["balance_due_cents"] == 99000

    def test_full_component_credit_voids_matching_accrual_rows(self):
        """PRD §3.8: "When cumulative credits against one component reach
        exactly that component's frozen total, every non-voided
        `ChargeAccrual` row of that kind for the container is flagged `voided`
        true, selected in order of `computed_at` ascending — never by id."

        Design: Difficulty/combinatorial_formula/credit_waterfall_evaluation_order_and_component_offset
        """
        ctx = _big_invoice_ctx("ACCT-D2", "CTR-D2", "MATU0000302")
        invoice = ctx["invoice"]
        # 54000 covers the detention component exactly (detention-first order)
        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 54000, "justification": "detention goodwill"},
            make_credit_supervisor_headers("sup-1"),
        ), 201)
        validate_success(api_client.approve_credit_waiver(
            wv["id"], {"expected_waiver_version": wv["version"]},
            make_credit_director_headers("dir-1"),
        ))
        rows = validate_success(api_client.list_container_accruals(ctx["container"]["id"], DIR))
        detention = [r for r in rows if r["charge_kind"] == "DETENTION"]
        demurrage = [r for r in rows if r["charge_kind"] == "DEMURRAGE"]
        assert detention and all(r["voided"] is True for r in detention)
        assert demurrage and all(r["voided"] is False for r in demurrage)


class TestWaiverTierBoundary:
    def test_agent_cannot_resolve_credit_above_tier1_limit(self):
        """PRD §3.8: "A credit whose amount is at most 50000 cents is
        `TIER_1_AGENT`, actionable by a `BillingAgent` alone; an amount above
        50000 cents and at most 500000 cents is `TIER_2_SUPERVISOR`, requiring
        a `CreditSupervisor` or `CreditDirector`; any amount above 500000 cents
        is `TIER_3_DIRECTOR`, requiring a `CreditDirector`."
        PRD §3.8: "An actor whose tier does not cover the amount is rejected
        with `ERR_WAIVER_AUTHORITY_EXCEEDED` — in dispute resolution this
        applies to the resolved amount, and in the goodwill path it applies at
        both proposal and approval."

        Design: Difficulty/boundary_precision_check/waiver_tier_boundary_exactly_at_tier1_limit
        """
        ctx = setup_dispute_under_review(
            dispute_reason="OTHER",
            contested_amount_cents=50001,
            invoice_kwargs={
                "account_overrides": {"account_code": "ACCT-L2", "legal_name": "Lima Retail"},
                "contract_overrides": {
                    "contract_ref": "CTR-L2",
                    "demurrage_free_days": 4,
                    "detention_free_days": 5,
                    "saturday_counts_as_free_day": False,
                },
                "container_overrides": {"container_number": "MATU0000244"},
                "gate_out_clock": "2026-09-15T12:00:00Z",
                "return_clock": "2026-09-29T12:00:00Z",
            },
        )
        dispute = ctx["dispute"]
        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        resp = api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "FULL_CREDIT",
                "resolved_amount_cents": 50001,
                "resolution_justification": "agent attempt above tier",
                "expected_dispute_version": current["version"],
            },
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_WAIVER_AUTHORITY_EXCEEDED)

    def test_tier1_limit_inclusive_and_one_cent_over(self):
        """PRD §3.8: "A credit whose amount is at most 50000 cents is
        `TIER_1_AGENT`, actionable by a `BillingAgent` alone; an amount above
        50000 cents and at most 500000 cents is `TIER_2_SUPERVISOR`, requiring
        a `CreditSupervisor` or `CreditDirector`; any amount above 500000 cents
        is `TIER_3_DIRECTOR`, requiring a `CreditDirector`."
        PRD §3.8: "The proposal records the proposer's `X-User-ID` in
        `applied_by_user_id`, derives `authority_tier` from the amount, and
        starts the waiver `PROPOSED` — except that a `TIER_1_AGENT` amount
        proposed by an actor of sufficient tier is applied immediately,
        propose-and-apply in one step."

        Design: Difficulty/boundary_precision_check/waiver_tier_boundary_exactly_at_tier1_limit
        """
        ctx = _big_invoice_ctx("ACCT-L", "CTR-L", "MATU0000144")
        invoice = ctx["invoice"]

        at_limit = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 50000, "justification": "at-limit goodwill"}, BA
        ), 201)
        assert at_limit["authority_tier"] == "TIER_1_AGENT"
        assert at_limit["status"] == "APPLIED"

        over = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 50001, "justification": "one cent over"}, BA
        ), 201)
        assert over["authority_tier"] == "TIER_2_SUPERVISOR"
        assert over["status"] == "PROPOSED"

        inv = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert inv["credit_total_cents"] == 50000


class TestWaiverLifecycle:
    def test_rejected_waiver_is_terminal_even_with_correct_version(self):
        """PRD §3.8: "A `CreditSupervisor` or `CreditDirector` may instead
        reject a `PROPOSED` waiver, moving it to `REJECTED`."
        PRD §2.10: "Fifth, the target resource must be in a state from which
        the requested transition exists, otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/credit_waiver_reject_terminal_then_approve_rejected
        """
        ctx = _big_invoice_ctx("ACCT-CW", "CTR-CW", "MATU0001050")
        invoice = ctx["invoice"]
        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 60000, "justification": "supervisor-level goodwill"}, BA
        ), 201)
        validate_success(api_client.reject_credit_waiver(wv["id"], SUP))
        current = validate_success(api_client.get_credit_waiver(wv["id"], SUP))
        resp = api_client.approve_credit_waiver(
            wv["id"], {"expected_waiver_version": current["version"]}, SUP
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_proposer_cannot_approve_own_waiver(self):
        """PRD §3.8: "the approver must not be the proposer, enforced by
        comparing against `applied_by_user_id` and rejecting with
        `ERR_SEGREGATION_OF_DUTIES`".

        Design: Corner/rbac/waiver_proposer_cannot_approve_own_waiver
        """
        ctx = _big_invoice_ctx("ACCT-SD", "CTR-SD", "MATU0001241")
        invoice = ctx["invoice"]
        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 60000, "justification": "supervisor goodwill"},
            make_credit_supervisor_headers("sup-1"),
        ), 201)
        own = api_client.approve_credit_waiver(
            wv["id"], {"expected_waiver_version": wv["version"]},
            make_credit_supervisor_headers("sup-1"),
        )
        validate_error(own, ApiErrorId.ERR_SEGREGATION_OF_DUTIES)

        other = validate_success(api_client.approve_credit_waiver(
            wv["id"], {"expected_waiver_version": wv["version"]},
            make_credit_supervisor_headers("sup-2"),
        ))
        assert other["status"] == "APPLIED"

    def test_reverse_requires_justification(self):
        """PRD §3.8: "An `APPLIED` waiver may be unwound only by a
        `CreditDirector`, only while the invoice is not `PAID` (else
        `ERR_INVOICE_ALREADY_SETTLED`), and only while the reversal would not
        push `paid_total_cents` beyond the gross less remaining credits (else
        `ERR_REVERSAL_EXCEEDS_NET`); reversal requires its own `justification`,
        moves the waiver to `REVERSED`, adds the amount back into
        `balance_due_cents` and the account's `outstanding_balance_cents`, and
        subtracts it from `credit_total_cents`."

        Design: Difficulty/compensating_invariant/credit_apply_reverse_preserves_invoice_net
        """
        ctx = _big_invoice_ctx("ACCT-Q2", "CTR-Q2", "MATU0000221")
        invoice = ctx["invoice"]
        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 40000, "justification": "goodwill"}, DIR
        ), 201)
        assert wv["status"] == "APPLIED"
        resp = api_client.reverse_credit_waiver(wv["id"], {"justification": ""}, DIR)
        validate_error(resp, ApiErrorId.ERR_JUSTIFICATION_REQUIRED)
        still = validate_success(api_client.get_credit_waiver(wv["id"], DIR))
        assert still["status"] == "APPLIED"

    def test_credit_apply_and_reverse_preserve_invoice_net(self):
        """PRD §3.8: "reversal requires its own `justification`, moves the
        waiver to `REVERSED`, adds the amount back into `balance_due_cents` and
        the account's `outstanding_balance_cents`, and subtracts it from
        `credit_total_cents`."
        PRD §3.6: "`balance_due_cents` is the gross minus credits minus
        payments, with the invariant that it never goes below zero."

        Design: Difficulty/compensating_invariant/credit_apply_reverse_preserves_invoice_net
        """
        ctx = _big_invoice_ctx("ACCT-Q", "CTR-Q", "MATU0000219")
        invoice, account = ctx["invoice"], ctx["account"]

        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"],
            {"amount_cents": 40000, "justification": "goodwill, then reconsidered"},
            DIR,
        ), 201)
        mid = validate_success(api_client.get_invoice(invoice["id"], DIR))
        assert mid["balance_due_cents"] == 119000
        acct_mid = validate_success(api_client.get_customer_account(account["id"], DIR))
        assert acct_mid["outstanding_balance_cents"] == 119000

        validate_success(api_client.reverse_credit_waiver(
            wv["id"], {"justification": "reversal per audit finding"}, DIR
        ))
        end = validate_success(api_client.get_invoice(invoice["id"], DIR))
        assert end["balance_due_cents"] == 159000
        assert end["credit_total_cents"] == 0
        assert end["gross_amount_cents"] - end["credit_total_cents"] - end["paid_total_cents"] == end["balance_due_cents"]
        acct_end = validate_success(api_client.get_customer_account(account["id"], DIR))
        assert acct_end["outstanding_balance_cents"] == 159000


class TestPartialCreditPartialPaymentReconciliation:
    def test_payment_plus_credit_reconcile_derived_fields(self):
        """PRD §3.6: "Every payment adds into `paid_total_cents`, recomputes
        `balance_due_cents`, subtracts the amount from the account's
        `outstanding_balance_cents`, and triggers an aging-posture sweep that
        may unsuspend the account."
        PRD §3.6: "A payment below the full balance moves an `ISSUED` invoice
        to `PARTIALLY_PAID`".

        Design: Corner/cross_cutting_layers/partial_credit_partial_payment_invoice_net_tracking
        """
        ctx = _big_invoice_ctx("ACCT-PP", "CTR-PP", "MATU0001266")
        invoice, account = ctx["invoice"], ctx["account"]

        validate_success(api_client.create_payment(
            invoice["id"], {"amount_cents": 50000}, BA
        ), 201)
        wv = validate_success(api_client.propose_credit_waiver(
            invoice["id"], {"amount_cents": 60000, "justification": "goodwill"},
            make_billing_agent_headers("ba-1"),
        ), 201)
        current = validate_success(api_client.get_credit_waiver(wv["id"], SUP))
        validate_success(api_client.approve_credit_waiver(
            wv["id"], {"expected_waiver_version": current["version"]},
            make_credit_supervisor_headers("sup-9"),
        ))

        inv = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert inv["paid_total_cents"] == 50000
        assert inv["credit_total_cents"] == 60000
        assert inv["balance_due_cents"] == 49000
        assert inv["status"] == "PARTIALLY_PAID"
        acct = validate_success(api_client.get_customer_account(account["id"], BA))
        assert acct["outstanding_balance_cents"] == 49000


class TestDisputeResolutionOutcomes:
    def test_denied_resolution_reverts_invoice_without_credit(self):
        """PRD §3.8: "A `DENIED` resolution takes no amount and moves the
        dispute to `RESOLVED_DENIED`."
        PRD §3.8: "A `DENIED` outcome creates no credit and simply returns the
        invoice to `ISSUED` or `PARTIALLY_PAID` on the same paid-versus-unpaid
        rule."

        Design: Corner/state_machines/invoice_disputed_returns_to_issued_on_denial
        """
        ctx = setup_dispute_under_review(
            dispute_reason="OTHER",
            contested_amount_cents=10000,
            invoice_kwargs={
                "account_overrides": {"account_code": "ACCT-DN", "legal_name": "Denial Co"},
                "contract_overrides": {"contract_ref": "CTR-DN", "demurrage_free_days": 0},
                "container_overrides": {"container_number": "MATU0001068"},
                "gate_out_clock": "2026-09-04T12:00:00Z",
                "with_holiday": False,
            },
        )
        invoice, dispute = ctx["invoice"], ctx["dispute"]
        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        validate_success(api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "DENIED",
                "resolution_justification": "charges computed correctly per contract",
                "expected_dispute_version": current["version"],
            },
            BA,
        ))
        inv = validate_success(api_client.get_invoice(invoice["id"], BA))
        assert inv["status"] == "ISSUED"
        assert inv["balance_due_cents"] == 45000
        assert inv["credit_total_cents"] == 0
        waivers = validate_success(api_client.list_invoice_credit_waivers(invoice["id"], BA))
        assert waivers == []

    def test_resolve_with_empty_justification_rejected(self):
        """PRD §3.8: "These checks are evaluated in order: the stale-version
        rejection `ERR_STALE_VERSION` fires first when the client's observed
        version no longer matches; then `resolution_justification` must be
        non-empty, else `ERR_JUSTIFICATION_REQUIRED`".

        Design: Corner/errors/justification_required_on_resolve_and_writeoff
        """
        ctx = setup_dispute_under_review(
            dispute_reason="OTHER",
            contested_amount_cents=5000,
            invoice_kwargs={
                "account_overrides": {"account_code": "ACCT-JR", "legal_name": "JustReq Co"},
                "contract_overrides": {"contract_ref": "CTR-JR", "demurrage_free_days": 0},
                "container_overrides": {"container_number": "MATU0001209"},
                "gate_out_clock": "2026-09-04T12:00:00Z",
                "with_holiday": False,
            },
        )
        dispute = ctx["dispute"]
        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        resp = api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "FULL_CREDIT",
                "resolved_amount_cents": 5000,
                "resolution_justification": "",
                "expected_dispute_version": current["version"],
            },
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_JUSTIFICATION_REQUIRED)

    def test_stale_version_rejected_then_fresh_version_resolves(self):
        """PRD §2.8: "If the dispute's current `version` on the server has
        advanced beyond that value — for example because another writer
        returned the dispute to the queue or attached evidence, each of which
        bumps the version — the resolve request is rejected with
        `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/dispute_resolve_occ_stale_version_rejected
        """
        ctx = setup_dispute_under_review(
            dispute_reason="OTHER",
            contested_amount_cents=5000,
            invoice_kwargs={
                "account_overrides": {"account_code": "ACCT-OC", "legal_name": "OccCo"},
                "contract_overrides": {"contract_ref": "CTR-OC", "demurrage_free_days": 0},
                "container_overrides": {"container_number": "MATU0001258"},
                "gate_out_clock": "2026-09-04T12:00:00Z",
                "with_holiday": False,
            },
        )
        dispute = ctx["dispute"]
        stale = validate_success(api_client.get_dispute(dispute["id"], BA))
        # Evidence attach bumps the dispute version after the read
        validate_success(api_client.attach_evidence(
            dispute["id"],
            {
                "evidence_type": "OTHER",
                "evidence_date": "2026-09-03T00:00:00Z",
                "reference_uri": "s3://ev/bump.png",
            },
            make_billing_agent_headers("ba-2"),
        ), 201)

        stale_resp = api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "DENIED",
                "resolution_justification": "stale version attempt",
                "expected_dispute_version": stale["version"],
            },
            BA,
        )
        validate_error(stale_resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = validate_success(api_client.get_dispute(dispute["id"], BA))
        ok = validate_success(api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "DENIED",
                "resolution_justification": "correct version",
                "expected_dispute_version": fresh["version"],
            },
            BA,
        ))
        assert ok["status"] == "RESOLVED_DENIED"

    def test_resolve_withdrawn_dispute_returns_state_error(self):
        """PRD §2.10: "Fifth, the target resource must be in a state from which
        the requested transition exists, otherwise `ERR_INVALID_STATE`. ...
        Tenth and last come the fiscal guards on payments, credits, dispute
        resolutions, and write-offs — amount-within-balance, authority tier,
        segregation of duties, and the OCC version match — producing the fiscal
        error codes enumerated in §5."
        PRD §3.8: "All four end states are terminal."

        Design: Corner/validations/state_precedes_fiscal_on_resolve
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-SF", "legal_name": "StateFiscal Co"},
            contract_overrides={"contract_ref": "CTR-SF", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001118"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        dispute = file_dispute(invoice, account, 45000, dispute_reason="OTHER",
                               evidence_summary="x")
        validate_success(api_client.withdraw_dispute(
            dispute["id"], make_customer_rep_headers(account["id"])
        ))
        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        resp = api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "FULL_CREDIT",
                "resolved_amount_cents": 45000,
                "resolution_justification": "attempt on withdrawn",
                "expected_dispute_version": current["version"],
            },
            BA,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestFullCreditCascadeToUnsuspend:
    def _suspended_account_with_dispute(self):
        """Account suspended over an escalated UNDER_REVIEW dispute."""
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-G", "legal_name": "Gulf Imports"},
            contract_overrides={
                "contract_ref": "CTR-G", "demurrage_free_days": 0, "detention_free_days": 5,
                "effective_to": "2027-06-30T00:00:00Z",
            },
            container_overrides={"container_number": "MATU0000086"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=True,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        dispute = file_dispute(
            invoice, account, 45000,
            dispute_reason="APPOINTMENT_UNAVAILABLE",
            evidence_summary="no gate appointments available all three days",
        )
        attach_evidence(
            dispute, account,
            evidence_type="APPOINTMENT_API_LOG",
            evidence_date="2026-09-02T00:00:00Z",
            reference_uri="s3://evidence/appt-log-0902.json",
        )
        validate_success(api_client.start_dispute_review(dispute["id"], BA))
        # 7 consecutive DAYS_61_PLUS sweeps (invoice due 2026-10-04)
        for day in ("2026-12-05", "2026-12-06", "2026-12-07", "2026-12-08",
                    "2026-12-09", "2026-12-10", "2026-12-11"):
            set_clock(f"{day}T12:00:00Z", BA)
        ctx["dispute"] = dispute
        return ctx

    def test_full_credit_cascades_invoice_paid_and_account_unsuspends(self):
        """PRD §3.8: "If the credit brings `balance_due_cents` to zero the
        invoice moves to `PAID`; otherwise it returns to `ISSUED` when nothing
        has been paid or `PARTIALLY_PAID` when `paid_total_cents` is positive."
        PRD §2.7: "Conversely, when a sweep finds the `DAYS_61_PLUS` exposure
        has returned to zero while the account is `SUSPENDED` — meaning no
        invoice for the account remains in `DAYS_61_PLUS` with a positive
        balance — the account transitions back to `ACTIVE` and `credit_hold`
        is cleared to `false`."

        Design: Difficulty/transitive_cascade/dispute_full_credit_cascade_to_account_unsuspend
        """
        ctx = self._suspended_account_with_dispute()
        account, invoice, dispute = ctx["account"], ctx["invoice"], ctx["dispute"]

        pre = validate_success(api_client.get_customer_account(account["id"], BA))
        assert pre["status"] == "SUSPENDED"

        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        resolved = validate_success(api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "FULL_CREDIT",
                "resolved_amount_cents": 45000,
                "resolution_justification": "terminal congestion documented; full demurrage credited",
                "expected_dispute_version": current["version"],
            },
            DIR,
        ))
        assert resolved["status"] == "RESOLVED_FULL_CREDIT"

        inv = validate_success(api_client.get_invoice(invoice["id"], DIR))
        assert inv["balance_due_cents"] == 0
        assert inv["status"] == "PAID"

        set_clock("2026-12-12T12:00:00Z", DIR)
        post = validate_success(api_client.get_customer_account(account["id"], DIR))
        assert post["status"] == "ACTIVE"
        assert post["credit_hold"] is False
        assert post["outstanding_balance_cents"] == 0

    def test_full_credit_creates_applied_waiver_and_voids_demurrage_accrual(self):
        """PRD §3.8: "For the two credit outcomes, the resolution creates a
        `CreditWaiver` already in `APPLIED` status, linked to the dispute via
        `dispute_id`, for the resolved amount; the credit flows through the
        waterfall described below, recomputes the invoice's
        `credit_total_cents` and `balance_due_cents`, and reduces the account's
        `outstanding_balance_cents` by the credited amount."
        PRD §3.8: "When cumulative credits against one component reach exactly
        that component's frozen total, every non-voided `ChargeAccrual` row of
        that kind for the container is flagged `voided` true".

        Design: Difficulty/transitive_cascade/dispute_full_credit_cascade_to_account_unsuspend
        """
        ctx = self._suspended_account_with_dispute()
        account, invoice, dispute, container = (
            ctx["account"], ctx["invoice"], ctx["dispute"], ctx["container"],
        )

        pre = validate_success(api_client.get_customer_account(account["id"], BA))
        assert pre["status"] == "SUSPENDED"
        current = validate_success(api_client.get_dispute(dispute["id"], BA))
        assert current["escalated"] is True

        validate_success(api_client.resolve_dispute(
            dispute["id"],
            {
                "resolution_code": "FULL_CREDIT",
                "resolved_amount_cents": 45000,
                "resolution_justification": "terminal congestion documented",
                "expected_dispute_version": current["version"],
            },
            DIR,
        ))
        waivers = validate_success(api_client.list_dispute_credit_waivers(dispute["id"], DIR))
        assert len(waivers) == 1
        waiver = waivers[0]
        assert waiver["status"] == "APPLIED"
        assert waiver["amount_cents"] == 45000
        assert waiver["authority_tier"] == "TIER_1_AGENT"
        assert waiver["dispute_id"] == dispute["id"]

        rows = validate_success(api_client.list_container_accruals(container["id"], DIR))
        dem_rows = [r for r in rows if r["charge_kind"] == "DEMURRAGE"]
        assert dem_rows and all(r["voided"] is True for r in dem_rows)
