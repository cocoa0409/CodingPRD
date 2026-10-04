"""Non-linear state machines: the letter bounce/requeue cycle and the
credit-deletion reject/resubmit cycle, each ending at its terminal ceiling."""
from test_helpers import (
    get_success_data,
    make_compliance_auditor_headers,
    make_donor_relations_headers,
    setup_finalized_batch,
    validate_success,
)


class TestLetterBounceCycle:
    def test_bounce_requeue_cycle_to_undeliverable(self, api):
        """PRD §3.7: "Marking a bounce increments `attempt_count` and consults
        the attempt ceiling, which is three attempts: if the incremented count
        is still below three, the letter falls back to `BOUNCED`, but if the
        incremented count reaches three the letter becomes terminally
        `UNDELIVERABLE` instead."
        PRD §3.7: "A `BOUNCED` letter may be requeued by the officer, optionally
        supplying a `corrected_address`; when one is provided, the letter's
        `mailing_address` is replaced with it."

        Design: Difficulty/non_linear_state_machine/notification_letter_bounce_requeue_cycle_to_undeliverable
        """
        ctx = setup_finalized_batch()
        dro = make_donor_relations_headers()
        a1 = ctx["accounts"][0]
        letter = next(
            l for l in ctx["letters"] if l["account_id"] == a1["id"]
        )
        letter_id = letter["id"]
        # Cycle 1: send -> bounce -> requeue with a corrected address.
        get_success_data(api.send_notification_letter(letter_id, dro))
        data = validate_success(
            api.mark_notification_letter_bounced(letter_id, dro), 200
        )
        assert data["status"] == "BOUNCED"
        assert data["attempt_count"] == 1
        data = validate_success(
            api.requeue_notification_letter(
                letter_id, dro, corrected_address="5 Fixed Ln"
            ),
            200,
        )
        assert data["status"] == "QUEUED"
        assert data["mailing_address"] == "5 Fixed Ln"
        # Cycle 2.
        get_success_data(api.send_notification_letter(letter_id, dro))
        data = validate_success(
            api.mark_notification_letter_bounced(letter_id, dro), 200
        )
        assert data["status"] == "BOUNCED"
        assert data["attempt_count"] == 2
        data = validate_success(api.requeue_notification_letter(letter_id, dro), 200)
        assert data["status"] == "QUEUED"
        # Cycle 3: the third bounce reaches the ceiling and terminates.
        get_success_data(api.send_notification_letter(letter_id, dro))
        data = validate_success(
            api.mark_notification_letter_bounced(letter_id, dro), 200
        )
        assert data["status"] == "UNDELIVERABLE"
        assert data["attempt_count"] == 3

    def test_requeue_after_second_bounce_restores_queue(self, api):
        """PRD §3.7: "A `BOUNCED` letter may be requeued by the officer,
        optionally supplying a `corrected_address`; when one is provided, the
        letter's `mailing_address` is replaced with it. Requeueing returns the
        letter to `QUEUED` for another send, but only while `attempt_count`
        remains below the three-attempt ceiling"

        Design: Difficulty/non_linear_state_machine/notification_letter_bounce_requeue_cycle_to_undeliverable
        """
        ctx = setup_finalized_batch()
        dro = make_donor_relations_headers()
        a2 = ctx["accounts"][1]
        letter = next(
            l for l in ctx["letters"] if l["account_id"] == a2["id"]
        )
        letter_id = letter["id"]
        assert letter["attempt_count"] == 0
        for expected_count in (1, 2):
            get_success_data(api.send_notification_letter(letter_id, dro))
            data = validate_success(
                api.mark_notification_letter_bounced(letter_id, dro), 200
            )
            assert data["status"] == "BOUNCED"
            assert data["attempt_count"] == expected_count
            data = validate_success(
                api.requeue_notification_letter(letter_id, dro), 200
            )
            assert data["status"] == "QUEUED"
            assert data["attempt_count"] == expected_count


