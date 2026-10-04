"""Reversal cascades, breakage sweeps, OCC, and the fraud-flag workflow."""
from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    set_clock, create_store, create_account, create_receipt, cash_line,
    create_active_program, create_job,
    submit_receipt, approve_submission, process_return, redeem_certificate,
    run_breakage, current_store_version,
    setup_store_with_program, setup_account_with_receipt,
    setup_issued_certificate, open_duplicate_receipt_flag,
    make_customer_headers, make_contractor_headers,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


class TestReturnReversalCascade:

    def test_return_reversal_cascade_four_levels(self, api):
        """PRD §3.8: "First, the submission transitions from `APPROVED` to
        `REVERSED`. Second, the certificate that settled the submission —
        whether `ACTIVE` or `PARTIALLY_REDEEMED` — transitions to `VOIDED`, a
        terminal state; its `remaining_balance_cents` stays at its pre-void
        value on the row, but a voided certificate is excluded from both the
        account balance and the store liability because of its status. Third,
        a `REVERSAL_DEBIT` ledger entry posts the certificate's
        `remaining_balance_cents` as a negative amount — value the customer
        already redeemed is *not* clawed back from the account; only the
        unredeemed remainder is reversed. Fourth, the account's
        `pending_award_cents` decreases by the submission's `award_cents`,
        the account's `credit_balance_cents` is recomputed, and the store's
        `outstanding_liability_cents` and `net_liability_cents` are
        recomputed."
        PRD §3.4: "its `status` is derived from return activity: `OPEN` while
        nothing is returned, `PARTIALLY_RETURNED` when some but not all units
        have come back, and `FULLY_RETURNED` when every unit on every line
        has been returned, which is terminal."

        Design: Difficulty/transitive_cascade/return_reversal_cascade_four_levels
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-TC1"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-TC1-1")
        cert = ctx["cert"]
        assert cert["issued_amount_cents"] == 1000

        set_clock("2026-09-11T12:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 5000)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-TC1-2",
        )
        cert = redeem_certificate(store["id"], cert["id"], r2["id"], 500)
        assert cert["status"] == "PARTIALLY_REDEEMED"

        ret = validate_success(api.create_return(
            store["id"], ctx["receipt"]["id"],
            {"lines": [{"line_number": 1, "quantity": 1}]}, GUEST,
        ))

        receipt_read = validate_success(
            api.get_receipt(store["id"], ctx["receipt"]["id"], GUEST)
        )
        assert receipt_read["status"] == "FULLY_RETURNED"

        submission_read = validate_success(api.get_submission(
            store["id"], ctx["submission"]["id"], GUEST
        ))
        assert submission_read["status"] == "REVERSED"

        cert_read = validate_success(
            api.get_certificate(store["id"], cert["id"], GUEST)
        )
        assert cert_read["status"] == "VOIDED"

        assert len(ret["reversal_entry_ids"]) == 1
        ledger = get_success_data(
            api.list_ledger(store["id"], ctx["account"]["id"], FINANCE)
        )
        reversals = [e for e in ledger if e["entry_type"] == "REVERSAL_DEBIT"]
        assert len(reversals) == 1
        assert reversals[0]["id"] == ret["reversal_entry_ids"][0]
        assert reversals[0]["certificate_id"] == cert["id"]
        assert reversals[0]["amount_cents"] == -500, (
            "only the unredeemed remainder is reversed"
        )

        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0
        assert account["pending_award_cents"] == 0

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 0
        assert store_read["net_liability_cents"] == 0

    def test_return_without_awarded_lines_fires_no_cascade(self, api):
        """PRD §3.8: "The return becomes consequential when it touches at
        least one receipt line that contributed a positive
        `eligible_base_cents` to an `APPROVED` submission on that receipt."
        PRD §3.8: "a `Return` resource carrying the `receipt_id`, the
        `lines`, a `processed_at` timestamp taken from the logical clock, and
        `reversal_entry_ids`, the ledger entries minted by the reversal
        cascade — empty when nothing had been awarded yet."

        Design: Difficulty/transitive_cascade/return_reversal_cascade_four_levels
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-TC1B"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        # receipt carries the rebate-eligible line PLUS an ineligible line
        ctx = setup_issued_certificate(
            store, lines=[
                cash_line(1, "AAA", "TOOLS", 1, 10000),
                cash_line(2, "ZZZ", "PAINT", 1, 5000),
            ],
            receipt_number="R-TC1B-1",
        )
        assert ctx["submission"]["award_cents"] == 1000
        # returning only the ineligible line leaves the award untouched
        ret = validate_success(api.create_return(
            store["id"], ctx["receipt"]["id"],
            {"lines": [{"line_number": 2, "quantity": 1}]}, GUEST,
        ))
        assert ret["reversal_entry_ids"] == [], (
            "empty when nothing that was awarded is touched"
        )
        receipt_read = validate_success(
            api.get_receipt(store["id"], ctx["receipt"]["id"], GUEST)
        )
        assert receipt_read["status"] == "PARTIALLY_RETURNED"
        submission_read = validate_success(api.get_submission(
            store["id"], ctx["submission"]["id"], GUEST
        ))
        assert submission_read["status"] == "APPROVED"
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["status"] == "ACTIVE"

    def test_ledger_signed_sum_equals_account_position(self, api):
        """PRD §3.8: "Third, a `REVERSAL_DEBIT` ledger entry posts the
        certificate's `remaining_balance_cents` as a negative amount — value
        the customer already redeemed is *not* clawed back from the account;
        only the unredeemed remainder is reversed."
        PRD §3.3: "`lifetime_rebate_cents`, the cumulative adjudicated rebate
        value ever awarded to the account, which is never decremented, not
        even by reversals."
        PRD §2.7: "Each entry carries a signed `amount_cents` — accruals and
        reissue credits positive, redemptions and reversals negative,
        breakage negative as liability relief"

        Design: Difficulty/compensating_invariant/ledger_signed_sum_equals_account_position
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CI2"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-CI2-1")
        cert = ctx["cert"]
        assert cert["issued_amount_cents"] == 1000

        set_clock("2026-09-11T12:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 3000)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-CI2-2",
        )
        redeem_certificate(store["id"], cert["id"], r2["id"], 300)

        process_return(store["id"], ctx["receipt"]["id"],
                       [{"line_number": 1, "quantity": 1}])

        ledger = get_success_data(
            api.list_ledger(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert len(ledger) == 3, (
            f"expected ISSUANCE_ACCRUAL + REDEMPTION + REVERSAL_DEBIT, got "
            f"{[(e['entry_type'], e['amount_cents']) for e in ledger]}"
        )
        assert ledger[0]["entry_type"] == "ISSUANCE_ACCRUAL"
        assert ledger[0]["amount_cents"] == 1000
        assert ledger[1]["entry_type"] == "REDEMPTION"
        assert ledger[1]["amount_cents"] == -300
        assert ledger[2]["entry_type"] == "REVERSAL_DEBIT"
        assert ledger[2]["amount_cents"] == -700

        signed_sum = sum(e["amount_cents"] for e in ledger)
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert signed_sum == 0
        assert account["credit_balance_cents"] == 0
        assert account["pending_award_cents"] == 0
        assert signed_sum == account["credit_balance_cents"] + account["pending_award_cents"]
        assert account["lifetime_rebate_cents"] == 1000, (
            "cumulative award never decremented by the reversal"
        )

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 0

    def test_ledger_never_records_clawback_of_redeemed_value(self, api):
        """PRD §3.8: "Third, a `REVERSAL_DEBIT` ledger entry posts the
        certificate's `remaining_balance_cents` as a negative amount — value
        the customer already redeemed is *not* clawed back from the account;
        only the unredeemed remainder is reversed."
        PRD §2.7: "Ledger entries are never updated or deleted; corrections
        are made by posting further entries."

        Design: Difficulty/compensating_invariant/ledger_signed_sum_equals_account_position
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CI2B"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-CI2B-1")
        cert = ctx["cert"]

        set_clock("2026-09-11T12:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 3000)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-CI2B-2",
        )
        redeem_certificate(store["id"], cert["id"], r2["id"], 300)
        process_return(store["id"], ctx["receipt"]["id"],
                       [{"line_number": 1, "quantity": 1}])

        ledger = get_success_data(
            api.list_ledger(store["id"], ctx["account"]["id"], FINANCE)
        )
        reversals = [e for e in ledger if e["entry_type"] == "REVERSAL_DEBIT"]
        assert len(reversals) == 1
        assert reversals[0]["amount_cents"] == -700, (
            "exactly the remaining 700 is reversed; the redeemed 300 is "
            "never clawed back"
        )
        # no fourth entry exists to recover the redeemed value
        assert all(e["amount_cents"] != -300 or e["entry_type"] == "REDEMPTION"
                   for e in ledger)
        assert len(ledger) == 3


