"""Channel creation, the monetization application loop and the reviewer queue.

Covers the channel onboarding surface and the reviewer decision choke point
between classification and monetization.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_channel,
    assert_channel_posture_matches_facts,
    create_channel_payload,
    create_content_item_payload,
    create_membership_schedule_payload,
    create_reference_file_payload,
    create_revenue_routing_payload,
    create_strike_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


# ─── Channel creation ────────────────────────────────

def test_channel_create_returns_every_declared_field_and_starts_not_applied(api):
    """PRD §3.1: "A newly created channel starts with `monetization_status` set
    to `MONETIZATION_NOT_APPLIED`, `monetization_posture` set to `OPEN`,
    `copyright_strike_count` at 0 and `last_copyright_strike_activated_at` null."
    PRD §2.5: "`id` (string): a server-minted UUID with no type prefix and no
    embedded entity name."
    PRD §2.5: "`version` (integer): a counter starting at 1 that increments by
    exactly 1 on every mutation"

    Design: Corner/entities/channel_create_returns_every_declared_field_and_starts_not_applied
    """
    res = api.create_channel(
        create_channel_payload(channel_name="Fresh Channel",
                               lifetime_watch_hours=500, subscriber_count=20),
        TEST_USERS["anonymous_headers"])
    channel = validate_success(res, 201)

    assert_channel(channel)
    assert channel["monetization_status"] == "MONETIZATION_NOT_APPLIED"
    assert channel["monetization_posture"] == "OPEN"
    assert channel["copyright_strike_count"] == 0
    assert channel["last_copyright_strike_activated_at"] is None
    assert channel["version"] == 1


def test_channel_defaults_applied_when_optional_fields_omitted(api):
    """PRD §3.1: "`tax_tin_status`, which defaults to `TIN_MISSING` and takes the
    value `TIN_PROVIDED` once documentation is on file; `tax_treaty`, a boolean
    defaulting to false that records whether a reduced-rate treaty applies for a
    non-US `country_code`; `payment_threshold_cents`, the adjusted-net balance a
    payout batch must reach before it may be issued and which defaults to 10000;
    and `policy_strike_count`, which defaults to 0"

    Design: Corner/entities/channel_defaults_applied_when_optional_fields_omitted
    """
    channel = get_success_data(api.create_channel(
        create_channel_payload(channel_name="Defaults Channel", country_code="US",
                               lifetime_watch_hours=4000, subscriber_count=1000),
        TEST_USERS["anonymous_headers"]))

    assert channel["membership_offered"] is False
    assert channel["tax_tin_status"] == "TIN_MISSING"
    assert channel["tax_treaty"] is False
    assert channel["payment_threshold_cents"] == 10000
    assert channel["policy_strike_count"] == 0


def test_channel_get_with_unknown_id_returns_not_found(api):
    """PRD §2.7: "an unknown channel yields `ERR_CHANNEL_NOT_FOUND`"

    Design: Corner/entities/channel_get_with_unknown_id_returns_not_found
    """
    res = api.get_channel(NON_EXISTENT_UUID, TEST_USERS["any_headers"])
    validate_error(res, "ERR_CHANNEL_NOT_FOUND", expected_status=404)


def test_channel_patch_updates_only_mutable_configuration(api):
    """PRD §3.1: "The updatable surface is exactly `channel_name`,
    `country_code`, `tax_tin_status`, `tax_treaty`, `payment_threshold_cents` and
    `policy_strike_count`"
    PRD §3.1: "Any such change increments the channel's `version` by 1 and
    triggers a recomputation of `monetization_posture`"

    Design: Corner/endpoints/channel_patch_updates_only_mutable_configuration
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Patch Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    original_name = channel["channel_name"]
    original_watch_hours = channel["lifetime_watch_hours"]

    updated = validate_success(api.patch_channel(
        channel["id"],
        {"payment_threshold_cents": 5000, "tax_tin_status": "TIN_PROVIDED",
         "tax_treaty": True},
        TEST_USERS["platform_admin_headers"]), 200)

    assert updated["payment_threshold_cents"] == 5000
    assert updated["tax_tin_status"] == "TIN_PROVIDED"
    assert updated["tax_treaty"] is True
    assert updated["channel_name"] == original_name
    assert updated["lifetime_watch_hours"] == original_watch_hours
    assert updated["version"] == channel["version"] + 1
    assert_channel_posture_matches_facts(updated)


