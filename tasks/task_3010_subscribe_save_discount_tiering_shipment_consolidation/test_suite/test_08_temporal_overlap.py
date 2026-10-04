"""Temporal overlap semantics: half-open promotion windows vs strict
price-event monotonicity (PRD §3.8, §2.9)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    create_price_event_payload,
    create_product,
    create_promotion_payload,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestPromotionWindowOverlap:
    def _setup_promotion(self):
        set_clock()
        bonus = create_product()
        first = validate_success(api_client.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=3,
                starts_on="2026-09-01", ends_on="2026-10-01"),
            ADMIN), expected_status=201)
        return bonus, first

    def test_overlapping_window_rejected_but_adjacency_allowed(self):
        """PRD §3.8: "Two `ACTIVE` promotions for the same bonus product may
        not have overlapping half-open windows; a conflicting creation is
        rejected with `ERR_PROMOTION_WINDOW_OVERLAP` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/promotion_windows_half_open_overlap_but_adjacency_allowed
        """
        bonus, first = self._setup_promotion()
        overlap = api_client.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=2,
                starts_on="2026-09-15", ends_on="2026-11-01"),
            ADMIN)
        validate_error(overlap, ApiErrorId.ERR_PROMOTION_WINDOW_OVERLAP)
        adjacent = validate_success(api_client.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=2,
                starts_on="2026-10-01", ends_on="2026-11-01"),
            ADMIN), expected_status=201)
        assert adjacent["promotion_status"] == "ACTIVE"

    def test_adjacent_window_shares_exclusive_bound_at_201(self):
        """PRD §3.8: "A `PlatformAdmin` creates a promotion naming a
        `bonus_product_id`, a `min_line_count`, and a half-open window
        `starts_on` to `ends_on`. Two `ACTIVE` promotions for the same bonus
        product may not have overlapping half-open windows".

        Design: Difficulty/resource_temporal_overlap/promotion_windows_half_open_overlap_but_adjacency_allowed
        """
        bonus, first = self._setup_promotion()
        adjacent = api_client.create_promotion(
            create_promotion_payload(
                bonus["id"], min_line_count=2,
                starts_on="2026-10-01", ends_on="2026-11-01"),
            ADMIN)
        assert adjacent.status_code == 201
        assert adjacent.json()["data"]["promotion_status"] == "ACTIVE"


class TestPriceEventMonotonicity:
    def _setup_priced_product(self):
        set_clock()
        product = create_product()
        validate_success(api_client.create_price_event(
            product["id"],
            create_price_event_payload(1000, "2026-09-01T00:00:00Z"),
            ADMIN), expected_status=201)
        return product

    def test_equal_effective_from_collides_next_instant_accepted(self):
        """PRD §2.9: "Price events for a product must be strictly increasing
        in `effective_from`: appending an event whose `effective_from` is not
        strictly greater than every existing event for that product is
        rejected with `ERR_PRICE_EVENT_NOT_MONOTONIC` (HTTP 409)."

        Design: Difficulty/resource_temporal_overlap/price_event_equal_effective_from_collides_closed_point_semantics
        """
        product = self._setup_priced_product()
        dup = api_client.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-01T00:00:00Z"),
            ADMIN)
        validate_error(dup, ApiErrorId.ERR_PRICE_EVENT_NOT_MONOTONIC)
        ok = validate_success(api_client.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-01T00:00:01Z"),
            ADMIN), expected_status=201)
        assert ok["price_cents"] == 1100

    def test_price_history_lists_exactly_two_events_after_retry(self):
        """PRD §2.9: "Price events for a product must be strictly increasing
        in `effective_from`".
        PRD §4: price history can be listed per product ("their price history
        can be listed per product" — §3.1).

        Design: Difficulty/resource_temporal_overlap/price_event_equal_effective_from_collides_closed_point_semantics
        """
        product = self._setup_priced_product()
        dup = api_client.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-01T00:00:00Z"),
            ADMIN)
        assert dup.status_code == 409
        validate_success(api_client.create_price_event(
            product["id"],
            create_price_event_payload(1100, "2026-09-01T00:00:01Z"),
            ADMIN), expected_status=201)
        events, _meta = validate_paginated(
            api_client.list_price_events(product["id"], ADMIN))
        assert len(events) == 2
