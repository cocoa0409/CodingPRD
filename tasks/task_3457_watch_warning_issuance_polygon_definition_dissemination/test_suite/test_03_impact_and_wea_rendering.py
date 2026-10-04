"""Impact tags and WEA message rendering.

The impact tag is computed at creation (and recomputed at issue) from the
linked storm's readings gated by resolved-zone population tiers; the WEA
render truncates the zone list against the channel budget under a pinned
evaluation order (PRD §3.4, §3.6).
"""

from test_helpers import (
    ApiErrorId,
    assert_wea_preview,
    create_storm,
    create_warning_draft,
    create_watch_draft,
    create_wea_channel,
    create_zone,
    get_product,
    list_records,
    set_clock,
    setup_office_with_forecaster,
    setup_office_with_storm,
    setup_office_with_zone,
    validate_error,
    validate_success,
)


class TestImpactTierPopulationGate:
    def test_impact_tag_low_tier_zone_yields_none(self, api):
        """PRD §3.4: "Catastrophic qualification requires wind of at least
        80 mph, hail of at least 2.75 inches, or a confirmed
        `debris_signature`."
        PRD §3.4: "When the storm qualifies as catastrophic and any resolved
        zone is `HIGH` or `URBAN`, `damage_threat` is `CATASTROPHIC`."
        PRD §3.4: "In every other case the tag is `NONE`."

        Design: Difficulty/combinatorial_formula/impact_tier_population_gate_downgrades_tag
        """
        bundle = setup_office_with_storm(
            api,
            hazard_type="SEVERE_THUNDERSTORM",
            readings={"max_wind_mph": 85},
            zone_overrides={"population_tier": "LOW", "lon_min": 0.2, "lon_max": 0.3},
        )
        draft = create_warning_draft(
            api,
            bundle.office,
            bundle.headers,
            bundle.storm,
            polygon={
                "vertices": [
                    {"lat": 0.0, "lon": 0.2},
                    {"lat": 0.0, "lon": 0.3},
                    {"lat": 0.1, "lon": 0.3},
                    {"lat": 0.1, "lon": 0.2},
                ]
            },
            expires_at="2026-09-01T01:00:00Z",
        )
        assert draft["resolved_zone_ids"] == [bundle.zone["id"]]
        assert draft["damage_threat"] == "NONE", (
            "wind 85 is catastrophic-qualified, but a LOW-tier resolved zone "
            "satisfies neither the HIGH/URBAN nor the MEDIUM+ gate"
        )
        assert draft["wea_360"] is False

    def test_impact_tag_urban_tier_zone_yields_catastrophic(self, api):
        """PRD §3.4: "When the storm qualifies as catastrophic and any resolved
        zone is `HIGH` or `URBAN`, `damage_threat` is `CATASTROPHIC`."
        PRD §3.4: "The companion flag `wea_360` is true exactly when the tag is
        not `NONE`"

        Design: Difficulty/combinatorial_formula/impact_tier_population_gate_downgrades_tag
        """
        bundle = setup_office_with_storm(
            api,
            hazard_type="SEVERE_THUNDERSTORM",
            readings={"max_wind_mph": 85},
            zone_overrides={"population_tier": "URBAN"},
        )
        draft = create_warning_draft(
            api,
            bundle.office,
            bundle.headers,
            bundle.storm,
            expires_at="2026-09-01T01:00:00Z",
        )
        assert draft["resolved_zone_ids"] == [bundle.zone["id"]]
        assert draft["damage_threat"] == "CATASTROPHIC"
        assert draft["wea_360"] is True


def _setup_three_zone_wea_draft(api):
    """Office with ZB01 (LOW, lon 0.0..0.1), ZA01 (URBAN, lon 0.1..0.2), ZC01
    (LOW, lon 0.2..0.3); a TORNADO storm with a confirmed debris signature; a
    WEA channel with a 36-character budget; and a polygon warning draft
    spanning lon 0.075..0.225, expiring 23:45."""
    bundle = setup_office_with_forecaster(api)
    zone_b = create_zone(
        api, bundle.office["id"], zone_code="ZB01", population_tier="LOW"
    )
    zone_a = create_zone(
        api,
        bundle.office["id"],
        zone_code="ZA01",
        lon_min=0.1,
        lon_max=0.2,
        population_tier="URBAN",
    )
    zone_c = create_zone(
        api,
        bundle.office["id"],
        zone_code="ZC01",
        lon_min=0.2,
        lon_max=0.3,
        population_tier="LOW",
    )
    channel = create_wea_channel(api, name="WEA-TEST", max_message_chars=36)
    storm = create_storm(
        api, bundle.office["id"], bundle.headers, "TORNADO", debris_signature=True
    )
    draft = create_warning_draft(
        api,
        bundle.office,
        bundle.headers,
        storm,
        hazard_type="TORNADO",
        polygon={
            "vertices": [
                {"lat": 0.0, "lon": 0.075},
                {"lat": 0.0, "lon": 0.225},
                {"lat": 0.1, "lon": 0.225},
                {"lat": 0.1, "lon": 0.075},
            ]
        },
        expires_at="2026-09-01T23:45:00Z",
    )
    return bundle, {"ZA01": zone_a, "ZB01": zone_b, "ZC01": zone_c}, channel, draft


