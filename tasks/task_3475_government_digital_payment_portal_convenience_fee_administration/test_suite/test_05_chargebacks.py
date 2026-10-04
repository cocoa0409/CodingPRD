"""Chargeback cases: branching fork (WON vs ACCEPTED), evidence deadline,
force-decided LOST, one-live-case intake rule."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    accept_chargeback,
    api_client,
    assert_chargeback_case,
    contest_chargeback,
    contest_chargeback_payload,
    create_chargeback_payload,
    get_transaction,
    list_batches,
    make_agency_admin_headers,
    open_chargeback,
    record_chargeback_outcome,
    record_outcome_payload,
    set_clock,
    setup_captured_card,
    setup_captured_card_pair,
    validate_error,
    validate_paginated,
)

PA = TEST_USERS["platform_admin_headers"]
AA_LEAD = make_agency_admin_headers("aa-lead")


class TestChargebackFork:
    def test_contested_then_won_moves_no_money(self, api):
        """PRD §3.7: "A `CONTESTED` case recorded as `WON` closes with no
        financial movement — the provisional case ends at zero debit."

        Design: Difficulty/non_linear_state_machine/chargeback_branching_contest_won_vs_accept
        """
        ctx = setup_captured_card()
        case = open_chargeback(ctx["transaction"]["id"], "FRAUD")
        contested = contest_chargeback(case["id"], "Signed receipt and delivery log attached")
        assert contested["status"] == "CONTESTED"
        won = record_chargeback_outcome(case["id"], "WON")
        assert_chargeback_case(won)
        assert won["status"] == "WON"
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["charged_back_cents"] == 0
        assert txn["remaining_refundable_cents"] == 100000
        assert list_batches(ctx["agency"]["id"]) == [], "the WON branch posts no batch debit"

    def test_accepted_books_network_debit_into_auto_batch(self, api):
        """PRD §3.7: "Accepting liability moves the case from `OPENED` to
        `ACCEPTED` and books the debit immediately: `network_debit_cents` is
        the transaction's `amount_cents` minus its `refunded_cents` at that
        moment — the convenience fee is never clawed back — the transaction's
        `charged_back_cents` is set to the network debit with
        `remaining_refundable_cents` recomputed, and a chargeback debit of
        `network_debit_cents` posts into the agency's `OPEN` batch through
        `chargeback_debits_cents`, auto-creating an `OPEN` batch stamped with
        the current clock date when none exists."

        Design: Difficulty/non_linear_state_machine/chargeback_branching_contest_won_vs_accept
        """
        ctx = setup_captured_card()
        case = open_chargeback(ctx["transaction"]["id"], "SERVICE_NOT_RECEIVED")
        accepted = accept_chargeback(case["id"])
        assert_chargeback_case(accepted)
        assert accepted["status"] == "ACCEPTED"
        assert accepted["network_debit_cents"] == 100000, "amount minus zero refunds; the fee is never clawed back"
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["charged_back_cents"] == 100000
        assert txn["remaining_refundable_cents"] == 0
        batches = list_batches(ctx["agency"]["id"])
        assert len(batches) == 1, "exactly one auto-created OPEN batch"
        assert batches[0]["status"] == "OPEN"
        assert batches[0]["chargeback_debits_cents"] == 100000
        assert batches[0]["business_date"] == "2026-09-01", "stamped with the current clock date"


class TestOutcomeGates:
    def test_outcome_on_opened_before_deadline_rejected(self, api):
        """PRD §3.7: "An `OPENED` case cannot be outcome-recorded before its
        evidence deadline — such an attempt is `ERR_INVALID_STATE`".

        Design: Corner/state_machines/chargeback_outcome_on_opened_before_deadline_rejected
        """
        ctx = setup_captured_card()  # case opens at 2026-09-01, evidence due 2026-09-11
        case = open_chargeback(ctx["transaction"]["id"], "FRAUD")
        resp = api_client.record_chargeback_outcome(case["id"], record_outcome_payload("LOST"), PA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["charged_back_cents"] == 0
        cases = api_client.list_transaction_chargebacks(txn["id"], PA)
        data, _ = validate_paginated(cases)
        assert data[0]["status"] == "OPENED"

    def test_past_deadline_record_outcome_forces_lost(self, api):
        """PRD §3.7: "once the logical clock has passed `evidence_due_at`, an
        `OPENED` case is force-decided `LOST` with the same financial effects."

        Design: Corner/state_machines/chargeback_past_deadline_record_outcome_forces_lost
        """
        ctx = setup_captured_card()  # case opens 2026-09-01, evidence due 2026-09-11
        case = open_chargeback(ctx["transaction"]["id"], "FRAUD")
        set_clock("2026-09-12T00:00:00Z")
        lost = record_chargeback_outcome(case["id"], "LOST")
        assert lost["status"] == "LOST"
        assert lost["network_debit_cents"] == 100000
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["charged_back_cents"] == 100000
        assert txn["remaining_refundable_cents"] == 0
        batches = list_batches(ctx["agency"]["id"])
        assert len(batches) == 1
        assert batches[0]["business_date"] == "2026-09-12"
        assert batches[0]["chargeback_debits_cents"] == 100000

    def test_contested_lost_books_debit(self, api):
        """PRD §3.7: "A `CONTESTED` case recorded as `LOST` books exactly the
        financial effects of acceptance, computed at that moment: the network
        debit, the transaction's `charged_back_cents`, and the open-batch
        debit with auto-create."

        Design: Corner/state_machines/chargeback_contested_lost_books_debit
        """
        ctx = setup_captured_card()
        case = open_chargeback(ctx["transaction"]["id"], "FRAUD")
        contest_chargeback(case["id"], "compelling evidence packet")
        lost = record_chargeback_outcome(case["id"], "LOST")
        assert lost["status"] == "LOST"
        assert lost["network_debit_cents"] == 100000
        txn = get_transaction(ctx["transaction"]["id"])
        assert txn["charged_back_cents"] == 100000
        assert txn["remaining_refundable_cents"] == 0
        batches = list_batches(ctx["agency"]["id"])
        assert len(batches) == 1
        assert batches[0]["chargeback_debits_cents"] == 100000


class TestChargebackIntakeRules:
    def test_second_chargeback_on_same_transaction_rejected(self, api):
        """PRD §3.7: "a transaction may carry at most one live case: an
        existing `OPENED` or `CONTESTED` case blocks a new intake with
        `ERR_CHARGEBACK_ALREADY_OPEN`."

        Design: Corner/errors/err_chargeback_already_open
        """
        ctx = setup_captured_card()
        open_chargeback(ctx["transaction"]["id"], "FRAUD")
        resp = api_client.create_chargeback(
            create_chargeback_payload(ctx["transaction"]["id"], "DUPLICATE"), PA
        )
        validate_error(resp, ApiErrorId.ERR_CHARGEBACK_ALREADY_OPEN)
        data, _ = validate_paginated(
            api_client.list_transaction_chargebacks(ctx["transaction"]["id"], PA)
        )
        assert len(data) == 1

    def test_evidence_deadline_boundary(self, api):
        """PRD §3.7: "the contest is accepted only while the logical clock is
        on or before `evidence_due_at`, and a later attempt is rejected with
        `ERR_EVIDENCE_DEADLINE_PASSED`."

        Design: Corner/errors/err_evidence_deadline_passed_on_contest
        """
        ctx = setup_captured_card_pair(amount_a=100000, amount_b=20000)  # opened 2026-09-01, due 2026-09-11
        case_a = open_chargeback(ctx["transaction_a"]["id"], "FRAUD")
        case_b = open_chargeback(ctx["transaction_b"]["id"], "DUPLICATE")
        set_clock("2026-09-11T00:00:00Z")  # exactly evidence_due_at: inclusive boundary
        contested = contest_chargeback(case_a["id"], "at the deadline exactly")
        assert contested["status"] == "CONTESTED"
        set_clock("2026-09-11T00:00:01Z")  # one second past
        resp = api_client.contest_chargeback(
            case_b["id"], contest_chargeback_payload("one second late"), AA_LEAD
        )
        validate_error(resp, ApiErrorId.ERR_EVIDENCE_DEADLINE_PASSED)
        data, _ = validate_paginated(
            api_client.list_transaction_chargebacks(ctx["transaction_b"]["id"], PA)
        )
        assert data[0]["status"] == "OPENED"
