"""Rate-sheet publication sequencing, supersession, retirement and quote immutability."""
from test_helpers import (
    ANY,
    ApiErrorId,
    publish_rate_sheet,
    validate_error,
    validate_paginated,
    validate_success,
    api_client,
)
from test_helpers.fixtures import (
    CM,
    broker_version,
    create_and_approve_broker,
    price_quote,
    setup_full_scenario,
)
from test_helpers.test_users import TEST_USERS, make_broker_headers, make_channel_manager_headers

STANDARD_TABLE = [
    {"dim": "credit", "bucket": "760-plus", "adjust_pct": -0.125},
    {"dim": "ltv", "bucket": "up-to-60", "adjust_pct": 0.000},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "CONVENTIONAL", "adjust_pct": 0.000},
]

FHA_TABLE = [
    {"dim": "credit", "bucket": "720-739", "adjust_pct": 0.000},
    {"dim": "ltv", "bucket": "70-80", "adjust_pct": 0.125},
    {"dim": "occupancy", "bucket": "PRIMARY_RESIDENCE", "adjust_pct": 0.000},
    {"dim": "product", "bucket": "FHA", "adjust_pct": 0.125},
]


def test_repricing_supersedes_the_prior_sheet_but_preserves_the_quote(api):
    """PRD §3.5: "the prior `PUBLISHED` sheet for the same broker and product moves to
    `SUPERSEDED` with its `superseded_by_sheet_id` set to the new sheet's identifier"
    PRD §3.5: "An existing quote keeps the sheet it was priced from and reports its staleness
    through `is_repriced`"

    Design: Difficulty/resource_temporal_overlap/base_rate_repricing_non_overlapping_publication_sequence
    """
    broker = create_and_approve_broker()
    sheet_v1 = publish_rate_sheet(broker["id"], base_rate_pct=6.125,
                                  adjustment_table=STANDARD_TABLE)
    quote = price_quote(broker["id"], sheet_v1, representative_fico=780, ltv_ratio=0.5500,
                        lock_period_days=30)
    assert quote["price_points"] == -1.375
    assert quote["note_rate_pct"] == 6.000
    assert quote["is_repriced"] is False

    sheet_v2 = publish_rate_sheet(broker["id"], base_rate_pct=6.375,
                                  adjustment_table=STANDARD_TABLE)
    assert sheet_v2["publish_sequence"] == 2

    superseded = validate_success(api_client.get_rate_sheet(sheet_v1["id"], ANY))
    assert superseded["status"] == "SUPERSEDED"
    assert superseded["superseded_by_sheet_id"] == sheet_v2["id"]

    after = validate_success(api_client.get_pricing_quote(quote["id"], ANY))
    assert after["price_points"] == -1.375, "the quote snapshots its own sheet"
    assert after["note_rate_pct"] == 6.000
    assert after["is_repriced"] is True
    assert after["rate_sheet_id"] == sheet_v1["id"]


