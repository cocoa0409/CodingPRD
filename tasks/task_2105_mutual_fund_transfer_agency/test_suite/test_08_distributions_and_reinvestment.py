"""Distribution declaration, the record step, payment and reinvestment cascades."""

from test_helpers import (
    ApiErrorId,
    assert_distribution,
    assert_distribution_payment,
    create_distribution_payload,
    ledger_entries_for_position,
    money,
    only_position,
    payment_for_account,
    payments_for_distribution,
    price,
    read_account,
    read_distribution,
    read_trade,
    read_share_class,
    set_clock,
    setup_declared_income_distribution_window,
    setup_recorded_reinvest_distribution,
    setup_reference_data,
    setup_three_holder_income_distribution,
    shares,
    pct,
    strike_nav,
    validate_error,
    validate_paginated,
    validate_success,
    MONDAY,
    SINGLE_TIER_BREAKPOINT_TIERS,
    TEST_USERS,
)

OPERATOR = TEST_USERS["operator_headers"]
ACCOUNTANT = TEST_USERS["accountant_headers"]


class TestDistributionPeriodOverlap:
    def test_a_declaration_whose_record_date_touches_an_existing_pay_date_is_refused(self, api):
        """PRD §3.7: "For a given share class and distribution type, the closed interval
        running from a new declaration's `record_date` through its `pay_date` inclusive may
        not intersect that of an existing declaration whose `status` is `DECLARED`,
        `RECORDED` or `PAID`."
        PRD §3.7: "Because both endpoints of that interval are inclusive, a new declaration
        whose `record_date` equals an existing declaration's `pay_date` *is* an intersection
        and is refused with `ERR_DISTRIBUTION_PERIOD_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/distribution_periods_are_closed_so_touching_endpoints_do_collide
        """
        setup = setup_declared_income_distribution_window()

        response = api.create_distribution(
            create_distribution_payload(
                setup["share_class"]["id"],
                distribution_type="ORDINARY_INCOME", rate_per_share=0.0500,
                record_date="2026-08-14", ex_date="2026-08-17", pay_date="2026-08-18",
            ),
            ACCOUNTANT,
        )
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_DISTRIBUTION_PERIOD_OVERLAP.value)

    def test_a_different_type_or_a_disjoint_period_is_accepted(self, api):
        """PRD §3.7: "For a given share class and distribution type, the closed interval
        running from a new declaration's `record_date` through its `pay_date` inclusive may
        not intersect that of an existing declaration whose `status` is `DECLARED`,
        `RECORDED` or `PAID`."
        PRD §3.7: "A new declaration begins `DECLARED` with `payment_count` at 0,
        `total_gross_amount`, `total_withholding_amount`, `total_cash_amount` and
        `total_reinvested_amount` all `0.00`, and `reinvest_nav_per_share` null."

        Design: Difficulty/resource_temporal_overlap/distribution_periods_are_closed_so_touching_endpoints_do_collide
        """
        setup = setup_declared_income_distribution_window()

        other_type = validate_success(
            api.create_distribution(
                create_distribution_payload(
                    setup["share_class"]["id"],
                    distribution_type="LONG_TERM_CAPITAL_GAIN", rate_per_share=0.2500,
                    record_date="2026-08-10", ex_date="2026-08-11", pay_date="2026-08-14",
                ),
                ACCOUNTANT,
            ),
            201,
        )
        assert_distribution(other_type)
        assert other_type["status"] == "DECLARED"

        disjoint = validate_success(
            api.create_distribution(
                create_distribution_payload(
                    setup["share_class"]["id"],
                    distribution_type="ORDINARY_INCOME", rate_per_share=0.0500,
                    record_date="2026-08-17", ex_date="2026-08-18", pay_date="2026-08-19",
                ),
                ACCOUNTANT,
            ),
            201,
        )
        assert disjoint["status"] == "DECLARED"

        _, meta = validate_paginated(
            api.list_share_class_distributions(setup["share_class"]["id"], ACCOUNTANT)
        )
        assert meta["total_count"] == 3


