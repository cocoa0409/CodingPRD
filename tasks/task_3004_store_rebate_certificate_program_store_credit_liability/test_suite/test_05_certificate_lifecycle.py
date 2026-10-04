"""Certificate redemption, expiry, reissue, holds, and terminal lockdown."""
from datetime import datetime, timezone

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId, NON_EXISTENT_UUID,
    set_clock, create_store, create_account, create_receipt, cash_line,
    create_active_program,
    submit_receipt, approve_submission, process_return, redeem_certificate,
    run_breakage, setup_store_with_program, setup_account_with_receipt,
    setup_issued_certificate, make_customer_headers,
)
from test_helpers.test_users import TEST_USERS

ADMIN = TEST_USERS["store_admin_headers"]
GUEST = TEST_USERS["guest_service_headers"]
FRAUD = TEST_USERS["fraud_analyst_headers"]
FINANCE = TEST_USERS["finance_admin_headers"]


def _instant(text):
    """Parse an ISO 8601 UTC timestamp for instant-level comparison."""
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(
        timezone.utc)


def _setup_cert(store_code="S-CERT"):
    """Store + ACTIVE program (AAA 0.10) + account + 10000 receipt + approved
    submission + issued 1000-cent certificate. Returns dict."""
    base = setup_store_with_program(
        store_overrides={"store_code": store_code},
        items=[{"sku": "AAA", "rebate_pct": 0.1}],
    )
    ctx = setup_issued_certificate(base["store"], owner_name="Ann")
    ctx["store"] = base["store"]
    return ctx


def _non_eligible_receipt(store, account, purchase_at="2026-09-11T10:00:00Z",
                          amount=2000, receipt_number="R-TGT"):
    return create_receipt(
        store["id"], account["id"],
        [cash_line(1, "ZZZ", "PAINT", 1, amount)],
        purchase_at=purchase_at, receipt_number=receipt_number,
    )