class TestBreakageSweepCascade:

    def test_breakage_run_cascade_three_levels(self, api):
        """PRD §3.7: "For each swept certificate, the certificate transitions
        to `EXPIRED` and a `BREAKAGE_EXPIRY` ledger entry posts its negative
        `remaining_balance_cents`, tagged with the run's epoch. The run
        records `expired_count`, the number of certificates it swept, and
        `breakage_recognized_cents`, the total swept value, and the store's
        `accrued_breakage_income_cents` increases by that total. The run
        advances the store's `liability_epoch` by 1, records the new epoch in
        the run's `epoch` field"
        PRD §3.7: "expired certificates stay on the books until they are
        reissued or age out of the reissue grace window"
        PRD §3.3: "certificates that are `EXPIRED`, `REISSUED`, `VOIDED`, or
        `FULLY_REDEEMED` contribute nothing"

        Design: Difficulty/transitive_cascade/breakage_run_cascade_three_levels
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-TC2"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx1 = setup_issued_certificate(store, receipt_number="R-TC2-1")
        assert ctx1["cert"]["issued_amount_cents"] == 1000
        ctx2 = setup_issued_certificate(
            store, account=ctx1["account"],
            lines=[cash_line(1, "AAA", "TOOLS", 1, 15000)],
            purchase_at="2026-09-08T11:00:00Z",
            create_clock=None, receipt_number="R-TC2-2",
            issue_clock="2026-09-11T12:00:00Z",
        )
        assert ctx2["cert"]["issued_amount_cents"] == 1500

        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["status"] == "COMPLETED"
        assert run["expired_count"] == 2
        assert run["breakage_recognized_cents"] == 2500
        assert run["epoch"] == 1

        for ctx in (ctx1, ctx2):
            cert_read = validate_success(
                api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
            )
            assert cert_read["status"] == "EXPIRED"

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["liability_epoch"] == 1
        assert store_read["accrued_breakage_income_cents"] == 2500
        assert store_read["outstanding_liability_cents"] == 2500, (
            "EXPIRED stays in gross liability until reissue grace lapses"
        )
        account = validate_success(
            api.get_account(store["id"], ctx1["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0, (
            "EXPIRED excluded from the redeemable balance"
        )

    def test_breakage_entries_carry_run_epoch_and_sweep_order(self, api):
        """PRD §3.7: "For each swept certificate, the certificate transitions
        to `EXPIRED` and a `BREAKAGE_EXPIRY` ledger entry posts its negative
        `remaining_balance_cents`, tagged with the run's epoch."
        PRD §3.7: "Swept certificates are processed in ascending `expires_at`
        order, ties broken by earlier `created_at`."
        PRD §2.7: "Each entry carries a signed `amount_cents` — accruals and
        reissue credits positive, redemptions and reversals negative,
        breakage negative as liability relief"

        Design: Difficulty/transitive_cascade/breakage_run_cascade_three_levels
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-TC2B"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx1 = setup_issued_certificate(store, receipt_number="R-TC2B-1")
        ctx2 = setup_issued_certificate(
            store, account=ctx1["account"],
            lines=[cash_line(1, "AAA", "TOOLS", 1, 15000)],
            purchase_at="2026-09-08T11:00:00Z",
            create_clock=None, receipt_number="R-TC2B-2",
            issue_clock="2026-09-11T12:00:00Z",
        )
        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["epoch"] == 1

        # PRD §3.5 endpoint table declares entry-type filtering only on the
        # platform-wide /ledger-entries listing, so the account-scoped
        # chronological listing is filtered client-side.
        all_entries = get_success_data(api.list_ledger(
            store["id"], ctx1["account"]["id"], FINANCE,
        ))
        ledger = [e for e in all_entries
                  if e["entry_type"] == "BREAKAGE_EXPIRY"]
        assert len(ledger) == 2
        # ascending expires_at order: cert1 (issued 09-10, expires 10-10)
        # before cert2 (issued 09-11, expires 10-11)
        assert ledger[0]["certificate_id"] == ctx1["cert"]["id"]
        assert ledger[0]["amount_cents"] == -1000
        assert ledger[1]["certificate_id"] == ctx2["cert"]["id"]
        assert ledger[1]["amount_cents"] == -1500
        assert all(e["liability_epoch"] == run["epoch"] for e in ledger), (
            "breakage entries are tagged with the run's epoch"
        )

    def test_occ_breakage_run_stale_version_rejected(self, api):
        """PRD §2.8: "Starting a breakage run is guarded the same way: the
        request must carry `expected_store_version` matching the store's
        current `version`, and a mismatch is rejected with
        `ERR_STALE_VERSION` (412)."
        PRD §3.7: "A run that finds nothing to sweep is legal:
        `expired_count` and `breakage_recognized_cents` are both 0, and the
        `liability_epoch` still advances by 1."

        Design: Corner/cross_cutting_layers/occ_breakage_run_stale_version_rejected
        """
        store = create_store(store_code="S-CC1")
        stale_version = store["version"]
        validate_success(api.update_store(
            store["id"],
            {"expected_store_version": stale_version,
             "split_txn_window_hours": 4},
            ADMIN,
        ))
        resp = api.create_breakage_run(
            store["id"], {"expected_store_version": stale_version}, FINANCE
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        fresh = current_store_version(store["id"])
        run = validate_success(api.create_breakage_run(
            store["id"], {"expected_store_version": fresh}, FINANCE
        ), 201)
        assert run["expired_count"] == 0
        assert run["breakage_recognized_cents"] == 0
        assert run["epoch"] == 1
        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["liability_epoch"] == 1

    def test_breakage_run_get_returns_run_record(self, api):
        """PRD §3.7: "The run is atomic — it executes and completes within
        the request, so only `COMPLETED` runs are ever observable even though
        the run passes through `RUNNING` internally"
        PRD §3.7: "The run records `expired_count`, the number of
        certificates it swept, and `breakage_recognized_cents`, the total
        swept value"

        Design: Corner/endpoints/breakage_run_get_returns_run_record
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-EP5"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-EP5")
        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        run_read = validate_success(
            api.get_breakage_run(store["id"], run["id"], ADMIN)
        )
        assert run_read["status"] == "COMPLETED"
        assert run_read["expired_count"] == 1
        assert run_read["breakage_recognized_cents"] == 1000
        assert run_read["epoch"] == 1
        assert run_read["store_id"] == store["id"]


class TestValueConservationAcrossReissue:

    def test_certificate_value_conservation_across_issue_redeem_reissue(self, api):
        """PRD §3.6: "A successful reissue mints a brand-new certificate:
        status `ACTIVE`, `issued_amount_cents` equal to the source
        certificate's `remaining_balance_cents`, `reissued_from_id` pointing
        at the source, and a fresh `issued_at` and `expires_at` computed from
        the current store policy. A `REISSUE_CREDIT` ledger entry posts the
        positive value against the new certificate, the source certificate's
        `remaining_balance_cents` drops to 0, and the source's status becomes
        `REISSUED`."
        PRD §3.7: "the `remaining_balance_cents` of every certificate of the
        store in `ACTIVE`, `PARTIALLY_REDEEMED`, or `EXPIRED` status"

        Design: Difficulty/compensating_invariant/certificate_value_conservation_across_issue_redeem_reissue
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CI1"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-CI1-1")
        cert1 = ctx["cert"]
        assert cert1["issued_amount_cents"] == 1000

        set_clock("2026-09-11T12:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 4000)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-CI1-2",
        )
        redeem_certificate(store["id"], cert1["id"], r2["id"], 400)

        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["breakage_recognized_cents"] == 600

        set_clock("2026-10-20T12:00:00Z")
        cert2 = validate_success(
            api.reissue_certificate(store["id"], cert1["id"], GUEST)
        )
        assert cert2["issued_amount_cents"] == 600, (
            "reissue conserves the swept balance"
        )
        assert cert2["remaining_balance_cents"] == 600
        assert cert2["reissued_from_id"] == cert1["id"]

        # per-certificate identity on the source: issued 1000 ==
        # redeemed 400 + breakage-swept 600
        ledger = get_success_data(
            api.list_ledger(store["id"], ctx["account"]["id"], FINANCE,
                            params={"certificate_id": cert1["id"]})
        )
        by_type = {e["entry_type"]: e["amount_cents"] for e in ledger}
        assert by_type["ISSUANCE_ACCRUAL"] == 1000
        assert by_type["REDEMPTION"] == -400
        assert by_type["BREAKAGE_EXPIRY"] == -600
        assert 1000 == 400 + 600

        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 600
        assert account["pending_award_cents"] == 0
        # account-level identity: lifetime issued 1000 == redeemed 400 +
        # credit balance 600 (reissue created no new value)
        assert 1000 == 400 + account["credit_balance_cents"]

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["accrued_breakage_income_cents"] == 600
        assert store_read["outstanding_liability_cents"] == 600, (
            "gross liability reinstated by the reissue"
        )

    def test_value_conserved_across_issue_redeem_and_expiry_sweep(self, api):
        """PRD §3.7: "the `remaining_balance_cents` of every certificate of
        the store in `ACTIVE`, `PARTIALLY_REDEEMED`, or `EXPIRED` status —
        expired certificates stay on the books until they are reissued or age
        out of the reissue grace window, while `VOIDED`, `FULLY_REDEEMED`,
        and `REISSUED` certificates contribute nothing"
        PRD §3.3: "`credit_balance_cents`, the sum of
        `remaining_balance_cents` over the account's certificates in `ACTIVE`
        or `PARTIALLY_REDEEMED` status — certificates that are `EXPIRED`,
        `REISSUED`, `VOIDED`, or `FULLY_REDEEMED` contribute nothing"

        Design: Difficulty/compensating_invariant/certificate_value_conservation_across_issue_redeem_reissue
        """
        # issue 1000, redeem 400, sweep the 600 remainder at expiry: the
        # value is conserved as 400 redeemed + 600 breakage income, with the
        # expired certificate still on the gross books and off the account's
        # redeemable balance
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CI1C"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-CI1C-1")
        cert1 = ctx["cert"]

        set_clock("2026-09-11T12:00:00Z")
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 4000)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-CI1C-2",
        )
        redeem_certificate(store["id"], cert1["id"], r2["id"], 400)

        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["breakage_recognized_cents"] == 600

        cert_read = validate_success(
            api.get_certificate(store["id"], cert1["id"], GUEST)
        )
        assert cert_read["status"] == "EXPIRED"
        assert cert_read["remaining_balance_cents"] == 600

        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 600, (
            "EXPIRED stays on the gross books until reissued"
        )
        assert store_read["accrued_breakage_income_cents"] == 600
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0
        # issued 1000 == redeemed 400 + swept 600
        assert cert1["issued_amount_cents"] == 1000
        assert 1000 == 400 + run["breakage_recognized_cents"]


