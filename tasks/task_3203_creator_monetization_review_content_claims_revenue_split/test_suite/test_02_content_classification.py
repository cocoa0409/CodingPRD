"""Content item upload, classification outcome and the classification command.

Covers the classification threshold rule, the MILDLANGUAGE engagement
exception and the item lifecycle transitions.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_content_item,
    create_channel_payload,
    create_classification_payload,
    create_content_item_payload,
    get_success_data,
    make_creator_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _open_channel(name, **overrides):
    payload = create_channel_payload(channel_name=name, lifetime_watch_hours=4000,
                                     subscriber_count=1000)
    payload.update(overrides)
    return get_success_data(api_client.create_channel(
        payload, TEST_USERS["anonymous_headers"]))


# ─── Upload ──────────────────────────────────────────

def test_content_item_create_ignores_client_supplied_computed_fields(api):
    """PRD §3.3: "It enters the system in `UPLOADED` status with `ad_suitability`
    null, `gross_revenue_cents` and `routed_revenue_cents` both at zero, and
    `holds_revenue` and `takedown_flag` both false."
    PRD §2.5: "`id` (string): a server-minted UUID with no type prefix and no
    embedded entity name."

    Design: Corner/entities/content_item_create_ignores_client_supplied_computed_fields
    """
    channel = _open_channel("Ignoring Channel")

    payload = create_content_item_payload(title="Seeded Attempt")
    payload["gross_revenue_cents"] = 999999
    payload["ad_suitability"] = "AD_FRIENDLY"
    item = validate_success(api.create_content_item(
        channel["id"], payload, make_creator_headers(channel["id"])), 201)

    assert_content_item(item)
    assert item["upload_status"] == "UPLOADED"
    assert item["ad_suitability"] is None
    assert item["gross_revenue_cents"] == 0
    assert item["routed_revenue_cents"] == 0
    assert item["holds_revenue"] is False
    assert item["takedown_flag"] is False


def test_content_item_create_does_not_accept_a_client_supplied_hold_flag(api):
    """PRD §3.3: "It enters the system in `UPLOADED` status with `ad_suitability`
    null, `gross_revenue_cents` and `routed_revenue_cents` both at zero, and
    `holds_revenue` and `takedown_flag` both false."

    Design: Corner/entities/content_item_create_ignores_client_supplied_computed_fields
    """
    channel = _open_channel("Ignoring Hold Channel")

    payload = create_content_item_payload(title="Seeded Hold Attempt")
    payload["holds_revenue"] = True
    payload["takedown_flag"] = True
    payload["routed_revenue_cents"] = 4242
    item = validate_success(api.create_content_item(
        channel["id"], payload, make_creator_headers(channel["id"])), 201)

    assert item["holds_revenue"] is False
    assert item["takedown_flag"] is False
    assert item["routed_revenue_cents"] == 0


def test_content_item_filtered_list_by_channel_id(api):
    """PRD §2.3: "The cross-channel content-item listing accepts a `channel_id`
    filter."

    Design: Corner/entities/content_item_filtered_list_by_channel_id
    """
    channel_a = _open_channel("Filter A")
    channel_b = _open_channel("Filter B")
    item_a = get_success_data(api.create_content_item(
        channel_a["id"], create_content_item_payload(title="Only On A"),
        make_creator_headers(channel_a["id"])))

    data, _meta = validate_paginated(api.list_content_items(
        TEST_USERS["any_headers"], params={"channel_id": channel_a["id"]}))
    assert [row["id"] for row in data] == [item_a["id"]]

    data_b, meta_b = validate_paginated(api.list_content_items(
        TEST_USERS["any_headers"], params={"channel_id": channel_b["id"]}))
    assert data_b == []
    assert meta_b["total_count"] == 0


# ─── Review request transitions ──────────────────────

def test_content_item_review_request_from_uploaded_moves_to_classifying(api):
    """PRD §3.3: "A creator requests review to move the item from `UPLOADED` to
    `CLASSIFYING`."

    Design: Corner/state_machines/content_item_review_request_from_uploaded_moves_to_classifying
    """
    channel = _open_channel("Transition Channel")
    creator = make_creator_headers(channel["id"])
    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(title="Transition Item"), creator))
    assert item["upload_status"] == "UPLOADED"

    moved = validate_success(api.request_review(channel["id"], item["id"], creator), 200)
    assert moved["upload_status"] != "UPLOADED"
    assert moved["upload_status"] in ["CLASSIFYING", "CLASSIFIED", "CLAIM_SCAN_COMPLETE"]


def test_content_item_review_request_from_classified_is_invalid_state(api):
    """PRD §2.7: "Only after every path identifier resolves does the server apply
    the state and business rules described in §3"
    PRD §3.3: "A creator requests review to move the item from `UPLOADED` to
    `CLASSIFYING`."

    Design: Corner/state_machines/content_item_review_request_from_classified_is_invalid_state
    """
    channel = _open_channel("No Replay Channel")
    creator = make_creator_headers(channel["id"])
    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(title="Already Reviewed"), creator))
    validate_success(api.request_review(channel["id"], item["id"], creator), 200)

    res = api.request_review(channel["id"], item["id"], creator)
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


# ─── Classification rule ─────────────────────────────

def _settled_item(channel, title, category_code, **overrides):
    creator = make_creator_headers(channel["id"])
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(
            title=title, category_code=category_code, **overrides), creator))
    return validate_success(api_client.request_review(channel["id"], item["id"], creator), 200)


def test_ad_review_decision_two_matched_categories_yield_no_ads(api):
    """PRD §3.3: "exactly one matched category yields `LIMITED_ADS`, and two or
    more matched categories yield `NO_ADS`"

    Design: Difficulty/combinatorial_formula/ad_review_decision_multi_input_non_linear_outcome
    """
    channel = _open_channel("Classify US", lifetime_watch_hours=8000, subscriber_count=1500)
    item = validate_success(api.classify_item(
        _settled_item(channel, "Two Flags", "NEWS")["id"],
        create_classification_payload(["NEWS", "POLITICS"], like_count=10,
                                      comment_count=5),
        TEST_USERS["reviewer_headers"]), 200)

    assert item["ad_suitability"] == "NO_ADS"
    assert item["limited_ads_reasons"] == ["NEWS", "POLITICS"]


def test_ad_review_decision_one_matched_category_yields_limited_ads(api):
    """PRD §3.3: "exactly one matched category yields `LIMITED_ADS`, and two or
    more matched categories yield `NO_ADS`"

    Design: Difficulty/combinatorial_formula/ad_review_decision_multi_input_non_linear_outcome
    """
    channel = _open_channel("Classify Single US", lifetime_watch_hours=8000,
                            subscriber_count=1500)
    item = validate_success(api.classify_item(
        _settled_item(channel, "One Flag", "MUSIC")["id"],
        create_classification_payload(["NEWS"], like_count=10, comment_count=5),
        TEST_USERS["reviewer_headers"]), 200)

    assert item["ad_suitability"] == "LIMITED_ADS"
    assert item["limited_ads_reasons"] == ["NEWS"]


def test_mildlanguage_is_limited_at_999_combined_engagement(api):
    """PRD §3.3: "The boundary is inclusive — 1000 suppresses and 999 does not"
    PRD §3.3: "exactly one matched category yields `LIMITED_ADS`, and two or more
    matched categories yield `NO_ADS`"

    Design: Corner/calculations/mildlanguage_suppressed_at_the_engagement_threshold
    """
    channel = _open_channel("Mild Channel")

    below = validate_success(api.classify_item(
        _settled_item(channel, "Mild Item Below", "MUSIC")["id"],
        create_classification_payload(["MILDLANGUAGE"], like_count=999, comment_count=0),
        TEST_USERS["reviewer_headers"]), 200)

    assert below["ad_suitability"] == "LIMITED_ADS"
    assert below["limited_ads_reasons"] == ["MILDLANGUAGE"]


def test_mildlanguage_is_suppressed_at_1000_combined_engagement(api):
    """PRD §3.3: "`MILDLANGUAGE` is removed from the matched set before the
    outcome is decided"
    PRD §3.3: "The boundary is inclusive — 1000 suppresses and 999 does not"
    PRD §3.3: "no matched categories yields `AD_FRIENDLY`"

    Design: Corner/calculations/mildlanguage_suppressed_at_the_engagement_threshold
    """
    channel = _open_channel("Mild Threshold Channel")

    at_threshold = validate_success(api.classify_item(
        _settled_item(channel, "Mild Item At", "MUSIC")["id"],
        create_classification_payload(["MILDLANGUAGE"], like_count=600, comment_count=400),
        TEST_USERS["reviewer_headers"]), 200)

    assert at_threshold["ad_suitability"] == "AD_FRIENDLY"
    assert at_threshold["limited_ads_reasons"] == []


def test_classification_rejects_a_category_outside_the_vocabulary(api):
    """PRD §2.10: "a classification pass that supplies a category outside the
    recognised vocabulary is rejected with `ERR_INVALID_CATEGORY_CODE` (HTTP 400)"

    Design: Difficulty/combinatorial_formula/ad_review_decision_multi_input_non_linear_outcome
    """
    channel = _open_channel("Bad Category Channel")
    item = _settled_item(channel, "Bad Category Item", "MUSIC")

    res = api.classify_item(
        item["id"], create_classification_payload(["NOT_A_REAL_CATEGORY"]),
        TEST_USERS["reviewer_headers"])
    validate_error(res, "ERR_INVALID_CATEGORY_CODE", expected_status=400)