class TestRedemptionGuards:

    def test_redeem_fully_redeemed_certificate_returns_invalid_state(self, api):
        """PRD §3.6: "the certificate must be in `ACTIVE` or
        `PARTIALLY_REDEEMED` status — redeeming in any other status is
        rejected with `ERR_INVALID_STATE` (409)"
        PRD §3.6: "an amount exactly equal to the remaining balance moves it
        to `FULLY_REDEEMED` with the balance at 0 — the boundary case takes
        the full-redemption transition."

        Design: Corner/state_machines/redeem_fully_redeemed_certificate_returns_invalid_state
        """
        ctx = _setup_cert("S-SM2")
        store = ctx["store"]
        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(store, ctx["account"], receipt_number="R-SM2-2")
        cert = redeem_certificate(store["id"], ctx["cert"]["id"], r2["id"], 1000)
        assert cert["status"] == "FULLY_REDEEMED"
        assert cert["remaining_balance_cents"] == 0

        resp = api.redeem_certificate(
            store["id"], cert["id"],
            {"receipt_id": r2["id"], "amount_cents": 1}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)
        cert_read = validate_success(
            api.get_certificate(store["id"], cert["id"], GUEST)
        )
        assert cert_read["remaining_balance_cents"] == 0

    def test_redemption_exceeding_balance_rejected(self, api):
        """PRD §3.6: "The amount must be at least 1 cent and no more than the
        certificate's `remaining_balance_cents`; an overdraw is rejected with
        `ERR_REDEMPTION_EXCEEDS_BALANCE` (422)."

        Design: Corner/validations/redemption_exceeding_balance_rejected
        """
        ctx = _setup_cert("S-VAL3")
        store = ctx["store"]
        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(store, ctx["account"], receipt_number="R-VAL3-2")
        resp = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 1001}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_REDEMPTION_EXCEEDS_BALANCE)
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["remaining_balance_cents"] == 1000

    def test_redeem_at_or_past_expiry_rejected_without_run(self, api):
        """PRD §3.6: "the logical clock must be strictly before
        `expires_at`, with `ERR_CERTIFICATE_EXPIRED` (422) at or past it"
        PRD §3.6: "The expiry instant itself is already expired: redemption
        requires the logical clock to be strictly before `expires_at`, while
        a breakage sweep claims certificates whose `expires_at` is at or
        before the run time."

        Design: Corner/validations/redeem_at_or_past_expiry_rejected_without_run
        """
        ctx = _setup_cert("S-VAL7")
        store = ctx["store"]
        # cert issued at 2026-09-10T12:00:00Z, validity 1 month
        # -> expires_at 2026-10-10T00:00:00Z; receipt recorded before the
        # clock advance so it is not in the future
        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(store, ctx["account"], receipt_number="R-VAL7-2")
        set_clock("2026-10-10T00:00:00Z")
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["status"] == "ACTIVE", (
            "no breakage run has swept it, so the status is still ACTIVE"
        )
        resp = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 100}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_EXPIRED)

    def test_redeem_certificate_against_other_accounts_receipt_rejected(self, api):
        """PRD §3.6: "the redeeming receipt must belong to the certificate's
        issuing store and to the certificate holder's own account, with
        `ERR_CERTIFICATE_WRONG_STORE` (422) otherwise"

        Design: Corner/validations/redeem_certificate_against_other_accounts_receipt_rejected
        """
        ctx = _setup_cert("S-VAL11")
        store = ctx["store"]
        set_clock("2026-09-12T00:00:00Z")
        other = create_account(store["id"], owner_name="Bob")
        r2 = _non_eligible_receipt(store, other, receipt_number="R-VAL11-2")
        resp = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 100}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_WRONG_STORE)
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["remaining_balance_cents"] == 1000

    def test_redeem_barred_when_receipt_line_is_rebate_eligible(self, api):
        """PRD §3.6: "and the redemption bar applies — no line of the
        redeeming receipt may match any program item of a program whose
        advertised week contains that receipt's `purchase_at` at the
        redeeming store, because certificates may never pay for further
        rebate-eligible purchases, and a violating basket is rejected with
        `ERR_CERTIFICATE_REBATE_PURCHASE_BARRED` (422)."

        Design: Difficulty/cross_entity_state_dependency/certificate_redeem_gated_by_receipt_line_rebate_eligibility
        """
        ctx = _setup_cert("S-XD2")
        store = ctx["store"]
        # receipt purchased INSIDE the program week with the matching sku
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 5000)],
            purchase_at="2026-09-10T10:00:00Z", receipt_number="R-XD2-2",
        )
        resp = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 100}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_REBATE_PURCHASE_BARRED)

    def test_redeem_allowed_after_program_week_closed(self, api):
        """PRD §3.5: "Find the program item whose `sku` equals the line's
        `sku` and whose program's advertised week contains the receipt's
        `purchase_at` — the week opens at 00:00:00Z on `week_start_date` and
        closes at 00:00:00Z on `week_end_date`, the closing instant excluded."
        PRD §3.6: "and the redemption bar applies — no line of the redeeming
        receipt may match any program item of a program whose advertised week
        contains that receipt's `purchase_at` at the redeeming store"

        Design: Difficulty/cross_entity_state_dependency/certificate_redeem_gated_by_receipt_line_rebate_eligibility
        """
        ctx = _setup_cert("S-XD2")
        store = ctx["store"]
        set_clock("2026-09-21T00:00:00Z")
        # same SKU, but purchased after the advertised week closed
        r3 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 5000)],
            purchase_at="2026-09-20T10:00:00Z", receipt_number="R-XD2-3",
        )
        cert = redeem_certificate(store["id"], ctx["cert"]["id"], r3["id"], 100)
        assert cert["status"] == "PARTIALLY_REDEEMED"
        assert cert["remaining_balance_cents"] == 900


