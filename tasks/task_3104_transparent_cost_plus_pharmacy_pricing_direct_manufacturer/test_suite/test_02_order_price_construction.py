"""Order price construction: markup, fees and the shipping-waiver fixed point."""
from test_helpers import (
    create_order_payload,
    get_success_data,
    create_sourced_price,
    setup_full_stack,
    reset_clock,
    OPS,

)


class TestShippingWaiverFixedPoint:

    def test_provisional_total_at_or_above_threshold_waives_shipping(self, api):
        """PRD §3.6: "the order's shipping_fee_cents is 0 when the provisional
        total is at least 1500 cents, and 500 otherwise."
        PRD §3.6: "The waive is therefore genuinely absent from the total rather
        than offset later: when the provisional total fell below 1500 cents the
        shipping fee stays 500 and the patient price equals the provisional
        total, and when the provisional total reached 1500 cents the shipping
        fee becomes 0 and the patient price equals the provisional total minus
        500."

        Design: Difficulty/combinatorial_formula/order_price_fixed_point_shipping_waiver_then_markup
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 200, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            ctx["primary_price"]["id"], quantity=60,
        ), OPS))
        paid = pay(api, order["id"])

        assert paid["acquisition_cost_cents"] == 200, (
            "the blended total 200 * 60 = 12000 is divided back down to a "
            "per-unit 200 before any markup is applied"
        )
        assert paid["markup_cents"] == 30, "15 percent of 200 is exactly 30"
        assert paid["pharmacy_fee_cents"] == 800
        assert paid["shipping_fee_cents"] == 0, (
            "the provisional total 200 + 30 + 800 + 500 = 1530 reaches the "
            "1500-cent threshold, so the 500-cent shipping fee is waived"
        )
        assert paid["patient_price_cents"] == 1030, (
            "the waived fee is genuinely absent: 200 + 30 + 800 + 0 = 1030, "
            "which is the provisional 1530 minus the waived 500"
        )

    def test_patient_price_is_never_re_tested_against_the_threshold(self, api):
        """PRD §3.6: "The final total is never re-tested against the 1500-cent threshold after the waiver, so waiving shipping can never reinstate it."
        PRD §3.6: "The order's patient_price_cents is the acquisition cost plus
        markup_cents plus pharmacy_fee_cents plus shipping_fee_cents, as an
        exact integer sum with no further rounding."

        Design: Difficulty/combinatorial_formula/order_price_fixed_point_shipping_waiver_then_markup
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 200, "available_units": 600,
                        "reliability_tier": "A"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            ctx["primary_price"]["id"], quantity=60,
        ), OPS))
        paid = pay(api, order["id"])

        assert paid["patient_price_cents"] == (
            paid["acquisition_cost_cents"]
            + paid["markup_cents"]
            + paid["pharmacy_fee_cents"]
            + paid["shipping_fee_cents"]
        ), "the final total is the exact integer sum of the settled parts"
        assert paid["patient_price_cents"] == 1030
        assert paid["patient_price_cents"] != 1530, (
            "1530 is the provisional figure a single-pass reading that "
            "reassembled before waiving would report"
        )


class TestMarkupRoundingSite:

    def test_markup_is_rounded_on_the_per_unit_acquisition_cost(self, api):
        """PRD §3.6: "The order's markup_cents is the rounded 15 percent figure"
        applied to the acquisition cost produced by step one.
        PRD §2.6: "The markup is a fixed rate of 15 percent applied to the
        acquisition cost."

        Design: Difficulty/combinatorial_formula/order_price_round_per_unit_before_markup_not_after
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 16, "available_units": 400,
                        "reliability_tier": "C", "packaging": "400-count bottle"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        short_source = create_sourced_row(
            ctx, unit_cost_cents=12, available_units=20, packaging="20-count bottle"
        )
        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            short_source["id"], quantity=60,
            sub_source_price_id=ctx["prices"][0]["id"],
        ), OPS))
        paid = pay(api, order["id"])

        assert paid["acquisition_cost_cents"] == 15, (
            "the blend 12*20 + 16*40 = 880 cents is divided back down by the "
            "quantity 60 and rounded half up, giving 15"
        )
        assert paid["markup_cents"] == 2, (
            "15 percent of the rounded per-unit acquisition cost 15 is 2.25, "
            "rounded half up to 2"
        )

    def test_blended_order_ships_at_the_unwaived_fee(self, api):
        """PRD §3.6: "when the provisional total fell below 1500 cents the shipping fee stays 500 and the patient price equals the provisional total, and when the provisional total reached 1500 cents the shipping fee becomes 0 and the patient price equals the provisional total minus 500."

        Design: Difficulty/combinatorial_formula/order_price_round_per_unit_before_markup_not_after
        """
        reset_clock()
        ctx = setup_full_stack(
            drug_rows=[{"unit_cost_cents": 16, "available_units": 400,
                        "reliability_tier": "C", "packaging": "400-count bottle"}],
            formulary=True, quantity=60, packaged_quantity=100,
        )
        short_source = create_sourced_row(
            ctx, unit_cost_cents=12, available_units=20, packaging="20-count bottle"
        )
        order = get_success_data(api.create_order(create_order_payload(
            ctx["prescription"]["id"], ctx["request"]["id"], ctx["pharmacy"]["id"],
            short_source["id"], quantity=60,
            sub_source_price_id=ctx["prices"][0]["id"],
        ), OPS))
        paid = pay(api, order["id"])

        assert paid["pharmacy_fee_cents"] == 800
        assert paid["shipping_fee_cents"] == 500, (
            "the provisional total 15 + 2 + 800 + 500 = 1317 stays below the "
            "1500-cent threshold, so the fee is not waived"
        )
        assert paid["patient_price_cents"] == 1317


# ─── local helpers ────────────────────────────────────

def pay(api, order_id):
    return get_success_data(api.pay_order(order_id, OPS))


def create_sourced_row(ctx, **row_overrides):
    """Add one more ACTIVE+SOURCED row to the context's drug."""
    return create_sourced_price(ctx["drug"]["id"], ctx["manufacturer"]["id"], **row_overrides)