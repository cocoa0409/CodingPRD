"""Membership pricing, savings ledgers, and renewal fee tiers
(PRD §3.4, §3.6, §3.7)."""
from test_helpers import (
    add_line,
    create_active_item,
    create_membership_payload,
    enroll_member,
    get_success_data,
    make_completed_sale,
    make_customer,
    make_open_sale,
    make_store,
    set_clock,
    validate_success,
    TEST_USERS,
)

SC = TEST_USERS["store_clerk_headers"]


class TestMembershipSavingsVariants:

    def test_membership_savings_settled_vs_optimistic(self, api):
        """PRD §3.7: "The settled variant sums, over the member's `COMPLETED`
        and `RETURNED_PARTIAL` sales and per non-warranty line, the difference
        between the item's `unit_retail_cents` and the line's
        `unit_price_cents` multiplied by the not-yet-returned quantity" and
        "The optimistic variant is the settled figure plus projected savings on
        the member's `OPEN` sales computed as though member pricing will apply"

        Design: Difficulty/dual_variant_calc/membership_savings_settled_vs_optimistic
        """
        item = create_active_item(sku="S1", unit_retail_cents=5000,
                                  member_price_cents=4500,
                                  floor_margin_pct=0.05)
        store = make_store([item["id"]], store_code="ST1")
        cust = make_customer(email="c1@x.com")
        memb = enroll_member(cust["id"], "CLUB")

        # Completed sale: settled savings 500.
        make_completed_sale(store["id"], cust["id"], item["id"], 1)
        # Open sale: projected savings 500.
        s2 = make_open_sale(store["id"], cust["id"])
        add_line(s2["id"], item["id"], 1)

        memb_after = validate_success(api.get_membership(memb["id"], SC))
        assert memb_after["settled_savings_cents"] == 500
        assert memb_after["optimistic_savings_cents"] == 1000
        assert (memb_after["optimistic_savings_cents"]
                - memb_after["settled_savings_cents"]) == 500

    def test_membership_savings_converge_when_no_open_sales(self, api):
        """PRD §3.7: "The two variants diverge whenever open sales exist; the
        settled figure is the ledger of record and the optimistic figure is the
        projection view."

        Design: Difficulty/dual_variant_calc/membership_savings_settled_vs_optimistic
        """
        item = create_active_item(sku="S1B", unit_retail_cents=5000,
                                  member_price_cents=4500)
        store = make_store([item["id"]])
        cust = make_customer()
        memb = enroll_member(cust["id"], "CLUB")
        make_completed_sale(store["id"], cust["id"], item["id"], 1)
        memb_after = validate_success(api.get_membership(memb["id"], SC))
        assert memb_after["settled_savings_cents"] == 500
        assert memb_after["optimistic_savings_cents"] == 500