class TestRecordStepRounding:
    def test_each_payment_is_rounded_to_cents_before_the_totals_are_summed(self, api):
        """PRD §3.7: "Its `gross_amount` is `shares_of_record` multiplied by the
        distribution's `rate_per_share`, rounded half-up to cents *before* anything is
        summed."
        PRD §3.7: "The distribution's `payment_count` is the number of payment rows created,
        its `total_gross_amount` is the sum of the already-rounded per-payment `gross_amount`
        values, and its `total_withholding_amount` is the sum of the already-rounded
        per-payment `withholding_amount` values."
        PRD §3.7: "Its `withholding_amount` is backup withholding retained from the gross:
        when the owning account's `tin_certified` is false and its `registration_type` is not
        one of `IRA_TRADITIONAL`, `ROTH_IRA` or `UGMA_UTMA`, it is twenty-four percent of
        `gross_amount` rounded half-up to cents; in every other case — a certified account,
        or any of those three tax-advantaged registrations regardless of certification — it is
        `0.00`."

        Design: Difficulty/combinatorial_formula/distribution_rounds_each_payment_to_cents_before_summing_totals
        """
        setup = setup_three_holder_income_distribution()
        assert setup["nav_tuesday"]["nav_per_share"] == price(11.0000)

        set_clock("2026-08-04T17:00:00Z")
        recorded = validate_success(
            api.record_distribution(setup["distribution"]["id"], ACCOUNTANT), 200
        )
        assert recorded["status"] == "RECORDED"
        assert recorded["payment_count"] == 3

        first = payment_for_account(
            setup["distribution"]["id"], setup["reinvest_account"]["id"]
        )
        assert_distribution_payment(first)
        assert first["gross_amount"] == money(558.26)
        assert first["withholding_amount"] == money(0.00)

        second = payment_for_account(
            setup["distribution"]["id"], setup["cash_account"]["id"]
        )
        assert second["gross_amount"] == money(290.76)
        assert second["withholding_amount"] == money(0.00)

        third = payment_for_account(
            setup["distribution"]["id"], setup["uncertified_account"]["id"]
        )
        assert third["gross_amount"] == money(93.04)
        assert third["withholding_amount"] == money(22.33)

        assert recorded["total_gross_amount"] == money(942.06)
        assert recorded["total_gross_amount"] != money(942.07), (
            "summing unrounded products and rounding once is explicitly wrong"
        )
        assert recorded["total_withholding_amount"] == money(22.33)

    def test_payment_splits_cash_from_reinvestment_at_the_ex_date_price(self, api):
        """PRD §3.7: "On success the distribution moves `RECORDED → PAID`, that record's
        `nav_per_share` is stamped onto the distribution as `reinvest_nav_per_share`, and
        every payment moves `PENDING → PAID`."
        PRD §3.7: "A payment whose `payout_option` is `REINVEST` takes `reinvested_shares`
        as its `net_amount` divided by the reinvestment NAV, rounded half-up to three
        decimals, and leaves `cash_amount` at `0.00`; a `REINVESTMENT` order is created for
        it carrying `parent_distribution_id` pointing at the distribution, and that order is
        created already `PRICED_FINAL` on the pricing dimension and `SETTLED` on the
        settlement dimension in one step, with its identifier stamped onto the payment as
        `reinvestment_trade_id`."
        PRD §3.7: "The distribution's `total_cash_amount` is written as the sum of the
        per-payment `cash_amount` values, and its `total_reinvested_amount` as the sum of the
        `net_amount` values of the reinvesting payments."

        Design: Difficulty/combinatorial_formula/distribution_rounds_each_payment_to_cents_before_summing_totals
        """
        setup = setup_three_holder_income_distribution()

        set_clock("2026-08-04T17:00:00Z")
        validate_success(
            api.record_distribution(setup["distribution"]["id"], ACCOUNTANT), 200
        )
        set_clock("2026-08-05T10:00:00Z")
        paid = validate_success(
            api.pay_distribution(setup["distribution"]["id"], ACCOUNTANT), 200
        )

        assert paid["status"] == "PAID"
        assert paid["reinvest_nav_per_share"] == price(11.0000)
        assert paid["total_cash_amount"] == money(290.76)
        assert paid["total_reinvested_amount"] == money(628.97)

        first = payment_for_account(
            setup["distribution"]["id"], setup["reinvest_account"]["id"]
        )
        assert first["reinvested_shares"] == shares(50.751)

        third = payment_for_account(
            setup["distribution"]["id"], setup["uncertified_account"]["id"]
        )
        assert third["reinvested_shares"] == shares(6.428)

        total = (
            paid["total_cash_amount"]
            + paid["total_reinvested_amount"]
            + paid["total_withholding_amount"]
        )
        assert total == money(942.06)


