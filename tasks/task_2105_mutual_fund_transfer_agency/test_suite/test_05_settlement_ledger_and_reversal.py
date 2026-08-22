"""Settlement, the append-only share ledger, cancellation and reversal."""

from test_helpers import (
    ApiErrorId,
    assert_position,
    assert_share_ledger_entry,
    assert_trade_state,
    buy_and_settle,
    capture_purchase,
    ledger_entries_for_position,
    ledger_entries_for_trade,
    money,
    only_position,
    price,
    price_trade,
    read_account,
    read_registration,
    read_share_class,
    read_trade,
    settle_trade,
    setup_capacity_identity_desk,
    setup_settled_purchase,
    setup_trading_desk,
    setup_two_settled_purchases_same_class,
    shares,
    strike_nav,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TWO_TIER_BREAKPOINT_TIERS,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestParallelStatusDimensions:
    def test_pricing_and_settlement_advance_the_two_dimensions_separately(self, api):
        """PRD §3.6: "The two dimensions are genuinely independent, and the pair of them is
        the order's full state. An order can be `PRICED_FINAL` and `UNSETTLED`,
        `PRICED_FINAL` and `SETTLED`, or — after a material pricing correction — `RESTATED`
        and `SETTLED`."
        PRD §3.6: "A successful settlement moves the order `UNSETTLED → SETTLED` and carries
        out a chain of book entries."

        Design: Difficulty/non_linear_state_machine/trade_execution_and_settlement_dimensions_advance_independently
        """
        desk = setup_trading_desk(
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Zoe Parallel"},
        )
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 60000.00
        )

        priced = validate_success(api.price_trade(trade["id"], OPERATOR), 200)
        assert_trade_state(priced, "PRICED_FINAL", "UNSETTLED")
        assert priced["shares_transacted"] == shares(5730.000)

        settled = validate_success(api.settle_trade(trade["id"], OPERATOR), 200)
        assert_trade_state(settled, "PRICED_FINAL", "SETTLED")
        assert settled["shares_transacted"] == shares(5730.000)
        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(5730.000)

    def test_reversal_moves_only_the_settlement_dimension(self, api):
        """PRD §3.6: "Reversal is the settled counterpart and belongs to a
        `ComplianceOfficer`. It moves an order `SETTLED → REVERSED` and requires that the
        order is currently `SETTLED`, that its `trade_type` is not `REINVESTMENT` —
        reinvestment trades are unwound only through their parent distribution — and that
        the resulting position balance would not go negative."
        PRD §3.6: "The two dimensions are genuinely independent, and the pair of them is
        the order's full state. An order can be `PRICED_FINAL` and `UNSETTLED`,
        `PRICED_FINAL` and `SETTLED`, or — after a material pricing correction — `RESTATED`
        and `SETTLED`."

        Design: Difficulty/non_linear_state_machine/trade_execution_and_settlement_dimensions_advance_independently
        """
        desk = setup_settled_purchase(
            gross_amount=60000.00,
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Zoe Parallel"},
        )
        reversed_trade = validate_success(
            api.reverse_trade(
                desk["trade"]["id"],
                {"reversal_reason": "Dealer recall of the order"},
                COMPLIANCE,
            ),
            200,
        )
        assert_trade_state(reversed_trade, "PRICED_FINAL", "REVERSED")
        assert reversed_trade["execution_status"] != "CANCELLED"
        assert reversed_trade["shares_transacted"] == shares(5730.000)
        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(0.000)


