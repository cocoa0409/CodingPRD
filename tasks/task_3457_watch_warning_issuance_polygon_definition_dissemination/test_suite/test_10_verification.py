"""Verification events, statistics variants, and office performance bands.

Adjudication matches CONFIRMED events to WARNING products polygon-strict;
statistics recompute set membership under the requested variant and cascade a
performance band onto the office (PRD §3.8).
"""

from test_helpers import (
    ApiErrorId,
    adjudicate_event,
    compute_statistic,
    create_and_confirm_event,
    create_event,
    create_warning_draft,
    get_event,
    get_office,
    get_product,
    issue_product,
    setup_issued_warning,
    setup_office_with_zone,
    square_polygon,
    validate_error,
)

LEFT_HALF = square_polygon(lon_max=0.05)
TINY_CORNER = {
    "vertices": [
        {"lat": 0.08, "lon": 0.08},
        {"lat": 0.08, "lon": 0.09},
        {"lat": 0.09, "lon": 0.09},
        {"lat": 0.09, "lon": 0.08},
    ]
}


def _setup_half_covered_warning_with_two_events(api):
    """A FLASH_FLOOD warning over the zone's left half (issued 10:00), plus two
    CONFIRMED events: E1 inside the polygon at 10:30, E2 inside the zone but
    outside the polygon at 10:40."""
    bundle = setup_issued_warning(
        api,
        hazard_type="FLASH_FLOOD",
        readings={"rainfall_rate_in_hr": 2.5},
        polygon=LEFT_HALF,
        expires_at="2026-09-01T11:00:00Z",
    )
    bundle.e1 = create_and_confirm_event(
        api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:30:00Z", 0.05, 0.02, "2.5in"
    )
    bundle.e2 = create_and_confirm_event(
        api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:40:00Z", 0.05, 0.075, "2.4in"
    )
    return bundle


class TestMatchingVariants:
    def test_polygon_strict_statistic_counts_only_in_polygon_events(self, api):
        """PRD §3.8: "Matching follows the requested variant: `POLYGON_STRICT`
        applies the containment rule of adjudication, while `COUNTY_FALLBACK`
        counts an event as matched when its `zone_id` appears in the product's
        `resolved_zone_ids`"
        PRD §3.8: "A `CONFIRMED` outcome stamps `adjudicated_at` and computes
        `matched_product_ids` under the polygon-strict rule applied across all
        offices' products"

        Design: Difficulty/dual_variant_calc/verification_matching_polygon_strict_vs_county_fallback
        """
        bundle = _setup_half_covered_warning_with_two_events(api)
        assert bundle.e1["matched_product_ids"] == [bundle.product["id"]]
        assert bundle.e2["matched_product_ids"] == [], (
            "adjudication always uses the polygon-strict rule"
        )

        stat = compute_statistic(
            api, bundle.office["id"], "FLASH_FLOOD", matching_variant="POLYGON_STRICT"
        )
        assert stat["total_warnings"] == 1
        assert stat["events_total"] == 2
        assert stat["events_warned"] == 1
        assert stat["events_unwarned"] == 1
        assert stat["false_alarms"] == 0
        assert stat["pod"] == 0.5
        assert stat["far"] == 0.0
        assert stat["avg_lead_time_minutes"] == 30.0, "E1's lead is exactly 30 minutes"

    def test_county_fallback_statistic_counts_covered_county_events(self, api):
        """PRD §3.8: "`COUNTY_FALLBACK` counts an event as matched when its
        `zone_id` appears in the product's `resolved_zone_ids` — so an event
        inside a covered county but outside the drawn polygon still counts as
        warned under the fallback, raising detection and lowering the false
        alarm ratio relative to the strict variant."

        Design: Difficulty/dual_variant_calc/verification_matching_polygon_strict_vs_county_fallback
        """
        bundle = _setup_half_covered_warning_with_two_events(api)
        stat = compute_statistic(
            api, bundle.office["id"], "FLASH_FLOOD", matching_variant="COUNTY_FALLBACK"
        )
        assert stat["total_warnings"] == 1
        assert stat["events_total"] == 2
        assert stat["events_warned"] == 2, "E2's zone is in resolved_zone_ids"
        assert stat["events_unwarned"] == 0
        assert stat["false_alarms"] == 0
        assert stat["pod"] == 1.0
        assert stat["far"] == 0.0
        assert stat["avg_lead_time_minutes"] == 35.0, "mean of 30 and 40 minute leads"