class TestExactBalanceBoundary:

    def test_exact_balance_redemption_lands_fully_redeemed(self, api):
        """PRD §3.6: "an amount exactly equal to the remaining balance moves
        it to `FULLY_REDEEMED` with the balance at 0 — the boundary case
        takes the full-redemption transition."

        Design: Difficulty/boundary_precision_check/redemption_exact_balance_full_vs_partial_and_expiry_edge
        """
        ctx = _setup_cert("S-BP2")
        store = ctx["store"]
        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(store, ctx["account"], receipt_number="R-BP2-2")
        cert = redeem_certificate(store["id"], ctx["cert"]["id"], r2["id"], 1000)
        assert cert["status"] == "FULLY_REDEEMED", (
            "exact-balance redemption takes the FULL branch, not PARTIAL"
        )
        assert cert["remaining_balance_cents"] == 0

    def test_breakage_run_at_expiry_instant_sweeps_inclusive(self, api):
        """PRD §3.7: "it sweeps every certificate of the store in `ACTIVE` or
        `PARTIALLY_REDEEMED` status whose `expires_at` is at or before the
        run's `run_at` timestamp, the boundary included."
        PRD §3.6: "while a breakage sweep claims certificates whose
        `expires_at` is at or before the run time."

        Design: Difficulty/boundary_precision_check/redemption_exact_balance_full_vs_partial_and_expiry_edge
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-BP2"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(
            store, lines=[cash_line(1, "AAA", "TOOLS", 1, 5000)],
            receipt_number="R-BP2-3",
        )
        cert2 = ctx["cert"]
        assert cert2["issued_amount_cents"] == 500
        # expires_at == 2026-10-10T00:00:00Z (issued 2026-09-10 + 1 month)
        set_clock("2026-10-10T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["expired_count"] == 1, (
            "run_at == expires_at exactly IS swept (inclusive boundary)"
        )
        assert run["breakage_recognized_cents"] == 500
        cert_read = validate_success(
            api.get_certificate(store["id"], cert2["id"], GUEST)
        )
        assert cert_read["status"] == "EXPIRED"
        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0


class TestExpiryAndReissue:

    def test_certificate_expiry_month_end_clamp(self, api):
        """PRD §3.6: "When the day-of-month does not exist in the target
        month, the date clamps to that month's last day — a certificate
        issued on January 31 with one month of validity expires at 00:00:00Z
        on February 28."

        Design: Corner/calculations/certificate_expiry_month_end_clamp
        """
        set_clock("2026-01-26T00:00:00Z")
        store = create_store(store_code="S-CAL5")
        create_active_program(
            store["id"], [{"sku": "AAA", "rebate_pct": 0.1}],
            week_start="2026-01-26", week_end="2026-02-02",
        )
        set_clock("2026-01-31T12:00:00Z")
        account = create_account(store["id"], owner_name="Ann")
        receipt = create_receipt(
            store["id"], account["id"],
            [cash_line(1, "AAA", "TOOLS", 1, 10000)],
            purchase_at="2026-01-31T10:00:00Z", receipt_number="R-CAL5",
        )
        submission = approve_submission(
            store["id"], submit_receipt(store["id"], receipt["id"], account)["id"]
        )
        cert = validate_success(
            api.issue_certificate(store["id"], submission["id"], GUEST)
        )
        # compare instants: the PRD pins the instant, not the fractional-
        # second wire spelling
        assert _instant(cert["issued_at"]) == _instant("2026-01-31T12:00:00Z")
        assert _instant(cert["expires_at"]) == _instant("2026-02-28T00:00:00Z"), (
            "day 31 clamps to the last day of February"
        )

    def test_certificate_expire_reissue_cycle_redeems_on_second_life(self, api):
        """PRD §3.6: "A successful reissue mints a brand-new certificate:
        status `ACTIVE`, `issued_amount_cents` equal to the source
        certificate's `remaining_balance_cents`, `reissued_from_id` pointing
        at the source, and a fresh `issued_at` and `expires_at` computed from
        the current store policy."
        PRD §3.6: "the source certificate's `remaining_balance_cents` drops
        to 0, and the source's status becomes `REISSUED`."

        Design: Difficulty/non_linear_state_machine/certificate_expire_reissue_cycle_redeems_on_second_life
        """
        ctx = _setup_cert("S-NL1")
        store = ctx["store"]
        set_clock("2026-10-15T00:00:00Z")
        run = run_breakage(store["id"])
        assert run["expired_count"] == 1
        assert run["breakage_recognized_cents"] == 1000

        set_clock("2026-10-20T12:00:00Z")
        cert2 = validate_success(
            api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert2["status"] == "ACTIVE"
        assert cert2["issued_amount_cents"] == 1000
        assert cert2["reissued_from_id"] == ctx["cert"]["id"]

        source = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert source["status"] == "REISSUED"
        assert source["remaining_balance_cents"] == 0

        # the same monetary value redeems on the certificate's second life
        r2 = create_receipt(
            store["id"], ctx["account"]["id"],
            [cash_line(1, "ZZZ", "PAINT", 1, 1000)],
            purchase_at="2026-10-20T10:00:00Z", receipt_number="R-NL1-2",
        )
        cert2 = redeem_certificate(store["id"], cert2["id"], r2["id"], 1000)
        assert cert2["status"] == "FULLY_REDEEMED"

        account = validate_success(
            api.get_account(store["id"], ctx["account"]["id"], FINANCE)
        )
        assert account["credit_balance_cents"] == 0
        store_read = validate_success(api.get_store(store["id"], FINANCE))
        assert store_read["outstanding_liability_cents"] == 0
        assert store_read["accrued_breakage_income_cents"] == 1000

    def test_reissue_posts_reissue_credit_ledger_entry_and_zeroes_source(self, api):
        """PRD §3.6: "A `REISSUE_CREDIT` ledger entry posts the positive
        value against the new certificate, the source certificate's
        `remaining_balance_cents` drops to 0, and the source's status becomes
        `REISSUED`."
        PRD §2.7: "Each entry carries a signed `amount_cents` — accruals and
        reissue credits positive, redemptions and reversals negative,
        breakage negative as liability relief"

        Design: Difficulty/non_linear_state_machine/certificate_expire_reissue_cycle_redeems_on_second_life
        """
        ctx = _setup_cert("S-NL1B")
        store = ctx["store"]
        set_clock("2026-10-15T00:00:00Z")
        run_breakage(store["id"])
        set_clock("2026-10-20T12:00:00Z")
        cert2 = validate_success(
            api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert2["status"] == "ACTIVE"
        assert cert2["issued_amount_cents"] == 1000

        source = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert source["status"] == "REISSUED"
        assert source["remaining_balance_cents"] == 0

        entries = get_success_data(api.list_ledger(
            store["id"], ctx["account"]["id"], FINANCE,
            params={"certificate_id": cert2["id"]},
        ))
        assert len(entries) == 1
        assert entries[0]["entry_type"] == "REISSUE_CREDIT"
        assert entries[0]["amount_cents"] == 1000

    def test_reissue_after_grace_window_rejected(self, api):
        """PRD §3.6: "Reissue is refused with `ERR_REISSUE_WINDOW_CLOSED`
        (422) once the logical clock reaches 30 days past expiry"
        PRD §3.6: "within a grace window of 30 days after `expires_at`, guest
        service may reissue it."

        Design: Corner/validations/reissue_after_grace_window_rejected
        """
        ctx = _setup_cert("S-VAL6")
        store = ctx["store"]
        # cert expires 2026-10-10T00:00:00Z; grace ends 2026-11-09T00:00:00Z
        set_clock("2026-10-15T00:00:00Z")
        run_breakage(store["id"])
        set_clock("2026-11-09T00:00:00Z")
        resp = api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        validate_error(resp, ApiErrorId.ERR_REISSUE_WINDOW_CLOSED)
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["status"] == "EXPIRED"

    def test_voided_certificate_terminal_rejects_reissue_and_redeem(self, api):
        """PRD §3.6: "the certificate must be in `ACTIVE` or
        `PARTIALLY_REDEEMED` status — redeeming in any other status is
        rejected with `ERR_INVALID_STATE` (409)"
        PRD §3.8: "Second, the certificate that settled the submission —
        whether `ACTIVE` or `PARTIALLY_REDEEMED` — transitions to `VOIDED`, a
        terminal state"

        Design: Corner/state_machines/voided_certificate_terminal_rejects_reissue_and_redeem
        """
        ctx = _setup_cert("S-SM6")
        store = ctx["store"]
        # full return on the awarding receipt voids the certificate
        process_return(store["id"], ctx["receipt"]["id"],
                       [{"line_number": 1, "quantity": 1}])
        cert_read = validate_success(
            api.get_certificate(store["id"], ctx["cert"]["id"], GUEST)
        )
        assert cert_read["status"] == "VOIDED"

        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(store, ctx["account"], receipt_number="R-SM6-2")
        resp1 = api.reissue_certificate(store["id"], ctx["cert"]["id"], GUEST)
        validate_error(resp1, ApiErrorId.ERR_INVALID_STATE)
        resp2 = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 100}, GUEST,
        )
        validate_error(resp2, ApiErrorId.ERR_INVALID_STATE)


class TestFraudHoldParallelDimension:

    def test_certificate_hold_release_parallel_dimension_leaves_status_untouched(self, api):
        """PRD §3.6: "Fraud holds form a parallel state dimension on the
        certificate, independent of its lifecycle status: `fraud_hold` moves
        between `NONE`, `HELD`, and `RELEASED` without touching `status`. A
        `FraudAnalyst` may place a hold — moving `fraud_hold` to `HELD` — or
        release it — moving it to `RELEASED` — from any non-terminal status;
        a hold blocks redemption and reissue without otherwise changing the
        certificate."
        PRD §3.6: "a certificate under a fraud hold — `fraud_hold` equal to
        `HELD` — is rejected with `ERR_CERTIFICATE_HELD` (409)"

        Design: Corner/state_machines/certificate_hold_release_parallel_dimension_leaves_status_untouched
        """
        ctx = _setup_cert("S-SM5")
        store = ctx["store"]
        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(
            store, ctx["account"], amount=100, receipt_number="R-SM5-2"
        )

        held = validate_success(
            api.hold_certificate(store["id"], ctx["cert"]["id"], FRAUD)
        )
        assert held["fraud_hold"] == "HELD"
        assert held["status"] == "ACTIVE"
        resp = api.redeem_certificate(
            store["id"], ctx["cert"]["id"],
            {"receipt_id": r2["id"], "amount_cents": 100}, GUEST,
        )
        validate_error(resp, ApiErrorId.ERR_CERTIFICATE_HELD)

        released = validate_success(
            api.release_certificate(store["id"], ctx["cert"]["id"], FRAUD)
        )
        assert released["fraud_hold"] == "RELEASED"
        assert released["status"] == "ACTIVE"
        cert = redeem_certificate(store["id"], ctx["cert"]["id"], r2["id"], 100)
        assert cert["status"] == "PARTIALLY_REDEEMED"
        assert cert["fraud_hold"] == "RELEASED"
        assert cert["remaining_balance_cents"] == 900


class TestCertificateLookup:

    def test_get_certificate_with_unknown_id_returns_404(self, api):
        """PRD §2.9: "For any request whose path addresses nested resources,
        the server validates path identifiers from left to right: each
        identifier must exist and must nest correctly under its parent before
        the next is considered. The first identifier that fails — a missing
        store, a receipt belonging to a different store, a submission under
        the wrong account — yields `ERR_NOT_FOUND` (404) before any business
        rule is evaluated."

        Design: Corner/entities/get_certificate_with_unknown_id_returns_404
        """
        ctx = _setup_cert("S-ENT4A")
        s2 = create_store(store_code="S-ENT4B")
        resp1 = api.get_certificate(ctx["store"]["id"], NON_EXISTENT_UUID, GUEST)
        validate_error(resp1, ApiErrorId.ERR_NOT_FOUND)
        resp2 = api.get_certificate(s2["id"], ctx["cert"]["id"], GUEST)
        validate_error(resp2, ApiErrorId.ERR_NOT_FOUND)


class TestAccountClosure:

    def test_credit_account_close_blocked_while_balance_nonzero(self, api):
        """PRD §3.3: "A `StoreAdmin` closes an account only when both
        `credit_balance_cents` and `pending_award_cents` are exactly zero;
        otherwise the close is rejected with
        `ERR_ACCOUNT_BALANCE_NONZERO` (409)."

        Design: Corner/entities/credit_account_close_blocked_while_balance_nonzero
        """
        base = setup_store_with_program(
            store_overrides={"store_code": "S-ENT10"},
            items=[{"sku": "AAA", "rebate_pct": 0.1}],
        )
        store = base["store"]
        ctx = setup_issued_certificate(
            store, lines=[cash_line(1, "AAA", "TOOLS", 1, 5000)],
            receipt_number="R-ENT10-1",
        )
        assert ctx["cert"]["issued_amount_cents"] == 500
        resp = api.close_account(store["id"], ctx["account"]["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_ACCOUNT_BALANCE_NONZERO)

        set_clock("2026-09-12T00:00:00Z")
        r2 = _non_eligible_receipt(
            store, ctx["account"], amount=500, receipt_number="R-ENT10-2"
        )
        redeem_certificate(store["id"], ctx["cert"]["id"], r2["id"], 500)
        closed = validate_success(
            api.close_account(store["id"], ctx["account"]["id"], ADMIN)
        )
        assert closed["status"] == "CLOSED"
