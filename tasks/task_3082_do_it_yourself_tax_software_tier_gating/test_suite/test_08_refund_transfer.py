"""Refund transfer: pricing, disclosure gating, fee conservation, and the
bank-partner registry."""
from test_helpers import (
    ACTIVE_BANK_DISCLOSURE_VERSION,
    TEST_USERS,
    accept_disclosure,
    add_form,
    create_account,
    create_refund_transfer,
    create_return,
    get_return,
    list_refund_transfers,
    make_taxpayer_headers,
    seed_catalog,
    setup_return_with_forms,
    unique_email,
    validate_error,
    validate_success,
    void_refund_transfer,
)
from test_helpers.api_errors import ApiErrorId


class TestTotalFeesCircularOrder:
    def _setup_premier_return_with_active_rt(self, w2_amount):
        """PREMIER return (prompt acknowledged) + CA state return + ACTIVE
        refund transfer + W2_WH withholding of w2_amount, then submit-review.
        Total fees = 12999 + 4999 + 4000 = 21998."""
        from test_helpers import add_state_return, submit_review

        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"),
            agi_cents=2000000,
            email=unique_email("comb1"),
            resolve_prompt="acknowledge",
        )
        add_form(ret, "W2_WH", w2_amount)
        add_state_return(ret, "CA")
        create_refund_transfer(ret, bank_partner_code="BANK_A")
        accept_disclosure(ret)
        submit_review(ret)
        return account, ret

    def test_refund_one_cent_short_of_fees_state_untouched(self, api):
        """PRD §3.6: "if refund transfer was elected, the refund must cover
        the fees — `federal_refund_cents` must be at least
        `total_fees_due_cents`, checked against the fully computed total, else
        `ERR_REFUND_INSUFFICIENT_FOR_FEES` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/total_fees_circular_order_pinned
        """
        account, ret = self._setup_premier_return_with_active_rt(21997)
        after = get_return(ret)
        # Pinned evaluation order: 12999 base + 4999 state add-on + 4000 fee.
        assert after["total_fees_due_cents"] == 21998
        assert after["federal_refund_cents"] == 21997
        resp = api.file_return(
            ret.id, "hash-a", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_INSUFFICIENT_FOR_FEES)
        assert get_return(ret)["status"] == "READY_FOR_REVIEW"

    def test_refund_exactly_at_fees_files(self, api):
        """PRD §3.6: "if refund transfer was elected, the refund must cover
        the fees — `federal_refund_cents` must be at least
        `total_fees_due_cents`, checked against the fully computed total, else
        `ERR_REFUND_INSUFFICIENT_FOR_FEES` (HTTP 402)."

        Design: Difficulty/combinatorial_formula/total_fees_circular_order_pinned
        """
        account, ret = self._setup_premier_return_with_active_rt(21998)
        resp = api.file_return(
            ret.id, "hash-a", ret.version, make_taxpayer_headers(account["id"])
        )
        attempt = validate_success(resp, expected_status=201)
        assert attempt["outcome"] == "PENDING"
        assert get_return(ret)["status"] == "SUBMITTED"


class TestRefundBoundary:
    def _setup_free_return_with_active_rt(self, w2_amount):
        """FREE-tier return, no state add-ons, ACTIVE refund transfer.
        Total fees = 0 + 0 + 4000 = 4000."""
        from test_helpers import submit_review

        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("bnd1")
        )
        add_form(ret, "W2_WH", w2_amount)
        create_refund_transfer(ret, bank_partner_code="BANK_A")
        accept_disclosure(ret)
        submit_review(ret)
        return account, ret

    def test_refund_exactly_covers_fees_boundary(self, api):
        """PRD §3.6: "if refund transfer was elected, the refund must cover
        the fees — `federal_refund_cents` must be at least
        `total_fees_due_cents`, checked against the fully computed total, else
        `ERR_REFUND_INSUFFICIENT_FOR_FEES` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/refund_exactly_covers_fees_boundary
        """
        account, ret = self._setup_free_return_with_active_rt(4000)
        after = get_return(ret)
        assert after["total_fees_due_cents"] == 4000
        assert after["federal_refund_cents"] == 4000
        resp = api.file_return(
            ret.id, "hash-b", ret.version, make_taxpayer_headers(account["id"])
        )
        attempt = validate_success(resp, expected_status=201)
        assert attempt["outcome"] == "PENDING"
        assert get_return(ret)["status"] == "SUBMITTED"

    def test_refund_one_cent_below_fees_rejected(self, api):
        """PRD §3.6: "if refund transfer was elected, the refund must cover
        the fees — `federal_refund_cents` must be at least
        `total_fees_due_cents`, checked against the fully computed total, else
        `ERR_REFUND_INSUFFICIENT_FOR_FEES` (HTTP 402)."

        Design: Difficulty/boundary_precision_check/refund_exactly_covers_fees_boundary
        """
        account, ret = self._setup_free_return_with_active_rt(3999)
        resp = api.file_return(
            ret.id, "hash-c", ret.version, make_taxpayer_headers(account["id"])
        )
        validate_error(resp, ApiErrorId.ERR_REFUND_INSUFFICIENT_FOR_FEES)
        assert get_return(ret)["status"] == "READY_FOR_REVIEW"


