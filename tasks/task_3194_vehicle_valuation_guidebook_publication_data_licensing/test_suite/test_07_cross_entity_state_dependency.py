"""Difficulty rule: cross_entity_state_dependency.

One entity's transition is gated by another entity's state or derived field.
"""
from test_helpers import (
    api_client, validate_success, validate_error, validate_paginated,
    make_region, make_config, make_source, make_series, get_series,
    submit_accepted_batch, reject_n_batches,
    setup_offer_scenario, inspect_offer, get_offer,
    create_batch_item_payload, make_dealer_headers, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS
import pytest


class TestEditionPublishGatedBySeriesConfidence:
    def _setup_low_confidence_series(self):
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN", external_key="cfg-ce")
        source = make_source(region["id"], source_type="DEALER",
                             external_key="src-ce", name="CED")
        submit_accepted_batch(source["id"], [
            create_batch_item_payload(config["id"], region["id"],
                                      sold_price_cents=2000000,
                                      sale_date="2026-07-31", mileage=10000),
        ], submission_ref="b-ce")
        series = make_series(config["id"], region["id"],
                             external_key="ser-ce")
        return region, config, source, series

    def test_confidence_below_gate_blocks_publish(self, api):
        """PRD §3.4: "the series' confidence_score is at least 0.25
        (otherwise ERR_LOW_CONFIDENCE, HTTP 422)".

        One stale item from one source type: 0.5*(1/30) + 0.3*(1/3) + 0.2*0
        = 0.1167 < 0.25.

        Design: Difficulty/cross_entity_state_dependency/edition_publish_gated_by_series_confidence
        """
        region, config, source, series = self._setup_low_confidence_series()
        assert get_series(series["id"])["confidence_score"] == pytest.approx(
            0.1167, abs=1e-4)
        edition = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
            ADMIN), 201)
        res = api.publish_valuation_edition(edition["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_LOW_CONFIDENCE.value)

    def test_rejected_publish_leaves_edition_pending(self, api):
        """PRD §3.4: "the series' confidence_score is at least 0.25
        (otherwise ERR_LOW_CONFIDENCE, HTTP 422)" and the edition starts
        PENDING — a rejected publish must not advance it.

        Design: Difficulty/cross_entity_state_dependency/edition_publish_gated_by_series_confidence
        """
        region, config, source, series = self._setup_low_confidence_series()
        edition = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
            ADMIN), 201)
        validate_error(api.publish_valuation_edition(edition["id"], ADMIN),
                       ApiErrorId.ERR_LOW_CONFIDENCE.value)
        fetched = validate_success(
            api.get_valuation_edition(edition["id"], ADMIN), 200)
        assert fetched["status"] == "PENDING"


class TestOfferRedeemGatedByFundingSourceStatus:
    def test_redeem_with_suspended_funding_dealer_rejected(self, api):
        """PRD §3.6: "Redemption moves INSPECTED -> REDEEMED, requires the
        same not-expired clock check, and additionally requires the funding
        source to be ACTIVE — redeeming against a suspended funding dealer is
        rejected with ERR_INVALID_STATE (HTTP 409)."

        Design: Difficulty/cross_entity_state_dependency/offer_redeem_gated_by_funding_source_status
        """
        env = setup_offer_scenario(segment="SEDAN", price_cents=2000000)
        offer = inspect_offer(env["offer"]["id"], env["source"]["id"], "GOOD")
        assert offer["status"] == "INSPECTED"

        reject_n_batches(env["source"]["id"], env["configuration"]["id"],
                         env["region"]["id"], 5, "ce2")
        from test_helpers import get_source
        assert get_source(env["source"]["id"])["status"] == "SUSPENDED"

        res = api.redeem_cash_offer(
            offer["id"], make_dealer_headers(env["source"]["id"]))
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)

    def test_rejected_redeem_leaves_offer_inspected(self, api):
        """PRD §3.6: "Redemption moves INSPECTED -> REDEEMED, requires the
        same not-expired clock check, and additionally requires the funding
        source to be ACTIVE — redeeming against a suspended funding dealer is
        rejected with ERR_INVALID_STATE (HTTP 409)." A rejected redeem must
        leave the offer INSPECTED.

        Design: Difficulty/cross_entity_state_dependency/offer_redeem_gated_by_funding_source_status
        """
        env = setup_offer_scenario(segment="SEDAN", price_cents=2000000)
        offer = inspect_offer(env["offer"]["id"], env["source"]["id"], "GOOD")

        reject_n_batches(env["source"]["id"], env["configuration"]["id"],
                         env["region"]["id"], 5, "ce2b")
        validate_error(
            api.redeem_cash_offer(
                offer["id"], make_dealer_headers(env["source"]["id"])),
            ApiErrorId.ERR_INVALID_STATE.value)
        assert get_offer(offer["id"])["status"] == "INSPECTED"
