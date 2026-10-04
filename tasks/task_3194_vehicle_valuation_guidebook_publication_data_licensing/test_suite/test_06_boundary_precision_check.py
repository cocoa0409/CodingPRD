"""Difficulty rule: boundary_precision_check.

Numeric threshold boundaries: the confidence publish gate at exactly 0.25.
"""
import pytest

from test_helpers import (
    api_client, validate_success,
    make_region, make_config, make_source, make_series, get_series,
    submit_accepted_batch, create_batch_item_payload,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestConfidenceGateExactlyAt025Publishes:
    def _setup_nine_stale_items(self):
        region = make_region(region_code="EAST")
        config = make_config(segment="SEDAN", external_key="cfg-bp")
        source = make_source(region["id"], source_type="DEALER",
                             external_key="src-bp", name="BPD")
        items = [
            create_batch_item_payload(
                config["id"], region["id"], sold_price_cents=2000000,
                sale_date="2026-07-31", mileage=10000 + i)
            for i in range(9)
        ]
        submit_accepted_batch(source["id"], items, submission_ref="b-bp")
        series = make_series(config["id"], region["id"],
                             external_key="ser-bp")
        return series

    def test_confidence_computes_to_exactly_0_25(self, api):
        """PRD §3.3: "Volume contributes one half of the score: the count of
        matching items divided by 30, capped at 1, then halved" and "Source
        diversity contributes three tenths" and "Recency contributes the
        remaining two tenths: the fraction of the window's items whose
        sale_date falls within the last 30 days." and "The three weighted
        terms sum, and the result is rounded half-up to 4 decimal places."

        9 items, one source type, none recent:
        0.5*(9/30) + 0.3*(1/3) + 0.2*0 = 0.2500.

        Design: Difficulty/boundary_precision_check/confidence_gate_exactly_at_0_25_publishes
        """
        series = self._setup_nine_stale_items()
        fetched = get_series(series["id"])
        assert fetched["confidence_score"] == pytest.approx(0.25, abs=1e-9)

    def test_publish_succeeds_at_exactly_the_gate(self, api):
        """PRD §3.4: "the series' confidence_score is at least 0.25
        (otherwise ERR_LOW_CONFIDENCE, HTTP 422)". The gate is >=, so a score
        of exactly 0.2500 publishes.

        Design: Difficulty/boundary_precision_check/confidence_gate_exactly_at_0_25_publishes
        """
        series = self._setup_nine_stale_items()
        assert get_series(series["id"])["confidence_score"] == pytest.approx(0.25, abs=1e-9)
        edition = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-01T00:00:00Z"},
            ADMIN), 201)
        published = validate_success(
            api.publish_valuation_edition(edition["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"
