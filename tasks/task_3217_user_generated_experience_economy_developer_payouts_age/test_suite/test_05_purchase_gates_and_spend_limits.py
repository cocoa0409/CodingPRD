"""Purchase-order confirmation gates: cross-entity state (item ON_SALE), the
parental monthly spend limit (strict >= rejection), the calendar-month window,
and the safety-before-fiscal validation order (PRD §2.5, §2.8, §3.7)."""
from test_helpers import (
    ApiErrorId,
    create_on_sale_item,
    create_parental_controls_payload,
    create_purchase_order_payload,
    create_user,
    fund_user,
    get_user,
    make_creator_headers,
    set_clock,
    setup_parent_child,
    validate_error,
    validate_success,
)


class TestItemNotOnSaleGate:
    def test_purchase_order_confirm_gated_on_marketplace_item_on_sale(self, api):
        """PRD §3.7: "For a marketplace item, the item must be `ON_SALE`, else
        `ERR_ITEM_NOT_ON_SALE`."

        Design: Difficulty/cross_entity_state_dependency/purchase_order_confirm_gated_on_marketplace_item_on_sale
        """
        set_clock()
        seller = create_user(username="s_i", email="s_i@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_i", email="b_i@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap", price_robux=100)
        fund_user(buyer["id"], 700)  # 700c -> 560 Robux

        buyer_headers = make_creator_headers(buyer["id"])
        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 100),
                buyer_headers,
            ),
            201,
        )
        # Seller takes the item off sale between create and confirm.
        validate_success(
            api.take_item_off_sale(item["id"], make_creator_headers(seller["id"])), 200
        )

        resp = api.confirm_purchase_order(po["id"], buyer_headers)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ON_SALE)

        stale = validate_success(api.get_purchase_order(po["id"], buyer_headers), 200)
        assert stale["status"] == "PENDING", (
            f"failed confirm must leave the order PENDING, got {stale['status']}"
        )
        assert get_user(buyer["id"])["robux_balance"] == 560, "buyer balance must be unchanged"
        item_now = validate_success(api.get_marketplace_item(item["id"], buyer_headers), 200)
        assert item_now["status"] == "OFF_SALE"

    def test_purchase_confirm_succeeds_when_item_back_on_sale(self, api):
        """PRD §3.7: "For a marketplace item, the item must be `ON_SALE`, else
        `ERR_ITEM_NOT_ON_SALE`."
        PRD §3.6: "later put it back on sale, returning it from `OFF_SALE` to
        `ON_SALE`"

        Design: Difficulty/cross_entity_state_dependency/purchase_order_confirm_gated_on_marketplace_item_on_sale
        """
        set_clock()
        seller = create_user(username="s_i2", email="s_i2@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="b_i2", email="b_i2@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap Two", price_robux=100)
        fund_user(buyer["id"], 700)

        seller_headers = make_creator_headers(seller["id"])
        buyer_headers = make_creator_headers(buyer["id"])
        validate_success(api.take_item_off_sale(item["id"], seller_headers), 200)
        validate_success(api.put_item_on_sale(item["id"], seller_headers), 200)

        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 100),
                buyer_headers,
            ),
            201,
        )
        completed = validate_success(api.confirm_purchase_order(po["id"], buyer_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert get_user(buyer["id"])["robux_balance"] == 460


class TestParentalSpendLimitBoundary:
    def test_parental_spend_limit_exactly_at_limit_rejected(self, api):
        """PRD §3.7: "If the buyer has parental controls with a
        `monthly_spend_limit_robux` set, the sum of this purchase's `price_robux` plus
        every `COMPLETED` purchase's `price_robux` in the current UTC calendar month
        (from the first instant of the month through now) must stay strictly below the
        limit: reaching the limit exactly is rejected, because the comparison includes
        equality — a purchase that would bring the month's total to precisely the cap
        fails with `ERR_PARENTAL_SPEND_LIMIT`, the opposite of the usual "at the cap is
        fine" convention, and this strictness is deliberate."

        Design: Difficulty/boundary_precision_check/parental_spend_limit_exactly_at_limit_rejected
        """
        set_clock()
        parent, child, _pc = setup_parent_child(spend_limit=200, chat_mode="FILTERED")
        seller = create_user(username="seller_g", email="s_g@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Big Hat", price_robux=200)
        _order, credited = fund_user(child["id"], 1500)  # -> 1250 Robux
        assert credited == 1250

        child_headers = make_creator_headers(child["id"])
        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 200),
                child_headers,
            ),
            201,
        )
        # 0 spent so far + 200 = 200 >= 200 -> rejected at exactly the limit.
        resp = api.confirm_purchase_order(po["id"], child_headers)
        validate_error(resp, ApiErrorId.ERR_PARENTAL_SPEND_LIMIT)

        stale = validate_success(api.get_purchase_order(po["id"], child_headers), 200)
        assert stale["status"] == "PENDING", (
            f"rejected confirm must leave the order PENDING, got {stale['status']}"
        )
        assert get_user(child["id"])["robux_balance"] == 1250, "balance must be unchanged"

    def test_parental_spend_limit_one_robux_below_limit_accepted(self, api):
        """PRD §3.7: "the sum of this purchase's `price_robux` plus every `COMPLETED`
        purchase's `price_robux` in the current UTC calendar month (from the first
        instant of the month through now) must stay strictly below the limit: reaching
        the limit exactly is rejected, because the comparison includes equality"

        Design: Difficulty/boundary_precision_check/parental_spend_limit_exactly_at_limit_rejected
        """
        set_clock()
        parent, child, _pc = setup_parent_child(spend_limit=200, chat_mode="FILTERED")
        seller = create_user(username="seller_b", email="s_b@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Small Hat", price_robux=199)
        fund_user(child["id"], 1500)

        child_headers = make_creator_headers(child["id"])
        po1 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 199),
                child_headers,
            ),
            201,
        )
        # 0 + 199 = 199 < 200 -> accepted.
        completed = validate_success(api.confirm_purchase_order(po1["id"], child_headers), 200)
        assert completed["status"] == "COMPLETED"

        # 199 + 1 = 200 >= 200 -> the next single Robux hits the strict cap.
        po2 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 1),
                child_headers,
            ),
            201,
        )
        resp = api.confirm_purchase_order(po2["id"], child_headers)
        validate_error(resp, ApiErrorId.ERR_PARENTAL_SPEND_LIMIT)


