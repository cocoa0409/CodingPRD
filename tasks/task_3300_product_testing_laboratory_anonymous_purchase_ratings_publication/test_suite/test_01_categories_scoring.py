"""Category creation, selection score, purchase-order tax, and lab scoring.

Covers difficulty instances: selection_score_multi_input_nonlinear,
po_tax_per_line_vs_sum_then_round, po_tax_nested_rounding_order,
measurement_score_two_stage_vs_flat — and corner instances:
category_create_success_and_defaults, category_duplicate_name_rejected,
selection_score_excludes_retired.
"""
import pytest

from test_helpers import (
    validate_success, validate_error, get_success_data,
    ApiErrorId,
    assert_product_category,
    create_product_category_payload, create_purchase_order_payload,
    create_po_line_payload, create_measurement_payload,
    create_category, create_program, create_active_protocol, approve_program,
    create_sample, setup_program_sourcing, setup_program_testing,
    TEST_USERS,
)

LM = TEST_USERS["lab_manager_headers"]
PA = TEST_USERS["purchasing_agent_headers"]
LT = TEST_USERS["lab_technician_headers"]


class TestCategoryCreationAndSelectionScore:
    def test_category_create_success_and_defaults(self, api):
        """PRD §3.1: "A category starts in `status` `ACTIVE`".
        PRD §3.1: "if the category has never published (`last_published_at` is null), the full 60-month cap applies."
        PRD §3.1: "Urgency itself is then one hundred times those months divided by `refresh_cycle_months`, rounded half-up to two decimal places, and capped at 100."
        PRD §3.1: "The score blends three signals with fixed weights: forty percent of `market_share_pct`, thirty-five percent of `member_interest_pct`, and twenty-five percent of a refresh-urgency component, with the final figure rounded half-up to two decimal places."

        Design: Corner/entities/category_create_success_and_defaults
        """
        resp = api.create_product_category(
            create_product_category_payload(
                name="Vacuums", refresh_cycle_months=24,
                market_share_pct=50, member_interest_pct=50,
            ),
            LM,
        )
        data = validate_success(resp, expected_status=201)
        assert_product_category(data)
        assert data["status"] == "ACTIVE"
        assert data["last_published_at"] is None
        assert data["version"] == 1
        # urgency = min(100, round_half_up(100*60/24, 2)) = 100
        # score = 0.40*50 + 0.35*50 + 0.25*100 = 20 + 17.5 + 25 = 62.5
        assert data["selection_score"] == pytest.approx(62.5, abs=0.01)

    def test_category_duplicate_name_rejected(self, api):
        """PRD §3.1: "A `LabManager` creates a `ProductCategory` by supplying its display `name` (unique across categories — a duplicate is rejected with `ERR_DUPLICATE`)".

        Design: Corner/entities/category_duplicate_name_rejected
        """
        create_category(name="Vacuums")
        resp = api.create_product_category(
            create_product_category_payload(
                name="Vacuums", refresh_cycle_months=12,
                market_share_pct=10, member_interest_pct=10,
            ),
            LM,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE)

    def test_cycle_run_rescores_active_category(self, api):
        """PRD §3.9: "Every `ProductCategory` whose `status` is not `RETIRED` has its `selection_score` recomputed per §3.1, using the cycle-run clock."

        Design: Corner/calculations/selection_score_excludes_retired
        """
        create_category(name="Vacuums")
        resp = api.run_cycle(LM)
        data = validate_success(resp)
        assert data["categories_rescored"] == 1

    def test_selection_score_at_cycle_with_never_published_category(self, api):
        """PRD §3.1: "if the category has never published (`last_published_at` is null), the full 60-month cap applies."
        PRD §3.1: "The score blends three signals with fixed weights: forty percent of `market_share_pct`, thirty-five percent of `member_interest_pct`, and twenty-five percent of a refresh-urgency component, with the final figure rounded half-up to two decimal places."
        PRD §3.9: "Every `ProductCategory` whose `status` is not `RETIRED` has its `selection_score` recomputed per §3.1, using the cycle-run clock."

        Design: Difficulty/combinatorial_formula/selection_score_multi_input_nonlinear
        """
        category = create_category(
            name="Vacuums", refresh_cycle_months=24,
            market_share_pct=50, member_interest_pct=50,
        )
        resp = api.run_cycle(LM)
        validate_success(resp)
        data = get_success_data(api.get_product_category(category["id"], LM))
        # months_since = 60 (null -> cap); urgency = min(100, 100*60/24 = 250) = 100
        # score = 0.40*50 + 0.35*50 + 0.25*100 = 62.5
        assert data["selection_score"] == pytest.approx(62.5, abs=0.01)

    def test_selection_score_urgency_not_capped_below_100(self, api):
        """PRD §3.1: "Urgency itself is then one hundred times those months divided by `refresh_cycle_months`, rounded half-up to two decimal places, and capped at 100."
        PRD §3.1: "if the category has never published (`last_published_at` is null), the full 60-month cap applies."

        Design: Difficulty/combinatorial_formula/selection_score_multi_input_nonlinear
        """
        # refresh_cycle_months 100 -> urgency = round_half_up(100*60/100,2) = 60 (not capped)
        category = create_category(
            name="Dryers", refresh_cycle_months=100,
            market_share_pct=20, member_interest_pct=40,
        )
        validate_success(api.run_cycle(LM))
        data = get_success_data(api.get_product_category(category["id"], LM))
        # score = 0.40*20 + 0.35*40 + 0.25*60 = 8 + 14 + 15 = 37.0
        assert data["selection_score"] == pytest.approx(37.0, abs=0.01)