class TestMemberPriceGraceWindow:

    def test_member_price_grace_window_resolution(self, api):
        """PRD §3.6: "if the customer is an effective member at the current
        logical time — meaning the customer holds a Membership whose status is
        `ACTIVE` or `LAPSED` and the current time is at or before `expires_at`
        plus 30 days of grace (a `CANCELLED` membership never qualifies) — the
        unit price is the lower of the item's `member_price_cents` and
        `unit_retail_cents`; otherwise it is `unit_retail_cents`."

        Design: Corner/calculations/member_price_grace_window_resolution
        """
        item = create_active_item(sku="CALC3", unit_retail_cents=4000,
                                  member_price_cents=3000,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-C3")
        cust = make_customer(email="calc5@x.com")
        set_clock("2026-01-01T00:00:00Z")
        enroll_member(cust["id"], "CLUB")  # expires 2027-01-01

        set_clock("2027-01-20T00:00:00Z")  # LAPSED but within 30-day grace
        s1 = make_completed_sale(store["id"], cust["id"], item["id"], 1)
        assert s1["total_cents"] == 3000

        set_clock("2027-02-01T00:00:00Z")  # past grace (expires + 30d = Jan 31)
        s2 = make_completed_sale(store["id"], cust["id"], item["id"], 1)
        assert s2["total_cents"] == 4000


class TestRenewalFeeTiers:

    def test_renewal_fee_tier_boundary_inclusive(self, api):
        """PRD §3.4: "For the `CLUB` tier: settled savings of at least 20000
        cents bring the fee down to 1999 cents; at least 5000 cents but below
        20000 bring it to 2999 cents; below 5000 cents the full 3999 cents
        applies. The boundaries are inclusive — savings exactly at 5000 cents
        earn the 2999-cent fee. `CLUB_PLUS` charges a flat 6999 cents with no
        savings tiers."

        Design: Corner/calculations/renewal_fee_tier_boundary_inclusive
        """
        item = create_active_item(sku="CALC1", unit_retail_cents=5500,
                                  member_price_cents=500,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-C1")
        # C1: savings exactly 5000 (one completed member-priced unit)
        c1 = make_customer(email="calc1@x.com")
        m1 = enroll_member(c1["id"], "CLUB")
        make_completed_sale(store["id"], c1["id"], item["id"], 1)
        # C2: savings 0
        c2 = make_customer(email="calc2@x.com")
        m2 = enroll_member(c2["id"], "CLUB")
        # C3: CLUB_PLUS
        c3 = make_customer(email="calc3@x.com")
        m3 = get_success_data(api.create_membership(
            c3["id"], create_membership_payload("CLUB_PLUS"), SC))
        assert m3["renewal_fee_cents"] == 6999

        m1_after = validate_success(api.renew_membership(m1["id"], SC))
        assert m1_after["settled_savings_cents"] == 5000
        assert m1_after["renewal_fee_cents"] == 2999

        m2_after = validate_success(api.renew_membership(m2["id"], SC))
        assert m2_after["renewal_fee_cents"] == 3999

    def test_renewal_fee_high_tier_savings(self, api):
        """PRD §3.4: "settled savings of at least 20000 cents bring the fee
        down to 1999 cents"

        Design: Corner/calculations/renewal_fee_tier_boundary_inclusive
        """
        item = create_active_item(sku="CALC1B", unit_retail_cents=5500,
                                  member_price_cents=500,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]])
        cust = make_customer()
        memb = enroll_member(cust["id"], "CLUB")
        # 4 completed units * 5000 savings = 20000 exactly (inclusive).
        make_completed_sale(store["id"], cust["id"], item["id"], 4)
        renewed = validate_success(api.renew_membership(memb["id"], SC))
        assert renewed["settled_savings_cents"] == 20000
        assert renewed["renewal_fee_cents"] == 1999


class TestSavingsReconciliationAfterReturn:

    def test_derived_field_reconciliation_savings_after_return(self, api):
        """PRD §3.8: "When returned lines had contributed to membership
        savings, `settled_savings_cents` is reduced accordingly, upholding the
        invariant that settled savings and refunds never double-count." and
        "The refund is credited to the customer's `store_credit_cents`"

        Design: Corner/cross_cutting_layers/derived_field_reconciliation_savings_after_return
        """
        item = create_active_item(sku="CC4", unit_retail_cents=1500,
                                  member_price_cents=1000,
                                  floor_margin_pct=0.01)
        store = make_store([item["id"]], store_code="ST-CC4")
        cust = make_customer(email="cc4@x.com")
        memb = enroll_member(cust["id"], "CLUB")
        sale = make_open_sale(store["id"], cust["id"])
        line = add_line(sale["id"], item["id"], 2)
        completed = validate_success(api.complete_sale(sale["id"], {}, SC))
        assert completed["status"] == "COMPLETED"

        mid = validate_success(api.get_membership(memb["id"], SC))
        assert mid["settled_savings_cents"] == 1000

        validate_success(api.return_sale(
            sale["id"], {"sale_line_id": line["id"], "quantity": 1}, SC))
        memb_after = validate_success(api.get_membership(memb["id"], SC))
        assert memb_after["settled_savings_cents"] == 500
        cust_after = validate_success(api.get_customer(cust["id"], SC))
        assert cust_after["store_credit_cents"] == 1000
