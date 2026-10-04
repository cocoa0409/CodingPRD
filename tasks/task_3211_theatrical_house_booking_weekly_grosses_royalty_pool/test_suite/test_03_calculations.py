"""Calculation claims: per-order rounding, gross variants, settlement split."""
from test_helpers import (
    api_client, validate_success, get_success_data, ApiErrorId,
    TEST_USERS, setup_active_booking, sell_week1_order, open_report,
    set_clock, submit_report, verify_report, get_report, get_order,
    add_pool_participant, add_fixed_participant,
    create_discount_code_payload, make_company_rep_headers,
    create_settlement_payload, TEST_DEFAULTS,
)

HM = TEST_USERS["house_manager_headers"]
BO = TEST_USERS["box_office_agent_headers"]


class TestWeeklyGrossVariants:
    def test_provisional_gross_at_draft_creation(self, api):
        """PRD §3.6: "The **provisional** variant applies while the report is
        in `DRAFT` — including after a rejected report is returned to `DRAFT` —
        and on every refund-cascade recompute: the gross is computed live from
        the current order set each time, so a later refund or a new sale
        changes it."

        Design: Difficulty/dual_variant_calc/weekly_gross_provisional_vs_final_divergence
        """
        ctx = setup_active_booking()
        sell_week1_order(ctx["booking"]["id"], performance_date="2026-09-08T19:00:00Z")
        sell_week1_order(ctx["booking"]["id"], performance_date="2026-09-09T19:00:00Z")
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        assert rep["gross_cents"] == 20000, (
            f"provisional gross over two SOLD orders of 10000 each must be "
            f"20000, got {rep['gross_cents']}")

    def test_submit_rederives_final_gross_after_refund(self, api):
        """PRD §3.6: "The **final** variant applies at submit: the gross is
        re-derived once and frozen for review. Identical order data at submit
        and at verify therefore yields an identical gross, while a provisional
        draft gross over the same week can legitimately differ from the
        submitted figure if orders changed in between."

        Design: Difficulty/dual_variant_calc/weekly_gross_provisional_vs_final_divergence
        """
        ctx = setup_active_booking()
        sell_week1_order(ctx["booking"]["id"], performance_date="2026-09-08T19:00:00Z")
        order_b = sell_week1_order(ctx["booking"]["id"],
                                   performance_date="2026-09-09T19:00:00Z")
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        assert rep["gross_cents"] == 20000
        validate_success(api_client.refund_ticket_order(order_b["id"], BO))
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submitted = submit_report(rep["id"], ctx["company"]["id"])
        assert submitted["gross_cents"] == 10000, (
            f"final variant re-derived at submit must exclude the refunded "
            f"order: expected 10000, got {submitted['gross_cents']}")
        assert 20000 - submitted["gross_cents"] == 10000


class TestOrderGrossRounding:
    def test_discount_stacking_per_order_rounding(self, api):
        """PRD §2.7: "per-order rounding is pinned: the discount factor and
        dynamic-pricing factor are applied to the raw whole-order value first,
        and the result is rounded half-up to integer cents exactly once, per
        order, before any aggregation. The implementation must not round per
        ticket and multiply, and must not sum raw unrounded values and round
        once at the report level."

        Design: Difficulty/dual_variant_calc/order_gross_discount_stacking_divergence
        """
        ctx = setup_active_booking()
        code = get_success_data(api_client.create_discount_code(
            ctx["production"]["id"],
            create_discount_code_payload(code="SAVE11", percent_off=11),
            ctx["rep"]))
        resp = api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 7,
             "is_group_sale": False, "face_value_cents": 999,
             "discount_code_id": code["id"], "dynamic_pricing_factor": 1.5},
            BO)
        data = validate_success(resp, expected_status=201)
        # round_half_up(7 * 999 * 1.5 * 0.89) = round_half_up(9335.655) = 9336
        assert data["computed_gross_cents"] == 9336, (
            f"pinned per-order rounding gives 9336; the per-ticket reading "
            f"would give 9338; got {data['computed_gross_cents']}")

    def test_discount_stacking_diverges_from_per_ticket_reading(self, api):
        """PRD §3.5: "The rounding order is pinned: apply both factors to the
        raw whole-order value first, then round once; never round per ticket
        and multiply, and never defer rounding to the weekly aggregation."

        Design: Difficulty/dual_variant_calc/order_gross_discount_stacking_divergence
        """
        ctx = setup_active_booking()
        code = get_success_data(api_client.create_discount_code(
            ctx["production"]["id"],
            create_discount_code_payload(code="SAVE11", percent_off=11),
            ctx["rep"]))
        resp = api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 7,
             "is_group_sale": False, "face_value_cents": 999,
             "discount_code_id": code["id"], "dynamic_pricing_factor": 1.5},
            BO)
        data = validate_success(resp, expected_status=201)
        per_ticket_reading = 9338  # round_half_up(999*1.5*0.89)=1334, x7
        assert data["computed_gross_cents"] != per_ticket_reading
        assert data["computed_gross_cents"] == 9336

    def test_per_order_rounding_order_pinned_half_up(self, api):
        """PRD §3.5: "The order's `computed_gross_cents` is computed at
        creation as the whole-order value — ticket count times face value
        times the dynamic-pricing factor times one minus the discount percent
        divided by a hundred (or no discount when no code is applied) —
        rounded half-up to integer cents exactly once."

        Design: Difficulty/combinatorial_formula/per_order_rounding_order_pinned
        """
        ctx = setup_active_booking()
        resp = api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 3,
             "is_group_sale": False, "face_value_cents": 999,
             "dynamic_pricing_factor": 1.5},
            BO)
        data = validate_success(resp, expected_status=201)
        # round_half_up(3 * 999 * 1.5) = round_half_up(4495.5) = 4496
        assert data["computed_gross_cents"] == 4496, (
            f"whole-order round_half_up of 4495.5 must give 4496, "
            f"got {data['computed_gross_cents']}")

    def test_per_order_rounding_never_per_ticket(self, api):
        """PRD §2.7: "The implementation must not round per ticket and
        multiply, and must not sum raw unrounded values and round once at the
        report level."

        Design: Difficulty/combinatorial_formula/per_order_rounding_order_pinned
        """
        ctx = setup_active_booking()
        resp = api_client.create_ticket_order(
            ctx["booking"]["id"],
            {"performance_date": "2026-09-08T19:00:00Z", "ticket_count": 3,
             "is_group_sale": False, "face_value_cents": 999,
             "dynamic_pricing_factor": 1.5},
            BO)
        data = validate_success(resp, expected_status=201)
        per_ticket_reading = 4497  # round_half_up(999*1.5)=1499, x3
        assert data["computed_gross_cents"] != per_ticket_reading
        assert data["computed_gross_cents"] == 4496