class TestCreditDeletionRejectCycle:
    def test_reject_resubmit_cycle_to_failed(self, api):
        """PRD §3.8: "Rejection records the supplied `rejection_reason` and
        depends on how many times the request has already been resubmitted, with
        the ceiling set at two resubmissions: while `resubmission_count` is
        below two, the request falls back to `REJECTED` and the account's
        `bureau_status` returns from `DELETION_REQUESTED` to `REPORTED`, opening
        another cycle; when the count already equals two, rejection instead
        moves the request to terminal `FAILED` and the account's `bureau_status`
        to terminal `DELETION_FAILED`."
        PRD §3.8: "A `REJECTED` request may be resubmitted by the auditor while
        `resubmission_count` is below two — at the ceiling, resubmission is
        rejected with `ERR_RESUBMISSION_LIMIT` — which increments the count,
        returns the request to `SUBMITTED`, and flips the account's
        `bureau_status` from `REPORTED` back to `DELETION_REQUESTED`."

        Design: Difficulty/non_linear_state_machine/credit_deletion_reject_resubmit_cycle_to_failed
        """
        ctx = setup_finalized_batch()
        auditor = make_compliance_auditor_headers()
        a1 = ctx["accounts"][0]
        cdr = ctx["cdrs"][0]
        assert cdr["account_id"] == a1["id"]
        assert cdr["status"] == "SUBMITTED"
        assert cdr["resubmission_count"] == 0
        cdr_id = cdr["id"]
        # reject 1 -> REJECTED (account back to REPORTED)
        data = validate_success(
            api.reject_credit_deletion_request(cdr_id, "tradeline mismatch", auditor),
            200,
        )
        assert data["status"] == "REJECTED"
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["bureau_status"] == "REPORTED"
        # resubmit 1 -> SUBMITTED, count 1
        data = validate_success(
            api.resubmit_credit_deletion_request(cdr_id, auditor), 200
        )
        assert data["status"] == "SUBMITTED"
        assert data["resubmission_count"] == 1
        # reject 2 -> REJECTED
        data = validate_success(
            api.reject_credit_deletion_request(cdr_id, "still mismatch", auditor), 200
        )
        assert data["status"] == "REJECTED"
        # resubmit 2 -> SUBMITTED, count 2 (at the ceiling)
        data = validate_success(
            api.resubmit_credit_deletion_request(cdr_id, auditor), 200
        )
        assert data["status"] == "SUBMITTED"
        assert data["resubmission_count"] == 2
        # reject 3 at the ceiling -> FAILED (terminal), account DELETION_FAILED
        data = validate_success(
            api.reject_credit_deletion_request(cdr_id, "final refusal", auditor), 200
        )
        assert data["status"] == "FAILED"
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["bureau_status"] == "DELETION_FAILED"

    def test_rejection_returns_account_to_reported_mid_cycle(self, api):
        """PRD §3.8: "while `resubmission_count` is below two, the request falls
        back to `REJECTED` and the account's `bureau_status` returns from
        `DELETION_REQUESTED` to `REPORTED`, opening another cycle"

        Design: Difficulty/non_linear_state_machine/credit_deletion_reject_resubmit_cycle_to_failed
        """
        ctx = setup_finalized_batch()
        auditor = make_compliance_auditor_headers()
        a1 = ctx["accounts"][0]
        cdr = ctx["cdrs"][0]
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["bureau_status"] == "DELETION_REQUESTED"
        data = validate_success(
            api.reject_credit_deletion_request(
                cdr["id"], "tradeline mismatch", auditor
            ),
            200,
        )
        assert data["status"] == "REJECTED"
        assert data["rejection_reason"] == "tradeline mismatch"
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["bureau_status"] == "REPORTED"
        data = validate_success(
            api.resubmit_credit_deletion_request(cdr["id"], auditor), 200
        )
        assert data["status"] == "SUBMITTED"
        account = get_success_data(api.get_account(a1["id"], auditor))
        assert account["bureau_status"] == "DELETION_REQUESTED"
