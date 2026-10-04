"""Receipts: variance valuation with per-line rounding, spend finalization,
provisional-vs-finalized open-to-buy variants, and immediate consistency."""
import pytest

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    get_season,
    setup_receipt_scenario,
    validate_error,
    validate_paginated,
    validate_success,
)

CLERK = TEST_USERS["warehouse_clerk_headers"]
AUDITOR = TEST_USERS["shrink_auditor_headers"]
PLANNER = TEST_USERS["planning_lead_headers"]


def _lines(api, receipt_id):
    data, _meta = validate_paginated(api.list_receipt_lines(receipt_id, CLERK))
    return data


class TestProvisionalVsFinalizedSpend:
    def test_provisional_commitment_vs_finalized_receipt_spend(self, api):
        """PRD §3.1: "The spend side finalizes at receipt completion: for each
        receipt line, the extended cost is the line's `received_qty` multiplied by
        the lot's `landed_cost_cents` divided by the lot's `unit_count`, rounded
        half-up to integer cents; `spent_forward_cents` is the sum of extended
        cost over receipt lines on `RECEIVED` receipts whose lot's disposition is
        `IMMEDIATE`".

        Design: Difficulty/dual_variant_calc/open_to_buy_provisional_commitment_vs_finalized_receipt_spend
        """
        scenario = setup_receipt_scenario(
            received_qty=30,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_specs=[{"quantity": 40, "unit_cost_cents": 150_000,
                         "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000}],
        )
        validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        season = get_season(scenario["base"]["season"]["id"])
        assert season["committed_forward_cents"] == 6_150_000
        assert season["spent_forward_cents"] == 4_612_500
        assert season["over_spend_alert"] is False
        line = _lines(api, scenario["receipt"]["id"])[0]
        assert line["variance_qty"] == 10
        assert line["variance_value_cents"] == 1_537_500

    def test_completion_files_one_open_shrink_case_per_short_line(self, api):
        """PRD §3.5: "For every line with a positive variance, the system files
        one **ShrinkCase** in `OPEN`: unattributed to any store (`store_id` null,
        `store_sku_id` null), tied to the receipt's lot, with `shrink_type`
        `MIXED_LOT_SHORTAGE` when the lot is `mixed_lot` and `UNSCANNED_UNIT`
        otherwise".

        Design: Difficulty/dual_variant_calc/open_to_buy_provisional_commitment_vs_finalized_receipt_spend
        """
        scenario = setup_receipt_scenario(
            received_qty=30,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_specs=[{"quantity": 40, "unit_cost_cents": 150_000,
                         "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000}],
        )
        validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        cases, _meta = validate_paginated(api.list_lot_shrink_cases(scenario["lot"]["id"], AUDITOR))
        assert len(cases) == 1
        assert cases[0]["shrink_type"] == "UNSCANNED_UNIT"
        assert cases[0]["units_untraceable"] == 10
        assert cases[0]["status"] == "OPEN"


class TestPerLineRoundingOrder:
    def test_extended_cost_rounded_per_line_before_summing(self, api):
        """PRD §3.5: "Completion runs **variance valuation** in a pinned order —
        each line is valued first, then results are summed; never a lot-average."

        Design: Difficulty/combinatorial_formula/receipt_variance_per_line_rounding_order_pinned
        """
        scenario = setup_receipt_scenario(
            received_qty=[1, 1],
            lot_overrides={"asking_price_cents": 1_000_001, "negotiated_price_cents": 1_000_001,
                           "unit_count": 3, "expected_sell_through_pct": 0.9,
                           "estimated_unit_retail_cents": 500_000},
            line_specs=[
                {"style_code": "RND-A", "department": "HOME", "quantity": 2,
                 "unit_cost_cents": 333_333, "compare_at_claim_cents": 900_000,
                 "target_retail_cents": 500_000},
                {"style_code": "RND-B", "department": "HOME", "quantity": 1,
                 "unit_cost_cents": 333_334, "compare_at_claim_cents": 900_000,
                 "target_retail_cents": 500_000},
            ],
        )
        validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        lines = _lines(api, scenario["receipt"]["id"])
        assert lines[0]["extended_cost_cents"] == 383_334
        assert lines[1]["extended_cost_cents"] == 383_334
        season = get_season(scenario["base"]["season"]["id"])
        assert season["spent_forward_cents"] == 766_668

    def test_variance_value_per_line(self, api):
        """PRD §3.5: "`variance_value_cents` is the variance quantity times the
        same per-unit basis, again rounded half-up."

        Design: Difficulty/combinatorial_formula/receipt_variance_per_line_rounding_order_pinned
        """
        scenario = setup_receipt_scenario(
            received_qty=[1, 1],
            lot_overrides={"asking_price_cents": 1_000_001, "negotiated_price_cents": 1_000_001,
                           "unit_count": 3, "expected_sell_through_pct": 0.9,
                           "estimated_unit_retail_cents": 500_000},
            line_specs=[
                {"style_code": "RND-A", "department": "HOME", "quantity": 2,
                 "unit_cost_cents": 333_333, "compare_at_claim_cents": 900_000,
                 "target_retail_cents": 500_000},
                {"style_code": "RND-B", "department": "HOME", "quantity": 1,
                 "unit_cost_cents": 333_334, "compare_at_claim_cents": 900_000,
                 "target_retail_cents": 500_000},
            ],
        )
        validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        lines = _lines(api, scenario["receipt"]["id"])
        assert lines[0]["variance_qty"] == 1
        assert lines[0]["variance_value_cents"] == 383_334
        assert lines[1]["variance_qty"] == 0
        assert lines[1]["variance_value_cents"] == 0


class TestImmediateConsistency:
    def test_cascade_writes_visible_in_next_read(self, api):
        """PRD §3.5: "Completion also finalizes the season's spend side per §3.1 —
        `spent_forward_cents` and `spent_packaway_cents` are recomputed from
        extended costs, and the season's `version` increments — and bumps the
        receipt's own `version`."

        Design: Corner/consistency_model/immediate_consistency_of_cascade_writes_in_same_read
        """
        scenario = setup_receipt_scenario(
            received_qty=30,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_specs=[{"quantity": 40, "unit_cost_cents": 150_000,
                         "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000}],
        )
        completed = validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        assert completed["status"] == "RECEIVED"
        season = get_season(scenario["base"]["season"]["id"])
        assert season["spent_forward_cents"] == 4_612_500
        cases, _meta = validate_paginated(api.list_lot_shrink_cases(scenario["lot"]["id"], AUDITOR))
        assert len(cases) == 1
        assert cases[0]["units_untraceable"] == 10
        assert cases[0]["status"] == "OPEN"

    def test_receipt_version_bumped_by_completion(self, api):
        """PRD §3.5: "Completion also finalizes the season's spend side per §3.1
        ... and bumps the receipt's own `version`."

        Design: Corner/consistency_model/immediate_consistency_of_cascade_writes_in_same_read
        """
        scenario = setup_receipt_scenario(
            received_qty=40,
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_specs=[{"quantity": 40, "unit_cost_cents": 150_000,
                         "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000}],
        )
        assert scenario["receipt"]["version"] == 1
        completed = validate_success(api.complete_receipt(scenario["receipt"]["id"], CLERK))
        assert completed["version"] == 2
        receipt = validate_success(api.get_receipt(scenario["receipt"]["id"], CLERK))
        assert receipt["version"] == 2


class TestReceiptLineQtyGuards:
    def test_received_qty_above_declared_rejected(self, api):
        """PRD §3.5: "the clerk records each line's `received_qty` — which must
        lie between 0 and the declared quantity inclusive, else
        `ERR_RECEIPT_LINE_QTY_INVALID`."

        Design: Corner/validations/receipt_line_received_qty_above_declared_rejected
        """
        scenario = setup_receipt_scenario(
            lot_overrides={"asking_price_cents": 6_000_000, "negotiated_price_cents": 6_000_000,
                           "unit_count": 40, "expected_sell_through_pct": 0.8,
                           "estimated_unit_retail_cents": 20_000},
            line_specs=[{"quantity": 40, "unit_cost_cents": 150_000,
                         "compare_at_claim_cents": 40_000, "target_retail_cents": 20_000}],
        )
        line = scenario["receipt_lines"][0]
        res = api.update_receipt_line(scenario["receipt"]["id"], line["id"], {"received_qty": 41}, CLERK)
        validate_error(res, ApiErrorId.ERR_RECEIPT_LINE_QTY_INVALID)
        receipt = validate_success(api.get_receipt(scenario["receipt"]["id"], CLERK))
        assert receipt["status"] == "OPEN"