# ─── Monetization eligibility ────────────────────────

@pytest.mark.parametrize("watch_hours,subscribers", [(3999, 1000), (4000, 999)])
def test_monetization_application_below_the_thresholds_is_rejected(api, watch_hours, subscribers):
    """PRD §3.1: "below 4000 watch hours or below 1000 subscribers — is reported
    as `ERR_MONETIZATION_INELIGIBLE` (HTTP 409)"

    Design: Corner/validations/monetization_application_below_watch_time_is_rejected
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Just Short Channel", lifetime_watch_hours=watch_hours,
        subscriber_count=subscribers), TEST_USERS["anonymous_headers"]))

    res = api.apply_monetization(channel["id"], make_creator_headers(channel["id"]))
    validate_error(res, "ERR_MONETIZATION_INELIGIBLE", expected_status=409)

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["monetization_status"] == "MONETIZATION_NOT_APPLIED"


def test_monetization_application_with_active_policy_strike_is_blocked(api):
    """PRD §3.1: "a non-zero policy strike count is reported separately as
    `ERR_MONETIZATION_BLOCKED_BY_STRIKE` (HTTP 409)"

    Design: Corner/validations/monetization_application_with_active_policy_strike_is_blocked
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Struck Channel", lifetime_watch_hours=5000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))
    validate_success(api.issue_strike(channel["id"], create_strike_payload(
        reason_code="HATE_SPEECH"), TEST_USERS["moderator_headers"]), 201)

    res = api.apply_monetization(channel["id"], make_creator_headers(channel["id"]))
    validate_error(res, "ERR_MONETIZATION_BLOCKED_BY_STRIKE", expected_status=409)