class TestShareBalanceConservation:
    def test_reversing_one_leg_leaves_the_other_holders_balance_intact(self, api):
        """PRD §3.1: "Finally, every class carries `total_shares_outstanding`, a computed
        three-decimal share balance that begins at `0.000`, never goes negative, and always
        equals the sum of `shares` across every position held in that class."
        PRD §3.6: "Reversing a `PURCHASE` additionally decreases the position's
        `cost_basis_amount` by the order's `gross_amount` and decreases the registration's
        `consumed_amount` by the same amount; if that lifts `remaining_amount` above `0.00`
        while the registration was `EXHAUSTED`, it returns to `ACTIVE`."
        PRD §3.6: "A settling `PURCHASE` increases the position's `cost_basis_amount` by
        the order's `gross_amount`, and converts its state-registration hold into permanent
        use: the selected registration's `reserved_amount` decreases by `gross_amount` while
        its `consumed_amount` increases by the same figure."

        Design: Difficulty/compensating_invariant/trade_reversal_conserves_class_share_balance_against_ledger_sum
        """
        setup = setup_two_settled_purchases_same_class()
        share_class_id = setup["share_class"]["id"]

        before = read_share_class(share_class_id)
        assert before["total_shares_outstanding"] == shares(8086.250)

        validate_success(
            api.reverse_trade(
                setup["main_trade"]["id"],
                {"reversal_reason": "Order booked to the wrong registration"},
                COMPLIANCE,
            ),
            200,
        )
        after = read_share_class(share_class_id)
        assert after["total_shares_outstanding"] == shares(2356.250)

        main_position = only_position(setup["main_account"]["id"])
        assert main_position["shares"] == shares(0.000)
        assert main_position["cost_basis_amount"] == money(0.00)

        neighbour_position = only_position(setup["neighbour_account"]["id"])
        assert neighbour_position["shares"] == shares(2356.250)
        assert neighbour_position["cost_basis_amount"] == money(25000.00)

    def test_the_ledger_sum_reconciles_against_the_class_share_balance(self, api):
        """PRD §3.6: "A **ShareLedgerEntry** is appended recording the movement, with its
        `position_id` naming the position, its `trade_id` naming the order, its
        `share_delta` equal to the order's `shares_transacted`, its `effective_date` set to
        the order's `trade_date`, its `resulting_share_balance` set to the position's
        `shares` immediately after the entry was appended, and its `entry_reason` set to the
        cause of the movement."
        PRD §3.6: "The supplied `reversal_reason` is stamped onto the order, and a
        compensating ledger entry with an `entry_reason` of `TRADE_REVERSAL` and a
        `share_delta` equal to the negative of the order's `shares_transacted` is appended,
        so the position's `shares` and the class's `total_shares_outstanding` both move back
        by the same magnitude."

        Design: Difficulty/compensating_invariant/trade_reversal_conserves_class_share_balance_against_ledger_sum
        """
        setup = setup_two_settled_purchases_same_class()
        main_position = only_position(setup["main_account"]["id"])

        validate_success(
            api.reverse_trade(
                setup["main_trade"]["id"],
                {"reversal_reason": "Order booked to the wrong registration"},
                COMPLIANCE,
            ),
            200,
        )

        entries = ledger_entries_for_position(main_position["id"])
        assert len(entries) == 2, "one settlement entry and one compensating entry"
        by_reason = {entry["entry_reason"]: entry for entry in entries}
        assert set(by_reason) == {"PURCHASE_SETTLEMENT", "TRADE_REVERSAL"}
        assert by_reason["PURCHASE_SETTLEMENT"]["share_delta"] == shares(5730.000)
        assert by_reason["PURCHASE_SETTLEMENT"]["resulting_share_balance"] == shares(5730.000)
        assert by_reason["TRADE_REVERSAL"]["share_delta"] == shares(-5730.000)
        assert by_reason["TRADE_REVERSAL"]["resulting_share_balance"] == shares(0.000)

        neighbour_position = only_position(setup["neighbour_account"]["id"])
        all_entries = entries + ledger_entries_for_position(neighbour_position["id"])
        ledger_sum = sum(entry["share_delta"] for entry in all_entries)
        assert ledger_sum == shares(2356.250)
        assert read_share_class(setup["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(ledger_sum)

        settled_trade = read_trade(setup["main_trade"]["id"])
        assert_trade_state(settled_trade, "PRICED_FINAL", "REVERSED")


class TestPositionCreation:
    def test_a_position_row_appears_only_once_the_order_settles(self, api):
        """PRD §3.2: "Positions are never created directly by a client; the system creates
        one the first time a trade settles into that account-and-class pair, and a freshly
        created position starts with `shares` at `0.000`, `cost_basis_amount` at `0.00`,
        `reinvested_shares` at `0.000`, `avg_cost_per_share` at `0.0000`,
        `current_roa_tier_pct` at `0.0000`, `market_value_amount` at `0.00` and
        `first_purchase_date` null."
        PRD §3.2: "`avg_cost_per_share`, which is `cost_basis_amount` divided by `shares` to
        four decimal places and is `0.0000` whenever `shares` is `0.000`;
        `first_purchase_date`, the ISO `YYYY-MM-DD` trade date of the first settled purchase
        into the position, which drives contingent deferred sales charge aging and is null
        until that first purchase settles"

        Design: Corner/entities/position_row_appears_only_after_settlement
        """
        desk = setup_trading_desk(
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Quinn Position"},
        )
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 60000.00
        )
        price_trade(trade["id"])

        _, before = validate_paginated(
            api.list_account_positions(desk["account"]["id"], OPERATOR)
        )
        assert before["total_count"] == 0

        settle_trade(trade["id"])

        rows, after = validate_paginated(
            api.list_positions(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert after["total_count"] == 1
        position = rows[0]
        assert_position(position)
        assert position["shares"] == shares(5730.000)
        assert position["cost_basis_amount"] == money(60000.00)
        assert position["avg_cost_per_share"] == price(10.4712)
        assert position["first_purchase_date"] == MONDAY
        assert position["reinvested_shares"] == shares(0.000)


class TestShareLedgerImmutability:
    def test_a_rejected_repeat_settlement_appends_no_second_ledger_entry(self, api):
        """PRD §2.5: "A `ShareLedgerEntry` is the one exception. The share ledger is
        append-only: an entry is written once and never modified, so an entry carries only
        `id` and `created_at`. It has no `updated_at` field and no `version` field at all."
        PRD §3.6: "An order may settle only when its `execution_status` is `PRICED_FINAL`
        and its `settlement_status` is still `UNSETTLED`; an attempt from any other
        combination answers `ERR_INVALID_TRADE_STATE`, which is what blocks a provisionally
        priced order from reaching the books."

        Design: Corner/entities/share_ledger_entry_is_append_only_with_no_version_field_semantics
        """
        desk = setup_settled_purchase(
            gross_amount=60000.00,
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Lea Ledger"},
        )
        response = api.settle_trade(desk["trade"]["id"], OPERATOR)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_TRADE_STATE.value)

        rows, meta = validate_paginated(
            api.list_share_ledger_entries(
                OPERATOR, params={"trade_id": desk["trade"]["id"]}
            )
        )
        assert meta["total_count"] == 1
        entry = rows[0]
        assert_share_ledger_entry(entry)
        assert entry["share_delta"] == shares(5730.000)
        assert entry["entry_reason"] == "PURCHASE_SETTLEMENT"
        assert entry["resulting_share_balance"] == shares(5730.000)
        assert entry["effective_date"] == MONDAY


class TestTransitionGuards:
    def test_settling_a_provisionally_priced_order_is_refused(self, api):
        """PRD §3.6: "An order may settle only when its `execution_status` is
        `PRICED_FINAL` and its `settlement_status` is still `UNSETTLED`; an attempt from any
        other combination answers `ERR_INVALID_TRADE_STATE`, which is what blocks a
        provisionally priced order from reaching the books."
        PRD §3.5: "When the record is still `PRELIMINARY`, the order prices against the
        preliminary strike, `pricing_variant` is set to `PRELIMINARY_NAV`, and the order
        moves `RECEIVED → PRICED_PROVISIONAL`; provisional pricing touches no position and
        settlement remains blocked."

        Design: Corner/state_machines/settle_before_the_execution_dimension_is_final_returns_invalid_trade_state
        """
        desk = setup_trading_desk(
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            strike_seed_nav=False,
            account_overrides={"primary_owner_name": "Gus Provisional"},
        )
        strike_nav(desk["share_class"]["id"], MONDAY, 0.00, finalize=False)
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 60000.00
        )
        price_trade(trade["id"])

        response = api.settle_trade(trade["id"], OPERATOR)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_TRADE_STATE.value)

        after = read_trade(trade["id"])
        assert_trade_state(after, "PRICED_PROVISIONAL", "UNSETTLED")
        assert after["pricing_variant"] == "PRELIMINARY_NAV"
        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(0.000)

        _, meta = validate_paginated(
            api.list_positions(OPERATOR, params={"account_id": desk["account"]["id"]})
        )
        assert meta["total_count"] == 0

    def test_cancelling_an_already_settled_order_is_refused(self, api):
        """PRD §3.6: "Cancellation is available to a `TransferAgentOperator` from
        `RECEIVED → CANCELLED`, `PRICED_PROVISIONAL → CANCELLED` and
        `PRICED_FINAL → CANCELLED`, and to a `ComplianceOfficer` from
        `PENDING_AS_OF_APPROVAL → CANCELLED`; in every case the order's `settlement_status`
        must still be `UNSETTLED`, and the request supplies a `cancel_reason` that is
        stamped onto the order."
        PRD §2.7: "**Declared transition.** The target resource is in a state from which
        the requested transition is declared. The code names the resource whose state
        blocked the request: `ERR_INVALID_TRADE_STATE`, `ERR_INVALID_NAV_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_DISTRIBUTION_STATE`, `ERR_INVALID_PLAN_STATE`
        or `ERR_INVALID_RECONCILIATION_STATE`, each 409."

        Design: Corner/state_machines/cancel_after_settlement_returns_invalid_trade_state
        """
        desk = setup_capacity_identity_desk()
        trade = buy_and_settle(
            desk["account"]["id"], desk["share_class"]["id"], 20000.00
        )

        response = api.cancel_trade(
            trade["id"], {"cancel_reason": "Too late to cancel"}, OPERATOR
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_TRADE_STATE.value)

        after = read_trade(trade["id"])
        assert_trade_state(after, "PRICED_FINAL", "SETTLED")

        registration = read_registration(desk["registration"]["id"])
        assert registration["consumed_amount"] == money(20000.00)
        assert registration["remaining_amount"] == money(30000.00)

    def test_reversing_an_order_that_never_settled_is_refused(self, api):
        """PRD §3.6: "Reversal is the settled counterpart and belongs to a
        `ComplianceOfficer`. It moves an order `SETTLED → REVERSED` and requires that the
        order is currently `SETTLED`, that its `trade_type` is not `REINVESTMENT` —
        reinvestment trades are unwound only through their parent distribution — and that
        the resulting position balance would not go negative."
        PRD §2.7: "**Declared transition.** The target resource is in a state from which
        the requested transition is declared. The code names the resource whose state
        blocked the request: `ERR_INVALID_TRADE_STATE`, `ERR_INVALID_NAV_STATE`,
        `ERR_INVALID_CASE_STATE`, `ERR_INVALID_DISTRIBUTION_STATE`, `ERR_INVALID_PLAN_STATE`
        or `ERR_INVALID_RECONCILIATION_STATE`, each 409."

        Design: Corner/state_machines/reverse_an_unsettled_trade_returns_invalid_trade_state
        """
        desk = setup_trading_desk(
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Jo Unsettled"},
        )
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 60000.00
        )
        price_trade(trade["id"])

        response = api.reverse_trade(
            trade["id"], {"reversal_reason": "Nothing to reverse yet"}, COMPLIANCE
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_TRADE_STATE.value)

        after = read_trade(trade["id"])
        assert after["settlement_status"] == "UNSETTLED"
        assert after.get("reversal_reason") is None


