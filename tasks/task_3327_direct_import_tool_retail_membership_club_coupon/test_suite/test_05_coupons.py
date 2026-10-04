"""Coupon discount math, redemption gates, and budget conservation
(PRD §3.5, §3.7)."""
from test_helpers import (
    ApiErrorId,
    add_line,
    create_active_item,
    create_coupon_payload,
    get_success_data,
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

MM = TEST_USERS["marketing_manager_headers"]
SC = TEST_USERS["store_clerk_headers"]


class TestCouponDiscountFormula:

    def test_coupon_discount_multigate_formula(self, api):
        """PRD §3.7: "for `PERCENT_OFF_ITEM` and `AMOUNT_OFF_ITEM`, E is the
        `line_total_cents` of the single line whose item has the lowest
        per-line `unit_price_cents`, breaking ties toward the line created
        earliest" and "If `max_discount_cents` is set, the final discount is
        the smaller of the raw discount and the cap" and "Applying a coupon
        computes the discount, records it in `coupon_discount_cents`, and adds
        the discount to the coupon's `budget_reserved_cents` as a reservation."

        Design: Difficulty/combinatorial_formula/coupon_discount_multigate_formula
        """
        item_p = create_active_item(sku="P1", unit_retail_cents=2000,
                                    member_price_cents=2000)
        item_q = create_active_item(sku="Q1", unit_retail_cents=5000,
                                    member_price_cents=5000)
        store = make_store([item_p["id"], item_q["id"]], store_code="ST2")
        cust = make_customer(email="c2@x.com")
        coupon = make_coupon(code="SAVE25", discount_type="PERCENT_OFF_ITEM",
                             discount_value=25, max_discount_cents=400,
                             per_customer_limit=5, budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item_q["id"], 1)
        add_line(sale["id"], item_p["id"], 1)

        applied = validate_success(api.apply_coupon(sale["id"], "SAVE25", SC))
        assert applied["subtotal_cents"] == 7000
        # Eligible line = P (lowest unit price, 2000): raw = floor(2000*25/100)=500;
        # cap min(500, 400) = 400.
        assert applied["coupon_discount_cents"] == 400

        coupon_after = validate_success(api.get_coupon(coupon["id"], MM))
        assert coupon_after["budget_reserved_cents"] == 400
        assert coupon_after["budget_spent_cents"] == 0

    def test_coupon_discount_item_amount_uses_min_of_value_and_base(self, api):
        """PRD §3.7: "for the amount types, the smaller of `discount_value` and
        E" and "E is the `line_total_cents` of the single line whose item has
        the lowest per-line `unit_price_cents`"

        Design: Difficulty/combinatorial_formula/coupon_discount_multigate_formula
        """
        item_p = create_active_item(sku="P2", unit_retail_cents=2000,
                                    member_price_cents=2000)
        item_q = create_active_item(sku="Q2", unit_retail_cents=5000,
                                    member_price_cents=5000)
        store = make_store([item_p["id"], item_q["id"]])
        cust = make_customer()
        make_coupon(code="AMT1", discount_type="AMOUNT_OFF_ITEM",
                    discount_value=3000, per_customer_limit=5,
                    budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item_q["id"], 1)
        add_line(sale["id"], item_p["id"], 1)
        applied = validate_success(api.apply_coupon(sale["id"], "AMT1", SC))
        # Eligible base = P line total 2000; min(3000, 2000) = 2000.
        assert applied["coupon_discount_cents"] == 2000


class TestSaleTotalEvaluationOrder:

    def test_sale_total_evaluation_order_circular_pin(self, api):
        """PRD §3.7: "The evaluation order is pinned: B is computed from
        per-line totals first; the discount is computed from B second; the sale
        total is computed third. The discount never feeds back into B, even
        though B's own eligibility gate references B." and "When B is below
        `min_basket_cents`, redemption fails with
        `ERR_COUPON_MIN_BASKET_NOT_MET`."

        Design: Difficulty/combinatorial_formula/sale_total_evaluation_order_circular_pin
        """
        item = create_active_item(sku="M1", unit_retail_cents=3000,
                                  member_price_cents=3000)
        store = make_store([item["id"]], store_code="ST3")
        cust = make_customer(email="c3@x.com")
        make_coupon(code="HALF", channel="EMAIL",
                    discount_type="PERCENT_OFF_BASKET", discount_value=50,
                    min_basket_cents=3000, per_customer_limit=5,
                    budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        applied = validate_success(api.apply_coupon(sale["id"], "HALF", SC))
        assert applied["coupon_discount_cents"] == 1500

        completed = validate_success(api.complete_sale(sale["id"], {}, SC))
        assert completed["status"] == "COMPLETED"
        assert completed["coupon_discount_cents"] == 1500
        assert completed["total_cents"] == 1500

    def test_sale_total_below_min_basket_rejected(self, api):
        """PRD §3.7: "When B is below `min_basket_cents`, redemption fails with
        `ERR_COUPON_MIN_BASKET_NOT_MET`."

        Design: Difficulty/combinatorial_formula/sale_total_evaluation_order_circular_pin
        """
        item = create_active_item(sku="M1B", unit_retail_cents=2999,
                                  member_price_cents=2999)
        store = make_store([item["id"]])
        cust = make_customer()
        make_coupon(code="HALF2", discount_type="PERCENT_OFF_BASKET",
                    discount_value=50, min_basket_cents=3000,
                    per_customer_limit=5, budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        resp = api.apply_coupon(sale["id"], "HALF2", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_MIN_BASKET_NOT_MET)


class TestCouponMinBasketGate:

    def test_coupon_min_basket_gate(self, api):
        """PRD §3.7: "When B is below `min_basket_cents`, redemption fails with
        `ERR_COUPON_MIN_BASKET_NOT_MET`." and "the minimum post-member-price
        basket subtotal required to redeem"

        Design: Corner/validations/coupon_min_basket_gate
        """
        item = create_active_item(sku="V4", unit_retail_cents=2999,
                                  member_price_cents=2999)
        store = make_store([item["id"]], store_code="ST-V4")
        cust = make_customer(email="v4@x.com")
        coupon = make_coupon(code="MIN30", discount_type="PERCENT_OFF_BASKET",
                             discount_value=10, min_basket_cents=3000,
                             per_customer_limit=9, budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        resp = api.apply_coupon(sale["id"], "MIN30", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_MIN_BASKET_NOT_MET)

        add_line(sale["id"], item["id"], 1)
        applied = validate_success(api.apply_coupon(sale["id"], "MIN30", SC))
        assert applied["applied_coupon_id"] == coupon["id"]


class TestCouponAudienceAndEarlyAccess:

    def test_members_only_audience_gate(self, api):
        """PRD §3.7: "Audience: a `MEMBERS_ONLY` coupon requires the redeeming
        customer to be an effective member now, otherwise
        `ERR_COUPON_MEMBERS_ONLY`."

        Design: Corner/validations/members_only_audience_gate
        """
        from test_helpers import enroll_member
        item = create_active_item(sku="V5", unit_retail_cents=2000,
                                  member_price_cents=1800)
        store = make_store([item["id"]], store_code="ST-V5")
        nm = make_customer(email="v5nm@x.com")
        mm_cust = make_customer(email="v5m@x.com")
        enroll_member(mm_cust["id"], "CLUB")
        coupon = make_coupon(code="MEMB", audience="MEMBERS_ONLY",
                             discount_type="PERCENT_OFF_BASKET",
                             discount_value=10, per_customer_limit=9,
                             budget_cents=100000)
        s_nm = make_open_sale(store["id"], nm["id"])
        add_line(s_nm["id"], item["id"], 1)
        s_m = make_open_sale(store["id"], mm_cust["id"])
        add_line(s_m["id"], item["id"], 1)

        resp = api.apply_coupon(s_nm["id"], "MEMB", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_MEMBERS_ONLY)
        applied = validate_success(api.apply_coupon(s_m["id"], "MEMB", SC))
        assert applied["applied_coupon_id"] == coupon["id"]

    def test_member_early_access_window(self, api):
        """PRD §3.7: "when the customer is an effective member now and the
        coupon has `member_early_start` set, redemption is valid from
        `member_early_start`; otherwise it is valid from `window_start`"

        Design: Corner/validations/member_early_access_window
        """
        from test_helpers import enroll_member
        item = create_active_item(sku="V6", unit_retail_cents=2000,
                                  member_price_cents=1800)
        store = make_store([item["id"]], store_code="ST-V6")
        mm_cust = make_customer(email="v6m@x.com")
        enroll_member(mm_cust["id"], "CLUB")
        nm = make_customer(email="v6nm@x.com")
        coupon_payload = create_coupon_payload(
            code="EARLY", discount_type="PERCENT_OFF_BASKET",
            discount_value=10, per_customer_limit=9, budget_cents=100000,
            window_start="2026-09-08T00:00:00Z",
            window_end="2026-09-30T00:00:00Z",
            member_early_start="2026-09-01T00:00:00Z")
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))

        set_clock("2026-09-05T12:00:00Z")
        s_m = make_open_sale(store["id"], mm_cust["id"])
        add_line(s_m["id"], item["id"], 1)
        s_nm = make_open_sale(store["id"], nm["id"])
        add_line(s_nm["id"], item["id"], 1)

        applied = validate_success(api.apply_coupon(s_m["id"], "EARLY", SC))
        assert applied["applied_coupon_id"] == coupon["id"]
        resp = api.apply_coupon(s_nm["id"], "EARLY", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_OUTSIDE_WINDOW)


class TestCouponWindowHalfOpen:

    def test_coupon_window_half_open_membership(self, api):
        """PRD §3.7: "either way, redemption at or after `window_end` is
        invalid — the start is inclusive and the end is exclusive. A violation
        is rejected with `ERR_COUPON_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/coupon_window_half_open_membership
        """
        item = create_active_item(sku="TO1", unit_retail_cents=1500,
                                  member_price_cents=1500)
        store = make_store([item["id"]], store_code="ST11")
        cust = make_customer(email="c11@x.com")
        coupon_payload = create_coupon_payload(
            code="WIN1", discount_type="PERCENT_OFF_BASKET", discount_value=5,
            per_customer_limit=9, budget_cents=50000,
            window_start="2026-10-01T00:00:00Z",
            window_end="2026-10-02T00:00:00Z")
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))

        set_clock("2026-10-01T00:00:00Z")
        s1 = make_open_sale(store["id"], cust["id"])
        add_line(s1["id"], item["id"], 1)
        s2 = make_open_sale(store["id"], cust["id"])
        add_line(s2["id"], item["id"], 1)

        # window_start inclusive
        applied = validate_success(api.apply_coupon(s1["id"], "WIN1", SC))
        assert applied["applied_coupon_id"] == coupon["id"]

        # window_end exclusive
        set_clock("2026-10-02T00:00:00Z")
        resp = api.apply_coupon(s2["id"], "WIN1", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_OUTSIDE_WINDOW)

    def test_coupon_before_window_start_rejected(self, api):
        """PRD §3.7: "otherwise it is valid from `window_start`" and "the start
        is inclusive and the end is exclusive. A violation is rejected with
        `ERR_COUPON_OUTSIDE_WINDOW`."

        Design: Difficulty/resource_temporal_overlap/coupon_window_half_open_membership
        """
        item = create_active_item(sku="TO1B")
        store = make_store([item["id"]])
        cust = make_customer()
        coupon_payload = create_coupon_payload(
            code="WIN2", window_start="2026-10-01T00:00:00Z",
            window_end="2026-10-02T00:00:00Z")
        coupon = get_success_data(api.create_coupon(coupon_payload, MM))
        get_success_data(api.activate_coupon(coupon["id"], MM))

        set_clock("2026-09-30T23:59:59Z")
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        resp = api.apply_coupon(sale["id"], "WIN2", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_OUTSIDE_WINDOW)


