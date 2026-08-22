"""Redemption proceeds with contingent deferred sales charges, and exchange pricing."""

from test_helpers import (
    ApiErrorId,
    capture_purchase,
    capture_redemption,
    create_purchase_payload,
    money,
    only_position,
    position_for,
    price,
    price_trade,
    read_registration,
    read_share_class,
    settle_trade,
    setup_cdsc_position,
    setup_restricted_account_holding_shares,
    setup_same_fund_exchange,
    shares,
    pct,
    validate_error,
    validate_paginated,
    validate_success,
    TUESDAY,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
COMPLIANCE = TEST_USERS["compliance_headers"]


class TestContingentDeferredSalesCharge:
    def test_the_charge_applies_the_free_allowance_and_the_lower_of_cost_or_nav(self, api):
        """PRD §3.5: "Its `gross_proceeds_amount` is `shares_requested` multiplied by the
        applied NAV, rounded half-up to two decimals."
        PRD §3.5: "If the class does carry a contingent deferred sales charge, the holding
        period is the number of calendar days from the position's `first_purchase_date` to
        the order's `trade_date`, and the charge rate is one percent — `0.0100` — while the
        holding period is under 365 days, one half of one percent — `0.0050` — while it is
        at least 365 days and under 730 days, and zero — `0.0000` — from 730 days onward."
        PRD §3.5: "The free allowance is ten percent of the position's current `shares`,
        rounded half-up to three decimals."
        PRD §3.5: "`cdsc_amount` is then the chargeable quantity multiplied by the charge
        basis multiplied by the charge rate, with that whole product rounded half-up to two
        decimals exactly once, at the end."
        PRD §3.6: "A settling `REDEMPTION` reduces the position's `cost_basis_amount`
        proportionally — by the cost basis before the settlement multiplied by the
        `shares_requested` quantity divided by the share balance before the settlement,
        rounded half-up to two decimal places."
        PRD §3.2: "`avg_cost_per_share`, which is `cost_basis_amount` divided by `shares` to
        four decimal places and is `0.0000` whenever `shares` is `0.000`;
        `first_purchase_date`, the ISO `YYYY-MM-DD` trade date of the first settled purchase
        into the position, which drives contingent deferred sales charge aging and is null
        until that first purchase settles"

        Design: Corner/calculations/cdsc_charge_applies_free_allowance_reinvest_exclusion_and_lower_of_cost_or_nav
        """
        desk = setup_cdsc_position()
        assert desk["nav_wednesday"]["nav_per_share"] == price(12.0000)
        assert desk["purchase"]["sales_load_amount"] == money(0.00)
        assert desk["purchase"]["shares_transacted"] == shares(2000.000)

        redemption = capture_redemption(
            desk["account"]["id"], desk["share_class"]["id"], 500.000
        )
        priced = validate_success(api.price_trade(redemption["id"], OPERATOR), 200)

        assert priced["gross_proceeds_amount"] == money(6000.00)
        assert priced["cdsc_amount"] == money(30.00)
        assert priced["net_proceeds_amount"] == money(5970.00)
        assert priced["shares_transacted"] == shares(-500.000)

        settle_trade(redemption["id"])
        position = only_position(desk["account"]["id"])
        assert position["shares"] == shares(1500.000)
        assert position["cost_basis_amount"] == money(15000.00)
        assert position["avg_cost_per_share"] == price(10.0000)

        assert read_share_class(desk["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(1500.000)
        assert read_registration(desk["registration"]["id"])[
            "consumed_amount"
        ] == money(20000.00)


class TestExchangePricing:
    def test_an_exchange_inside_one_fund_carries_no_target_load(self, api):
        """PRD §3.5: "When the source and target classes belong to the same fund — that is,
        when the two classes carry the same `fund_id`, which is how a family's own share
        classes are grouped — the target load percentage is `0.0000` and the exchange is
        load-free."
        PRD §3.5: "`exchange_target_shares` is `gross_proceeds_amount` minus
        `sales_load_amount`, divided by the target class's NAV, rounded half-up to three
        decimals."
        PRD §3.6: "A settling `EXCHANGE` does double duty: the target position gains the
        order's `exchange_target_shares`, a second ledger entry with an `entry_reason` of
        `EXCHANGE_IN` is appended for that target position while the source movement carries
        `EXCHANGE_OUT`, and the target class's registration consumes the order's
        `gross_proceeds_amount` — this is the point at which an exchange finally touches
        state-registration capacity, since it reserved none at capture."

        Design: Corner/calculations/exchange_between_classes_of_the_same_fund_carries_no_sales_load
        """
        setup = setup_same_fund_exchange()
        assert setup["nav_target"]["nav_per_share"] == price(20.0000)

        exchange = validate_success(
            api.create_trade(
                {
                    "account_id": setup["account"]["id"],
                    "share_class_id": setup["source_class"]["id"],
                    "trade_type": "EXCHANGE",
                    "shares_requested": 1000.000,
                    "exchange_target_share_class_id": setup["target_class"]["id"],
                },
                OPERATOR,
            ),
            201,
        )
        priced = price_trade(exchange["id"])
        assert priced["gross_proceeds_amount"] == money(11000.00)
        assert priced["sales_load_pct"] == pct(0.0000)
        assert priced["sales_load_amount"] == money(0.00)
        assert priced["cdsc_amount"] == money(0.00)
        assert priced["net_proceeds_amount"] == money(11000.00)
        assert priced["exchange_target_shares"] == shares(550.000)
        assert priced["shares_transacted"] == shares(-1000.000)

        settle_trade(exchange["id"])

        source_position = position_for(
            setup["account"]["id"], setup["source_class"]["id"]
        )
        assert source_position["shares"] == shares(4730.000)

        target_position = position_for(
            setup["account"]["id"], setup["target_class"]["id"]
        )
        assert target_position["shares"] == shares(550.000)

        assert read_share_class(setup["source_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(4730.000)
        assert read_share_class(setup["target_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(550.000)
        assert read_registration(setup["target_registration"]["id"])[
            "consumed_amount"
        ] == money(11000.00)

        entries, meta = validate_paginated(
            api.list_share_ledger_entries(OPERATOR, params={"trade_id": exchange["id"]})
        )
        assert meta["total_count"] == 2
        assert {entry["entry_reason"] for entry in entries} == {
            "EXCHANGE_OUT", "EXCHANGE_IN",
        }


class TestRestrictedAccountDirectionality:
    def test_a_restricted_account_may_not_originate_a_purchase(self, api):
        """PRD §3.4: "The owning account must be `ACTIVE` or `RESTRICTED`, and a
        `PENDING_DOCS` or `CLOSED` account is refused with `ERR_ACCOUNT_NOT_ACTIVE`; a
        `RESTRICTED` account may redeem but a `PURCHASE` or `EXCHANGE` from it is refused
        with `ERR_ACCOUNT_RESTRICTED`."
        PRD §3.2: "A `ComplianceOfficer` may place a restriction, moving
        `ACTIVE → RESTRICTED`; the supplied `restriction_reason` is stamped onto the
        account, every systematic plan on the account that was `ACTIVE` moves to `SUSPENDED`
        with its `suspension_reason` set to `ACCOUNT_RESTRICTED`, and the account's
        `version` increments."

        Design: Difficulty/cross_entity_state_dependency/purchase_blocked_but_redemption_allowed_on_restricted_account
        """
        setup = setup_restricted_account_holding_shares()
        assert setup["account"]["status"] == "RESTRICTED"

        response = api.create_trade(
            create_purchase_payload(
                setup["account"]["id"], setup["share_class"]["id"], 1000.00
            ),
            OPERATOR,
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_ACCOUNT_RESTRICTED.value)

    def test_a_restricted_account_may_still_redeem(self, api):
        """PRD §3.2: "A `RESTRICTED` account may still redeem and still receives
        distributions, but it may not purchase or exchange."
        PRD §3.5: "`net_proceeds_amount` is `gross_proceeds_amount` minus `cdsc_amount`,
        and `shares_transacted` is the negative of `shares_requested`, because a redemption
        removes shares."
        PRD §3.4: "Reserved capacity is held for captured but not yet settled
        purchase-side dollars; consumed capacity is permanently used by settled
        purchase-side dollars. Redemptions never restore capacity."

        Design: Difficulty/cross_entity_state_dependency/purchase_blocked_but_redemption_allowed_on_restricted_account
        """
        setup = setup_restricted_account_holding_shares()

        response = api.create_trade(
            {
                "account_id": setup["account"]["id"],
                "share_class_id": setup["share_class"]["id"],
                "trade_type": "REDEMPTION",
                "shares_requested": 100.000,
            },
            OPERATOR,
        )
        redemption = validate_success(response, 201)
        assert redemption["execution_status"] == "RECEIVED"
        assert redemption["trade_date"] == TUESDAY

        priced = price_trade(redemption["id"])
        assert priced["gross_proceeds_amount"] == money(1100.00)
        assert priced["cdsc_amount"] == money(0.00)
        assert priced["net_proceeds_amount"] == money(1100.00)
        assert priced["shares_transacted"] == shares(-100.000)

        assert read_registration(setup["registration"]["id"])[
            "consumed_amount"
        ] == money(60000.00)
