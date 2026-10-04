"""Difficulty rule: resource_temporal_overlap.

Edition weekly cadence minimum-gap semantics; MarketShift scope-bucket
non-overlap semantics.
"""
from test_helpers import (
    api_client, validate_success, validate_error,
    make_region, make_config, make_source, make_series, make_edition,
    setup_published_edition, create_market_shift_payload,
    get_edition, ApiErrorId,
)
from test_helpers.fixtures import ADMIN, DATAOPS


class TestEditionWeeklyCadenceMinimumGap:
    def _setup_series_with_first_edition(self):
        env = setup_published_edition(segment="SEDAN", price_cents=2000000)
        return env

    def test_second_edition_within_seven_days_rejected(self, api):
        """PRD §3.4: "because the cadence is WEEKLY — no other PUBLISHED
        edition of the same series has an effective_at within 7 days of this
        one, while the very first edition published for the series must have
        effective_at exactly equal to the series' effective_from (violations
        surface as ERR_CADENCE_VIOLATION, HTTP 422)."

        A second edition 4 days after the first PUBLISHED edition is rejected
        and stays PENDING.

        Design: Difficulty/resource_temporal_overlap/edition_weekly_cadence_minimum_gap
        """
        env = self._setup_series_with_first_edition()
        series = env["series"]
        second = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-05T00:00:00Z"},
            ADMIN), 201)
        res = api.publish_valuation_edition(second["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_CADENCE_VIOLATION.value)
        assert get_edition(second["id"])["status"] == "PENDING"

    def test_edition_exactly_seven_days_later_publishes(self, api):
        """PRD §3.4: "no other PUBLISHED edition of the same series has an
        effective_at within 7 days of this one". Exactly 7 days is not within
        7 days, so the publish succeeds.

        Design: Difficulty/resource_temporal_overlap/edition_weekly_cadence_minimum_gap
        """
        env = self._setup_series_with_first_edition()
        series = env["series"]
        third = validate_success(api.create_valuation_edition(
            {"series_id": series["id"], "effective_at": "2026-09-08T00:00:00Z"},
            ADMIN), 201)
        published = validate_success(
            api.publish_valuation_edition(third["id"], ADMIN), 200)
        assert published["status"] == "PUBLISHED"


class TestMarketShiftNonoverlapPerScopeBucket:
    def _setup_active_region_shift(self, api):
        region = make_region(region_code="EAST")
        sh1 = validate_success(api.create_market_shift(
            create_market_shift_payload(region_id=region["id"], segment=None,
                                        effective_at="2026-09-01T00:00:00Z",
                                        pct_adjustment=0.02),
            ADMIN), 201)
        validate_success(api.activate_market_shift(sh1["id"], ADMIN), 200)
        return region

    def test_same_bucket_second_shift_activation_rejected(self, api):
        """PRD §3.5: "And no other ACTIVE shift may occupy the same scope
        bucket: two shifts share a bucket when both are fully global (both
        region_id and segment null), when both name the same region_id with
        null segment, when both name the same segment with null region_id, or
        when both name the same (region_id, segment) pair."

        A second (region EAST, segment null) shift cannot activate while the
        first is ACTIVE; the failure is a state-precondition failure
        (ERR_INVALID_STATE) and the shift stays DRAFT.

        Design: Difficulty/resource_temporal_overlap/market_shift_nonoverlap_per_scope_bucket
        """
        region = self._setup_active_region_shift(api)
        sh2 = validate_success(api.create_market_shift(
            create_market_shift_payload(region_id=region["id"], segment=None,
                                        effective_at="2026-09-03T00:00:00Z",
                                        pct_adjustment=0.01),
            ADMIN), 201)
        res = api.activate_market_shift(sh2["id"], ADMIN)
        validate_error(res, ApiErrorId.ERR_INVALID_STATE.value)
        # Stays DRAFT — confirm via the region-scoped shift listing.
        from test_helpers import validate_paginated
        data, meta = validate_paginated(api.list_region_market_shifts(
            region["id"], ADMIN))
        rows = {row["id"]: row["status"] for row in data}
        assert rows.get(sh2["id"]) == "DRAFT"

    def test_different_bucket_shift_activates(self, api):
        """PRD §3.5: "And no other ACTIVE shift may occupy the same scope
        bucket: two shifts share a bucket when both are fully global (both
        region_id and segment null), when both name the same region_id with
        null segment, when both name the same segment with null region_id, or
        when both name the same (region_id, segment) pair."

        A (region EAST, segment TRUCK) shift names a different bucket than
        (region EAST, segment null), so activation succeeds.

        Design: Difficulty/resource_temporal_overlap/market_shift_nonoverlap_per_scope_bucket
        """
        region = self._setup_active_region_shift(api)
        sh3 = validate_success(api.create_market_shift(
            create_market_shift_payload(region_id=region["id"], segment="TRUCK",
                                        effective_at="2026-09-03T00:00:00Z",
                                        pct_adjustment=0.01),
            ADMIN), 201)
        activated = validate_success(
            api.activate_market_shift(sh3["id"], ADMIN), 200)
        assert activated["status"] == "ACTIVE"
