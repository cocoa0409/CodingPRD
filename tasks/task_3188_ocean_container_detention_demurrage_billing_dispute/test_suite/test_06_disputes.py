"""Dispute lifecycle: review loop, evidence rules, SLA escalation, OCC, errors."""
from test_helpers import (
    ApiErrorId,
    api_client,
    create_account,
    create_active_contract,
    create_terminal,
    create_return_location,
    create_available_container,
    attach_evidence,
    create_dispute_payload,
    create_evidence_payload,
    file_dispute,
    gate_out,
    make_customer_rep_headers,
    return_empty,
    set_clock,
    setup_dispute_under_review,
    setup_issued_invoice,
    validate_error,
    validate_success,
)

CM = {"X-User-ID": "cm-1", "X-User-Role": "ContractManager"}
TO = {"X-User-ID": "to-1", "X-User-Role": "TerminalOperator"}
EC = {"X-User-ID": "ec-1", "X-User-Role": "EquipmentController"}
BA = {"X-User-ID": "ba-1", "X-User-Role": "BillingAgent"}
DIR = {"X-User-ID": "dir-1", "X-User-Role": "CreditDirector"}


class TestDisputeReviewLoop:
    def test_review_loop_cycles_and_bumps_version(self):
        """PRD §3.7: "A `BillingAgent` picks a dispute out of the queue by
        starting review, moving it from `SUBMITTED` to `UNDER_REVIEW`".
        PRD §3.7: "Review is a cycle, not a one-way door: the agent may return
        the dispute to the queue, moving it back from `UNDER_REVIEW` to
        `SUBMITTED` and clearing the reviewing-user stamp."
        PRD §2.5: "**`version`** (integer): a system-managed integer that
        increments with every modification, serving as the basis for
        optimistic concurrency control where declared."

        Design: Difficulty/non_linear_state_machine/dispute_revision_loop_submit_review_queue_resubmit
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-E", "legal_name": "Epsilon Cargo"},
            contract_overrides={"contract_ref": "CTR-E", "demurrage_free_days": 0, "detention_free_days": 5},
            container_overrides={"container_number": "MATU0000060"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        dispute = file_dispute(
            ctx["invoice"], ctx["account"], 45000,
            dispute_reason="FREE_TIME_MISCALC",
            evidence_summary="free time miscomputed per contract",
        )
        v0 = dispute["version"]

        d1 = validate_success(api_client.start_dispute_review(dispute["id"], BA))
        assert d1["status"] == "UNDER_REVIEW"
        d2 = validate_success(api_client.return_dispute_to_queue(dispute["id"], BA))
        assert d2["status"] == "SUBMITTED"
        d3 = validate_success(api_client.start_dispute_review(dispute["id"], BA))
        assert d3["status"] == "UNDER_REVIEW"
        assert d3["version"] == v0 + 3

    def test_invoice_stays_disputed_throughout_the_loop(self):
        """PRD §3.7: "Filing stamps `submitted_at` from the logical clock, sets
        `sla_due_at` fourteen calendar days after submission, moves the invoice
        to `DISPUTED`, and starts the dispute in `SUBMITTED` status."

        Design: Difficulty/non_linear_state_machine/dispute_revision_loop_submit_review_queue_resubmit
        """
        ctx = setup_issued_invoice(
            contract_overrides={"demurrage_free_days": 0, "detention_free_days": 5},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        dispute = file_dispute(ctx["invoice"], ctx["account"], 1000, dispute_reason="OTHER")
        api_client.start_dispute_review(dispute["id"], BA)
        api_client.return_dispute_to_queue(dispute["id"], BA)
        api_client.start_dispute_review(dispute["id"], BA)
        invoice = validate_success(api_client.get_invoice(ctx["invoice"]["id"], BA))
        assert invoice["status"] == "DISPUTED"


class TestDisputeStateGuards:
    def test_withdraw_from_under_review_rejected(self):
        """PRD §3.8: "Separately, the customer may withdraw a dispute still in
        `SUBMITTED` — only their own, enforced through the account match with
        `ERR_FORBIDDEN` — moving it to `WITHDRAWN` and reverting the invoice
        the same way."

        Design: Corner/state_machines/dispute_withdraw_from_under_review_rejected
        """
        ctx = setup_dispute_under_review(
            dispute_reason="OTHER",
            contested_amount_cents=1000,
            invoice_kwargs={
                "account_overrides": {"account_code": "ACCT-WD", "legal_name": "Withdraw Co"},
                "contract_overrides": {"contract_ref": "CTR-WD", "demurrage_free_days": 0},
                "container_overrides": {"container_number": "MATU0001043"},
                "gate_out_clock": "2026-09-04T12:00:00Z",
                "with_holiday": False,
            },
        )
        dispute = ctx["dispute"]
        resp = api_client.withdraw_dispute(
            dispute["id"], make_customer_rep_headers(ctx["account"]["id"])
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = validate_success(api_client.get_dispute(dispute["id"], BA))
        assert after["status"] == "UNDER_REVIEW"

    def test_second_filing_rejected_until_withdrawal(self):
        """PRD §3.7: "Only one dispute may be open per invoice at a time;
        filing while another dispute on the same invoice is `SUBMITTED` or
        `UNDER_REVIEW` is rejected with `ERR_DISPUTE_ALREADY_OPEN`."

        Design: Corner/errors/dispute_already_open_second_filing_rejected
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-DAO", "legal_name": "DupDisp Co"},
            contract_overrides={"contract_ref": "CTR-DAO", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001183"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        rep = make_customer_rep_headers(account["id"])
        first = file_dispute(invoice, account, 5000, dispute_reason="OTHER",
                             evidence_summary="first")
        dup = api_client.create_dispute(
            invoice["id"],
            create_dispute_payload(5000, dispute_reason="RATE_MISMATCH",
                                   evidence_summary="second while open"),
            rep,
        )
        validate_error(dup, ApiErrorId.ERR_DISPUTE_ALREADY_OPEN)

        validate_success(api_client.withdraw_dispute(first["id"], rep))
        second = validate_success(api_client.create_dispute(
            invoice["id"],
            create_dispute_payload(5000, dispute_reason="RATE_MISMATCH",
                                   evidence_summary="after withdrawal"),
            rep,
        ), 201)
        assert second["id"]


class TestEvidenceRules:
    def test_evidence_required_only_for_evidence_driven_reasons(self):
        """PRD §3.7: "For the three evidence-driven reasons —
        `APPOINTMENT_UNAVAILABLE`, `CHASSIS_SHORTAGE`, and `CUSTOMS_HOLD` — at
        least one evidence item must already be attached, otherwise
        start-review is rejected with `ERR_EVIDENCE_REQUIRED`; the remaining
        reasons may enter review bare."

        Design: Corner/validations/conditional_validation_evidence_required_only_for_evidence_based_reasons
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-CV", "legal_name": "CondVal Co"},
            contract_overrides={"contract_ref": "CTR-CV", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001126"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        account, terminal, contract = ctx["account"], ctx["terminal"], ctx["contract"]
        # Second container -> second invoice on the same account
        c2 = create_available_container(
            account, contract, terminal,
            container_number="MATU0001134",
            discharge_ts="2026-08-31T12:00:00Z",
            available_ts="2026-09-01T12:00:00Z",
        )
        gate_out(c2["id"])
        return_empty(c2["id"])
        inv2 = validate_success(api_client.issue_invoice(c2["id"], BA), 201)

        dsp1 = file_dispute(ctx["invoice"], account, 10000,
                            dispute_reason="APPOINTMENT_UNAVAILABLE",
                            evidence_summary="no appts")
        dsp2 = file_dispute(inv2, account, 10000,
                            dispute_reason="OTHER", evidence_summary="misc")

        e1 = api_client.start_dispute_review(dsp1["id"], BA)
        validate_error(e1, ApiErrorId.ERR_EVIDENCE_REQUIRED)
        ok = validate_success(api_client.start_dispute_review(dsp2["id"], BA))
        assert ok["status"] == "UNDER_REVIEW"

    def test_evidence_at_window_boundary_accepted(self):
        """PRD §3.7: "The `evidence_date` must fall within the dispute's
        evidence window, else `ERR_NOT_A_WORKING_DAY`."

        Design: Difficulty/priority_pair_validation_conflict/evidence_outside_window_vs_dispute_state_temporal_vs_state
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-J2", "legal_name": "Jade Imports II"},
            contract_overrides={"contract_ref": "CTR-J2", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0000220"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        rep = make_customer_rep_headers(account["id"])
        dsp = file_dispute(invoice, account, 45000,
                           dispute_reason="APPOINTMENT_UNAVAILABLE",
                           evidence_summary="gate congestion")
        # Window is 2026-09-02..2026-09-04 inclusive; the end date is inside it
        in_window = api_client.attach_evidence(
            dsp["id"],
            create_evidence_payload(
                evidence_type="APPOINTMENT_SCREENSHOT",
                evidence_date="2026-09-04T00:00:00Z",
                reference_uri="s3://evidence/in-window.png",
            ),
            rep,
        )
        validate_success(in_window, 201)

    def test_terminal_dispute_rejects_evidence_and_live_dispute_rejects_out_of_window(self):
        """PRD §2.10: "Fifth, the target resource must be in a state from which
        the requested transition exists, otherwise `ERR_INVALID_STATE`. ...
        Seventh come terminal working-day and evidence-window checks
        (`ERR_NOT_A_WORKING_DAY`)."
        PRD §3.7: "The `evidence_date` must fall within the dispute's evidence
        window, else `ERR_NOT_A_WORKING_DAY`."

        Design: Difficulty/priority_pair_validation_conflict/evidence_outside_window_vs_dispute_state_temporal_vs_state
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-J", "legal_name": "Jade Imports"},
            contract_overrides={"contract_ref": "CTR-J", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0000110"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        rep = make_customer_rep_headers(account["id"])
        dsp1 = file_dispute(invoice, account, 45000,
                            dispute_reason="FREE_TIME_MISCALC",
                            evidence_summary="miscomputation")
        validate_success(api_client.withdraw_dispute(dsp1["id"], rep))
        dsp2 = file_dispute(invoice, account, 45000,
                            dispute_reason="APPOINTMENT_UNAVAILABLE",
                            evidence_summary="second dispute after withdrawal")

        out_of_window = create_evidence_payload(
            evidence_type="APPOINTMENT_SCREENSHOT",
            evidence_date="2026-09-10T00:00:00Z",
            reference_uri="s3://evidence/late.png",
        )
        terminal_resp = api_client.attach_evidence(dsp1["id"], out_of_window, rep)
        validate_error(terminal_resp, ApiErrorId.ERR_INVALID_STATE)

        live_resp = api_client.attach_evidence(
            dsp2["id"],
            create_evidence_payload(
                evidence_type="APPOINTMENT_SCREENSHOT",
                evidence_date="2026-09-10T00:00:00Z",
                reference_uri="s3://evidence/late2.png",
            ),
            rep,
        )
        validate_error(live_resp, ApiErrorId.ERR_NOT_A_WORKING_DAY)

    def test_superseded_evidence_remains_queryable(self):
        """PRD §3.7: "An item may carry `supersedes_evidence_id` pointing at an
        earlier artifact it corrects; the superseded item remains queryable —
        the evidence list supports filtering by `dispute_id` and
        `supersedes_evidence_id`, enabling chain traversal — but is excluded
        from verification totals."

        Design: Corner/entities/dispute_evidence_self_reference_supersession
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-SE", "legal_name": "Supersede Co"},
            contract_overrides={"contract_ref": "CTR-SE", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001019"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        invoice, account = ctx["invoice"], ctx["account"]
        dsp = file_dispute(invoice, account, 45000,
                           dispute_reason="APPOINTMENT_UNAVAILABLE",
                           evidence_summary="gate full")
        ev1 = attach_evidence(
            dsp, account,
            evidence_type="APPOINTMENT_SCREENSHOT",
            evidence_date="2026-09-02T00:00:00Z",
            reference_uri="s3://ev/v1.png",
        )
        ev2 = attach_evidence(
            dsp, account,
            evidence_type="APPOINTMENT_SCREENSHOT",
            evidence_date="2026-09-02T00:00:00Z",
            reference_uri="s3://ev/v2.png",
            supersedes_evidence_id=ev1["id"],
        )
        assert ev2["id"] != ev1["id"]
        assert ev2["supersedes_evidence_id"] == ev1["id"]
        rows = validate_success(api_client.list_dispute_evidence(
            dsp["id"], make_customer_rep_headers(account["id"])
        ))
        ids = [r["id"] for r in rows]
        assert ev1["id"] in ids and ev2["id"] in ids
        assert len(rows) == 2


class TestDisputeSlaEscalation:
    def test_escalation_flips_only_after_sla_due(self):
        """PRD §3.7: "Filing stamps `submitted_at` from the logical clock, sets
        `sla_due_at` fourteen calendar days after submission, moves the invoice
        to `DISPUTED`, and starts the dispute in `SUBMITTED` status."
        PRD §3.7: "When the logical clock advances past a dispute's
        `sla_due_at` while the dispute is still `SUBMITTED` or `UNDER_REVIEW`,
        the system sets its `escalated` flag true".

        Design: Corner/cross_cutting_layers/dispute_escalation_on_sla_breach
        """
        ctx = setup_issued_invoice(
            account_overrides={"account_code": "ACCT-ES", "legal_name": "Escal Co"},
            contract_overrides={"contract_ref": "CTR-ES", "demurrage_free_days": 0},
            container_overrides={"container_number": "MATU0001274"},
            gate_out_clock="2026-09-04T12:00:00Z",
            with_holiday=False,
        )
        dispute = file_dispute(ctx["invoice"], ctx["account"], 5000, dispute_reason="OTHER")

        set_clock("2026-09-18T00:00:00Z", BA)
        at = validate_success(api_client.get_dispute(dispute["id"], BA))
        assert at["escalated"] is False

        set_clock("2026-09-18T12:00:01Z", BA)
        after = validate_success(api_client.get_dispute(dispute["id"], BA))
        assert after["escalated"] is True
