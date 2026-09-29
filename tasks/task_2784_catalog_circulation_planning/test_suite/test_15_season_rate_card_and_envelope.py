"""The configuration root, created from two fields, and the envelope it arrives in.

A season is the only entity that can be created from nothing but a code and a
fiscal year, so it is where the rate-card defaults and the success envelope are
both observable in a single call. The defaults are load-bearing constants: every
cost, forecast and fatigue figure downstream is computed from them, so they are
asserted as exact literals rather than merely as present keys.
"""
import re

from test_helpers import (
    ADMIN,
    ANALYST,
    CLOCK_START,
    PLANNER,
    assert_catalog_season,
    assert_circulation_line,
    assert_suppression_rule,
    create_season_payload,
    create_suppression_rule_payload,
    fetch_season,
    is_valid_uuid,
    new_drop,
    new_housefile_line,
    new_plan,
    new_season,
    new_segment,
    set_clock,
    validate_paginated,
    validate_success,
)

THREE_FRACTIONAL_DIGITS = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$"
)

RATE_CARD_FIELDS = (
    "print_cost_per_page_per_thousand_cents",
    "paper_cost_per_lb_cents",
    "paper_oz_per_page_milli",
    "usable_sq_in_per_page",
    "default_postage_estimate_cents_per_piece",
    "cogs_rate_bps",
    "prospect_base_response_bps",
    "prospect_avg_order_value_cents",
    "min_inhome_gap_days",
    "fatigue_window_days",
    "fatigue_suppression_threshold",
)


class TestSeasonCreationEnvelope:
    def test_two_fields_are_enough_and_the_whole_rate_card_comes_back(self, api):
        """PRD §2.5: "Everything else on the season is a rate-card value with a
        defined default, so a season can be created with two fields and still
        price a plan."

        Design: Corner/entities/season_creation_returns_the_full_rate_card_in_the_envelope
        """
        set_clock(CLOCK_START)

        response = api.create_season(
            create_season_payload(season_code="FW26", fiscal_year=2026), ADMIN
        )
        season = validate_success(response, 201)

        assert_catalog_season(season)
        assert season["season_code"] == "FW26"
        assert season["fiscal_year"] == 2026
        assert season["version"] == 1

        for field in RATE_CARD_FIELDS:
            assert field in season, f"rate-card field {field} missing from data"

    def test_the_envelope_carries_meta_and_a_bare_uuid_with_millisecond_stamps(
        self, api
    ):
        """PRD §2.4: "Every resource the service persists carries a server-minted
        `id`: a UUID string with no type prefix and no client influence over its
        value. Every resource also carries `created_at`, an ISO 8601 UTC
        timestamp with three fractional-second digits recording when the row came
        into existence."

        Design: Corner/entities/season_creation_returns_the_full_rate_card_in_the_envelope
        """
        set_clock(CLOCK_START)

        response = api.create_season(
            create_season_payload(season_code="FW26", fiscal_year=2026), ADMIN
        )
        season = validate_success(response, 201)
        body = response.json()

        assert response.status_code == 201
        assert body["response_type"] == "object"
        assert body["meta"]["api_request_id"].startswith("req_")
        assert THREE_FRACTIONAL_DIGITS.match(body["meta"]["api_request_timestamp"]), (
            f"meta.api_request_timestamp must carry three fractional digits: "
            f"{body['meta']['api_request_timestamp']!r}"
        )

        assert is_valid_uuid(season["id"])
        assert len(season["id"]) == 36
        assert ":" not in season["id"] and "_" not in season["id"]

        for field in ("created_at", "updated_at"):
            assert THREE_FRACTIONAL_DIGITS.match(season[field]), (
                f"{field} must be ISO 8601 UTC with three fractional digits: "
                f"{season[field]!r}"
            )