class TestCouponBudgetGate:

    def test_err_coupon_budget_exceeded_triggerable(self, api):
        """PRD §3.7: "Budget: the coupon's computed discount for this sale plus
        `budget_spent_cents` plus `budget_reserved_cents` must be at most
        `budget_cents`; equality is allowed. A breach is rejected with
        `ERR_COUPON_BUDGET_EXCEEDED`."

        Design: Corner/errors/err_coupon_budget_exceeded_triggerable
        """
        item = create_active_item(sku="ER1", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]], store_code="ST-ER1")
        ca = make_customer(email="er1a@x.com")
        cb = make_customer(email="er1b@x.com")
        coupon = make_coupon(code="BDG", discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=500, per_customer_limit=9,
                             budget_cents=1000)
        # CU1 completes a sale: spent 500.
        make_completed_sale(store["id"], ca["id"], item["id"], 1,
                            coupon_code="BDG")
        # CB sale S1 applies: reserved 500.
        s1 = make_open_sale(store["id"], cb["id"])
        add_line(s1["id"], item["id"], 1)
        validate_success(api.apply_coupon(s1["id"], "BDG", SC))
        mid = validate_success(api.get_coupon(coupon["id"], MM))
        assert mid["budget_spent_cents"] == 500
        assert mid["budget_reserved_cents"] == 500

        # CB sale S2: 500 + 500 + 500 > 1000 -> rejected.
        s2 = make_open_sale(store["id"], cb["id"])
        add_line(s2["id"], item["id"], 1)
        resp = api.apply_coupon(s2["id"], "BDG", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_BUDGET_EXCEEDED)

    def test_coupon_budget_equality_allowed(self, api):
        """PRD §3.7: "Budget: the coupon's computed discount for this sale plus
        `budget_spent_cents` plus `budget_reserved_cents` must be at most
        `budget_cents`; equality is allowed."

        Design: Corner/errors/err_coupon_budget_exceeded_triggerable
        """
        item = create_active_item(sku="ER1B", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]])
        cust = make_customer()
        coupon = make_coupon(code="BDG2", discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=500, per_customer_limit=9,
                             budget_cents=1000)
        # Complete one sale: spent 500. Apply on a second: 500+500+0 == 1000 OK.
        make_completed_sale(store["id"], cust["id"], item["id"], 1,
                            coupon_code="BDG2")
        s2 = make_open_sale(store["id"], cust["id"])
        add_line(s2["id"], item["id"], 1)
        applied = validate_success(api.apply_coupon(s2["id"], "BDG2", SC))
        assert applied["applied_coupon_id"] == coupon["id"]