class TestLedgerListing:

    def test_ledger_list_filter_by_certificate_and_ordering(self, api):
        """PRD §2.7: "Value movement is recorded in an append-only ledger.
        Every accrual, redemption, reversal, breakage sweep, and reissue
        posts a `CreditLedgerEntry`"
        PRD §2.3: "Ledger listings are chronological on the same basis."

        Design: Corner/endpoints/ledger_list_filter_by_certificate_and_ordering
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-EP4"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx1 = setup_issued_certificate(store, receipt_number="R-EP4-1")
        cert1 = ctx1["cert"]
        ctx2 = setup_issued_certificate(
            store, account=ctx1["account"],
            lines=[cash_line(1, "AAA", "TOOLS", 1, 5000)],
            purchase_at="2026-09-08T11:00:00Z",
            create_clock=None, receipt_number="R-EP4-2",
        )
        cert2 = ctx2["cert"]
        assert cert2["issued_amount_cents"] == 500

        set_clock("2026-09-12T00:00:00Z")
        r3 = create_receipt(
            store["id"], ctx1["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 100)],
            purchase_at="2026-09-11T10:00:00Z", receipt_number="R-EP4-3",
        )
        r4 = create_receipt(
            store["id"], ctx1["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 200)],
            purchase_at="2026-09-11T11:00:00Z", receipt_number="R-EP4-4",
        )
        redeem_certificate(store["id"], cert1["id"], r3["id"], 100)
        redeem_certificate(store["id"], cert1["id"], r4["id"], 200)

        entries = get_success_data(api.list_ledger(
            store["id"], ctx1["account"]["id"], FINANCE,
            params={"certificate_id": cert1["id"]},
        ))
        assert len(entries) == 3
        assert entries[0]["entry_type"] == "ISSUANCE_ACCRUAL"
        assert entries[0]["amount_cents"] == 1000
        assert entries[1]["entry_type"] == "REDEMPTION"
        assert entries[1]["amount_cents"] == -100
        assert entries[2]["entry_type"] == "REDEMPTION"
        assert entries[2]["amount_cents"] == -200
        assert all(e["certificate_id"] == cert1["id"] for e in entries), (
            "no entry references the other certificate"
        )


class TestFraudFlagWorkflow:

    def test_fraud_flag_cleared_reopen_confirm_cycle(self, api):
        """PRD §3.9: "Clearing a flag moves it to `CLEARED` and releases no
        holds automatically — any hold requires an explicit release. A
        cleared flag may be reopened, returning it to `OPEN` for
        re-investigation; resolving a flag that is not `OPEN`, or reopening
        one that is not `CLEARED`, is rejected with `ERR_INVALID_STATE`
        (409)."
        PRD §3.9: "Confirming a flag moves it to `CONFIRMED`, a terminal
        state"

        Design: Corner/state_machines/fraud_flag_cleared_reopen_confirm_cycle
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-SM7")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-SM7",
        )
        flag = open_duplicate_receipt_flag(store["id"], receipt["id"], account)
        assert flag["status"] == "OPEN"

        flag = validate_success(api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CLEAR"}, FRAUD
        ))
        assert flag["status"] == "CLEARED"
        flag = validate_success(
            api.reopen_fraud_flag(store["id"], flag["id"], FRAUD)
        )
        assert flag["status"] == "OPEN"
        flag = validate_success(api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CONFIRM"}, FRAUD
        ))
        assert flag["status"] == "CONFIRMED"
        resp = api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CLEAR"}, FRAUD
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_unfreeze_blocked_while_duplicate_receipt_flag_open(self, api):
        """PRD §3.3: "Unfreezing returns the account to `ACTIVE` but is
        refused with `ERR_FRAUD_FLAG_OPEN` (409) while any
        `DUPLICATE_RECEIPT` fraud flag on the account is still `OPEN`."

        Design: Corner/state_machines/unfreeze_blocked_while_duplicate_receipt_flag_open
        """
        set_clock("2026-09-08T12:00:00Z")
        store = create_store(store_code="S-SM8")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            purchase_at="2026-09-08T10:00:00Z", receipt_number="R-SM8",
        )
        flag = open_duplicate_receipt_flag(store["id"], receipt["id"], account)
        validate_success(api.freeze_account(store["id"], account["id"], FRAUD))

        resp = api.unfreeze_account(store["id"], account["id"], FRAUD)
        validate_error(resp, ApiErrorId.ERR_FRAUD_FLAG_OPEN)

        validate_success(api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CLEAR"}, FRAUD
        ))
        account_read = validate_success(
            api.unfreeze_account(store["id"], account["id"], FRAUD)
        )
        assert account_read["status"] == "ACTIVE"

    def test_reissue_allowed_while_flag_cleared(self, api):
        """PRD §3.6: "within a grace window of 30 days after `expires_at`,
        guest service may reissue it."
        PRD §3.9: "Clearing a flag moves it to `CLEARED`"

        Design: Difficulty/cross_entity_state_dependency/certificate_reissue_gated_by_confirmed_fraudflag
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-XD1"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-XD1-1")
        set_clock("2026-10-15T00:00:00Z")
        run_breakage(store["id"])
        set_clock("2026-10-20T12:00:00Z")

        # open then CLEAR a DUPLICATE_RECEIPT flag on the account
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 7000)],
            purchase_at="2026-10-19T10:00:00Z", receipt_number="R-XD1-2",
        )
        submit_receipt(store["id"], r2["id"], ctx["account"])
        dup_resp = api.create_submission(
            store["id"], {"receipt_id": r2["id"]},
            make_customer_headers(ctx["account"]["id"]),
        )
        validate_error(dup_resp, ApiErrorId.ERR_DUPLICATE_RECEIPT_SUBMISSION)
        flags = get_success_data(api.list_fraud_flags(
            store["id"], FRAUD,
            params={"account_id": ctx["account"]["id"],
                    "flag_type": "DUPLICATE_RECEIPT"},
        ))
        assert len(flags) == 1
        flag = flags[0]
        validate_success(api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CLEAR"}, FRAUD
        ))

        # reissue succeeds while the flag is merely CLEARED
        cert2 = validate_success(
            api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert2["status"] == "ACTIVE"
        assert cert2["issued_amount_cents"] == 1000
        assert cert2["reissued_from_id"] == ctx["cert"]["id"]

    def test_reissue_blocked_once_flag_confirmed(self, api):
        """PRD §3.6: "refused with `ERR_ACCOUNT_FRAUD_CONFIRMED` (409) while
        any fraud flag on the account is `CONFIRMED`"
        PRD §3.9: "Confirming a flag moves it to `CONFIRMED`, a terminal
        state, and places every certificate of the account whose
        `fraud_hold` is `NONE` into `HELD`"

        Design: Difficulty/cross_entity_state_dependency/certificate_reissue_gated_by_confirmed_fraudflag
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-XD1"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(store, receipt_number="R-XD1-1")
        set_clock("2026-10-15T00:00:00Z")
        run_breakage(store["id"])
        set_clock("2026-10-20T12:00:00Z")

        # CONFIRM a duplicate-receipt flag on the account
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 7000)],
            purchase_at="2026-10-19T10:00:00Z", receipt_number="R-XD1-2",
        )
        submit_receipt(store["id"], r2["id"], ctx["account"])
        validate_error(api.create_submission(
            store["id"], {"receipt_id": r2["id"]},
            make_customer_headers(ctx["account"]["id"]),
        ), ApiErrorId.ERR_DUPLICATE_RECEIPT_SUBMISSION)
        flags = get_success_data(api.list_fraud_flags(
            store["id"], FRAUD,
            params={"account_id": ctx["account"]["id"],
                    "flag_type": "DUPLICATE_RECEIPT"},
        ))
        flag = flags[0]
        validate_success(api.resolve_fraud_flag(
            store["id"], flag["id"], {"resolution": "CONFIRM"}, FRAUD
        ))
        # the CONFIRM places the expired certificate on hold; release it so
        # the fraud-confirmation gate is the one under test
        validate_success(
            api.release_certificate(store["id"], ctx["cert"]["id"], FRAUD)
        )
        resp = api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_FRAUD_CONFIRMED)
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["status"] == "EXPIRED", (
            "unchanged by the failed reissue"
        )