class TestRateCardDefaults:
    def test_all_eleven_rate_card_values_land_on_their_documented_defaults(self):
        """PRD §2.5: "`print_cost_per_page_per_thousand_cents` is the web-offset
        printing charge in cents for one catalog page across one thousand books
        and defaults to 2600, meaning twenty-six dollars per page per thousand
        books; it may not be negative."

        Design: Corner/entities/season_rate_card_defaults_are_applied_when_omitted
        """
        set_clock(CLOCK_START)
        created = new_season(season_code="FW26", fiscal_year=2026)

        season = fetch_season(created["id"], PLANNER)
        assert_catalog_season(season)

        assert season["print_cost_per_page_per_thousand_cents"] == 2600
        assert season["paper_cost_per_lb_cents"] == 92
        assert season["paper_oz_per_page_milli"] == 40
        assert season["usable_sq_in_per_page"] == 88

        assert season["default_postage_estimate_cents_per_piece"] == 55
        assert season["cogs_rate_bps"] == 5800

        assert season["prospect_base_response_bps"] == 110
        assert season["prospect_avg_order_value_cents"] == 11800

        assert season["min_inhome_gap_days"] == 21
        assert season["fatigue_window_days"] == 90
        assert season["fatigue_suppression_threshold"] == 100

    def test_a_list_read_with_no_limit_returns_ten_of_eleven_rows(self, api):
        """PRD §2.3: "`limit` controls the page size: it defaults to 10 when
        omitted, may not be smaller than 1, and may not be larger than 100."

        Design: Corner/entities/season_rate_card_defaults_are_applied_when_omitted
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)
        for index in range(1, 12):
            new_segment(season["id"], segment_code=f"S_{index:02d}")

        segments, meta = validate_paginated(
            api.list_segments(ANALYST, {"season_id": season["id"]})
        )
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 11
        assert meta["has_more"] is True
        assert len(segments) == 10
        assert [row["segment_code"] for row in segments] == [
            f"S_{index:02d}" for index in range(1, 11)
        ]

    def test_a_line_omitting_the_holdout_fields_is_not_a_holdout(self):
        """PRD §3.5: "A line may also be marked as a measurement holdout:
        `is_holdout` defaults to false, and `holdout_pct_bps` — the share of the
        eventual allocation withheld from the mail, expressed in basis points
        between 0 and 5000 inclusive — defaults to 0."

        Design: Corner/entities/season_rate_card_defaults_are_applied_when_omitted
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)
        segment = new_segment(season["id"], segment_code="S_A")
        plan = new_plan(season["id"], plan_code="P1", budget_cents=20000000)
        drop = new_drop(plan["id"], drop_number=1, page_count=64)

        line = new_housefile_line(drop["id"], segment["id"], requested_quantity=20000)
        assert_circulation_line(line)
        assert line["is_holdout"] is False
        assert line["holdout_pct_bps"] == 0
        assert line["holdout_quantity"] == 0

    def test_a_suppression_rule_omitting_the_flag_participates_by_default(self, api):
        """PRD §3.8: "Each rule carries a `rule_code` such as `CAP_EMAIL_30D`,
        unique within the season with a repeat rejected as
        `ERR_DUPLICATE_SUPPRESSION_RULE_CODE`; a `channel_scope` of `MAIL`,
        `EMAIL`, `DIGITAL` or `ALL`, where `ALL` counts every channel together; a
        `window_days` trailing window between 1 and 365 whole days inclusive; a
        `max_contacts_per_window` ceiling that may not be negative; a `priority`
        of at least 1 that fixes evaluation order among a season's rules, with
        lower numbers evaluated first and `created_at` ascending breaking ties;
        and an `is_enabled` flag that defaults to true and determines whether the
        rule participates at all."

        Design: Corner/entities/season_rate_card_defaults_are_applied_when_omitted
        """
        set_clock(CLOCK_START)
        season = new_season(season_code="FW26", fiscal_year=2026)

        payload = create_suppression_rule_payload(
            rule_code="CAP_EMAIL_30D",
            channel_scope="EMAIL",
            window_days=30,
            max_contacts_per_window=2,
            priority=1,
        )
        assert "is_enabled" not in payload

        rule = validate_success(
            api.create_suppression_rule(season["id"], payload, ADMIN), 201
        )
        assert_suppression_rule(rule)
        assert rule["is_enabled"] is True
        assert rule["channel_scope"] == "EMAIL"
        assert rule["window_days"] == 30
        assert rule["max_contacts_per_window"] == 2
        assert rule["priority"] == 1