class TestLeadTimeRoundingOrder:
    def _setup_two_subminute_lead_events(self, api):
        """A warning covering the whole zone, issued 10:00; two CONFIRMED
        in-polygon events at 10:01:29 (89 s lead) and 10:02:01 (121 s lead)."""
        bundle = setup_issued_warning(
            api,
            hazard_type="FLASH_FLOOD",
            readings={"rainfall_rate_in_hr": 2.5},
            expires_at="2026-09-01T11:00:00Z",
        )
        create_and_confirm_event(
            api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:01:29Z", 0.05, 0.05, "2.5in"
        )
        create_and_confirm_event(
            api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:02:01Z", 0.06, 0.06, "2.6in"
        )
        return bundle

    def test_avg_lead_time_floors_each_event_before_averaging(self, api):
        """PRD §3.8: "`avg_lead_time_minutes`, computed by flooring each warned
        event's lead — the gap between the earliest matching warning's
        `issued_at` and the event's `observed_at` — to whole minutes first,
        then averaging those floored leads and rounding the mean half-up to 1
        decimal place, null when nothing was warned."

        Design: Difficulty/combinatorial_formula/lead_time_per_event_floor_then_average
        """
        bundle = self._setup_two_subminute_lead_events(api)
        stat = compute_statistic(api, bundle.office["id"], "FLASH_FLOOD")
        assert stat["events_warned"] == 2
        assert stat["pod"] == 1.0
        # floor(89 s) = 1, floor(121 s) = 2, mean = 1.5
        assert stat["avg_lead_time_minutes"] == 1.5

    def test_avg_lead_time_rejects_average_then_convert_order(self, api):
        """PRD §3.8: "Flooring each lead before averaging is mandatory;
        averaging raw seconds and converting to minutes afterward is the
        prohibited alternative order."

        Design: Difficulty/combinatorial_formula/lead_time_per_event_floor_then_average
        """
        bundle = self._setup_two_subminute_lead_events(api)
        stat = compute_statistic(api, bundle.office["id"], "FLASH_FLOOD")
        assert stat["avg_lead_time_minutes"] == 1.5
        assert stat["avg_lead_time_minutes"] != 1.8, (
            "1.8 is the forbidden average-of-raw-seconds result (105 s -> 1.75 -> 1.8)"
        )


