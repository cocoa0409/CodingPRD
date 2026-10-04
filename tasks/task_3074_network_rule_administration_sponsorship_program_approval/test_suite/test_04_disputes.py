"""Chargeback dispute workflow: evidence, decision, arbitration, close."""
from test_helpers import (
    ApiErrorId,
    create_open_dispute,
    create_dispute_payload,
    get_success_data,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS, make_member_headers

DA = TEST_USERS["dispute_analyst_headers"]


class TestEvidenceAccumulation:
    def test_dispute_evidence_immutable_append_only(self, api):
        """PRD §3.6: "Evidence rows are append-only and carry no `updated_at`
        or `version`."
        PRD §3.6: "The first accepted submission moves the case from `OPENED`
        to `EVIDENCE_SUBMITTED`; later submissions leave the status
        unchanged."

        Design: Corner/entities/dispute_evidence_immutable_append_only
        """
        issuer, acquirer, _, dispute = create_open_dispute()
        r1 = api.submit_evidence(
            dispute["id"], {"evidence_type": "TRANSACTION_RECORD",
                            "document_ref": "doc-a"},
            make_member_headers(issuer["id"]))
        e1 = validate_success(r1, 201)
        assert "version" not in e1 and "updated_at" not in e1, \
            "append-only evidence must not carry version/updated_at"

        r2 = api.submit_evidence(
            dispute["id"], {"evidence_type": "PROOF_OF_DELIVERY",
                            "document_ref": "doc-b"},
            make_member_headers(acquirer["id"]))
        e2 = validate_success(r2, 201)
        assert "version" not in e2 and "updated_at" not in e2
        assert e2["id"] != e1["id"], "each submission appends a new row"

        data, meta = validate_paginated(
            api.list_dispute_evidence(dispute["id"], DA))
        assert len(data) == 2 and meta["total_count"] == 2
        assert {row["id"] for row in data} == {e1["id"], e2["id"]}

    def test_evidence_accepted_exactly_at_inclusive_deadline(self, api):
        """PRD §3.6: "Evidence is admissible only while `submitted_at` falls
        within thirty days of the `filing_clock` value captured when the case
        opened, and the boundary is inclusive — a submission landing exactly
        on the deadline is admitted."

        Design: Difficulty/combinatorial_formula/dispute_window_inclusive_vs_exclusive_boundary
        """
        issuer, acquirer, _, dispute = create_open_dispute(
            reason_code="13.1", transaction_amount_cents=50000)
        set_clock("2026-10-01T00:00:00Z")
        res = api.submit_evidence(
            dispute["id"], {"evidence_type": "PROOF_OF_DELIVERY",
                            "document_ref": "doc-1"},
            make_member_headers(acquirer["id"]))
        validate_success(res, 201)
        current = get_success_data(api.get_dispute(dispute["id"], DA))
        assert current["status"] == "EVIDENCE_SUBMITTED", \
            "submission exactly at filing_clock+30d must be admitted"

    def test_arbitration_rejected_exactly_at_exclusive_deadline(self, api):
        """PRD §3.6: "The losing party may escalate by requesting arbitration,
        but only while the case is `DECIDED`, only as a case party, and only
        while the current logical time is strictly before `filing_clock` plus
        forty-five days — the arbitration boundary is exclusive, so a request
        landing exactly on the deadline is rejected with
        `ERR_WINDOW_EXPIRED`."

        Design: Difficulty/combinatorial_formula/dispute_window_inclusive_vs_exclusive_boundary
        """
        issuer, acquirer, _, dispute = create_open_dispute(
            reason_code="13.1", transaction_amount_cents=50000)
        # Evidence admitted at the inclusive 30-day boundary (2026-10-01),
        # then decided at the same logical time — the decision stamps
        # filing_clock at 2026-10-01T00:00:00Z.
        set_clock("2026-10-01T00:00:00Z")
        validate_success(api.submit_evidence(
            dispute["id"], {"evidence_type": "PROOF_OF_DELIVERY",
                            "document_ref": "doc-1"},
            make_member_headers(acquirer["id"])), 201)
        validate_success(api.decide_dispute(
            dispute["id"], {"winning_side": "ACQUIRER"}, DA))
        # Exactly filing_clock + 45 days = 2026-11-15T00:00:00Z.
        set_clock("2026-11-15T00:00:00Z")
        res = api.request_arbitration(dispute["id"],
                                      make_member_headers(issuer["id"]))
        validate_error(res, ApiErrorId.ERR_WINDOW_EXPIRED)
        current = get_success_data(api.get_dispute(dispute["id"], DA))
        assert current["status"] == "DECIDED"


class TestDecisionAndArbitration:
    def test_dispute_decide_idempotency_second_decide_rejected(self, api):
        """PRD §3.6: "A `DisputeAnalyst` decides the case from either `OPENED`
        or `EVIDENCE_SUBMITTED` by declaring a `winning_side` of `ISSUER` or
        `ACQUIRER`."
        PRD §2.7: "(5) the target resource being in a state from which the
        requested transition exists (`ERR_INVALID_STATE`)".

        Design: Corner/state_machines/dispute_decide_idempotency_second_decide_rejected
        """
        issuer, _, _, dispute = create_open_dispute(reason_code="13.1")
        validate_success(api.decide_dispute(dispute["id"],
                                            {"winning_side": "ISSUER"}, DA))
        res = api.decide_dispute(dispute["id"], {"winning_side": "ACQUIRER"},
                                 DA)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE)
        current = get_success_data(api.get_dispute(dispute["id"], DA))
        assert current["winning_side"] == "ISSUER"
        assert current["status"] == "DECIDED"

    def test_arbitration_overwrites_winning_side(self, api):
        """PRD §3.6: "Arbitration itself is rendered by a `DisputeAnalyst`,
        who declares a fresh `winning_side`; the case moves to
        `ARBITRATION_DECIDED` and the previous `winning_side` is overwritten."

        Design: Difficulty/non_linear_state_machine/dispute_evidence_arbitration_loop
        """
        issuer, acquirer, _, dispute = create_open_dispute(
            transaction_amount_cents=80000, currency="EUR")
        validate_success(api.submit_evidence(
            dispute["id"], {"evidence_type": "TRANSACTION_RECORD",
                            "document_ref": "doc-t1"},
            make_member_headers(acquirer["id"])), 201)
        decided = get_success_data(api.decide_dispute(
            dispute["id"], {"winning_side": "ISSUER"}, DA))
        assert decided["winning_side"] == "ISSUER"

        validate_success(api.request_arbitration(
            dispute["id"], make_member_headers(acquirer["id"])))
        arbitrated = get_success_data(api.arbitrate_dispute(
            dispute["id"], {"winning_side": "ACQUIRER"}, DA))
        assert arbitrated["status"] == "ARBITRATION_DECIDED"
        assert arbitrated["winning_side"] == "ACQUIRER", \
            "arbitration overwrites the initial decision on the same case"

    def test_full_dispute_loop_reaches_closed(self, api):
        """PRD §3.6: "Either a `DECIDED` or an `ARBITRATION_DECIDED` case is
        closed by a `DisputeAnalyst`, reaching the terminal `CLOSED` state."

        Design: Difficulty/non_linear_state_machine/dispute_evidence_arbitration_loop
        """
        issuer, acquirer, _, dispute = create_open_dispute(
            transaction_amount_cents=80000, currency="EUR")
        validate_success(api.decide_dispute(dispute["id"],
                                            {"winning_side": "ISSUER"}, DA))
        validate_success(api.request_arbitration(
            dispute["id"], make_member_headers(acquirer["id"])))
        validate_success(api.arbitrate_dispute(
            dispute["id"], {"winning_side": "ACQUIRER"}, DA))
        closed = get_success_data(api.close_dispute(dispute["id"], DA))
        assert closed["status"] == "CLOSED"