class TestContractorAggregation:

    def test_contractor_summary_tier_boundary_and_net_of_reversal(self, api):
        """PRD §3.3: "each job's awarded total is the sum of `award_cents`
        over `APPROVED` submissions whose receipts are charged to that job,
        minus the `award_cents` of `REVERSED` submissions on those same
        receipts — a net-of-reversal figure."
        PRD §3.3: "totals below 500,000 cents earn no bonus (tier `NONE`);
        totals of at least 500,000 cents but below 2,000,000 cents fall in
        tier `PRO` and earn a bonus of the total multiplied by 0.02, rounded
        half-up to whole cents"
        PRD §3.3: "A total landing exactly on 500,000 cents is in `PRO` — the
        tier boundary is inclusive upward."

        Design: Corner/calculations/contractor_summary_tier_boundary_and_net_of_reversal
        """
        from test_helpers import issue_certificate
        base = setup_store_with_program(
            store_overrides={"store_code": "S-CAL4"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        set_clock("2026-09-08T12:00:00Z")
        account = create_account(store["id"], owner_name="Carl Contractor",
                                 account_type="CONTRACTOR")
        j1 = create_job(store["id"], account["id"], job_reference="JOB-1")
        j2 = create_job(store["id"], account["id"], job_reference="JOB-2")

        def _job_receipt(number, job_id, price, hhmm):
            return create_receipt(
                store["id"], account["id"],
                [cash_line(1, "AAA", "TOOLS", 1, price)],
                purchase_at=f"2026-09-08T{hhmm}:00Z",
                job_purchase_id=job_id, receipt_number=number,
            )

        def _approve_and_issue(receipt):
            sub = approve_submission(
                store["id"],
                submit_receipt(store["id"], receipt["id"], account)["id"],
            )
            issue_certificate(store["id"], sub["id"])

        r1 = _job_receipt("R-CAL4-1", j1["id"], 3000000, "10:00")
        r2 = _job_receipt("R-CAL4-2", j2["id"], 2000000, "10:30")
        r3 = _job_receipt("R-CAL4-3", j1["id"], 1000000, "11:00")
        r4 = _job_receipt("R-CAL4-4", j2["id"], 1000000, "11:30")

        _approve_and_issue(r1)
        sub2 = approve_submission(
            store["id"], submit_receipt(store["id"], r2["id"], account)["id"]
        )
        issue_certificate(store["id"], sub2["id"])
        _approve_and_issue(r3)

        # R2 fully returned -> its approved award nets out of the summary
        process_return(store["id"], r2["id"],
                       [{"line_number": 1, "quantity": 1}])

        summary = validate_success(api.get_contractor_summary(
            store["id"], account["id"], make_contractor_headers(account["id"])
        ))
        assert summary["account_job_total_cents"] == 400000, (
            f"300000 (J1) + 100000 (J1) + 0 net (J2 reversed), got "
            f"{summary['account_job_total_cents']}"
        )
        assert summary["bonus_tier"] == "NONE"
        assert summary["bonus_cents"] == 0

        _approve_and_issue(r4)
        summary = validate_success(api.get_contractor_summary(
            store["id"], account["id"], make_contractor_headers(account["id"])
        ))
        assert summary["account_job_total_cents"] == 500000, (
            "exactly the 500,000-cent tier threshold"
        )
        assert summary["bonus_tier"] == "PRO", (
            "the tier boundary is inclusive upward"
        )
        assert summary["bonus_cents"] == 10000, (
            f"round_half_up(500000 * 0.02) = 10000, got "
            f"{summary['bonus_cents']}"
        )
