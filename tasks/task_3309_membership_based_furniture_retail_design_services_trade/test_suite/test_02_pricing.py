"""Pricing engine: line pricing, promo interaction, totals, fee waiver, deposits."""
from test_helpers import (
    validate_success,
    get_success_data,
    assert_order,
    TEST_USERS,
    make_member_headers,
    make_trade_designer_headers,
    setup_gallery,
    setup_member,
    setup_product,
    setup_trade_account,
    verify_trade_account,
    create_retail_quote,
    create_member_quote,
    create_trade_quote,
    add_line,
    read_order,
    set_clock,
    run_daily_cycle,
    create_source_book_payload,
    extend_quote_via_consultation,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ASSOCIATE = TEST_USERS["gallery_associate_headers"]


class TestQuoteVsSettlementVariants:

    def test_quote_total_frozen_while_settlement_repriced_on_promo_release(self, api):
        """PRD §2.7: "an order in `QUOTE` keeps a `quote_total_cents` snapshot that is frozen at the moment the first line is added and never rewritten; the live `total_cents` keeps tracking current membership standing and the current promotional set, and the two may legitimately diverge (for example, when a source book releases between quoting and confirming)."
        PRD §3.4: "On success the pricing engine is re-run end to end with the member standing and promotional set as of confirm time — the final settlement variant, in which `total_cents` may diverge from the frozen `quote_total_cents`"

        Design: Difficulty/dual_variant_calc/quote_vs_settlement_repricing_on_promo_release
        """
        gallery = setup_gallery(name="Gallery A")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        # Extend the quote past the release instant so expiry does not gate
        # confirm (PRD §3.6: completion extends expiry by 14 days).
        extend_quote_via_consultation(order["id"], days=28)
        get_success_data(
            api.create_source_book(
                create_source_book_payload(
                    title="Fall Book", product_ids=[product["id"]],
                    print_ready_date="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert_order(confirmed)
        assert confirmed["quote_total_cents"] == 219900
        assert confirmed["total_cents"] == 199900
        assert confirmed["status"] == "READY_FOR_DELIVERY"

    def test_quote_total_still_frozen_when_confirm_matches_quote(self, api):
        """PRD §2.7: "an order in `QUOTE` keeps a `quote_total_cents` snapshot that is frozen at the moment the first line is added and never rewritten"
        PRD §3.4: "`total_cents` is `subtotal_cents` plus `white_glove_fee_cents`."

        Design: Difficulty/dual_variant_calc/quote_vs_settlement_repricing_on_promo_release
        """
        gallery = setup_gallery(name="Gallery A2")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert confirmed["quote_total_cents"] == 219900
        assert confirmed["total_cents"] == 219900
        assert confirmed["subtotal_cents"] == 200000
        assert confirmed["white_glove_fee_cents"] == 19900
        assert confirmed["status"] == "READY_FOR_DELIVERY"


class TestCustomDepositByTier:

    def test_member_custom_deposit_floor_binds(self, api):
        """PRD §3.4: "the line's `line_charged_cents` multiplied by the deposit rate — one-half for member and retail orders, one-quarter for trade orders — rounded half up to integer cents, then raised to a floor of 50000 cents ($500.00) for member and retail orders or 25000 cents ($250.00) for trade orders when the computed amount falls below it."
        PRD §3.4: "The order's `deposit_due_cents` is the sum of `deposit_cents` over its custom lines."

        Design: Difficulty/combinatorial_formula/custom_deposit_floor_and_rate_by_tier
        """
        gallery = setup_gallery(name="Gallery C")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        member = setup_member(email="m2@x.com", full_name="M Two")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)

        priced = read_order(order["id"])
        assert priced["subtotal_cents"] == 90000
        assert priced["deposit_due_cents"] == 50000

    def test_trade_custom_deposit_floor_binds(self, api):
        """PRD §3.4: "one-quarter for trade orders — rounded half up to integer cents, then raised to a floor of 50000 cents ($500.00) for member and retail orders or 25000 cents ($250.00) for trade orders when the computed amount falls below it."
        PRD §3.4: "For a `TRADE` order the promotional price is ignored entirely — the unit price is the base reduced by the account's trade discount (thirty percent for `TIER_1`, forty percent for `TIER_2`), rounded half up to integer cents."

        Design: Difficulty/combinatorial_formula/custom_deposit_floor_and_rate_by_tier
        """
        gallery = setup_gallery(name="Gallery C2")
        product = setup_product(list_price_cents=120000, line_kind="CUSTOM")
        account = setup_trade_account(email="t1@x.com", business_name="Design Co")
        verify_trade_account(account["id"], tier="TIER_2")
        headers = make_trade_designer_headers(account["id"])
        order = create_trade_quote(gallery["id"], account["id"])
        add_line(order["id"], product["id"], qty=1, headers=headers)

        priced = read_order(order["id"])
        assert priced["subtotal_cents"] == 72000
        assert priced["deposit_due_cents"] == 25000


class TestFeeWaiverEvaluationOrder:

    def test_fee_applies_below_threshold_then_waived_after_amendment(self, api):
        """PRD §3.4: "a `MEMBER` or `RETAIL` order pays 19900 cents, waived to zero when the subtotal reaches 1000000 cents ($10,000.00) or more."
        PRD §3.4: "Every line mutation — adding or removing a line — re-prices the whole order"

        Design: Difficulty/combinatorial_formula/evaluation_order_fee_waiver_subtotal_then_fee
        """
        gallery = setup_gallery(name="Gallery E")
        member = setup_member(email="m3@x.com", full_name="M Three")
        product = setup_product(list_price_cents=400000, line_kind="STOCK")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line = add_line(order["id"], product["id"], qty=3, headers=headers)

        first = read_order(order["id"])
        assert first["total_cents"] == 919900
        assert first["white_glove_fee_cents"] == 19900
        assert first["quote_total_cents"] == 919900

        get_success_data(api.remove_order_line(order["id"], line["id"], {}, headers))
        add_line(order["id"], product["id"], qty=4, headers=headers)

        second = read_order(order["id"])
        assert second["white_glove_fee_cents"] == 0
        assert second["total_cents"] == 1200000
        assert second["quote_total_cents"] == 919900

    def test_quote_with_no_lines_carries_zero_fee(self, api):
        """PRD §3.4: "An order in `QUOTE` with no lines carries a fee of zero."
        PRD §3.4: "all of its computed money fields — `quote_total_cents`, `subtotal_cents`, `white_glove_fee_cents`, `total_cents`, `deposit_due_cents`, `deposit_paid_cents`, `cancel_refund_cents` — start at zero"

        Design: Difficulty/combinatorial_formula/evaluation_order_fee_waiver_subtotal_then_fee
        """
        gallery = setup_gallery(name="Gallery E2")
        order = create_retail_quote(gallery["id"])
        assert order["white_glove_fee_cents"] == 0
        assert order["subtotal_cents"] == 0
        assert order["total_cents"] == 0


class TestFeeWaiverThresholdBoundary:

    def test_subtotal_exactly_at_threshold_waives_fee(self, api):
        """PRD §3.4: "a `MEMBER` or `RETAIL` order pays 19900 cents, waived to zero when the subtotal reaches 1000000 cents ($10,000.00) or more."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_exact_vs_below
        """
        gallery = setup_gallery(name="Gallery K")
        product = setup_product(list_price_cents=1000000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert confirmed["white_glove_fee_cents"] == 0
        assert confirmed["total_cents"] == 1000000

    def test_subtotal_one_cent_below_threshold_charges_fee(self, api):
        """PRD §3.4: "a `MEMBER` or `RETAIL` order pays 19900 cents, waived to zero when the subtotal reaches 1000000 cents ($10,000.00) or more."

        Design: Difficulty/boundary_precision_check/fee_waiver_threshold_exact_vs_below
        """
        gallery = setup_gallery(name="Gallery K2")
        product = setup_product(list_price_cents=999999, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert confirmed["white_glove_fee_cents"] == 19900
        assert confirmed["total_cents"] == 1019899


class TestPromoAndTrackInteraction:

    def test_promo_stacks_member_discount_multiplicatively(self, api):
        """PRD §3.4: "Compute the promotional price: if the product's `promo_active` is currently true, the base reduced by ten percent, rounded half up to integer cents; otherwise the base itself."
        PRD §3.4: "For a `MEMBER` order the unit price is the promotional price reduced by twenty-five percent, rounded half up to integer cents."

        Design: Corner/calculations/promo_stacks_member_discount_multiplicatively
        """
        gallery = setup_gallery(name="Gallery C1")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        get_success_data(
            api.create_source_book(
                create_source_book_payload(
                    title="Book C1", product_ids=[product["id"]],
                    print_ready_date="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()
        member = setup_member(email="c3@x.com", full_name="C Three")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line = add_line(order["id"], product["id"], qty=1, headers=headers)

        assert line["line_charged_cents"] == 135000
        priced = read_order(order["id"])
        assert priced["subtotal_cents"] == 135000
        assert priced["white_glove_fee_cents"] == 19900
        assert priced["total_cents"] == 154900

    def test_trade_price_excludes_promo(self, api):
        """PRD §3.4: "For a `TRADE` order the promotional price is ignored entirely — the unit price is the base reduced by the account's trade discount (thirty percent for `TIER_1`, forty percent for `TIER_2`), rounded half up to integer cents."
        PRD §3.4: "a `TRADE` order always pays a fee of 14900 cents with no waiver"

        Design: Corner/calculations/trade_price_excludes_promo
        """
        gallery = setup_gallery(name="Gallery C2")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        get_success_data(
            api.create_source_book(
                create_source_book_payload(
                    title="Book C2", product_ids=[product["id"]],
                    print_ready_date="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()
        account = setup_trade_account(email="c4@x.com", business_name="C4 Design")
        verify_trade_account(account["id"], tier="TIER_1")
        headers = make_trade_designer_headers(account["id"])
        order = create_trade_quote(gallery["id"], account["id"])
        line = add_line(order["id"], product["id"], qty=1, headers=headers)

        assert line["line_charged_cents"] == 140000
        priced = read_order(order["id"])
        assert priced["white_glove_fee_cents"] == 14900
        assert priced["total_cents"] == 154900

    def test_premium_fabric_multiplier_applies_before_discount(self, api):
        """PRD §3.4: "At creation the line snapshots `unit_list_price_cents`: the product's current `list_price_cents`, multiplied by 1.25 when the line is a `CUSTOM` line with `fabric_tier` `PREMIUM`."
        PRD §3.4: "For a `MEMBER` order the unit price is the promotional price reduced by twenty-five percent, rounded half up to integer cents."
        PRD §3.4: "the line's `line_charged_cents` multiplied by the deposit rate — one-half for member and retail orders, one-quarter for trade orders — rounded half up to integer cents, then raised to a floor of 50000 cents ($500.00) for member and retail orders or 25000 cents ($250.00) for trade orders when the computed amount falls below it."

        Design: Corner/calculations/premium_fabric_multiplier_applies_before_discount
        """
        gallery = setup_gallery(name="Gallery C3")
        member = setup_member(email="c5@x.com", full_name="C Five")
        product = setup_product(list_price_cents=100000, line_kind="CUSTOM")
        headers = make_member_headers(member["id"])
        order = create_member_quote(gallery["id"], member["id"])
        line = add_line(order["id"], product["id"], qty=1, fabric_tier="PREMIUM",
                        headers=headers)

        assert line["unit_list_price_cents"] == 125000
        assert line["line_charged_cents"] == 93750
        assert line["deposit_cents"] == 50000


class TestSourceBookReleaseCascade:

    def test_release_flips_promo_and_reprices_quote(self, api):
        """PRD §3.3: "Then (hop 2) every product listed in the newly released edition's `product_ids` has `promo_active` set to true."
        PRD §3.3: "Finally (hop 3), every order still in `QUOTE` that contains a product whose `promo_active` flag just changed — in either direction — is re-priced end to end: per-line pricing and the order total are recomputed against the new promotional set, with `quote_total_cents` again left frozen."

        Design: Difficulty/transitive_cascade/sourcebook_release_promo_repricing_cascade
        """
        gallery = setup_gallery(name="Gallery H")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)
        get_success_data(
            api.create_source_book(
                create_source_book_payload(
                    title="Winter Book", product_ids=[product["id"]],
                    print_ready_date="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()

        product_after = get_success_data(api.get_product(product["id"], ADMIN))
        assert product_after["promo_active"] is True

        order_after = read_order(order["id"])
        assert order_after["total_cents"] == 199900
        assert order_after["quote_total_cents"] == 219900

    def test_quote_unaffected_by_release_keeps_price(self, api):
        """PRD §3.3: "every order still in `QUOTE` that contains a product whose `promo_active` flag just changed — in either direction — is re-priced end to end"

        Design: Difficulty/transitive_cascade/sourcebook_release_promo_repricing_cascade
        """
        gallery = setup_gallery(name="Gallery H2")
        promo_product = setup_product(list_price_cents=200000, line_kind="STOCK")
        plain_product = setup_product(list_price_cents=100000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], plain_product["id"], qty=1)
        get_success_data(
            api.create_source_book(
                create_source_book_payload(
                    title="Winter Book 2", product_ids=[promo_product["id"]],
                    print_ready_date="2026-09-01T00:00:00Z",
                ),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()

        order_after = read_order(order["id"])
        assert order_after["subtotal_cents"] == 100000
        assert order_after["total_cents"] == 119900

    def test_second_release_archives_first_and_flips_promos(self, api):
        """PRD §3.3: "Because only one edition is ever current, any other edition in `RELEASED` moves to `ARCHIVED` at the same moment (Cascade B's archival hop): every product in the archived edition that is not also in the newly released edition has its `promo_active` set back to false."
        PRD §3.3: "Then (hop 2) every product listed in the newly released edition's `product_ids` has `promo_active` set to true."

        Design: Corner/cross_cutting_layers/second_sourcebook_release_archives_first
        """
        p1 = setup_product(list_price_cents=10000, line_kind="STOCK")
        p2 = setup_product(list_price_cents=10000, line_kind="STOCK")
        get_success_data(
            api.create_source_book(
                create_source_book_payload(title="SB1", product_ids=[p1["id"]],
                                           print_ready_date="2026-09-01T00:00:00Z"),
                ADMIN,
            )
        )
        set_clock("2026-09-22T00:00:00Z")
        run_daily_cycle()
        get_success_data(
            api.create_source_book(
                create_source_book_payload(title="SB2", product_ids=[p2["id"]],
                                           print_ready_date="2026-09-02T00:00:00Z"),
                ADMIN,
            )
        )
        set_clock("2026-09-23T00:00:00Z")
        run_daily_cycle()

        assert get_success_data(api.get_product(p1["id"], ADMIN))["promo_active"] is False
        assert get_success_data(api.get_product(p2["id"], ADMIN))["promo_active"] is True


class TestConfirmConsistency:

    def test_confirm_response_reflects_final_totals_immediately(self, api):
        """PRD §2.2: "Unless otherwise noted, operations that create or modify a resource will return the created or updated resource object in the data field."
        PRD §3.4: "`total_cents` is `subtotal_cents` plus `white_glove_fee_cents`."
        PRD §3.4: "an order with no custom lines at all skips that state and lands directly in `READY_FOR_DELIVERY`, since nothing stands between it and delivery scheduling."

        Design: Corner/consistency_model/confirm_response_reflects_final_totals_immediately
        """
        gallery = setup_gallery(name="Gallery S1")
        product = setup_product(list_price_cents=200000, line_kind="STOCK")
        order = create_retail_quote(gallery["id"])
        add_line(order["id"], product["id"], qty=1)

        confirmed = validate_success(api.confirm_order(order["id"], {}, ASSOCIATE))
        assert_order(confirmed)
        assert confirmed["subtotal_cents"] == 200000
        assert confirmed["white_glove_fee_cents"] == 19900
        assert confirmed["total_cents"] == 219900
        assert confirmed["status"] == "READY_FOR_DELIVERY"
