"""Classification appeals, the logical clock sweep and optimistic concurrency.

Covers the creator's remedy against a limited-ads classification, the deferred
strike expiry that returns a revoked channel to pending, and the three
version-guarded writes.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_approved_channel,
    create_channel_payload,
    create_classification_payload,
    create_content_item_payload,
    create_payout_lock_payload,
    create_revenue_routing_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_success,
)


def _limited_item(channel, title="Appealable Item"):
    creator = make_creator_headers(channel["id"])
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title=title), creator))
    item = validate_success(api_client.request_review(channel["id"], item["id"], creator), 200)
    return validate_success(api_client.classify_item(
        item["id"], create_classification_payload(["NEWS"], like_count=10, comment_count=5),
        TEST_USERS["reviewer_headers"]), 200)


# ─── Classification appeals ──────────────────────────

def test_classification_appeal_upheld_leaves_the_verdict_unchanged(api):
    """PRD §3.3: "The transition is a self-loop on the item: it does not move off
    `CLASSIFIED`, and the item remains `CLASSIFIED` with its `ad_suitability` and
    `limited_ads_reasons` unchanged."
    PRD §3.3: "The `AdReview` row's `appeal_outcome` becomes `UPHELD`, meaning the
    original determination stands rather than being reversed."

    Design: Corner/entities/content_item_review_request_from_classified_is_invalid_state
    """
    channel = create_approved_channel(channel_name="Appeal Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)
    item = _limited_item(channel)
    assert item["ad_suitability"] == "LIMITED_ADS"
    before_reasons = list(item["limited_ads_reasons"])
    before_version = item["version"]

    reviewed = validate_success(api.appeal_classification(
        channel["id"], item["id"], {"grounds_code": "REVIEW_ERROR"},
        TEST_USERS["monetization_reviewer_headers"]), 200)

    assert reviewed["upload_status"] == "CLASSIFIED"
    assert reviewed["ad_suitability"] == "LIMITED_ADS"
    assert reviewed["limited_ads_reasons"] == before_reasons
    assert reviewed["version"] == before_version + 1

    reviews, _meta = api.list_ad_reviews(item["id"], TEST_USERS["any_headers"]).json(), None
    assert reviews["data"][-1]["appeal_outcome"] == "UPHELD"


def test_classification_appeal_is_refused_on_a_restricted_channel(api):
    """PRD §3.3: "A channel whose posture is `RESTRICTED` may not pursue this
    appeal and receives `ERR_POSTURE_RESTRICTED`."

    Design: Corner/entities/content_item_review_request_from_classified_is_invalid_state
    """
    channel = create_approved_channel(channel_name="Appeal Restricted Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)
    item = _limited_item(channel, "Appeal Restricted Item")
    validate_success(api.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "HATE_SPEECH"},
        TEST_USERS["moderator_headers"]), 201)

    res = api.appeal_classification(
        channel["id"], item["id"], {"grounds_code": "MISIDENTIFIED"},
        TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_POSTURE_RESTRICTED", expected_status=409)


# ─── Optimistic concurrency ──────────────────────────

def test_stale_item_version_on_revenue_routing_returns_412(api):
    """PRD §3.8: "the mandatory `expected_content_item_version` naming the
    observed version of the owning content item. Omitting that field, or supplying
    a version older than the item's current `version`, is refused with
    `ERR_STALE_VERSION` (HTTP 412)"
    PRD §2.6: "Routing revenue for a content item requires
    `expected_content_item_version`, naming the observed `version` of that
    `ContentItem`. A stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_item_version_on_revenue_routing_returns_412
    """
    channel = create_approved_channel(channel_name="Stale Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)
    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api.create_content_item(
            channel["id"], create_content_item_payload(title="Stale Item"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    observed_version = item["version"]

    first = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], observed_version,
                                       stream_type="AD", gross_revenue_cents=1000),
        TEST_USERS["platform_admin_headers"]), 201)
    assert first["gross_revenue_cents"] == 1000

    fresh = get_success_data(api_client.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert fresh["version"] > observed_version

    res = api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], observed_version,
                                       stream_type="AD", gross_revenue_cents=1000),
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_stale_batch_version_on_release_returns_412(api):
    """PRD §2.6: "Releasing a locked payout batch requires
    `expected_payout_batch_version`, naming the observed `version` of that
    `PayoutBatch`. A stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_item_version_on_revenue_routing_returns_412
    """
    channel = create_approved_channel(channel_name="Stale Batch Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api.create_content_item(
            channel["id"], create_content_item_payload(title="Stale Batch Item"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"],
                                       stream_type="AD", gross_revenue_cents=20000),
        TEST_USERS["platform_admin_headers"]), 201)

    current = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    batch = validate_success(api_client.lock_payout(
        channel["id"], create_payout_lock_payload(current["version"]),
        TEST_USERS["platform_admin_headers"]), 200)
    stale_version = batch["version"] - 1

    res = api.release_payout(channel["id"], batch["id"],
                             {"expected_payout_batch_version": stale_version},
                             TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


def test_stale_claim_version_on_dispute_returns_412(api):
    """PRD §2.6: "Filing a dispute against a claim requires
    `expected_claim_version`, naming the observed `version` of that `Claim`. A
    stale value is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_layers/stale_item_version_on_revenue_routing_returns_412
    """
    channel = create_approved_channel(channel_name="Stale Claim Channel",
                                      lifetime_watch_hours=4000, subscriber_count=1000)
    creator = make_creator_headers(channel["id"])
    ref = validate_success(api.create_reference_file(
        {"rights_holder_name": "Stale Claim Rights", "asset_kind": "AUDIO",
         "reference_fingerprint": "fp-staleclaim-1", "policy_mode": "MONETIZE",
         "claimed_segment_seconds": 30},
        make_rights_holder_headers("rh-staleclaim-1")), 201)
    item = validate_success(api.request_review(
        channel["id"],
        get_success_data(api.create_content_item(
            channel["id"], create_content_item_payload(title="Stale Claim Item"),
            creator))["id"], creator), 200)
    claim = validate_success(api.create_claim(
        {"content_item_id": item["id"], "reference_file_id": ref["id"],
         "match_confidence": 0.900},
        make_rights_holder_headers(ref["id"])), 201)
    stale_version = claim["version"]

    validate_success(api.dispute_claim(
        claim["id"], {"expected_claim_version": stale_version, "reason_code": "FAIR_USE"},
        creator), 200)

    fresh = get_success_data(api.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert fresh["version"] > stale_version

    res = api.dispute_claim(
        claim["id"], {"expected_claim_version": stale_version, "reason_code": "MISMATCH"},
        creator)
    validate_error(res, "ERR_STALE_VERSION", expected_status=412)


# ─── Deferred strike expiry ──────────────────────────

def test_strike_expiry_sweeper_returns_a_revoked_channel_to_pending(api):
    """PRD §3.7: "when the channel is `MONETIZATION_REVOKED` and
    `copyright_strike_count` has reached zero — the channel's
    `monetization_status` returns to `MONETIZATION_PENDING`"
    PRD §3.7: "A revoked channel is restored to `MONETIZATION_PENDING` with
    posture `OPEN` only once the sweeper has left every one of its `ChannelStrike`
    and `CopyrightStrike` rows expired"

    Design: Corner/cross_cutting_layers/strike_expiry_sweeper_returns_a_revoked_channel_to_pending
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Expiry Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"]:
        validate_success(api.issue_strike(
            channel["id"], {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)

    revoked = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert revoked["monetization_status"] == "MONETIZATION_REVOKED"
    assert revoked["monetization_posture"] == "FROZEN"

    validate_success(api.set_clock("2026-11-30T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)

    swept = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert swept["policy_strike_count"] == 0
    assert swept["monetization_status"] == "MONETIZATION_PENDING"
    assert swept["monetization_posture"] == "OPEN"

    strikes, meta = api.list_channel_strikes(
        channel["id"], TEST_USERS["any_headers"]).json()["data"], None
    assert all(s["status"] == "EXPIRED" for s in strikes)
    assert len(strikes) == 3


def test_strike_sweep_one_second_early_leaves_the_strikes_active(api):
    """PRD §2.9: "the comparison is inclusive at the boundary, so a strike whose
    `expires_at` equals the newly set clock instant expires. Strikes already in
    `EXPIRED` are never revisited."
    PRD §3.7: "Strikes expire on a `STRIKE_LIFETIME_DAYS` clock of ninety days and
    the expiry is swept only when the logical clock advances."

    Design: Corner/cross_cutting_layers/strike_expiry_sweeper_returns_a_revoked_channel_to_pending
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Expiry Edge Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"]:
        validate_success(api.issue_strike(
            channel["id"], {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)

    validate_success(api.set_clock("2026-11-29T23:59:59Z",
                                   TEST_USERS["platform_admin_headers"]), 200)

    early = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert early["policy_strike_count"] == 3, "one second short of the expiry must not sweep"
    assert early["monetization_status"] == "MONETIZATION_REVOKED"
    assert early["monetization_posture"] == "FROZEN"