class TestWeaTruncation:
    def test_wea_preview_truncates_to_single_zone_with_exact_message(self, api):
        """PRD §3.6: "The message is the space-separated concatenation of the
        literal prefix "WEA", the product's `hazard_type`, its `damage_threat`
        tag, the resolved zones' `zone_code` values sorted ascending and joined
        with commas, and the expiration rendered as a four-digit
        hours-and-minutes UTC value followed by the letter Z."
        PRD §3.6: "The character budget is the smaller of 360 and the
        channel's `max_message_chars`."

        Design: Difficulty/combinatorial_formula/wea_truncation_drops_lowest_overlap_preserving_threshold
        """
        bundle, zones, channel, draft = _setup_three_zone_wea_draft(api)
        assert draft["damage_threat"] == "CATASTROPHIC", (
            "debris signature plus URBAN resolved zone ZA01"
        )
        resp = api.get_wea_preview(draft["id"], channel["id"], bundle.headers)
        preview = validate_success(resp)
        assert_wea_preview(preview)
        assert preview["message"] == "WEA TORNADO CATASTROPHIC ZA01 2345Z"
        assert preview["char_count"] == 35
        assert preview["included_zone_ids"] == [zones["ZA01"]["id"]]
        assert preview["would_overflow"] is False

    def test_wea_preview_drops_lowest_overlap_with_zone_code_tiebreak(self, api):
        """PRD §3.6: "third, while the message exceeds the budget and more than
        one zone remains, the zone with the smallest overlap percentage is
        removed — ties broken by removing the lexicographically greatest zone
        code — and the message re-rendered; fourth, the 0.10 inclusion
        threshold is never recomputed after removals"

        Design: Difficulty/combinatorial_formula/wea_truncation_drops_lowest_overlap_preserving_threshold
        """
        bundle, zones, channel, draft = _setup_three_zone_wea_draft(api)
        resp = api.get_wea_preview(draft["id"], channel["id"], bundle.headers)
        preview = validate_success(resp)
        # ZB01 and ZC01 tie at overlap 0.250; the tie-break drops ZC01 first,
        # then ZB01, leaving ZA01 (overlap 1.000).
        assert preview["dropped_zone_ids"] == [zones["ZC01"]["id"], zones["ZB01"]["id"]]
        assert preview["included_zone_ids"] == [zones["ZA01"]["id"]]
        assert preview["char_count"] <= 36, "budget honored without threshold recompute"


class TestWeaPreviewAndBudgetErrors:
    def test_wea_preview_on_zone_based_product_returns_400(self, api):
        """PRD §3.6: "asking for a preview of a polygon-less product is
        rejected with `ERR_INVALID_REQUEST`."

        Design: Corner/endpoints/wea_preview_on_zone_based_product_returns_invalid_request
        """
        bundle = setup_office_with_zone(api)
        channel = create_wea_channel(api, name="WEA-PV")
        draft = create_watch_draft(
            api,
            bundle.office,
            bundle.headers,
            [bundle.zone["id"]],
            hazard_type="WINTER_STORM",
            effective_from="2026-09-02T00:00:00Z",
            expires_at="2026-09-02T12:00:00Z",
        )
        resp = api.get_wea_preview(draft["id"], channel["id"], bundle.headers)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_wea_single_zone_over_budget_fails_issue_atomically(self, api):
        """PRD §3.6: "if a single zone remains and the message still exceeds
        the budget, issuance fails outright with
        `ERR_MESSAGE_FORMAT_OVERFLOW`."
        PRD §2.9: "Every mutation, including every cascade it triggers, commits
        atomically within the request that caused it"

        Design: Corner/errors/wea_single_zone_over_budget_returns_message_format_overflow
        """
        bundle = setup_office_with_storm(
            api, hazard_type="SEVERE_THUNDERSTORM", readings={"max_wind_mph": 60}
        )
        create_wea_channel(api, name="WEA-TINY", max_message_chars=10)
        set_clock(api, "2026-09-01T10:00:00Z")
        draft = create_warning_draft(
            api, bundle.office, bundle.headers, bundle.storm, expires_at="2026-09-01T10:45:00Z"
        )
        resp = api.issue_product(
            draft["id"], {"expected_product_version": draft["version"]}, bundle.headers
        )
        validate_error(resp, ApiErrorId.ERR_MESSAGE_FORMAT_OVERFLOW)
        product = get_product(api, draft["id"], bundle.headers)
        assert product["status"] == "DRAFT", "the failure is atomic — no partial issuance"
        assert list_records(api, draft["id"], bundle.headers) == [], (
            "no dissemination record was created on any channel"
        )