class TestPerformanceBand:
    def test_performance_band_pod_exactly_050_stays_satisfactory(self, api):
        """PRD §3.8: "The office's `performance_band` becomes `REVIEW_REQUIRED`
        when the new snapshot's `far` is non-null and strictly greater than
        0.70 or — failing that — its `pod` is non-null and strictly less than
        0.50; in every other case, including a `pod` of exactly 0.500, the band
        is `SATISFACTORY`."
        PRD §3.8: "The office's `last_statistic_at` is set to the snapshot's
        `computed_at`, and the office's `version` increments."

        Design: Corner/calculations/performance_band_pod_exactly_050_stays_satisfactory
        """
        bundle = setup_issued_warning(
            api,
            hazard_type="FLASH_FLOOD",
            readings={"rainfall_rate_in_hr": 2.5},
            polygon=LEFT_HALF,
            expires_at="2026-09-01T11:00:00Z",
        )
        # A second warning whose tiny polygon resolves zero zones: an in-scope
        # false alarm that shares no zone with the first warning.
        w2 = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm,
            hazard_type="FLASH_FLOOD",
            polygon=TINY_CORNER, expires_at="2026-09-01T11:00:00Z",
        )
        issue_product(api, w2["id"], bundle.headers)
        create_and_confirm_event(
            api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:30:00Z", 0.05, 0.02, "2.5in"
        )
        create_and_confirm_event(
            api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:35:00Z", 0.05, 0.075, "2.4in"
        )

        stat = compute_statistic(api, bundle.office["id"], "FLASH_FLOOD")
        assert stat["total_warnings"] == 2
        assert stat["events_total"] == 2
        assert stat["events_warned"] == 1
        assert stat["false_alarms"] == 1
        assert stat["pod"] == 0.5
        assert stat["far"] == 0.5

        office = get_office(api, bundle.office["id"])
        assert office["performance_band"] == "SATISFACTORY", (
            "0.5 is not < 0.50 and 0.5 is not > 0.70"
        )
        assert office["last_statistic_at"] == stat["computed_at"]
        assert office["version"] == bundle.office["version"] + 1, (
            "the compute cascaded onto the office"
        )

    def test_performance_band_far_100_flips_review_required_with_null_pod(self, api):
        """PRD §3.8: "`pod`, the warned events divided by `events_total`,
        rounded half-up to 3 decimal places and null when no events occurred;
        `far`, the false alarms divided by `total_warnings`, rounded half-up to
        3 decimal places and null when no warnings issued"
        PRD §3.8: "The office's `performance_band` becomes `REVIEW_REQUIRED`
        when the new snapshot's `far` is non-null and strictly greater than
        0.70"

        Design: Corner/calculations/performance_band_far_100_flips_review_required_with_null_pod
        """
        bundle = setup_issued_warning(
            api,
            hazard_type="FLASH_FLOOD",
            readings={"rainfall_rate_in_hr": 2.5},
            polygon=LEFT_HALF,
            expires_at="2026-09-01T11:00:00Z",
        )
        stat = compute_statistic(api, bundle.office["id"], "FLASH_FLOOD")
        assert stat["total_warnings"] == 1
        assert stat["events_total"] == 0
        assert stat["false_alarms"] == 1
        assert stat["pod"] is None, "no denominator"
        assert stat["avg_lead_time_minutes"] is None, "nothing was warned"
        assert stat["far"] == 1.0

        office = get_office(api, bundle.office["id"])
        assert office["performance_band"] == "REVIEW_REQUIRED", "far 1.0 > 0.70"


class TestAdjudication:
    def test_adjudicate_confirmed_event_returns_invalid_event_state(self, api, verification_analyst_headers):
        """PRD §3.8: "Adjudication takes an `outcome` and is final: acting on
        an event no longer `REPORTED` is rejected with
        `ERR_INVALID_EVENT_STATE`."

        Design: Corner/state_machines/adjudicate_confirmed_event_returns_invalid_event_state
        """
        bundle = setup_office_with_zone(api)
        event = create_event(
            api, bundle.zone["id"], "SEVERE_THUNDERSTORM",
            "2026-09-01T10:30:00Z", 0.05, 0.05, "60mph",
        )
        adjudicate_event(api, event["id"], "CONFIRMED")
        resp = api.adjudicate_verification_event(
            event["id"], {"outcome": "REJECTED"}, verification_analyst_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_EVENT_STATE)
        event = get_event(api, event["id"])
        assert event["status"] == "CONFIRMED"
        assert event["matched_product_ids"] == [], "no products exist and nothing recomputed"

    def test_confirm_unmatched_event_mutates_no_product(self, api):
        """PRD §3.8: "a confirmed event matches a product when their hazards
        agree, the product is a `WARNING`, the product's `issued_at` is no
        later than the event's `observed_at`, the `observed_at` is strictly
        earlier than the product's `window_end`, and the observation point
        lies inside the product's polygon"
        PRD §3.8: "Every matched product has its `verified_event_count`
        increased by one"

        Design: Corner/cross_cutting_layers/confirm_unmatched_event_mutates_no_product
        """
        bundle = setup_issued_warning(
            api,
            hazard_type="FLASH_FLOOD",
            readings={"rainfall_rate_in_hr": 2.5},
            polygon=LEFT_HALF,
            expires_at="2026-09-01T11:00:00Z",
        )
        # Inside the zone but outside the drawn polygon (polygon is lon 0..0.05).
        event = create_and_confirm_event(
            api, bundle.zone["id"], "FLASH_FLOOD", "2026-09-01T10:20:00Z", 0.05, 0.075, "2.5in"
        )
        assert event["status"] == "CONFIRMED"
        assert event["matched_product_ids"] == []

        product = get_product(api, bundle.product["id"], bundle.headers)
        assert product["verified_event_count"] == 0
        assert product["verification_status"] == "UNVERIFIED"
        assert product["version"] == bundle.product["version"], (
            "the adjudication left the unmatched product untouched"
        )
