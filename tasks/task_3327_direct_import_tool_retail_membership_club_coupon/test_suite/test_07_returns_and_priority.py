"""Returns, refund waterfall, and coupon clawback (PRD §3.7, §3.8)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    create_active_item,
    create_coupon_payload,
    enroll_member,
    get_success_data,
    make_active_recall,
    make_completed_sale,
    make_coupon,
    make_customer,
    make_open_sale,
    make_store,
    set_clock,
    validate_error,
    validate_success,
    TEST_USERS,
)

SC = TEST_USERS["store_clerk_headers"]
MM = TEST_USERS["marketing_manager_headers"]


class TestReturnWindows:

    def test_return_window_member_vs_nonmember(self, api):
        """PRD §3.8: "The return window runs from `completed_at` against the
        logical clock: 90 days when the customer is an effective member now,
        otherwise 30 days; a return past its window is rejected with
        `ERR_RETURN_WINDOW_EXPIRED`."

        Design: Corner/validations/return_window_member_vs_nonmember
        """
        item = create_active_item(sku="V7", unit_retail_cents=2000,
                                  member_price_cents=1800,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-V7")
        set_clock("2026-09-01T00:00:00Z")
        mm_cust = make_customer(email="v7m@x.com")
        enroll_member(mm_cust["id"], "CLUB")
        nm = make_customer(email="v7nm@x.com")

        s_m = make_open_sale(store["id"], mm_cust["id"])
        ml = add_line(s_m["id"], item["id"], 1)
        validate_success(api.complete_sale(s_m["id"], {}, SC))
        s_nm = make_open_sale(store["id"], nm["id"])
        nml = add_line(s_nm["id"], item["id"], 1)
        validate_success(api.complete_sale(s_nm["id"], {}, SC))

        set_clock("2026-10-16T00:00:00Z")  # 45 days later
        returned = validate_success(api.return_sale(
            s_m["id"], {"sale_line_id": ml["id"], "quantity": 1}, SC))
        assert returned["status"] == "RETURNED_FULL"
        resp = api.return_sale(
            s_nm["id"], {"sale_line_id": nml["id"], "quantity": 1}, SC)
        validate_error(resp, ApiErrorId.ERR_RETURN_WINDOW_EXPIRED)

    def test_hazard_recall_return_overrides_window(self, api):
        """PRD §3.8: "However, when any returned line's item sits under an
        `ACTIVE` recall of severity `HAZARD`, the refund is always allowed
        regardless of the window — a safety override."

        Design: Corner/validations/hazard_recall_return_overrides_window
        """
        item = create_active_item(sku="V8", unit_retail_cents=3000,
                                  member_price_cents=3000,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-V8")
        cust = make_customer(email="v8@x.com")
        set_clock("2026-09-01T00:00:00Z")
        sale = make_open_sale(store["id"], cust["id"])
        line = add_line(sale["id"], item["id"], 1)
        validate_success(api.complete_sale(sale["id"], {}, SC))

        make_active_recall(item["id"], "HAZARD")
        set_clock("2027-03-20T00:00:00Z")  # ~200 days later, past every window
        returned = validate_success(api.return_sale(
            sale["id"], {"sale_line_id": line["id"], "quantity": 1}, SC))
        assert returned["status"] == "RETURNED_FULL"
        cust_after = validate_success(api.get_customer(cust["id"], SC))
        assert cust_after["store_credit_cents"] == 3000


class TestReturnQuantity:

    def test_return_quantity_cumulative_exceeded(self, api):
        """PRD §3.8: "The cumulative returned quantity per line, tracked in
        `returned_line_quantities`, must never exceed the line's quantity,
        otherwise `ERR_RETURN_QUANTITY_EXCEEDED`."

        Design: Corner/validations/return_quantity_cumulative_exceeded
        """
        item = create_active_item(sku="V9", unit_retail_cents=1000,
                                  member_price_cents=1000,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-V9")
        cust = make_customer(email="v9@x.com")
        enroll_member(cust["id"], "CLUB")  # 90-day window
        sale = make_open_sale(store["id"], cust["id"])
        line = add_line(sale["id"], item["id"], 3)
        validate_success(api.complete_sale(sale["id"], {}, SC))

        partial = validate_success(api.return_sale(
            sale["id"], {"sale_line_id": line["id"], "quantity": 2}, SC))
        assert partial["status"] == "RETURNED_PARTIAL"
        resp = api.return_sale(
            sale["id"], {"sale_line_id": line["id"], "quantity": 2}, SC)
        validate_error(resp, ApiErrorId.ERR_RETURN_QUANTITY_EXCEEDED)
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["status"] == "RETURNED_PARTIAL"
        cust_after = validate_success(api.get_customer(cust["id"], SC))
        assert cust_after["store_credit_cents"] == 2000


class TestReturnCouponClawback:

    def test_return_refund_coupon_clawback(self, api):
        """PRD §3.8: "If the sale had an applied coupon and the returned line
        was the coupon's eligible line under the eligible-line rule of §3.7, a
        proportional clawback applies: the sale's `coupon_discount_cents`
        multiplied by q and divided by the line's quantity as it stood at
        coupon application, truncated to whole cents, subtracted from the line
        refund but never below zero."

        Design: Corner/calculations/return_refund_coupon_clawback
        """
        ip = create_active_item(sku="CALC2P", unit_retail_cents=2000,
                                member_price_cents=2000, floor_margin_pct=0.01)
        iq = create_active_item(sku="CALC2Q", unit_retail_cents=5000,
                                member_price_cents=5000, floor_margin_pct=0.01)
        store = make_store([ip["id"], iq["id"]], store_code="ST-C2")
        cust = make_customer(email="calc4@x.com")
        make_coupon(code="CLAW", discount_type="PERCENT_OFF_ITEM",
                    discount_value=25, per_customer_limit=9,
                    budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        pline = add_line(sale["id"], ip["id"], 4)
        qline = add_line(sale["id"], iq["id"], 1)
        validate_success(api.apply_coupon(sale["id"], "CLAW", SC))
        validate_success(api.complete_sale(sale["id"], {}, SC))
        # discount = floor(8000 * 25 / 100) = 2000 on the eligible P line.

        # Return 1 of 4 P units: refund 2000 - floor(2000*1/4) = 1500.
        validate_success(api.return_sale(
            sale["id"], {"sale_line_id": pline["id"], "quantity": 1}, SC))
        mid = validate_success(api.get_customer(cust["id"], SC))
        assert mid["store_credit_cents"] == 1500

        # Q line is not the eligible line: face-value refund 5000.
        validate_success(api.return_sale(
            sale["id"], {"sale_line_id": qline["id"], "quantity": 1}, SC))
        cust_after = validate_success(api.get_customer(cust["id"], SC))
        assert cust_after["store_credit_cents"] == 6500
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["status"] == "RETURNED_PARTIAL"


class TestCompletionValidationPriority:

    def test_state_gate_beats_fiscal_store_credit(self, api):
        """PRD §2.9: "the server evaluates checks in a fixed priority order and
        reports the first failure" — item lifecycle gate (step 7,
        `ERR_ITEM_NOT_ACTIVE`) precedes coupon budget and store-credit
        sufficiency (step 12, `ERR_INSUFFICIENT_STORE_CREDIT`).

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_store_credit
        """
        item = create_active_item(sku="PV1", unit_retail_cents=2500,
                                  member_price_cents=2400)
        store = make_store([item["id"]], store_code="ST6")
        cust = make_customer(email="c6@x.com")
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        from test_helpers import TEST_USERS as _TU
        get_success_data(api.discontinue_item(
            item["id"], _TU["purchasing_manager_headers"]))

        resp = api.complete_sale(
            sale["id"], {"store_credit_applied_cents": 500}, SC)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ACTIVE)
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["status"] == "OPEN"

    def test_state_gate_beats_store_credit_when_both_would_fail(self, api):
        """PRD §2.9: "An earlier failure masks all later ones" — completing a
        sale over a `DISCONTINUED` line item reports the lifecycle gate even
        when the requested store credit also exceeds the balance.

        Design: Difficulty/priority_pair_validation_conflict/state_gate_beats_fiscal_store_credit
        """
        item = create_active_item(sku="PV1C", unit_retail_cents=2500,
                                  member_price_cents=2400)
        store = make_store([item["id"]])
        cust = make_customer()
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        from test_helpers import TEST_USERS as _TU
        get_success_data(api.discontinue_item(
            item["id"], _TU["purchasing_manager_headers"]))
        # Customer balance is 0; both lifecycle and credit checks would fail.
        resp = api.complete_sale(
            sale["id"], {"store_credit_applied_cents": 1}, SC)
        validate_error(resp, ApiErrorId.ERR_ITEM_NOT_ACTIVE)
        cust_after = validate_success(api.get_customer(cust["id"], SC))
        assert cust_after["store_credit_cents"] == 0

    def test_safety_hold_beats_coupon_window(self, api):
        """PRD §2.9: "the server evaluates checks in a fixed priority order and
        reports the first failure" — recall safety gate (step 8,
        `ERR_SAFETY_HOLD`) precedes the coupon time window (step 9,
        `ERR_COUPON_OUTSIDE_WINDOW`).

        Design: Difficulty/priority_pair_validation_conflict/safety_hold_beats_coupon_window
        """
        item = create_active_item(sku="PV2", unit_retail_cents=8000,
                                  member_price_cents=7500)
        store = make_store([item["id"]], store_code="ST7")
        cust = make_customer(email="c7@x.com")
        coupon_payload = create_coupon_payload(
            code="AUG10", channel="PRINT",
            discount_type="PERCENT_OFF_BASKET", discount_value=10,
            per_customer_limit=2, budget_cents=50000,
            window_start="2026-08-01T00:00:00Z",
            window_end="2026-08-15T00:00:00Z")
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))

        set_clock("2026-08-10T12:00:00Z")
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        validate_success(api.apply_coupon(sale["id"], "AUG10", SC))

        set_clock("2026-08-20T12:00:00Z")
        make_active_recall(item["id"], "HAZARD")
        resp = api.complete_sale(sale["id"], {}, SC)
        validate_error(resp, ApiErrorId.ERR_SAFETY_HOLD)
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["status"] == "OPEN"

    def test_safety_hold_alone_rejects_completion(self, api):
        """PRD §3.7: "no line item to sit under an `ACTIVE` recall of severity
        `STOP_SALE` or `HAZARD`, otherwise `ERR_SAFETY_HOLD`"

        Design: Difficulty/priority_pair_validation_conflict/safety_hold_beats_coupon_window
        """
        item = create_active_item(sku="PV2B", unit_retail_cents=8000,
                                  member_price_cents=7500)
        store = make_store([item["id"]])
        cust = make_customer()
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        make_active_recall(item["id"], "STOP_SALE")
        resp = api.complete_sale(sale["id"], {}, SC)
        validate_error(resp, ApiErrorId.ERR_SAFETY_HOLD)
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["status"] == "OPEN"