class TestPurchaseOrderTax:
    def _sourcing_ctx(self, category_name, protocol_code, model_label, budget=1000000):
        return setup_program_sourcing(
            category_name=category_name, protocol_code=protocol_code,
            model_label=model_label, budget_cents=budget,
        )

    def test_po_tax_per_line_then_sum_half_up_each_line(self, api):
        """PRD §3.3: "for each line the server computes `line_tax_cents` as `unit_price_cents` times `qty` times `tax_rate_bp` divided by 10000, rounded half-up to whole cents per line, and `tax_cents` is the sum of those per-line figures."
        PRD §3.3: "`total_cents` is then `subtotal_cents` plus `shipping_cents` plus `tax_cents`."

        Design: Difficulty/dual_variant_calc/po_tax_per_line_vs_sum_then_round
        """
        ctx = self._sourcing_ctx("Vacuums", "VAC-01", "ModelX")
        lines = [
            create_po_line_payload(ctx["sample"]["id"], unit_price_cents=333, qty=1, tax_rate_bp=1500)
            for _ in range(3)
        ]
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"], lines,
                buyer_alias="alias-7", retailer_name="BigBox Retail",
                receipt_doc_ref="RCPT-1", shipping_cents=0,
            ),
            PA,
        )
        data = validate_success(resp, expected_status=201)
        # per line: round_half_up(333*1*1500/10000) = round_half_up(49.95) = 50; 50*3 = 150
        assert data["tax_cents"] == 150
        # subtotal 999 + shipping 0 + tax 150
        assert data["total_cents"] == 1149

    def test_po_tax_per_line_rounding_beats_sum_then_round(self, api):
        """PRD §3.3: "This matters: summing raw fractional tax across lines and rounding once would differ — three lines each with half a cent of raw tax yield 2 cents under the pinned rule but 1 cent under the rejected alternative."

        Design: Difficulty/combinatorial_formula/po_tax_nested_rounding_order
        """
        ctx = self._sourcing_ctx("Mowers", "MOW-01", "Mow1")
        # 3 lines of unit_price 1, qty 1, 5000 bp: raw tax 0.5 cents per line
        lines = [
            create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1, qty=1, tax_rate_bp=5000)
            for _ in range(3)
        ]
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"], lines,
                buyer_alias="alias-3", retailer_name="ToolMart",
                receipt_doc_ref="RCPT-3", shipping_cents=0,
            ),
            PA,
        )
        data = validate_success(resp, expected_status=201)
        # pinned: round_half_up(0.5) = 1 per line -> 3
        # rejected alternative (sum then round): round_half_up(1.5) = 2
        assert data["tax_cents"] == 3

    def test_po_subtotal_and_total_aggregation(self, api):
        """PRD §3.3: "The `subtotal_cents` is the sum over lines of `unit_price_cents` multiplied by `qty`."
        PRD §3.3: "`total_cents` is then `subtotal_cents` plus `shipping_cents` plus `tax_cents`."

        Design: Difficulty/dual_variant_calc/po_tax_per_line_vs_sum_then_round
        """
        ctx = self._sourcing_ctx("Washers", "WSH-T1", "WashT")
        lines = [
            create_po_line_payload(ctx["sample"]["id"], unit_price_cents=2000, qty=2, tax_rate_bp=1000),
            create_po_line_payload(ctx["sample"]["id"], unit_price_cents=500, qty=1, tax_rate_bp=0),
        ]
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"], lines,
                buyer_alias="alias-5", retailer_name="ShopMart",
                receipt_doc_ref="RCPT-5", shipping_cents=250,
            ),
            PA,
        )
        data = validate_success(resp, expected_status=201)
        # subtotal = 2000*2 + 500*1 = 4500
        # tax = round_half_up(2000*2*1000/10000) + 0 = 400
        # total = 4500 + 250 + 400 = 5150
        assert data["subtotal_cents"] == 4500
        assert data["tax_cents"] == 400
        assert data["total_cents"] == 5150