def test_second_quote_against_a_superseded_sheet_is_refused(api):
    """PRD §3.5: "an attempt to price or submit against a sheet whose status is `SUPERSEDED`
    or `RETIRED` is refused with `ERR_PRICING_QUOTE_SUPERSEDED`."

    Design: Difficulty/resource_temporal_overlap/base_rate_repricing_non_overlapping_publication_sequence
    """
    scenario = setup_full_scenario()
    sheet_v1 = scenario["sheet"]
    publish_rate_sheet(scenario["broker_id"], base_rate_pct=6.375, adjustment_table=STANDARD_TABLE)

    # Superseding bumped v1's version, so re-read it: the version guard must pass
    # and the SUPERSEDED state gate must be the thing that refuses the quote.
    superseded = validate_success(api_client.get_rate_sheet(sheet_v1["id"], ANY))
    assert superseded["status"] == "SUPERSEDED"

    response = api_client.create_pricing_quote(
        sheet_v1["id"],
        {
            "representative_fico": 780, "ltv_ratio": 0.5500,
            "occupancy_type": "PRIMARY_RESIDENCE", "loan_amount_cents": 40_000_000,
            "lock_period_days": 30, "loan_purpose": "PURCHASE",
            "expected_rate_sheet_version": superseded["version"],
        },
        make_broker_headers(scenario["broker_id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRICING_QUOTE_SUPERSEDED, expected_status=409)


def test_quote_is_immutable_and_carries_no_version_or_update_route(api):
    """PRD §2.8: "`PricingQuote` is an immutable pricing snapshot: it carries only `id` and
    `created_at`, and it has no `updated_at`, no `version`, and no update endpoint of any kind."

    Design: Corner/entities/pricing_quote_is_immutable_with_no_version_and_no_update_route
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    quote = price_quote(broker["id"], sheet, representative_fico=780, ltv_ratio=0.5500,
                        lock_period_days=30)
    assert "version" not in quote
    assert "updated_at" not in quote
    assert quote["id"] and quote["created_at"]

    reprice = publish_rate_sheet(broker["id"], base_rate_pct=6.500,
                                 adjustment_table=STANDARD_TABLE)
    after = validate_success(api_client.get_pricing_quote(quote["id"], ANY))
    assert after["note_rate_pct"] == 6.000, "the stored pricing was not recomputed"
    assert after["price_points"] == -1.375
    assert after["is_repriced"] is True
    assert after["rate_sheet_id"] == sheet["id"]

    original = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    assert original["status"] == "SUPERSEDED"
    assert reprice["publish_sequence"] == 2
    assert "version" not in after and "updated_at" not in after


def test_publish_sequence_increments_per_broker_and_product_pair(api):
    """PRD §3.5: "a `publish_sequence` that is one more than the highest sequence previously
    used for that broker-and-product pair"

    Design: Difficulty/resource_temporal_overlap/base_rate_repricing_non_overlapping_publication_sequence
    """
    broker = create_and_approve_broker()
    v1 = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    v2 = publish_rate_sheet(broker["id"], base_rate_pct=6.250, adjustment_table=STANDARD_TABLE)
    fha1 = publish_rate_sheet(broker["id"], product_code="FHA", base_rate_pct=6.000,
                              adjustment_table=FHA_TABLE)

    assert v1["publish_sequence"] == 1
    assert v2["publish_sequence"] == 2
    assert fha1["publish_sequence"] == 1, "a different product starts its own sequence"


def test_rate_sheet_read_returns_the_stored_adjustment_table_unchanged(api):
    """PRD §3.5: "an `adjustment_table` — an ordered list of rows, each carrying a `dim` of
    `credit`, `ltv`, `occupancy` or `product`, a `bucket` naming the band, and a signed
    `adjust_pct`."

    Design: Corner/entities/rate_sheet_get_returns_the_stored_adjustment_table_unchanged
    """
    broker = create_and_approve_broker()
    table = [
        {"dim": "credit", "bucket": "720-739", "adjust_pct": 0.000},
        {"dim": "ltv", "bucket": "80-90", "adjust_pct": 0.250},
        {"dim": "occupancy", "bucket": "SECOND_HOME", "adjust_pct": 0.250},
        {"dim": "product", "bucket": "VA", "adjust_pct": -0.125},
    ]
    sheet = publish_rate_sheet(broker["id"], product_code="VA", base_rate_pct=5.875,
                               adjustment_table=table)
    fetched = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))

    assert fetched["product_code"] == "VA"
    assert fetched["base_rate_pct"] == 5.875
    assert fetched["status"] == "PUBLISHED"
    assert fetched["publish_sequence"] == 1
    assert fetched["superseded_by_sheet_id"] is None
    assert len(fetched["adjustment_table"]) == 4
    assert [row["dim"] for row in fetched["adjustment_table"]] == [
        "credit", "ltv", "occupancy", "product"
    ]
    assert fetched["adjustment_table"][3]["bucket"] == "VA"
    assert fetched["adjustment_table"][3]["adjust_pct"] == -0.125
    assert fetched["adjustment_table"][2]["bucket"] == "SECOND_HOME"


def test_retire_is_refused_while_a_quote_references_the_sheet(api):
    """PRD §3.5: "A sheet may be retired from either `PUBLISHED` or `SUPERSEDED` status by a
    `ChannelManager`, but only while no `PricingQuote` references it; a retirement attempted
    while quotes exist is refused with `ERR_SHEET_IN_USE`."

    Design: Corner/endpoints/retire_refused_while_a_quote_references_the_sheet
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    price_quote(broker["id"], sheet, representative_fico=780, ltv_ratio=0.5500, lock_period_days=30)

    in_use = api_client.retire_rate_sheet(broker["id"], sheet["id"], make_channel_manager_headers())
    validate_error(in_use, ApiErrorId.ERR_SHEET_IN_USE, expected_status=409)
    assert validate_success(api_client.get_rate_sheet(sheet["id"], ANY))["status"] == "PUBLISHED"

    fresh = publish_rate_sheet(broker["id"], product_code="FHA", base_rate_pct=6.000,
                               adjustment_table=FHA_TABLE)
    retired = validate_success(
        api_client.retire_rate_sheet(broker["id"], fresh["id"], make_channel_manager_headers())
    )
    assert retired["status"] == "RETIRED"
    fetched = validate_success(api_client.get_rate_sheet(fresh["id"], ANY))
    assert fetched["status"] == "RETIRED"
    assert fetched["superseded_by_sheet_id"] is None


def test_unused_sheet_can_be_retired_and_then_cannot_be_priced(api):
    """PRD §3.5: "A sheet that has already been priced against and then repriced away is
    therefore readable forever but no longer priceable"
    PRD §3.5: "an attempt to price or submit against a sheet whose status is `SUPERSEDED` or
    `RETIRED` is refused with `ERR_PRICING_QUOTE_SUPERSEDED`."

    Design: Corner/endpoints/retire_refused_while_a_quote_references_the_sheet
    """
    broker = create_and_approve_broker()
    sheet = publish_rate_sheet(broker["id"], adjustment_table=STANDARD_TABLE)
    validate_success(api_client.retire_rate_sheet(broker["id"], sheet["id"], make_channel_manager_headers()))
    # Retiring mutates the sheet, so its version advances; pin the current value
    # so the refusal is the status gate, not the version guard (PRD §2.7).
    sheet = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    assert sheet["status"] == "RETIRED"

    response = api_client.create_pricing_quote(
        sheet["id"],
        {
            "representative_fico": 780, "ltv_ratio": 0.5500,
            "occupancy_type": "PRIMARY_RESIDENCE", "loan_amount_cents": 40_000_000,
            "lock_period_days": 30, "loan_purpose": "PURCHASE",
            "expected_rate_sheet_version": sheet["version"],
        },
        make_broker_headers(broker["id"]),
    )
    validate_error(response, ApiErrorId.ERR_PRICING_QUOTE_SUPERSEDED, expected_status=409)

    readable = validate_success(api_client.get_rate_sheet(sheet["id"], ANY))
    assert readable["status"] == "RETIRED"