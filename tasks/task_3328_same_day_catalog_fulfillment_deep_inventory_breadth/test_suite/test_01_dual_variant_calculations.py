"""Dual-variant calculations across the order-money and pipe-length domains."""

from test_helpers import (
    PICKER,
    confirm_cutoff,
    list_lines,
    setup_five_line_fee_order,
    setup_square_footage_quote,
    validate_success,
)


class TestOrderTotalVariantDivergenceAfterCutoff:
    """The same five lines price differently once the shipment cutoff is certified."""

    PRICES = [36000, 18000, 7000, 6000, 5000]

    def _allocated(self, api):
        scenario = setup_five_line_fee_order(
            api, prices=self.PRICES, quantities=[1, 1, 1, 1, 1])
        order = validate_success(api.allocate_order(
            scenario["order"]["id"],
            {"expected_order_version": scenario["order"]["version"]},
            scenario["acct_headers"]))
        return scenario, order

    def _shipped(self, api):
        scenario, order = self._allocated(api)
        for line in list_lines(api, scenario["acct"], scenario["order"]):
            api.pick_line(scenario["order"]["id"], line["id"], {"requested_units": 1}, PICKER)
            api.complete_pick(scenario["order"]["id"], line["id"], {"actual_units": 1}, PICKER)
        shipment = confirm_cutoff(api, order=scenario["order"], account=scenario["acct"])
        after = validate_success(api.get_order(scenario["order"]["id"],
                                               scenario["acct_headers"]))
        return scenario, after, shipment

    def test_before_the_cutoff_the_order_carries_the_own_precision_total(self, api):
        """PRD §3.5: "Take five eligible lines with `line_subtotal_cents` of 36000,
        18000, 7000, 6000 and 5000 — a material subtotal of 72000 cents."
        PRD §3.5: "Under the own-precision variant the per-line fees are 1080, 540, 210,
        180 and 150 cents, summing to a fee term of 2160 cents and an order total of 72000
        cents".

        Design: Difficulty/dual_variant_calc/order_total_variant_divergence_after_cutoff
        """
        scenario, order = self._allocated(api)

        assert order["line_count"] == 5
        assert order["order_total_cents"] == 72000, (
            f"own-precision total expected 72000, got {order['order_total_cents']}"
        )
        assert order["order_total_cents"] != 73588, (
            "before the cutoff the order has not yet re-priced onto the handling pool"
        )

    def test_after_the_cutoff_the_order_re_prices_onto_the_handling_pool(self, api):
        """PRD §3.5: "The second variant, which applies once `shipment_status` has become
        `CUTOFF_CONFIRMED` and the order is re-priced, uses instead the handling pool
        produced by the calculation above".
        PRD §3.5: "Either way the order total is the discounted material base plus the fee
        term, and the precision rule holds throughout: the material base rounds once for
        the order, each variant's fee term rounds in its own way, and neither is rounded
        again when they are added."

        Design: Difficulty/dual_variant_calc/order_total_variant_divergence_after_cutoff
        """
        scenario, order, shipment = self._shipped(api)

        assert shipment["shipment_status"] == "CUTOFF_CONFIRMED"
        assert order["order_total_cents"] == 73588, (
            f"handling-pool total expected 73588, got {order['order_total_cents']}"
        )
        assert order["total_small_line_fee_cents"] == 3748, (
            f"the re-priced fee term expected 3748, got "
            f"{order['total_small_line_fee_cents']}"
        )
        assert order["order_total_cents"] - 72000 == 1588, (
            "the two variants carry the identical lines and diverge by exactly 1588 cents"
        )


class TestPipeLengthVariantDivergenceBeforeAndAfterFirstCut:
    """The consignment commitment flips variant and drops at the first recorded cut."""

    def test_while_quoted_the_forward_looking_variant_seeds_the_prior_figure(self, api):
        """PRD §3.10: "A request's `committed_variant` is `FORWARD_LOOKING` while its
        `request_status` is `QUOTED`, and flips to `ON_HAND_ONLY` once any one of its lines
        has reached `line_status` `CUT`."
        PRD §3.10: "while the request is still `QUOTED` this field is seeded equal to
        `committed_length_feet`, and at the first cut it captures the forward-looking
        figure before the variant flips."

        Design: Difficulty/dual_variant_calc/pipe_length_variant_divergence_before_and_after_first_cut
        """
        scenario = setup_square_footage_quote(api, requested_feet=[40, 60, 50])
        request = validate_success(api.get_square_footage_request(
            scenario["request"]["id"], scenario["acct_headers"]))

        assert request["request_status"] == "QUOTED"
        assert request["committed_variant"] == "FORWARD_LOOKING"
        assert request["prior_committed_length_feet"] == request["committed_length_feet"]

    def test_the_first_cut_flips_the_variant_and_lowers_the_commitment(self, api):
        """PRD §3.10: "The two variants differ in the stock pool the running figure is
        drawn from, and in the allowance added at the end."
        PRD §3.10: "The distinction is not cosmetic — the on-hand-only figure is strictly
        lower whenever the two allowances differ, because it replaces the cut-in-progress
        allowance with the smaller finished-goods allowance."

        Design: Difficulty/dual_variant_calc/pipe_length_variant_divergence_before_and_after_first_cut
        """
        scenario = setup_square_footage_quote(api, requested_feet=[40, 60, 50])
        before = validate_success(api.get_square_footage_request(
            scenario["request"]["id"], scenario["acct_headers"]))
        quoted_forward = before["committed_length_feet"]

        validate_success(api.cut_square_footage_request(
            scenario["request"]["id"], {"cut_list_ordinal": 3}, PICKER))

        after = validate_success(api.get_square_footage_request(
            scenario["request"]["id"], scenario["acct_headers"]))
        assert after["committed_variant"] == "ON_HAND_ONLY"
        assert after["prior_committed_length_feet"] == quoted_forward, (
            "the prior figure captures the forward-looking value at the first cut"
        )
        assert after["committed_length_feet"] < quoted_forward, (
            "the on-hand-only commitment is strictly lower because its allowance is smaller"
        )