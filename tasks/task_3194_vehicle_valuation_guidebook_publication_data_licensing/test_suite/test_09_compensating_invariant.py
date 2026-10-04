"""Difficulty rule: compensating_invariant.

Conserved quantities: the source rejection counter across reject/accept
cycles; the dealer-liability floor across inspection re-pricing.
"""
from test_helpers import (
    api_client, validate_success,
    make_region, make_config, make_source, get_source,
    submit_accepted_batch, submit_rejected_batch,
    setup_offer_scenario, create_batch_item_payload, make_dealer_headers,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestRejectAcceptCyclesKeepRejectionCounterConserved:
    def _setup_source_with_reject_accept(self, key_suffix):
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN",
                             external_key=f"cfg-ci1{key_suffix}")
        source = make_source(region["id"], source_type="DEALER",
                             external_key=f"src-ci1{key_suffix}", name="CI1")
        submit_rejected_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"]),
        ], submission_ref=f"ci1-r1{key_suffix}")
        submit_rejected_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"]),
        ], submission_ref=f"ci1-r2{key_suffix}")
        submit_accepted_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"]),
        ], submission_ref=f"ci1-a1{key_suffix}")
        return region, config, source

    def test_accept_resets_counter_to_zero(self, api):
        """PRD §3.2: "Acceptance is the productive path: a VALIDATED batch
        moves to ACCEPTED, its accepted_count is set to the number of items
        ingested, and the submitting source's consecutive_rejections resets
        to zero."

        After reject, reject, accept the counter is 0 and the source is still
        ACTIVE (no suspension despite the two earlier rejects).

        Design: Difficulty/compensating_invariant/reject_accept_cycles_keep_rejection_counter_conserved
        """
        region, config, source = self._setup_source_with_reject_accept("a")
        fetched = get_source(source["id"])
        assert fetched["consecutive_rejections"] == 0
        assert fetched["status"] == "ACTIVE"

    def test_reject_after_accept_counts_from_zero(self, api):
        """PRD §3.2: "Rejection moves it RECEIVED -> REJECTED and increments
        the submitting source's consecutive_rejections" and "Acceptance is
        the productive path: a VALIDATED batch moves to ACCEPTED, its
        accepted_count is set to the number of items ingested, and the
        submitting source's consecutive_rejections resets to zero."

        A further reject after the accept sets consecutive_rejections to
        exactly 1, not 3 — the counter never accumulates across the
        interleaved cycles.

        Design: Difficulty/compensating_invariant/reject_accept_cycles_keep_rejection_counter_conserved
        """
        region, config, source = self._setup_source_with_reject_accept("b")
        submit_rejected_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"]),
        ], submission_ref="ci1b-r3")
        fetched = get_source(source["id"])
        assert fetched["consecutive_rejections"] == 1


class TestOfferQuoteVsInspectionCapConservesDealerLiability:
    def test_good_quote_with_no_adjustments(self, api):
        """PRD §3.6: "The computation starts from the pinned edition's
        private_party_cents multiplied by the catalog multiplier of the
        declared condition tier, then applies the mileage-and-option
        adjustment."

        reference 3040000 -> private_party 2888000; GOOD multiplier 1.00;
        mileage 20000 with age 2 * 10000 expected -> excess 0; no options
        -> offer_amount_cents == 2888000.

        Design: Difficulty/compensating_invariant/offer_quote_vs_inspection_cap_conserves_dealer_liability
        """
        env = setup_offer_scenario(segment="SEDAN", price_cents=3040000,
                                   offer_overrides={"mileage": 20000,
                                                    "age_years": 2,
                                                    "declared_condition_tier": "GOOD",
                                                    "option_ids": []})
        assert env["offer"]["offer_amount_cents"] == 2888000

    def test_poor_inspection_capped_at_ninety_percent_of_quote(self, api):
        """PRD §3.6: "final_amount_cents is computed by the same formula as
        the quote, but at the inspected tier rather than the declared tier,
        and then capped below at 90 percent of the frozen offer_amount_cents
        (the cap computed by multiplying the quote by 0.90 and rounding
        half-up)".

        Raw POOR re-price = 2888000*0.70 = 2021600 (below the floor);
        floor = round_half_up(2888000 * 0.90) = 2599200 binds exactly.

        Design: Difficulty/compensating_invariant/offer_quote_vs_inspection_cap_conserves_dealer_liability
        """
        env = setup_offer_scenario(segment="SEDAN", price_cents=3040000,
                                   offer_overrides={"mileage": 20000,
                                                    "age_years": 2,
                                                    "declared_condition_tier": "GOOD",
                                                    "option_ids": []})
        offer = env["offer"]
        assert offer["offer_amount_cents"] == 2888000

        inspected = validate_success(api.inspect_cash_offer(
            offer["id"], {"inspected_condition_tier": "POOR"},
            make_dealer_headers(env["source"]["id"])), 200)
        assert inspected["final_amount_cents"] == 2599200