def test_rejected_channel_may_reapply_once_thresholds_hold(api):
    """PRD §3.1: "A rejected channel may re-apply once it meets the eligibility
    thresholds again, which returns it to `MONETIZATION_PENDING` and puts it back
    into the review queue."

    Design: Corner/validations/rejected_channel_may_reapply_once_thresholds_hold
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Reapply Channel", lifetime_watch_hours=5000,
        subscriber_count=1200), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    validate_success(api.apply_monetization(channel["id"], creator), 200)
    validate_success(api.review_monetization(
        channel["id"], {"decision": "REJECT", "note": "Insufficient original content."},
        TEST_USERS["monetization_reviewer_headers"]), 200)

    reapplied = validate_success(api.apply_monetization(channel["id"], creator), 200)
    assert reapplied["monetization_status"] == "MONETIZATION_PENDING"


# ─── Reviewer queue and the decision gate ────────────

def test_review_queue_with_no_pending_channel_returns_an_empty_array(api):
    """PRD §3.1: "When no channel is pending, the queue is simply an empty array
    and no error is raised."

    Design: Corner/cross_cutting_layers/review_queue_with_no_pending_channel_returns_an_empty_array
    """
    get_success_data(api.create_channel(create_channel_payload(
        channel_name="Idle Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))

    data, meta = validate_paginated(api.get_review_queue(
        TEST_USERS["monetization_reviewer_headers"]))
    assert data == []
    assert meta["total_count"] == 0


def test_review_queue_ranks_pending_channels_by_the_score_expression(api):
    """PRD §3.1: "The review queue returns only channels whose
    `monetization_status` is `MONETIZATION_PENDING`, ranked by a composite health
    score"
    PRD §3.1: "Candidates are ordered by that score descending, with ties broken
    by `created_at` ascending"
    PRD §3.1: "Channels in `MONETIZATION_APPROVED`, `MONETIZATION_REJECTED`,
    `MONETIZATION_REVOKED` or `MONETIZATION_NOT_APPLIED` are excluded from the
    candidate set regardless of how strong their score would be."

    Design: Corner/endpoints/review_queue_ranks_pending_channels_by_the_score_expression
    """
    high = get_success_data(api.create_channel(create_channel_payload(
        channel_name="High Reach", country_code="US", lifetime_watch_hours=100000,
        subscriber_count=50000), TEST_USERS["anonymous_headers"]))
    low = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Low Reach", country_code="US", lifetime_watch_hours=5000,
        subscriber_count=1100), TEST_USERS["anonymous_headers"]))
    never = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Never Applied", country_code="US",
        lifetime_watch_hours=999999, subscriber_count=999999),
        TEST_USERS["anonymous_headers"]))

    for ch in (high, low):
        validate_success(api.apply_monetization(ch["id"], make_creator_headers(ch["id"])), 200)

    data, meta = validate_paginated(api.get_review_queue(
        TEST_USERS["monetization_reviewer_headers"]))

    ids = [row["id"] for row in data]
    assert meta["total_count"] == 2, f"queue should hold only the pending channels, got {ids}"
    assert ids[0] == high["id"], "the higher-scoring channel must rank first"
    assert never["id"] not in ids, "a never-applied channel must be absent from the queue"


def test_review_approval_blocked_by_a_limitless_item(api):
    """PRD §3.2: "A single item carrying `NO_ADS` blocks the approval and produces
    `ERR_CLASSIFICATION_BLOCKS_MONETIZATION` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/review_approval_blocked_by_a_limitless_item
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Gated Review US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500, tax_tin_status="TIN_PROVIDED",
        payment_threshold_cents=100), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(title="Unfriendly Source",
                                                   category_code="GAMBLING"), creator))
    validate_success(api.request_review(channel["id"], item["id"], creator), 200)
    validate_success(api.classify_item(
        item["id"], {"category_codes": ["GAMBLING", "ALCOHOL"], "like_count": 1,
                     "comment_count": 1}, TEST_USERS["reviewer_headers"]), 200)
    validate_success(api.apply_monetization(channel["id"], creator), 200)

    res = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                  TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_CLASSIFICATION_BLOCKS_MONETIZATION", expected_status=409)