class TestTradeListingAndImmediateConsistency:
    def test_the_settlement_filter_is_independent_of_the_execution_filter(self, api):
        """PRD §3.4: "Orders may be read individually and listed with narrowing by
        `account_id`, `share_class_id`, `exchange_target_share_class_id`,
        `parent_distribution_id`, `originating_plan_id`, `blue_sky_registration_id`,
        `execution_status`, `settlement_status`, `trade_date` or `trade_type`."
        PRD §3.6: "The two dimensions are genuinely independent, and the pair of them is
        the order's full state. An order can be `PRICED_FINAL` and `UNSETTLED`,
        `PRICED_FINAL` and `SETTLED`, or — after a material pricing correction — `RESTATED`
        and `SETTLED`."

        Design: Corner/endpoints/trade_listing_filters_on_the_settlement_dimension_independently
        """
        desk = setup_trading_desk(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Tara Lister"},
        )
        settled = buy_and_settle(
            desk["account"]["id"], desk["share_class"]["id"], 10000.00
        )
        unsettled = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 10000.00
        )
        price_trade(unsettled["id"])

        rows, settled_meta = validate_paginated(
            api.list_trades(
                OPERATOR,
                params={
                    "account_id": desk["account"]["id"],
                    "settlement_status": "SETTLED",
                },
            )
        )
        assert settled_meta["total_count"] == 1
        assert rows[0]["id"] == settled["id"]

        _, execution_meta = validate_paginated(
            api.list_trades(
                OPERATOR,
                params={
                    "account_id": desk["account"]["id"],
                    "execution_status": "PRICED_FINAL",
                },
            )
        )
        assert execution_meta["total_count"] == 2

        second = read_trade(unsettled["id"])
        assert_trade_state(second, "PRICED_FINAL", "UNSETTLED")

    def test_the_settle_response_already_carries_every_cascaded_value(self, api):
        """PRD §2.9: "Two properties hold throughout. First, cascades are immediate: by the
        time a request returns, every derived value it disturbed has been brought back into
        agreement, and a subsequent read observes the reconciled state."
        PRD §3.6: "The class's `total_shares_outstanding` then changes by the same
        `shares_transacted`."
        PRD §3.6: "A settling `PURCHASE` increases the position's `cost_basis_amount` by
        the order's `gross_amount`, and converts its state-registration hold into permanent
        use: the selected registration's `reserved_amount` decreases by `gross_amount` while
        its `consumed_amount` increases by the same figure."
        PRD §3.2: "The account's `household_basis_amount` is the rights-of-accumulation
        basis of that whole household, recomputed on every position change anywhere in the
        household — trade settlement, trade reversal, restatement following a NAV
        correction, distribution reinvestment and distribution reversal alike — and read
        whenever a purchase or an exchange is priced."

        Design: Corner/consistency_model/settlement_response_already_reflects_every_cascaded_field
        """
        desk = setup_trading_desk(
            tiers=TWO_TIER_BREAKPOINT_TIERS,
            account_overrides={"primary_owner_name": "Ivy Immediate"},
        )
        trade = capture_purchase(
            desk["account"]["id"], desk["share_class"]["id"], 60000.00
        )
        price_trade(trade["id"])

        settled = validate_success(api.settle_trade(trade["id"], OPERATOR), 200)
        assert settled["settlement_status"] == "SETTLED"
        assert settled["shares_transacted"] == shares(5730.000)

        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(5730.000)
        assert len(ledger_entries_for_trade(trade["id"])) == 1
        assert read_account(desk["account"]["id"])[
            "household_basis_amount"
        ] == money(57300.00)

        registration = read_registration(desk["registration"]["id"])
        assert registration["consumed_amount"] == money(60000.00)
        assert registration["reserved_amount"] == money(0.00)