class TestMeasurementScore:
    def test_two_stage_mean_unequal_repeat_counts(self, api):
        """PRD §3.5: "first, for each distinct `metric_code`, average the `value_num` of all of the sample's measurements with that metric code across all unit indexes, rounding each per-metric mean half-up to two decimal places; second, average those per-metric means across the distinct metric codes, again rounding half-up to two decimal places."
        PRD §3.5: "Because each metric weighs equally regardless of how many repeats it received, this two-stage result differs from a flat mean over all raw rows whenever repeat counts per metric are unequal — the flat mean is a rejected alternative, not an acceptable shortcut."

        Design: Difficulty/dual_variant_calc/measurement_score_two_stage_vs_flat
        """
        ctx = setup_program_testing(
            category_name="Blenders", protocol_code="BLD-01",
            model_label="Blendy", required_units=1, repeat_min=1,
            perf_weight=50, reliability_weight=25,
            budget_cents=500000, measurement_value=100, metric_code="POWER",
        )
        sample_id = ctx["sample"]["id"]
        # POWER already has 1 measurement of 100; add 2 more POWER 100s and one NOISE 50
        for value, metric in [(100, "POWER"), (100, "POWER"), (50, "NOISE")]:
            resp = api.create_measurement(
                create_measurement_payload(sample_id, unit_index=1,
                                           metric_code=metric, value_num=value),
                LT,
            )
            validate_success(resp, expected_status=201)
        resp = api.transition_test_program(ctx["program"]["id"], {"action": "start_scoring"}, LM)
        validate_success(resp)
        sample = get_success_data(api.get_test_sample(sample_id, LM))
        # two-stage: POWER mean 100, NOISE mean 50, lab_score (100+50)/2 = 75.0
        # flat mean would be (100*3 + 50)/4 = 87.5
        assert sample["lab_score"] == pytest.approx(75.0, abs=0.01)

    def test_lab_score_null_until_scoring(self, api):
        """PRD §3.5: "Until the program reaches `SCORING`, a sample's `lab_score` is null."

        Design: Difficulty/dual_variant_calc/measurement_score_two_stage_vs_flat
        """
        ctx = setup_program_testing(
            category_name="Blenders", protocol_code="BLD-02",
            model_label="Blendy2", required_units=1, repeat_min=1,
            perf_weight=50, reliability_weight=25, measurement_value=90,
        )
        sample = get_success_data(api.get_test_sample(ctx["sample"]["id"], LM))
        assert sample["status"] == "IN_LAB"
        assert sample["lab_score"] is None
        resp = api.transition_test_program(ctx["program"]["id"], {"action": "start_scoring"}, LM)
        validate_success(resp)
        sample = get_success_data(api.get_test_sample(ctx["sample"]["id"], LM))
        assert sample["lab_score"] == pytest.approx(90.0, abs=0.01)


class TestPoTaxBoundarySecond:
    def test_po_tax_single_half_cent_line(self, api):
        """PRD §3.3: "for each line the server computes `line_tax_cents` as `unit_price_cents` times `qty` times `tax_rate_bp` divided by 10000, rounded half-up to whole cents per line, and `tax_cents` is the sum of those per-line figures."

        Design: Difficulty/combinatorial_formula/po_tax_nested_rounding_order
        """
        ctx = setup_program_sourcing(
            category_name="Mowers", protocol_code="MOW-09",
            model_label="Mow9", budget_cents=100000,
            market_share_pct=30, member_interest_pct=30, refresh_cycle_months=36,
        )
        # single line with raw tax exactly 0.5 cents: 1 * 1 * 5000 / 10000
        lines = [create_po_line_payload(ctx["sample"]["id"], unit_price_cents=1,
                                        qty=1, tax_rate_bp=5000)]
        resp = api.create_purchase_order(
            create_purchase_order_payload(
                ctx["program"]["id"], lines,
                buyer_alias="alias-h", retailer_name="ToolMart",
                receipt_doc_ref="RH", shipping_cents=0,
            ),
            TEST_USERS["purchasing_agent_headers"],
        )
        data = validate_success(resp, expected_status=201)
        # half-up rounding of 0.5 rounds up to 1
        assert data["tax_cents"] == 1
        assert data["subtotal_cents"] == 1
        assert data["total_cents"] == 2