class TestSettlementWaterfall:
    def _setup_medium_split_scenario(self, api):
        ctx = setup_active_booking(
            crew_size=10, size_class="MEDIUM", weekly_rent_cents=400000,
            stop_clause_weekly_floor_cents=100000,
            company_name="SplitCo", company_email="sp@x.com",
            house_name="Midtown", production_title="Show M")
        add_pool_participant(ctx["production"]["id"], ctx["company"]["id"],
                             "Author", 40)
        add_pool_participant(ctx["production"]["id"], ctx["company"]["id"],
                             "Composer", 35)
        add_fixed_participant(ctx["production"]["id"], ctx["company"]["id"],
                              "Star", 25, 50000)
        sell_week1_order(ctx["booking"]["id"], ticket_count=8,
                         is_group_sale=True, face_value_cents=250000)
        rep = open_report(ctx["booking"]["id"], ctx["company"]["id"])
        set_clock(TEST_DEFAULTS["WEEK1_END"])
        submit_report(rep["id"], ctx["company"]["id"])
        verify_report(rep["id"])
        return ctx, rep

    def test_settlement_split_max_rent_vs_pct_theatre_share(self, api):
        """PRD §3.8: "**Theatre share** — the greater of the license
        agreement's `weekly_rent_cents` and 30 percent of the gross, with the
        percentage amount rounded half-up to integer cents, producing
        `theatre_share_cents`."

        Design: Difficulty/combinatorial_formula/settlement_split_max_rent_vs_pct_nonlinear
        """
        ctx, rep = self._setup_medium_split_scenario(api)
        resp = api_client.create_settlement(
            rep["id"], create_settlement_payload(house_expenses_cents=300000), HM)
        data = validate_success(resp, expected_status=201)
        # max(400000, round_half_up(0.30 * 2000000)=600000) = 600000
        assert data["theatre_share_cents"] == 600000, (
            f"0.30 * 2000000 = 600000 > rent 400000, pct branch must win; "
            f"got {data['theatre_share_cents']}")
        # engaged 10 > MEDIUM min 8; engaged wins: 10 * 120000
        assert data["crew_cost_cents"] == 1200000, (
            f"engaged 10 crew at 120000 each = 1200000, "
            f"got {data['crew_cost_cents']}")

    def test_settlement_split_negative_profit_gates_pool(self, api):
        """PRD §3.8: "**Royalty pool** — 65 percent of the operating profit
        when the profit is positive, rounded half-up to integer cents; zero
        when the operating profit is zero or negative."
        PRD §3.8: "**Weekly operating profit** — gross minus house expenses,
        minus crew cost, minus theatre share, minus fixed royalties; this
        `weekly_operating_profit_cents` may be negative."

        Design: Difficulty/combinatorial_formula/settlement_split_max_rent_vs_pct_nonlinear
        """
        ctx, rep = self._setup_medium_split_scenario(api)
        resp = api_client.create_settlement(
            rep["id"], create_settlement_payload(house_expenses_cents=300000), HM)
        data = validate_success(resp, expected_status=201)
        # 2000000 - 300000 - 1200000 - 600000 - 50000 = -150000
        assert data["weekly_operating_profit_cents"] == -150000, (
            f"profit must be -150000, got {data['weekly_operating_profit_cents']}")
        assert data["royalty_pool_cents"] == 0, (
            f"max(0, profit) gate must zero the pool, got {data['royalty_pool_cents']}")
