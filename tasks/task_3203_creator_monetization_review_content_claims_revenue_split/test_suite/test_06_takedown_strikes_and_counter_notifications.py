"""Claim refutation, takedown and counter-notification release.

Covers the terminal TAKEN_DOWN state, its claim-level lockdown, and the
counter-notification gate that is the standing prerequisite for a release.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    create_approved_channel,
    create_claim_payload,
    create_classified_item,
    create_reference_file_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _approved_with_claimed_item(name, rights_holder_id="rh-takeover-1",
                                fingerprint="fp-takeover-1"):
    channel = create_approved_channel(channel_name=name, country_code="US",
                                      lifetime_watch_hours=8000, subscriber_count=1500,
                                      tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    # The reference file has to be registered before the item's rights scan, so
    # that the scan itself materialises the claim the ladder then works on.
    ref = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name=f"{name} Rights",
                                      reference_fingerprint=fingerprint),
        make_rights_holder_headers(rights_holder_id)))
    item = create_classified_item(channel["id"], title=f"{name} Source")
    return channel, item, ref


def _to_pending_second_appeal(channel, item, ref):
    """ACTIVE -> DISPUTED -> APPEALED (FIRST) -> DENIED -> APPEALED (SECOND)."""
    ref_id = ref["id"]
    claims, _meta = validate_paginated(api_client.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item["id"],
                                           "reference_file_id": ref_id}))
    assert claims, "the item's rights scan must have materialised the claim"
    claim = claims[0]
    claim = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"])), 200)
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref_id)), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref_id)), 200)
    validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref_id)), 200)
    return get_success_data(api_client.get_claim(claim["id"], TEST_USERS["any_headers"]))


def _taken_down_channel(name, rights_holder_id="rh-td-1", fingerprint="fp-td-1"):
    channel, item, ref = _approved_with_claimed_item(name, rights_holder_id, fingerprint)
    claim = _to_pending_second_appeal(channel, item, ref)
    claim = validate_success(api_client.take_down_claim(
        claim["id"], make_rights_holder_headers(ref["id"])), 200)
    return channel, item, ref, claim


# ─── The ladder to takedown ──────────────────────────

def test_takedown_marks_the_claim_item_and_channel_strike(api):
    """PRD §3.7: "The claim's `status` becomes `TAKEN_DOWN` and its
    `taken_down_at` is stamped with the current logical clock instant."
    PRD §3.7: "The content item's `ad_suitability` is forced to `NO_ADS`, its
    `takedown_flag` becomes true, and the `AdReview` row for the item has its
    `is_visible` flag set to false so the item drops out of the visible review
    surface."

    Design: Difficulty/compensating_invariant/takedown_then_counter_notification_release_conserves_period_total
    """
    channel, item, ref, claim = _taken_down_channel("Takeover US")

    assert claim["status"] == "TAKEN_DOWN"
    assert claim["taken_down_at"] is not None

    after = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert after["ad_suitability"] == "NO_ADS"
    assert after["takedown_flag"] is True

    reviews, meta = validate_paginated(api.list_ad_reviews(
        item["id"], TEST_USERS["any_headers"]))
    assert meta["total_count"] >= 1
    assert reviews[-1]["is_visible"] is False, (
        "the item must drop out of the visible review surface")


def test_taken_down_claim_cannot_be_disputed_again(api):
    """PRD §3.5: "a claim that has already been taken down can take no further
    dispute, appeal or takedown and yields `ERR_CLAIM_TERMINAL` (HTTP 409)"

    Design: Corner/state_machines/taken_down_claim_cannot_be_disputed_again
    """
    channel, _item, _ref, claim = _taken_down_channel("Terminal US")

    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "OWNERSHIP"},
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_CLAIM_TERMINAL", expected_status=409)

    still = get_success_data(api.get_claim(claim["id"], TEST_USERS["any_headers"]))
    assert still["status"] == "TAKEN_DOWN"


def test_release_before_any_counter_notification_is_refused(api):
    """PRD §3.5: "A resolution aimed at a taken-down claim before any
    counter-notification exists is refused with `ERR_CONTENT_ITEM_NOT_TAKEN_DOWN`
    (HTTP 409)"

    Design: Difficulty/compensating_invariant/takedown_then_counter_notification_release_conserves_period_total
    """
    channel, _item, ref, claim = _taken_down_channel("Counter Gate US",
                                                     "rh-countergate-1",
                                                     "fp-countergate-1")

    res = api.resolve_dispute(claim["id"], {"resolution": "RELEASE"},
                              make_rights_holder_headers(ref["id"]))
    validate_error(res, "ERR_CONTENT_ITEM_NOT_TAKEN_DOWN", expected_status=409)


def test_counter_notification_then_release_clears_the_takedown(api):
    """PRD §3.5: "acceptance moves the claim from `TAKEN_DOWN` to `RELEASED`,
    returning its `lock_reason` to `NONE`"
    PRD §3.5: "the owning content item's `takedown_flag` is recomputed to false,
    since no claim on it remains taken down"

    Design: Difficulty/compensating_invariant/takedown_then_counter_notification_release_conserves_period_total
    """
    channel, item, ref, claim = _taken_down_channel("Counter Release US",
                                                    "rh-counterrel-1",
                                                    "fp-counterrel-1")

    notified = validate_success(api.file_counter_notification(
        claim["id"], {"statement": "I own the master recording and have licensed the segment."},
        make_creator_headers(channel["id"])), 200)
    assert notified["copyright_counter_notified"] is True

    released = validate_success(api.resolve_dispute(
        claim["id"], {"resolution": "RELEASE"},
        make_rights_holder_headers(ref["id"])), 200)
    assert released["status"] == "RELEASED"
    assert released["lock_reason"] == "NONE"

    restored = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert restored["takedown_flag"] is False, (
        "no claim on the item remains taken down, so the flag is cleared")


def test_takedown_issues_one_active_copyright_strike_with_a_ninety_day_expiry(api):
    """PRD §3.7: "One `CopyrightStrike` row is created in status `ACTIVE`, with
    its `expires_at` set to ninety days after its own creation."
    PRD §3.7: "A `CopyrightStrike` records the `strike_sequence`, a one-based
    ordinal of the strike within its channel ordered by `created_at` ascending"

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel, item, ref, claim = _taken_down_channel("Strike US", "rh-strike-a", "fp-strike-a")

    strikes, meta = validate_paginated(api.list_claim_copyright_strikes(
        claim["id"], TEST_USERS["any_headers"]))
    assert len(strikes) == 1, f"the takedown must raise exactly one strike, got {len(strikes)}"
    strike = strikes[0]
    assert strike["status"] == "ACTIVE"
    assert strike["strike_sequence"] == 1
    assert strike["claim_id"] == claim["id"]
    assert strike["content_item_id"] == item["id"]
    assert strike["channel_id"] == channel["id"]
    assert strike["expires_at"] > strike["created_at"]

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["copyright_strike_count"] == 1
    assert after["last_copyright_strike_activated_at"] is not None


def test_first_takedown_leaves_the_channel_posture_open(api):
    """PRD §3.7: "one strike leaves posture `OPEN`"
    PRD §3.7: "The owning channel's `copyright_strike_count` is recomputed as the
    number of its `ACTIVE` `CopyrightStrike` rows"

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel, _item, _ref, _claim = _taken_down_channel("Strike Open US",
                                                       "rh-strike-open", "fp-strike-open")

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["copyright_strike_count"] == 1
    assert after["monetization_posture"] == "OPEN"