class TestSafetyBeatsFiscal:
    def test_safety_vs_fiscal_on_purchase_confirm(self, api):
        """PRD §2.5: "Safety checks deliberately precede all other business checks, so
        a minor who is simultaneously over their spend limit and short of funds sees
        the safety error, not the fiscal one."
        PRD §2.5: "A request violating both a safety rule and a fiscal rule always
        reports the safety error."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_purchase_confirm
        """
        set_clock()
        parent, child, _pc = setup_parent_child(spend_limit=400, chat_mode="FILTERED")
        seller = create_user(username="seller_e", email="sel_e@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Hat", price_robux=100)
        fund_user(child["id"], 500)  # 500c -> 400 Robux

        child_headers = make_creator_headers(child["id"])
        # First purchase: 350 Robux -> month total 350 < 400, balance drops to 50.
        po1 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 350),
                child_headers,
            ),
            201,
        )
        validate_success(api.confirm_purchase_order(po1["id"], child_headers), 200)
        assert get_user(child["id"])["robux_balance"] == 50

        # Second purchase of 60: month total 350+60=410 >= 400 (safety failure) AND
        # balance 50 < 60 (fiscal failure). The safety error must win.
        po2 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 60),
                child_headers,
            ),
            201,
        )
        resp = api.confirm_purchase_order(po2["id"], child_headers)
        err = validate_error(resp, ApiErrorId.ERR_PARENTAL_SPEND_LIMIT)
        assert resp.status_code == 403
        assert err["error_id"] != ApiErrorId.ERR_INSUFFICIENT_ROBUX

    def test_fiscal_only_failure_reports_insufficient_robux(self, api):
        """PRD §3.7: "The buyer's `robux_balance` must cover `price_robux`, else
        `ERR_INSUFFICIENT_ROBUX`."
        PRD §3.7: "It may never go negative — any debit that would drive it below zero
        is rejected with `ERR_INSUFFICIENT_ROBUX`."

        Design: Difficulty/priority_pair_validation_conflict/safety_vs_fiscal_on_purchase_confirm
        """
        set_clock()
        seller = create_user(username="seller_f", email="sel_f@x.com", date_of_birth="1990-01-01")
        buyer = create_user(username="buyer_f", email="b_f@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Hat F", price_robux=100)
        fund_user(buyer["id"], 500)  # 400 Robux

        buyer_headers = make_creator_headers(buyer["id"])
        po = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 450),
                buyer_headers,
            ),
            201,
        )
        # An adult with no parental controls fails only the fiscal check.
        resp = api.confirm_purchase_order(po["id"], buyer_headers)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_ROBUX)
        assert resp.status_code == 402
        assert get_user(buyer["id"])["robux_balance"] == 400