class TestReinvestmentCascade:
    def test_paying_a_reinvesting_distribution_books_shares_to_the_ledger(self, api):
        """PRD §3.7: "Because that order settles, the position's `shares` and its
        `reinvested_shares` both increase by the payment's `reinvested_shares`, a ledger
        entry with an `entry_reason` of `DIVIDEND_REINVESTMENT` is appended, the position's
        `cost_basis_amount` increases by the payment's `net_amount`, and the class's
        `total_shares_outstanding` increases by the same share quantity."
        PRD §3.7: "A payment whose `payout_option` is `REINVEST` takes `reinvested_shares`
        as its `net_amount` divided by the reinvestment NAV, rounded half-up to three
        decimals, and leaves `cash_amount` at `0.00`; a `REINVESTMENT` order is created for
        it carrying `parent_distribution_id` pointing at the distribution, and that order is
        created already `PRICED_FINAL` on the pricing dimension and `SETTLED` on the
        settlement dimension in one step, with its identifier stamped onto the payment as
        `reinvestment_trade_id`."
        PRD §3.7: "Its `gross_amount` is `shares_of_record` multiplied by the
        distribution's `rate_per_share`, rounded half-up to cents *before* anything is
        summed."

        Design: Difficulty/transitive_cascade/distribution_pay_cascades_into_reinvestment_ledger_and_breakpoint_tier
        """
        setup = setup_recorded_reinvest_distribution()
        assert setup["nav_tuesday"]["nav_per_share"] == price(11.0000)

        validate_success(api.pay_distribution(setup["distribution"]["id"], ACCOUNTANT), 200)

        payment = payment_for_account(
            setup["distribution"]["id"], setup["account"]["id"]
        )
        assert payment["status"] == "PAID"
        assert payment["gross_amount"] == money(558.26)
        assert payment["net_amount"] == money(558.26)
        assert payment["reinvestment_trade_id"] is not None

        reinvestment = read_trade(payment["reinvestment_trade_id"])
        assert reinvestment["trade_type"] == "REINVESTMENT"
        assert reinvestment["parent_distribution_id"] == setup["distribution"]["id"]
        assert reinvestment["execution_status"] == "PRICED_FINAL"
        assert reinvestment["settlement_status"] == "SETTLED"
        assert reinvestment["nav_per_share_applied"] == price(11.0000)
        assert reinvestment["shares_transacted"] == shares(50.751)

        position = only_position(setup["account"]["id"])
        assert position["shares"] == shares(4574.751)
        assert position["reinvested_shares"] == shares(50.751)
        assert position["cost_basis_amount"] == money(48558.26)

        entries = [
            entry
            for entry in ledger_entries_for_position(position["id"])
            if entry["entry_reason"] == "DIVIDEND_REINVESTMENT"
        ]
        assert len(entries) == 1
        assert entries[0]["share_delta"] == shares(50.751)
        assert entries[0]["resulting_share_balance"] == shares(4574.751)

        assert read_share_class(setup["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(4574.751)

    def test_the_reinvestment_lifts_the_household_basis_into_the_next_breakpoint(self, api):
        """PRD §3.7: "Because those balances changed, each affected account's
        `household_basis_amount` is recomputed, and because that basis changed, every
        position of every affected household has its `current_roa_tier_pct` recomputed from
        its class's `breakpoint_tiers`."
        PRD §3.2: "The valuation date used is the `trade_date` of the trade being priced
        when the figure is computed for a pricing decision, and the current logical clock date
        whenever the field is recomputed outside a trade."
        PRD §3.7: "The distribution's `total_cash_amount` is written as the sum of the
        per-payment `cash_amount` values, and its `total_reinvested_amount` as the sum of the
        `net_amount` values of the reinvesting payments."

        Design: Difficulty/transitive_cascade/distribution_pay_cascades_into_reinvestment_ledger_and_breakpoint_tier
        """
        setup = setup_recorded_reinvest_distribution()
        assert setup["position"]["current_roa_tier_pct"] == pct(0.0575)

        paid = validate_success(
            api.pay_distribution(setup["distribution"]["id"], ACCOUNTANT), 200
        )

        account = read_account(setup["account"]["id"])
        assert account["household_basis_amount"] == money(50322.26)

        position = only_position(setup["account"]["id"])
        assert position["current_roa_tier_pct"] == pct(0.045)

        assert paid["total_gross_amount"] == money(558.26)
        assert paid["total_reinvested_amount"] == money(558.26)
        assert paid["total_cash_amount"] == money(0.00)


class TestRecordStepGuards:
    def test_recording_before_the_record_date_is_refused(self, api):
        """PRD §3.7: "Recording is the second step, again a `FundAccountant` action, and it
        is permitted only when the distribution is `DECLARED` and the logical clock date is
        on or after its `record_date`; otherwise it answers
        `ERR_INVALID_DISTRIBUTION_STATE`."

        Design: Corner/state_machines/distribution_record_before_the_record_date_returns_invalid_distribution_state
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        distribution = validate_success(
            api.create_distribution(
                create_distribution_payload(
                    base["share_class"]["id"],
                    distribution_type="SHORT_TERM_CAPITAL_GAIN", rate_per_share=0.0500,
                    record_date="2026-08-10", ex_date="2026-08-11", pay_date="2026-08-12",
                ),
                ACCOUNTANT,
            ),
            201,
        )

        response = api.record_distribution(distribution["id"], ACCOUNTANT)
        assert response.status_code == 409
        validate_error(response, ApiErrorId.ERR_INVALID_DISTRIBUTION_STATE.value)

        after = read_distribution(distribution["id"])
        assert after["status"] == "DECLARED"
        assert after["payment_count"] == 0
        assert after["total_gross_amount"] == money(0.00)

    def test_a_class_with_no_holders_records_and_pays_zero_payments(self, api):
        """PRD §3.7: "Recording moves the distribution `DECLARED → RECORDED` and freezes
        the holders of record by creating one **DistributionPayment** per eligible position.
        A position is eligible when its `share_class_id` matches the declaring class, its
        `shares` is greater than `0.000`, and its owning account's `status` is `ACTIVE` or
        `RESTRICTED`; eligible positions are processed in ascending `created_at` order."
        PRD §3.7: "On success the distribution moves `RECORDED → PAID`, that record's
        `nav_per_share` is stamped onto the distribution as `reinvest_nav_per_share`, and
        every payment moves `PENDING → PAID`."

        Design: Corner/calculations/distribution_with_no_eligible_positions_records_zero_payments
        """
        base = setup_reference_data(
            tiers=SINGLE_TIER_BREAKPOINT_TIERS, with_registration=False
        )
        strike_nav(base["share_class"]["id"], MONDAY, 0.00, finalize=True)
        distribution = validate_success(
            api.create_distribution(
                create_distribution_payload(
                    base["share_class"]["id"],
                    distribution_type="ORDINARY_INCOME", rate_per_share=0.5000,
                    record_date=MONDAY, ex_date=MONDAY, pay_date="2026-08-04",
                ),
                ACCOUNTANT,
            ),
            201,
        )

        validate_success(api.record_distribution(distribution["id"], ACCOUNTANT), 200)
        set_clock("2026-08-04T09:00:00Z")
        paid = validate_success(api.pay_distribution(distribution["id"], ACCOUNTANT), 200)

        assert paid["status"] == "PAID"
        assert paid["payment_count"] == 0
        assert paid["total_gross_amount"] == money(0.00)
        assert paid["total_withholding_amount"] == money(0.00)
        assert paid["total_cash_amount"] == money(0.00)
        assert paid["total_reinvested_amount"] == money(0.00)
        assert paid["reinvest_nav_per_share"] == price(10.0000)

        assert payments_for_distribution(distribution["id"]) == []
        assert read_share_class(base["share_class"]["id"])[
            "total_shares_outstanding"
        ] == shares(0.000)
