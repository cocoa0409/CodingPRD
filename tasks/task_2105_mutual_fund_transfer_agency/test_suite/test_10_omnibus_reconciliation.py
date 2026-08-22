"""Dealer activity reconciliation: the break, its tolerance and its disposition."""

from test_helpers import (
    ApiErrorId,
    assert_omnibus_reconciliation,
    create_omnibus_reconciliation_payload,
    money,
    open_active_account,
    read_reconciliation,
    setup_matched_reconciliation_with_unsettled_trade,
    setup_omnibus_account_with_settled_activity,
    setup_omnibus_break_identified,
    set_clock,
    shares,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
DEALER = TEST_USERS["dealer_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]

CLOCK_MONDAY = "2026-08-03T09:00:00Z"


class TestBreakClassification:
    def test_a_break_inside_the_tolerance_is_matched_and_one_beyond_it_is_not(self, api):
        """PRD §3.10: "The transfer agent's net is `ta_purchase_amount` minus
        `ta_redemption_amount`; the dealer's net is `dealer_reported_purchase_amount` minus
        `dealer_reported_redemption_amount`; and `break_amount` is the agent's net minus the
        dealer's net, rounded half-up to two decimals, so its sign says which side is
        claiming more."
        PRD §3.10: "The `tolerance_amount` applied to it is the greater of a floor of one
        dollar and one basis point of the dealer's gross activity — that is,
        `dealer_reported_purchase_amount` plus `dealer_reported_redemption_amount`,
        multiplied by `0.0001` and rounded half-up to two decimals."
        PRD §3.10: "The reconciliation is created directly in one of two states: `MATCHED`
        when the absolute value of `break_amount` is less than or equal to
        `tolerance_amount`, and `BREAK_IDENTIFIED` when it is strictly greater. The
        comparison is inclusive, so a break exactly equal to the tolerance is `MATCHED`."

        Design: Corner/calculations/omnibus_tolerance_is_inclusive_so_a_break_inside_it_is_matched
        """
        setup = setup_omnibus_account_with_settled_activity()
        assert setup["purchase"]["shares_transacted"] == shares(2827.500)
        assert setup["redemption"]["gross_proceeds_amount"] == money(1000.00)

        matched = validate_success(
            api.create_omnibus_reconciliation(
                create_omnibus_reconciliation_payload(
                    setup["account"]["id"], MONDAY, 29998.00, 1000.00, 2727.500
                ),
                DEALER,
            ),
            201,
        )
        assert_omnibus_reconciliation(matched)
        assert matched["ta_purchase_amount"] == money(30000.00)
        assert matched["ta_redemption_amount"] == money(1000.00)
        assert matched["ta_net_shares"] == shares(2727.500)
        assert matched["break_amount"] == money(2.00)
        assert matched["tolerance_amount"] == money(3.10)
        assert matched["status"] == "MATCHED"

        broken = validate_success(
            api.create_omnibus_reconciliation(
                create_omnibus_reconciliation_payload(
                    setup["account"]["id"], MONDAY, 29995.00, 1000.00, 2727.500
                ),
                DEALER,
            ),
            201,
        )
        assert broken["break_amount"] == money(5.00)
        assert broken["tolerance_amount"] == money(3.10)
        assert broken["status"] == "BREAK_IDENTIFIED"


class TestBreakDisposition:
    def test_citing_a_trade_whose_magnitude_differs_from_the_break_is_refused(self, api):
        """PRD §3.10: "The cited order must exist, must belong to the same account, must
        carry a `trade_date` equal to the reconciliation's `as_of_date`, must have a
        `settlement_status` of `SETTLED`, and its booked dollar magnitude must equal the
        absolute value of `break_amount`; any of those failing is refused with
        `ERR_ADJUSTMENT_MISMATCH`."

        Design: Corner/errors/adjustment_trade_amount_mismatch_returns_adjustment_mismatch
        """
        setup = setup_omnibus_break_identified()
        assert setup["reconciliation"]["break_amount"] == money(5.00)
        assert setup["reconciliation"]["tolerance_amount"] == money(3.00)
        assert setup["reconciliation"]["status"] == "BREAK_IDENTIFIED"

        response = api.adjust_omnibus_reconciliation(
            setup["reconciliation"]["id"],
            {
                "adjustment_trade_id": setup["purchase"]["id"],
                "resolution_note": "Pointing at the wrong trade on purpose",
            },
            COMPLIANCE,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_ADJUSTMENT_MISMATCH.value)

        after = read_reconciliation(setup["reconciliation"]["id"])
        assert after["status"] == "BREAK_IDENTIFIED"
        assert after.get("adjustment_trade_id") is None

    def test_adjusting_a_matched_reconciliation_is_refused(self, api):
        """PRD §3.10: "A `MATCHED` reconciliation is finished on arrival. A
        `BREAK_IDENTIFIED` one must be dispositioned by a `ComplianceOfficer`, in one of two
        ways, and both require the reconciliation to be `BREAK_IDENTIFIED` — any other state
        answers `ERR_INVALID_RECONCILIATION_STATE`."
        PRD §3.10: "Orders still `UNSETTLED`, or `CANCELLED`, or `REVERSED` are excluded,
        and `REINVESTMENT` and `EXCHANGE` orders are excluded from both dollar sums
        entirely."

        Design: Corner/state_machines/adjust_a_matched_reconciliation_returns_invalid_reconciliation_state
        """
        setup = setup_matched_reconciliation_with_unsettled_trade()
        assert setup["trade"]["settlement_status"] == "UNSETTLED"

        reconciliation = setup["reconciliation"]
        assert reconciliation["ta_purchase_amount"] == money(0.00)
        assert reconciliation["break_amount"] == money(0.00)
        assert reconciliation["tolerance_amount"] == money(1.00)
        assert reconciliation["status"] == "MATCHED"

        response = api.adjust_omnibus_reconciliation(
            reconciliation["id"],
            {
                "adjustment_trade_id": setup["trade"]["id"],
                "resolution_note": "Nothing to adjust",
            },
            COMPLIANCE,
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_RECONCILIATION_STATE.value)

        after = read_reconciliation(reconciliation["id"])
        assert after.get("adjustment_trade_id") is None


class TestReconciliationChannelGuard:
    def test_a_direct_channel_account_cannot_be_reconciled(self, api):
        """PRD §3.10: "An **OmnibusReconciliation** is filed by a `TransferAgentOperator`
        or by `DealerOperations` against an `account_id` whose `account_channel` is
        `NETWORKED` or `OMNIBUS`; filing one against a `DIRECT` account is refused with
        `ERR_RECON_CHANNEL_INVALID`."

        Design: Corner/errors/reconciliation_on_a_direct_channel_account_returns_recon_channel_invalid
        """
        set_clock(CLOCK_MONDAY)
        account = open_active_account(
            account_channel="DIRECT", state_code="CA", primary_owner_name="Dana Direct"
        )

        response = api.create_omnibus_reconciliation(
            create_omnibus_reconciliation_payload(
                account["id"], MONDAY, 0.00, 0.00, 0.000
            ),
            OPERATOR,
        )
        assert response.status_code == 422
        validate_error(response, ApiErrorId.ERR_RECON_CHANNEL_INVALID.value)

        _, meta = validate_paginated(
            api.list_omnibus_reconciliations(
                OPERATOR, params={"account_id": account["id"]}
            )
        )
        assert meta["total_count"] == 0