def test_approval_blocked_leaves_channel_still_pending(api):
    """PRD §3.2: "A single item carrying `NO_ADS` blocks the approval and produces
    `ERR_CLASSIFICATION_BLOCKS_MONETIZATION` (HTTP 409)."

    Design: Difficulty/cross_entity_state_dependency/review_approval_blocked_by_a_limitless_item
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Gated Review Two", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(category_code="GAMBLING"), creator))
    validate_success(api.request_review(channel["id"], item["id"], creator), 200)
    validate_success(api.classify_item(
        item["id"], {"category_codes": ["GAMBLING", "TRAGEDY"], "like_count": 0,
                     "comment_count": 0}, TEST_USERS["reviewer_headers"]), 200)
    validate_success(api.apply_monetization(channel["id"], creator), 200)

    api.review_monetization(channel["id"], {"decision": "APPROVE"},
                            TEST_USERS["monetization_reviewer_headers"])

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["monetization_status"] == "MONETIZATION_PENDING"


def test_membership_schedule_requires_approved_channel(api):
    """PRD §3.10: "Publishing is available only while the owning channel's
    `monetization_status` is `MONETIZATION_APPROVED`; a channel in any other
    monetization status is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/membership_schedule_requires_approved_channel
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Schedule Gated US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))
    assert channel["monetization_status"] == "MONETIZATION_NOT_APPLIED"

    res = api.create_membership_schedule(
        channel["id"], create_membership_schedule_payload(tier_name="Early Access",
                                                          monthly_fee_cents=499),
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_schedule_publish_succeeds_once_channel_approved(api):
    """PRD §3.10: "Publishing is available only while the owning channel's
    `monetization_status` is `MONETIZATION_APPROVED`; a channel in any other
    monetization status is refused with `ERR_INVALID_STATE` (HTTP 409)"

    Design: Difficulty/cross_entity_state_dependency/membership_schedule_requires_approved_channel
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Schedule Open US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    validate_success(api.apply_monetization(channel["id"], creator), 200)
    validate_success(api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                             TEST_USERS["monetization_reviewer_headers"]), 200)

    schedule = validate_success(api.create_membership_schedule(
        channel["id"], create_membership_schedule_payload(tier_name="Early Access",
                                                          monthly_fee_cents=499),
        creator), 201)
    assert schedule["tier_name"] == "Early Access"

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["membership_offered"] is True


def test_decision_state_beats_restricted_posture(api):
    """PRD §2.10: "4. **State admissibility** — the target resource must be in a
    state that admits the operation; publishing a membership schedule
    additionally requires the owning channel to be in `MONETIZATION_APPROVED`.
    A failure is `ERR_INVALID_STATE` (HTTP 409)."
    PRD §3.2: "Only a channel currently in `MONETIZATION_PENDING` may be
    reviewed; anything else is refused as `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/decision_state_beats_restricted_posture
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Decision US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(title="Decision Source"), creator))
    validate_success(api.request_review(channel["id"], item["id"], creator), 200)
    validate_success(api.issue_strike(channel["id"], create_strike_payload(
        reason_code="HATE_SPEECH"), TEST_USERS["moderator_headers"]), 201)

    restricted = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert restricted["monetization_posture"] == "RESTRICTED"

    res = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                  TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)

    after = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["monetization_status"] == "MONETIZATION_NOT_APPLIED"


def test_monetization_review_on_a_not_applied_channel_is_invalid_state(api):
    """PRD §3.2: "Only a channel currently in `MONETIZATION_PENDING` may be
    reviewed; anything else is refused as `ERR_INVALID_STATE` (HTTP 409)."

    Design: Difficulty/priority_pair_validation_conflict/decision_state_beats_restricted_posture
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Never Pending US", country_code="US", lifetime_watch_hours=8000,
        subscriber_count=1500), TEST_USERS["anonymous_headers"]))

    res = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                  TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_INVALID_STATE", expected_status=409)


def test_monetization_review_response_reflects_the_cascade_immediately(api):
    """PRD §3.2: "4. The same cascade recomputes the content item's
    `holds_revenue` to true. This is the value the review response reports, so a
    reviewer sees immediately that the item's money is now parked rather than
    paid."
    PRD §3.2: "1. The channel's `monetization_status` becomes
    `MONETIZATION_APPROVED`, and every content item of that channel whose
    `upload_status` is `CLASSIFIED` is settled forward to
    `CLAIM_SCAN_COMPLETE`."

    Design: Corner/cross_cutting_layers/monetization_review_response_reflects_the_cascade_immediately
    """
    channel = get_success_data(api.create_channel(create_channel_payload(
        channel_name="Immediate Channel", country_code="US", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])

    # The reference file is registered before the item is uploaded, so the item's
    # own rights scan materialises its claim and the claim-revenue-lock cascade
    # parks the item's money straight away.
    validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Immediate Rights",
                                      reference_fingerprint="fp-immediate-1"),
        make_rights_holder_headers("rh-immediate-1")), 201)
    item = get_success_data(api.create_content_item(
        channel["id"], create_content_item_payload(title="Immediate Item"), creator))
    scanned = validate_success(api.request_review(channel["id"], item["id"], creator), 200)
    assert scanned["upload_status"] == "CLAIM_SCAN_COMPLETE"
    assert scanned["holds_revenue"] is True

    validate_success(api.apply_monetization(channel["id"], creator), 200)

    approved = validate_success(api.review_monetization(
        channel["id"], {"decision": "APPROVE"},
        TEST_USERS["monetization_reviewer_headers"]), 200)
    assert approved["monetization_status"] == "MONETIZATION_APPROVED"

    settled = get_success_data(api.get_content_item(item["id"], TEST_USERS["any_headers"]))
    assert settled["upload_status"] == "CLAIM_SCAN_COMPLETE"
    assert settled["holds_revenue"] is True