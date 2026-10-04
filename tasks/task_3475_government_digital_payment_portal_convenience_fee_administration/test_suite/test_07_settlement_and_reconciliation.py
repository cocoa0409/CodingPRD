"""Settlement batches and treasury reconciliation: sweep membership, empty
closes, grace boundary, exception rows, exception-resolution bubble, role
segregation on deposit confirmation."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    assert_reconciliation_exception,
    assert_settlement_batch,
    capture,
    close_batch,
    confirm_batch,
    confirm_deposit_payload,
    get_batch,
    get_transaction,
    list_batches,
    list_exceptions,
    make_treasury_officer_headers,
    open_batch,
    pay,
    reconcile_batch,
    resolve_exception,
    resolve_exception_payload,
    set_clock,
    setup_cf_checkout,
    setup_exception_batch,
    setup_submitted_batch,
    submit_batch,
    validate_error,
    validate_paginated,
    validate_success,
)

PA = TEST_USERS["platform_admin_headers"]
TO = TEST_USERS["treasury_officer_headers"]


class TestExceptionBubble:
    def test_reconcile_raises_both_exceptions_first_resolve_keeps_exception(self, api):
        """PRD §3.5: "If `actual_deposit_cents` differs from `deposit_cents`,
        an `AMOUNT_MISMATCH` exception row is created under the batch's
        `batch_id` with `expected_cents` set to the frozen `deposit_cents`,
        `actual_cents` set to `actual_deposit_cents`, and a human-readable
        `detail` describing the mismatch. Independently, if the calendar date
        of `confirmed_at` is later than `deposit_due_date` plus a grace of one
        day, a `DEPOSIT_LATE` exception row is created with `actual_cents`
        null; a confirmation landing exactly on the first day after
        `deposit_due_date` is not late. One reconcile may create both
        exception rows."

        Design: Difficulty/transitive_cascade/exception_resolution_bubbles_batch_reconciled
        """
        ctx = setup_exception_batch()  # confirmed 99000 vs 100000 at 2026-09-13 (past grace)
        batch = ctx["batch"]
        assert batch["status"] == "EXCEPTION"
        assert batch["open_exception_count"] == 2
        exceptions = ctx["exceptions"]  # created_at ASC, then exception_type ASC
        assert len(exceptions) == 2
        mismatch, late = exceptions[0], exceptions[1]
        assert_reconciliation_exception(mismatch)
        assert mismatch["exception_type"] == "AMOUNT_MISMATCH"
        assert mismatch["expected_cents"] == 100000
        assert mismatch["actual_cents"] == 99000
        assert late["exception_type"] == "DEPOSIT_LATE"
        assert late["actual_cents"] is None
        resolve_exception(mismatch["id"], "Bank fee deducted at source; agency acknowledged")
        mid = get_batch(batch["id"])
        assert mid["status"] == "EXCEPTION", "no premature bubble while one exception remains OPEN"
        assert mid["open_exception_count"] == 1

    def test_resolving_last_exception_bubbles_batch_to_reconciled(self, api):
        """PRD §3.5: "When the batch's last `OPEN` exception resolves and its
        `open_exception_count` reaches zero, the batch bubbles up from
        `EXCEPTION` to `RECONCILED`, the terminal state of the settlement
        pipeline."

        Design: Difficulty/transitive_cascade/exception_resolution_bubbles_batch_reconciled
        """
        ctx = setup_exception_batch()
        for ex, note in zip(
            ctx["exceptions"],
            ["Bank fee deducted at source; agency acknowledged", "ACH rail delay documented"],
        ):
            resolve_exception(ex["id"], note)
        batch = get_batch(ctx["batch"]["id"])
        assert_settlement_batch(batch)
        assert batch["status"] == "RECONCILED"
        assert batch["open_exception_count"] == 0
        assert batch["deposit_cents"] == 100000
        assert batch["actual_deposit_cents"] == 99000


class TestBatchLifecycle:
    def test_batch_empty_close_finalizes_zeroes(self, api):
        """PRD §3.5: "The close finalizes the batch's totals: `member_count`
        — an empty close is legal and yields zero — `gross_amount_cents` as
        the sum of member `amount_cents`, `fees_withheld_cents` as the sum of
        member `charged_fee_cents` retained by the portal, `deposit_cents` as
        `gross_amount_cents` minus `refund_debits_cents` minus
        `return_debits_cents` minus `chargeback_debits_cents`, which may be
        negative, and `deposit_due_date` as the latest member `value_date`, or
        the batch's `business_date` itself when it closes empty."

        Design: Corner/state_machines/batch_empty_close_finalizes_zeroes
        """
        ctx = setup_cf_checkout(with_payer=False)
        batch = open_batch(ctx["agency"]["id"], "2026-09-05")
        closed = close_batch(batch["id"])
        assert_settlement_batch(closed)
        assert closed["status"] == "CLOSED"
        assert closed["member_count"] == 0
        assert closed["gross_amount_cents"] == 0
        assert closed["fees_withheld_cents"] == 0
        assert closed["deposit_cents"] == 0
        assert closed["deposit_due_date"] == "2026-09-05", "business_date fallback for the empty set"

    def test_batch_submit_before_close_rejected(self, api):
        """PRD §2.8: "`ERR_INVALID_STATE` for any other impermissible state".
        PRD §3.5: "Submitting a `CLOSED` batch — again `PlatformAdmin` —
        moves it to `SUBMITTED`, stamps `submitted_at` from the logical
        clock, and freezes the reconciliation expectation".

        Design: Corner/state_machines/batch_submit_before_close_rejected
        """
        ctx = setup_cf_checkout(with_payer=False)
        batch = open_batch(ctx["agency"]["id"], "2026-09-05")
        resp = api_client.submit_settlement_batch(batch["id"], PA)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        after = get_batch(batch["id"])
        assert after["status"] == "OPEN"
        assert after["submitted_at"] is None

    def test_batch_already_open_rejected(self, api):
        """PRD §3.5: "An agency may have only one `OPEN` batch at a time; a
        second open is rejected with `ERR_BATCH_ALREADY_OPEN`."

        Design: Corner/errors/err_batch_already_open
        """
        ctx = setup_cf_checkout(with_payer=False)
        open_batch(ctx["agency"]["id"], "2026-09-05")
        resp = api_client.create_settlement_batch(
            {"agency_id": ctx["agency"]["id"], "business_date": "2026-09-06"}, PA
        )
        validate_error(resp, ApiErrorId.ERR_BATCH_ALREADY_OPEN)
        assert len(list_batches(ctx["agency"]["id"])) == 1


class TestSweepMembership:
    def test_batch_membership_value_date_inclusive_boundary(self, api):
        """PRD §3.5: "Closing a batch — a `PlatformAdmin` operation — sweeps
        in every payment transaction of the batch's agency whose
        `funds_status` is `CAPTURED` or `RE_PRESENTED`, whose
        `current_batch_id` is null, and whose `value_date` is on or before
        the batch's `business_date`; the membership test is inclusive, so a
        `value_date` exactly equal to `business_date` is swept in."

        Design: Corner/calculations/batch_membership_value_date_inclusive_boundary
        """
        ctx = setup_cf_checkout(with_card=True, with_echeck=True)
        set_clock("2026-09-10T00:00:00Z")
        card = pay_and_capture_local(ctx, 100000, "CARD", ctx["card"]["id"])
        ech = pay_and_capture_local(ctx, 50000, "ECHECK", ctx["echeck"]["id"])
        assert card["value_date"] == "2026-09-11"
        assert ech["value_date"] == "2026-09-12"

        batch_a = open_batch(ctx["agency"]["id"], "2026-09-11")
        closed_a = close_batch(batch_a["id"])
        assert closed_a["member_count"] == 1, "the ECHECK (value 09-12) is excluded"
        assert closed_a["gross_amount_cents"] == 100000
        assert closed_a["fees_withheld_cents"] == 2281
        assert closed_a["deposit_due_date"] == "2026-09-11"
        assert get_transaction(ech["id"])["funds_status"] == "CAPTURED"

        batch_b = open_batch(ctx["agency"]["id"], "2026-09-12")
        closed_b = close_batch(batch_b["id"])
        assert closed_b["member_count"] == 1, "value_date == business_date is INCLUSIVE"
        assert closed_b["gross_amount_cents"] == 50000
        ech_after = get_transaction(ech["id"])
        assert ech_after["funds_status"] == "SETTLED"
        assert ech_after["current_batch_id"] == batch_b["id"]


def pay_and_capture_local(ctx, amount, method, instrument_id):
    paid = pay(ctx["service"]["id"], ctx["payer"]["id"], instrument_id, amount, method)
    return capture(paid["transaction"]["id"])


class TestReconcileGrace:
    def test_reconcile_grace_boundary_not_late(self, api):
        """PRD §3.5: "Independently, if the calendar date of `confirmed_at`
        is later than `deposit_due_date` plus a grace of one day, a
        `DEPOSIT_LATE` exception row is created with `actual_cents` null; a
        confirmation landing exactly on the first day after `deposit_due_date`
        is not late."

        Design: Corner/calculations/reconcile_grace_boundary_not_late
        """
        ctx = setup_submitted_batch()  # deposit 100000 due 2026-09-11; clock moves to 09-12 (due + 1)
        set_clock("2026-09-12T00:00:00Z")
        confirm_batch(ctx["batch"]["id"], 100000)
        reconciled = reconcile_batch(ctx["batch"]["id"])
        assert reconciled["status"] == "RECONCILED", "clean match goes CONFIRMED -> RECONCILED directly"
        assert list_exceptions(ctx["batch"]["id"]) == [], "on the grace boundary no DEPOSIT_LATE is raised"

    def test_exception_second_resolve_rejected(self, api):
        """PRD §3.5: "Resolving an exception takes a `resolution_note` and
        requires the parent batch in `EXCEPTION` status, otherwise
        `ERR_INVALID_STATE`; the row moves from `OPEN` to `RESOLVED` and
        records the note."

        Design: Corner/state_machines/exception_second_resolve_rejected
        """
        ctx = setup_exception_batch(confirm_clock="2026-09-12T00:00:00Z")
        # exact amount mismatch only (confirmation lands on the grace boundary: not late)
        assert len(ctx["exceptions"]) == 1
        assert ctx["exceptions"][0]["exception_type"] == "AMOUNT_MISMATCH"
        resolve_exception(ctx["exceptions"][0]["id"], "bank fee acknowledged")
        assert get_batch(ctx["batch"]["id"])["status"] == "RECONCILED"
        resp = api_client.resolve_reconciliation_exception(
            ctx["exceptions"][0]["id"], resolve_exception_payload("second resolve attempt"), PA
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        assert get_batch(ctx["batch"]["id"])["status"] == "RECONCILED"


class TestConfirmSegregation:
    def test_platform_admin_cannot_confirm_deposit(self, api):
        """PRD §3.5: "Deposit confirmation belongs to `TreasuryOfficer`,
        segregated from the `PlatformAdmin` role that submitted: the officer
        supplies `actual_deposit_cents`, the batch moves from `SUBMITTED` to
        `CONFIRMED`, and `confirmed_at` is stamped from the logical clock."

        Design: Corner/rbac/platform_admin_cannot_confirm_deposit
        """
        ctx = setup_submitted_batch()
        resp = api_client.confirm_batch_deposit(
            ctx["batch"]["id"], confirm_deposit_payload(100000), PA
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_FOR_ROLE)
        assert get_batch(ctx["batch"]["id"])["status"] == "SUBMITTED"
        confirmed = confirm_batch(ctx["batch"]["id"], 100000)
        assert confirmed["status"] == "CONFIRMED"
        assert confirmed["actual_deposit_cents"] == 100000