class TestFeeConservation:
    def _setup_premier_return_with_pending_rt(self):
        """PREMIER return + CA state return + PENDING_DISCLOSURE agreement.
        Pre-cycle total = 12999 + 4999 = 17998."""
        from test_helpers import add_state_return

        account, ret = setup_return_with_forms(
            forms=("F1040", "SCH_D"),
            agi_cents=2000000,
            email=unique_email("inv1"),
            resolve_prompt="acknowledge",
        )
        add_state_return(ret, "CA")
        agreement = create_refund_transfer(ret, bank_partner_code="BANK_A")
        return account, ret, agreement

    def test_accept_void_cycle_restores_fee_total(self, api):
        """PRD §3.5: "Voiding unwinds the election. From `PENDING_DISCLOSURE`
        the void always succeeds; from `ACTIVE` it is refused while a filing
        attempt is in flight, rejected with `ERR_FILING_IN_FLIGHT` (HTTP 409).
        Either way the agreement lands in its terminal `VOIDED` status,
        `refund_transfer_selected` returns to false (a no-op if the election
        was never activated), and the service fee is removed from the total if
        it had been included."

        Design: Difficulty/compensating_invariant/fee_conservation_across_rt_accept_void_cycle
        """
        account, ret, agreement = self._setup_premier_return_with_pending_rt()
        assert get_return(ret)["total_fees_due_cents"] == 17998
        accept_disclosure(ret)
        assert get_return(ret)["total_fees_due_cents"] == 21998
        void_refund_transfer(ret)
        after = get_return(ret)
        assert after["total_fees_due_cents"] == 17998
        assert after["refund_transfer_selected"] is False
        agreements = list_refund_transfers(ret)
        assert agreements[0]["status"] == "VOIDED"

    def test_disclosure_acceptance_persists_after_void(self, api):
        """PRD §3.5: "The disclosure is a hard gate. Accepting it moves the
        agreement `PENDING_DISCLOSURE` → `ACTIVE` — allowed while the return
        is `DRAFT`, `AMENDED`, or `READY_FOR_REVIEW`, and rejected from any
        other status with `ERR_INVALID_STATE` — and produces three effects:
        the owning account's `disclosure_accepted_version` is set to the
        agreement's `disclosure_version`, the return's
        `refund_transfer_selected` flag becomes true (it is never set
        directly, only by acceptance), and the $40.00 service fee folds into
        `total_fees_due_cents`."

        Design: Difficulty/compensating_invariant/fee_conservation_across_rt_accept_void_cycle
        """
        account, ret, agreement = self._setup_premier_return_with_pending_rt()
        accept_disclosure(ret)
        void_refund_transfer(ret)
        account_data = validate_success(
            api.get_account(account["id"], TEST_USERS["platform_operator_headers"])
        )
        assert (
            account_data["disclosure_accepted_version"]
            == ACTIVE_BANK_DISCLOSURE_VERSION
        )


class TestBankPartnerRegistry:
    def test_unknown_bank_partner_rejected(self, api):
        """PRD §3.5: "Creating a `RefundTransferAgreement` on a return names a
        `bank_partner_code`, which must be one of the registered partners
        `BANK_A` or `BANK_B` — anything else is rejected with
        `ERR_BANK_PARTNER_NOT_FOUND` (HTTP 404)."

        Design: Corner/errors/unknown_bank_partner_rejected
        """
        account, ret = setup_return_with_forms(
            forms=("F1040",), email=unique_email("err1")
        )
        resp = api.create_refund_transfer(
            ret.id, "BANK_ZZZ", ret.version,
            make_taxpayer_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_BANK_PARTNER_NOT_FOUND)