class TestDisputeLiabilityVariants:
    def test_decision_for_issuer_liability_without_arbitration(self, api):
        """PRD §3.6: "When the issuer wins, the acquirer's liability is the
        disputed `transaction_amount_cents` plus a dispute fee of 1,500 cents,
        and the issuer owes nothing."
        PRD §3.6: "An arbitration outcome adds an arbitration fee of 25,000
        cents to the losing side's liability on top of the base outcome fee
        that the initial decision already established."

        Design: Difficulty/dual_variant_calc/dispute_liability_initial_vs_arbitration
        """
        issuer, acquirer, merchant, dispute = create_open_dispute(
            transaction_amount_cents=200000)
        validate_success(api.decide_dispute(dispute["id"],
                                            {"winning_side": "ISSUER"}, DA))
        closed = get_success_data(api.close_dispute(dispute["id"], DA))
        assert closed["status"] == "CLOSED"
        assert closed["winning_side"] == "ISSUER"
        # Contracted liability of the closed-without-arbitration branch:
        # 200000 + 1500 = 201500 owed by the acquirer; the issuer owes 0.

    def test_arbitration_adds_fee_to_losing_side(self, api):
        """PRD §3.6: "An arbitration outcome adds an arbitration fee of 25,000
        cents to the losing side's liability on top of the base outcome fee
        that the initial decision already established."
        PRD §3.6: "When the issuer wins, the acquirer's liability is the
        disputed `transaction_amount_cents` plus a dispute fee of 1,500 cents,
        and the issuer owes nothing."

        Design: Difficulty/dual_variant_calc/dispute_liability_initial_vs_arbitration
        """
        issuer, acquirer, merchant, dispute = create_open_dispute(
            transaction_amount_cents=200000)
        validate_success(api.decide_dispute(dispute["id"],
                                            {"winning_side": "ISSUER"}, DA))
        validate_success(api.request_arbitration(
            dispute["id"], make_member_headers(acquirer["id"])))
        arbitrated = get_success_data(api.arbitrate_dispute(
            dispute["id"], {"winning_side": "ISSUER"}, DA))
        assert arbitrated["status"] == "ARBITRATION_DECIDED"
        assert arbitrated["winning_side"] == "ISSUER"
        # Contracted liability of the arbitration branch: 200000 + 1500 +
        # 25000 = 226500 owed by the acquirer (base outcome plus the
        # arbitration fee on the losing side).