class TestCouponAlreadyApplied:

    def test_second_coupon_on_same_sale_rejected(self, api):
        """PRD §3.7: "A sale carries at most one coupon: if
        `applied_coupon_id` is already set, a second application is rejected
        with `ERR_COUPON_ALREADY_APPLIED`."

        Design: Corner/endpoints/second_coupon_on_same_sale_rejected
        """
        item = create_active_item(sku="EP3", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]], store_code="ST-EP3")
        cust = make_customer(email="ep3@x.com")
        ca = make_coupon(code="CPCA", discount_type="PERCENT_OFF_BASKET",
                         discount_value=10, per_customer_limit=9,
                         budget_cents=100000)
        make_coupon(code="CPCB", channel="EMAIL",
                    discount_type="PERCENT_OFF_BASKET", discount_value=20,
                    per_customer_limit=9, budget_cents=100000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        validate_success(api.apply_coupon(sale["id"], "CPCA", SC))
        resp = api.apply_coupon(sale["id"], "CPCB", SC)
        validate_error(resp, ApiErrorId.ERR_COUPON_ALREADY_APPLIED)
        sale_after = validate_success(api.get_sale(sale["id"], SC))
        assert sale_after["applied_coupon_id"] == ca["id"]


class TestCouponBudgetConservation:

    def test_coupon_budget_conserved_under_apply_void(self, api):
        """PRD §3.7: "Voiding an `OPEN` sale moves it to `VOID`; when a coupon
        had been applied, its reservation is released (`budget_reserved_cents`
        shrinks by the discount) while `applied_coupon_id` is retained for
        audit." and "the coupon reservation settles (`budget_reserved_cents`
        shrinks by the discount while `budget_spent_cents` grows by it"

        Design: Difficulty/compensating_invariant/coupon_budget_conserved_under_apply_void
        """
        item = create_active_item(sku="CI2", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]], store_code="ST14")
        cust = make_customer(email="c14@x.com")
        coupon = make_coupon(code="FIX3", channel="EMAIL",
                             discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=300, per_customer_limit=9,
                             budget_cents=10000)

        s_void = make_open_sale(store["id"], cust["id"])
        add_line(s_void["id"], item["id"], 1)
        validate_success(api.apply_coupon(s_void["id"], "FIX3", SC))
        s_done = make_open_sale(store["id"], cust["id"])
        add_line(s_done["id"], item["id"], 1)
        validate_success(api.apply_coupon(s_done["id"], "FIX3", SC))

        validate_success(api.void_sale(s_void["id"], SC))
        validate_success(api.complete_sale(s_done["id"], {}, SC))

        coupon_after = validate_success(api.get_coupon(coupon["id"], MM))
        assert coupon_after["budget_reserved_cents"] == 0
        assert coupon_after["budget_spent_cents"] == 300
        # Invariant: spent + reserved tracks live discounts exactly; the voided
        # reservation leaked nothing.
        assert (coupon_after["budget_spent_cents"]
                + coupon_after["budget_reserved_cents"]) == 300

    def test_coupon_budget_reserved_on_apply_released_on_void(self, api):
        """PRD §3.7: "Applying a coupon computes the discount, records it in
        `coupon_discount_cents`, and adds the discount to the coupon's
        `budget_reserved_cents` as a reservation." and "when a coupon had been
        applied, its reservation is released (`budget_reserved_cents` shrinks
        by the discount)"

        Design: Difficulty/compensating_invariant/coupon_budget_conserved_under_apply_void
        """
        item = create_active_item(sku="CI2B", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]])
        cust = make_customer()
        coupon = make_coupon(code="FIX4", discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=300, per_customer_limit=9,
                             budget_cents=10000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        validate_success(api.apply_coupon(sale["id"], "FIX4", SC))
        mid = validate_success(api.get_coupon(coupon["id"], MM))
        assert mid["budget_reserved_cents"] == 300
        assert mid["budget_spent_cents"] == 0

        validate_success(api.void_sale(sale["id"], SC))
        after = validate_success(api.get_coupon(coupon["id"], MM))
        assert after["budget_reserved_cents"] == 0
        assert after["budget_spent_cents"] == 0


class TestImmediateConsistency:

    def test_immediate_visibility_of_completion_effects(self, api):
        """PRD §3.7: "the coupon reservation settles (`budget_reserved_cents`
        shrinks by the discount while `budget_spent_cents` grows by it" and
        "`total_cents` becomes `subtotal_cents` minus `coupon_discount_cents`
        minus `store_credit_applied_cents`"

        Design: Corner/consistency_model/immediate_visibility_of_completion_effects
        """
        item = create_active_item(sku="CM1", unit_retail_cents=2000,
                                  member_price_cents=2000)
        store = make_store([item["id"]], store_code="ST-CM1")
        cust = make_customer(email="cm1@x.com")
        coupon = make_coupon(code="IMM", discount_type="FIXED_AMOUNT_OFF_BASKET",
                             discount_value=300, per_customer_limit=9,
                             budget_cents=5000)
        sale = make_open_sale(store["id"], cust["id"])
        add_line(sale["id"], item["id"], 1)
        validate_success(api.apply_coupon(sale["id"], "IMM", SC))
        completed = validate_success(api.complete_sale(sale["id"], {}, SC))
        assert completed["total_cents"] == 1700
        coupon_after = validate_success(api.get_coupon(coupon["id"], MM))
        assert coupon_after["budget_spent_cents"] == 300
        assert coupon_after["budget_reserved_cents"] == 0