class TestCalendarMonthWindow:
    def test_parental_monthly_window_calendar_boundary(self, api, platform_admin_headers):
        """PRD §2.8: "Calendar-month windows used by the parental spend check and the
        engagement settlement are defined on UTC month boundaries."
        PRD §3.7: "the sum of this purchase's `price_robux` plus every `COMPLETED`
        purchase's `price_robux` in the current UTC calendar month (from the first
        instant of the month through now) must stay strictly below the limit: reaching
        the limit exactly is rejected, because the comparison includes equality"

        Design: Difficulty/resource_temporal_overlap/parental_monthly_window_calendar_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        parent = create_user(username="par_k", email="par_k@x.com", date_of_birth="1985-01-01")
        child = create_user(
            username="kid_k", email="kid_k@x.com",
            date_of_birth="2020-01-01", parent_user_id=parent["id"],
        )
        parent_fresh = get_user(parent["id"])
        validate_success(
            api.set_parental_controls(
                parent["id"],
                create_parental_controls_payload(
                    child["id"], parent_fresh["version"],
                    monthly_spend_limit_robux=100, chat_mode="FILTERED",
                ),
                make_creator_headers(parent["id"]),
            ),
            200,
        )
        seller = create_user(username="s_k", email="s_k@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap K", price_robux=50)
        fund_user(child["id"], 500)  # -> 400 Robux

        child_headers = make_creator_headers(child["id"])
        # August spend: 60 (0+60=60 < 100 -> accepted).
        po1 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 60),
                child_headers,
            ),
            201,
        )
        validate_success(api.confirm_purchase_order(po1["id"], child_headers), 200)

        # Still August (23:59:59 on the 31st): 60+50=110 >= 100 -> rejected.
        set_clock("2026-08-31T23:59:59Z")
        po2 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 50),
                child_headers,
            ),
            201,
        )
        resp = api.confirm_purchase_order(po2["id"], child_headers)
        validate_error(resp, ApiErrorId.ERR_PARENTAL_SPEND_LIMIT)

        # September: the window resets; 0+50=50 < 100 -> accepted.
        set_clock("2026-09-01T00:00:00Z")
        po3 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 50),
                child_headers,
            ),
            201,
        )
        completed = validate_success(api.confirm_purchase_order(po3["id"], child_headers), 200)
        assert completed["status"] == "COMPLETED"

    def test_prior_month_spend_does_not_count_in_new_month(self, api):
        """PRD §2.8: "Calendar-month windows used by the parental spend check and the
        engagement settlement are defined on UTC month boundaries."
        PRD §3.7: "the sum of this purchase's `price_robux` plus every `COMPLETED`
        purchase's `price_robux` in the current UTC calendar month (from the first
        instant of the month through now) must stay strictly below the limit"

        Design: Difficulty/resource_temporal_overlap/parental_monthly_window_calendar_boundary
        """
        set_clock("2026-08-01T00:00:00Z")
        parent, child, _pc = setup_parent_child(spend_limit=100, chat_mode="FILTERED")
        seller = create_user(username="s_k2", email="s_k2@x.com", date_of_birth="1990-01-01")
        item, _sub = create_on_sale_item(seller["id"], title="Cap K2", price_robux=99)
        fund_user(child["id"], 1500)  # -> 1250 Robux

        child_headers = make_creator_headers(child["id"])
        # August spend: 90 (90 < 100 -> accepted).
        po1 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 90),
                child_headers,
            ),
            201,
        )
        validate_success(api.confirm_purchase_order(po1["id"], child_headers), 200)

        # September: only the new month counts, so a 99-Robux purchase passes even
        # though 90+99 would far exceed the limit in a single window.
        set_clock("2026-09-01T00:00:00Z")
        po2 = validate_success(
            api.create_purchase_order(
                create_purchase_order_payload("MARKETPLACE_ITEM", item["id"], 99),
                child_headers,
            ),
            201,
        )
        completed = validate_success(api.confirm_purchase_order(po2["id"], child_headers), 200)
        assert completed["status"] == "COMPLETED"
        assert get_user(child["id"])["robux_balance"] == 1250 - 90 - 99
