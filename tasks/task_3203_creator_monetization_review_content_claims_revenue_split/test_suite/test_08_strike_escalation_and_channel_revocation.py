"""Strike escalation, posture recomputation and channel revocation.

Covers the copyright-strike chain that moves a channel from OPEN through
RESTRICTED to FROZEN, and the community-strike counter that revokes monetization.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_share_conservation,
    create_approved_channel,
    create_channel_payload,
    create_claim_payload,
    create_classification_payload,
    create_classified_item,
    create_content_item_payload,
    create_payout_lock_payload,
    create_reference_file_payload,
    create_revenue_routing_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_success,
)


def _posture_channel(name, community_strikes=0, **overrides):
    """Channel carrying a filed monetization application, raising its strikes.

    The channel is left at `MONETIZATION_PENDING`: strikes narrow the posture
    without ever deciding the application, so the strike counters and the
    monetization status remain independent axes, and the third community strike
    can still revoke the channel.
    """
    payload = create_channel_payload(channel_name=name, country_code="US",
                                     lifetime_watch_hours=8000, subscriber_count=1500,
                                     tax_tin_status="TIN_PROVIDED",
                                     payment_threshold_cents=100)
    payload.update(overrides)
    channel = get_success_data(api_client.create_channel(
        payload, TEST_USERS["anonymous_headers"]))
    validate_success(api_client.apply_monetization(
        channel["id"], make_creator_headers(channel["id"])), 200)
    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"][:community_strikes]:
        validate_success(api_client.issue_strike(
            channel["id"], {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)
    return get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))


def _register_reference(name, fingerprint):
    return get_success_data(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name=name,
                                      reference_fingerprint=fingerprint),
        make_rights_holder_headers(f"rh-{fingerprint}")))


def _claim_ladder_to_second_appeal(channel, ref):
    """Item with a matching reference, driven to a pending SECOND-level appeal.

    Stops one step short of takedown so that several ladders can be advanced
    before any takedown narrows the channel's posture.
    """
    item = validate_success(api_client.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title=f"Source {ref['id'][:8]}"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    claim = validate_success(api_client.create_claim(
        create_claim_payload(item["id"], ref["id"], match_confidence=0.900),
        make_rights_holder_headers(ref["id"])), 201)
    claim = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "MISMATCH"},
        make_creator_headers(channel["id"])), 200)
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    return get_success_data(api_client.get_claim(
        claim["id"], TEST_USERS["any_headers"])), item


def _claim_ladder_to_takedown(channel, ref):
    """Item with a matching reference, driven through the ladder to takedown."""
    item = validate_success(api_client.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title=f"Source {ref['id'][:8]}"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    claim = validate_success(api_client.create_claim(
        create_claim_payload(item["id"], ref["id"], match_confidence=0.900),
        make_rights_holder_headers(ref["id"])), 201)
    claim = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "MISMATCH"},
        make_creator_headers(channel["id"])), 200)
    first = validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "REVIEW_ERROR"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.decide_appeal(
        claim["id"], first["id"], {"decision": "DENY"},
        make_rights_holder_headers(ref["id"])), 200)
    validate_success(api_client.file_appeal(
        claim["id"], {"grounds_code": "NEW_EVIDENCE"},
        make_rights_holder_headers(ref["id"])), 200)
    return validate_success(api_client.take_down_claim(
        claim["id"], make_rights_holder_headers(ref["id"])), 200), item


# ─── Copyright strike chain ──────────────────────────

def test_second_copyright_strike_narrows_the_channel_to_restricted(api):
    """PRD §3.7: "Otherwise, if `copyright_strike_count` is exactly 2, the
    channel's `monetization_posture` becomes `RESTRICTED`."
    PRD §3.7: "The owning channel's `copyright_strike_count` is recomputed as the
    number of its `ACTIVE` `CopyrightStrike` rows"

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel = _posture_channel("Strike US")
    ref_a = _register_reference("Strike Rights A", "fp-strike-a-1")
    ref_b = _register_reference("Strike Rights B", "fp-strike-a-2")

    _claim, _item = _claim_ladder_to_takedown(channel, ref_a)
    after_first = get_success_data(api_client.get_channel(
        channel["id"], TEST_USERS["any_headers"]))
    assert after_first["copyright_strike_count"] == 1
    assert after_first["monetization_posture"] == "OPEN"

    _claim_two, _item_two = _claim_ladder_to_takedown(channel, ref_b)
    after_second = get_success_data(api_client.get_channel(
        channel["id"], TEST_USERS["any_headers"]))
    assert after_second["copyright_strike_count"] == 2
    assert after_second["monetization_posture"] == "RESTRICTED"


def test_second_copyright_strike_still_leaves_monetization_approved(api):
    """PRD §3.7: "Otherwise, if `copyright_strike_count` is exactly 2, the
    channel's `monetization_posture` becomes `RESTRICTED`."
    PRD §3.1: "Applying for monetization moves a channel from
    `MONETIZATION_NOT_APPLIED` to `MONETIZATION_PENDING`

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel = _posture_channel("Strike Status US")
    ref_a = _register_reference("Strike Status A", "fp-strike-s-1")
    ref_b = _register_reference("Strike Status B", "fp-strike-s-2")

    _claim_ladder_to_takedown(channel, ref_a)
    _claim_ladder_to_takedown(channel, ref_b)

    after = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["copyright_strike_count"] == 2
    assert after["monetization_status"] == "MONETIZATION_PENDING", (
        "two strikes restrict the posture without revoking the monetization status")


def test_second_copyright_strike_also_blocks_further_takedowns(api):
    """PRD §3.7: "Otherwise, if `copyright_strike_count` is exactly 2, the
    channel's `monetization_posture` becomes `RESTRICTED`."
    PRD §2.4: "A `RESTRICTED` posture is narrower still: it refuses new
    monetization applications and re-applications, dispute filings,
    classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (HTTP
    409), while leaving the read surface and the majority of the earnings
    workflow intact."

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel = _posture_channel("Strike Lockout US")
    ref_a = _register_reference("Strike Lockout A", "fp-strike-l-1")
    ref_b = _register_reference("Strike Lockout B", "fp-strike-l-2")
    ref_c = _register_reference("Strike Lockout C", "fp-strike-l-3")

    # All three ladders advance to a pending SECOND-level appeal while the
    # channel is still OPEN — a RESTRICTED channel refuses the dispute that the
    # ladder needs — and only then are the takedowns attempted in sequence.
    claim_a, _item_a = _claim_ladder_to_second_appeal(channel, ref_a)
    claim_b, _item_b = _claim_ladder_to_second_appeal(channel, ref_b)
    claim_c, _item_c = _claim_ladder_to_second_appeal(channel, ref_c)

    validate_success(api_client.take_down_claim(
        claim_a["id"], make_rights_holder_headers(ref_a["id"])), 200)
    validate_success(api_client.take_down_claim(
        claim_b["id"], make_rights_holder_headers(ref_b["id"])), 200)

    restricted = get_success_data(api_client.get_channel(
        channel["id"], TEST_USERS["any_headers"]))
    assert restricted["monetization_posture"] == "RESTRICTED"

    # A third takedown cannot land on a RESTRICTED channel, so the third strike
    # can only ever arrive through the no-ads re-classification cascade, which
    # carries no posture gate.
    blocked = api_client.take_down_claim(
        claim_c["id"], make_rights_holder_headers(ref_c["id"]))
    validate_error(blocked, "ERR_POSTURE_RESTRICTED", expected_status=409)

    still = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert still["copyright_strike_count"] == 2, (
        "a second strike restricts the channel, so no further takedown may be issued")
    assert still["monetization_posture"] == "RESTRICTED"


def test_third_copyright_strike_via_reclassification_revokes_the_channel(api):
    """PRD §3.7: "If `copyright_strike_count` has reached 3 or more, the channel's
    `monetization_status` becomes `MONETIZATION_REVOKED`, its
    `monetization_posture` becomes `FROZEN`, and every payout batch of that channel
    currently in status `LOCKED` is moved to `FAILED`."
    PRD §3.7: "A re-classification therefore punishes a video's own discovery of
    unsuitable content with the same strike machinery that a rights-holder
    escalation would trigger."

    Design: Difficulty/transitive_cascade/takedown_strike_chain_revokes_channel_monetization
    """
    channel = _posture_channel("Reclass Revoke US")

    # The third strike arrives through the no-ads re-classification cascade, so
    # the item it lands on is driven through its rights scan first, while the
    # channel is still OPEN; that scan materialises its single claim.
    ref_c = _register_reference("Reclass Revoke C", "fp-reclass-r-3")
    item_c = validate_success(api_client.request_review(
        channel["id"],
        get_success_data(api_client.create_content_item(
            channel["id"], create_content_item_payload(title="Reclass Source"),
            make_creator_headers(channel["id"])))["id"],
        make_creator_headers(channel["id"])), 200)
    assert item_c["upload_status"] == "CLAIM_SCAN_COMPLETE"

    ref_a = _register_reference("Reclass Revoke A", "fp-reclass-r-1")
    ref_b = _register_reference("Reclass Revoke B", "fp-reclass-r-2")
    claim_a, _item_a = _claim_ladder_to_second_appeal(channel, ref_a)
    claim_b, _item_b = _claim_ladder_to_second_appeal(channel, ref_b)

    validate_success(api_client.take_down_claim(
        claim_a["id"], make_rights_holder_headers(ref_a["id"])), 200)
    validate_success(api_client.take_down_claim(
        claim_b["id"], make_rights_holder_headers(ref_b["id"])), 200)

    mid = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert mid["copyright_strike_count"] == 2
    assert mid["monetization_posture"] == "RESTRICTED"

    # A third takedown cannot land on the now-RESTRICTED channel, so the third
    # strike arrives through the no-ads re-classification cascade, which takes
    # down every claim on the item and raises one CopyrightStrike per claim.
    settled = validate_success(api_client.classify_item(
        item_c["id"],
        create_classification_payload(["GAMBLING", "ALCOHOL"], like_count=1,
                                      comment_count=1),
        TEST_USERS["reviewer_headers"]), 200)
    assert settled["ad_suitability"] == "NO_ADS"

    after = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["copyright_strike_count"] == 3
    assert after["monetization_status"] == "MONETIZATION_REVOKED"
    assert after["monetization_posture"] == "FROZEN"


# ─── The posture boundary ────────────────────────────

def test_restricted_posture_allows_revenue_routing(api):
    """PRD §2.4: "A `RESTRICTED` posture is narrower still: it refuses new
    monetization applications and re-applications, dispute filings,
    classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (HTTP
    409), while leaving the read surface and the majority of the earnings
    workflow intact."
    PRD §3.8: "The creator receives the half-up rounding of the record's gross
    amount multiplied by the stream's rate: 0.55 for `AD`"

    Design: Difficulty/boundary_precision_check/frozen_posture_blocks_routing_while_restricted_allows_it
    """
    channel = _posture_channel("Boundary US", community_strikes=2)
    assert channel["monetization_posture"] == "RESTRICTED"

    item = create_classified_item(channel["id"], title="Boundary Source")
    routing = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"],
                                       stream_type="AD", gross_revenue_cents=100),
        TEST_USERS["platform_admin_headers"]), 201)

    assert routing["creator_share_cents"] == 55
    assert routing["partner_share_cents"] == 45
    assert_share_conservation(routing)


def test_frozen_posture_rejects_the_identical_routing_call(api):
    """PRD §2.4: "The consequence of `FROZEN` is that every operation which routes
    or pays out revenue is refused with `ERR_POSTURE_FROZEN` (HTTP 409)."

    Design: Difficulty/boundary_precision_check/frozen_posture_blocks_routing_while_restricted_allows_it
    """
    channel = _posture_channel("Boundary Frozen US")
    # The item is driven through its rights scan while the channel is still
    # OPEN; requesting classification review is itself a FROZEN-gated write.
    item = create_classified_item(channel["id"], title="Boundary Frozen Source")

    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"]:
        validate_success(api_client.issue_strike(
            channel["id"], {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)

    frozen = get_success_data(api_client.get_channel(channel["id"],
                                                     TEST_USERS["any_headers"]))
    assert frozen["monetization_posture"] == "FROZEN"
    assert frozen["monetization_status"] == "MONETIZATION_REVOKED"

    fresh = get_success_data(api_client.get_content_item(item["id"],
                                                         TEST_USERS["any_headers"]))
    res = api_client.create_revenue_routing(
        create_revenue_routing_payload(fresh["id"], fresh["version"],
                                       stream_type="AD", gross_revenue_cents=100),
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_POSTURE_FROZEN", expected_status=409)


def test_frozen_posture_fails_locked_payout_batches(api):
    """PRD §3.7: "every payout batch of that channel currently in status `LOCKED`
    is moved to `FAILED`."

    Design: Difficulty/boundary_precision_check/frozen_posture_blocks_routing_while_restricted_allows_it
    """
    channel = _posture_channel("Boundary Batches US", community_strikes=2)
    item = create_classified_item(channel["id"], title="Boundary Batch Source")
    validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"],
                                       stream_type="AD", gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    current = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    batch = validate_success(api_client.lock_payout(
        channel["id"], create_payout_lock_payload(current["version"]),
        TEST_USERS["platform_admin_headers"]), 200)
    assert batch["status"] == "LOCKED"

    validate_success(api_client.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "SEXUAL_CONTENT"},
        TEST_USERS["moderator_headers"]), 201)

    failed = get_success_data(api_client.get_channel_payout(
        channel["id"], batch["id"], TEST_USERS["any_headers"]))
    assert failed["status"] == "FAILED"


# ─── Community strike counter ────────────────────────

def test_monetization_revoke_is_maintained_by_the_strike_counter(api):
    """PRD §3.7: "When the third `ACTIVE` `COMMUNITY` strike lands on a channel,
    the channel's `monetization_status` becomes `MONETIZATION_REVOKED`"

    Design: Corner/state_machines/monetization_revoke_is_maintained_by_the_strike_counter
    """
    channel = _posture_channel("Revoke Channel", community_strikes=2)
    assert channel["policy_strike_count"] == 2

    revoked = validate_success(api_client.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "SEXUAL_CONTENT"},
        TEST_USERS["moderator_headers"]), 201)

    after = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert after["policy_strike_count"] == 3
    assert after["monetization_status"] == "MONETIZATION_REVOKED"
    assert after["monetization_posture"] == "FROZEN"
    assert revoked["status"] == "ACTIVE"


def test_strike_escalation_crosses_restrict_then_terminate(api):
    """PRD §2.4: "Otherwise, if `policy_strike_count` is greater than zero,
    posture is `RESTRICTED`."
    PRD §3.7: "the constant is the `POLICY_TERMINATION_THRESHOLD` of 3, so a
    channel on its first or second community strike continues to operate,
    narrowing to `RESTRICTED` at that point only if it has also accumulated two or
    more active copyright strikes."
    PRD §3.7: "the channel's `monetization_status` becomes `MONETIZATION_REVOKED`"

    Design: Corner/cross_cutting_layers/strike_escalation_crosses_restrict_then_terminate
    """
    channel = _posture_channel("Escalation Channel", community_strikes=1)
    assert channel["policy_strike_count"] == 1
    assert channel["monetization_posture"] == "RESTRICTED"

    validate_success(api_client.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "HATE_SPEECH"},
        TEST_USERS["moderator_headers"]), 201)
    at_two = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert at_two["policy_strike_count"] == 2
    assert at_two["monetization_posture"] == "RESTRICTED"
    assert at_two["monetization_status"] == "MONETIZATION_PENDING"

    validate_success(api_client.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "SEXUAL_CONTENT"},
        TEST_USERS["moderator_headers"]), 201)
    at_three = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert at_three["policy_strike_count"] == 3
    assert at_three["monetization_posture"] == "FROZEN"
    assert at_three["monetization_status"] == "MONETIZATION_REVOKED"


# ─── Other stream splits ─────────────────────────────

def test_super_chat_split_applies_the_seventy_percent_rate(api):
    """PRD §3.8: "The creator receives the half-up rounding of the record's gross
    amount multiplied by the stream's rate: 0.55 for `AD`, 0.70 for `MEMBERSHIP`,
    0.70 for `SUPER_CHAT`, and 0.60 for `SHOPPING`."

    Design: Corner/calculations/super_chat_split_applies_the_seventy_percent_rate
    """
    channel = create_approved_channel(channel_name="Super Chat Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000)
    item = create_classified_item(channel["id"], title="Live Stream VOD",
                                  duration_seconds=3600)

    routing = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"],
                                       stream_type="SUPER_CHAT",
                                       gross_revenue_cents=1000),
        TEST_USERS["platform_admin_headers"]), 201)

    assert routing["creator_share_cents"] == 700
    assert routing["partner_share_cents"] == 300
    assert_share_conservation(routing)


def test_adjusted_net_waterfall_excludes_escrow_but_keeps_it_in_gross(api):
    """PRD §3.11: "`held_cents` sums the creator shares of the `ESCROW` subset
    only — money that is parked rather than payable."
    PRD §3.11: "The payer base is the batch's `creator_share_cents` minus its
    `held_cents`, which excludes the parked escrow money from the payable amount."
    PRD §3.11: "`gross_cents` sums those rows' gross amounts, `creator_share_cents`
    sums their creator shares"

    Design: Corner/calculations/adjusted_net_waterfall_excludes_escrow_but_keeps_it_in_gross
    """
    channel = create_approved_channel(channel_name="Waterfall Split Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000, tax_tin_status="TIN_PROVIDED",
                                      payment_threshold_cents=100)
    creator = make_creator_headers(channel["id"])

    # Item A carries no claim, so its routing lands as PAID_CREATOR.  It is left
    # before its rights scan so that the reference file registered for item B
    # cannot retroactively capture it (PRD §3.4 captures only items resting at
    # CLASSIFIED), and the only claim in play is the one filed against item B.
    item_free = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title="Free Item"), creator))
    assert item_free["holds_revenue"] is False
    routing_free = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item_free["id"], item_free["version"],
                                       stream_type="AD", gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    assert routing_free["status"] == "PAID_CREATOR"

    # Item B has its revenue parked by the system cascade, which writes a
    # RETROACTIVE_OWED row; the routing minted while the item is holding is then
    # dated ESCROW (PRD §3.8), giving the batch the parked subset it must strip
    # back out of the payable amount.
    item_claimed = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title="Claimed Item"), creator))
    first = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item_claimed["id"], item_claimed["version"],
                                       stream_type="AD", gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    assert first["status"] == "PAID_CREATOR"

    locked = validate_success(api_client.set_revenue_lock(
        item_claimed["id"], {"locked": True, "reason_code": "PENDING_RETRO"},
        TEST_USERS["platform_admin_headers"]), 200)
    assert locked["holds_revenue"] is True

    escrow = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item_claimed["id"],
                                       get_success_data(api_client.get_content_item(
                                           item_claimed["id"],
                                           TEST_USERS["any_headers"]))["version"],
                                       stream_type="AD", gross_revenue_cents=10000),
        TEST_USERS["platform_admin_headers"]), 201)
    assert escrow["status"] == "ESCROW"

    current = get_success_data(api_client.get_channel(channel["id"], TEST_USERS["any_headers"]))
    batch = validate_success(api_client.lock_payout(
        channel["id"], create_payout_lock_payload(current["version"]),
        TEST_USERS["platform_admin_headers"]), 200)

    # Both rows are live: the free item's is PAID_CREATOR and the held item's is
    # ESCROW, so the batch sums both gross amounts and both creator shares, parks
    # only the ESCROW row's share, and carries the remainder as adjusted net.
    assert batch["gross_cents"] == 20000
    assert batch["creator_share_cents"] == 11000
    assert batch["partner_share_cents"] == 9000
    assert batch["held_cents"] == 5500, "only the ESCROW row's creator share is parked"
    assert batch["adjusted_net_cents"] == 5500


def test_ad_share_rounds_half_up_on_the_half_cent(api):
    """PRD §3.8: "The creator receives the half-up rounding of the record's gross
    amount multiplied by the stream's rate: 0.55 for `AD`"

    Design: Corner/calculations/ad_share_rounds_half_up_on_the_half_cent
    """
    channel = create_approved_channel(channel_name="Half Cent Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000)
    item = create_classified_item(channel["id"], title="Half Cent Item")

    routing = validate_success(api_client.create_revenue_routing(
        create_revenue_routing_payload(item["id"], item["version"],
                                       stream_type="AD", gross_revenue_cents=1001),
        TEST_USERS["platform_admin_headers"]), 201)

    assert routing["creator_share_cents"] == 551, "1001 * 0.55 = 550.55 rounds half-up"
    assert routing["partner_share_cents"] == 450
    assert_share_conservation(routing)


def test_unsupported_stream_type_rejection(api):
    """PRD §3.8: "A stream type outside those four values is rejected with
    `ERR_UNSUPPORTED_STREAM_TYPE` (HTTP 400)."

    Design: Corner/errors/unsupported_stream_type_rejection
    """
    channel = create_approved_channel(channel_name="Stream Type Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000)

    res = api.create_revenue_event(
        channel["id"], {"stream_type": "MERCHANDISE", "amount_cents": 500},
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_UNSUPPORTED_STREAM_TYPE", expected_status=400)


def test_supported_stream_type_is_accepted(api):
    """PRD §3.8: "A stream type outside those four values is rejected with
    `ERR_UNSUPPORTED_STREAM_TYPE` (HTTP 400)."
    PRD §3.8: "The event is created with `routed` false and its `occurred_at`
    stamped with the current logical clock instant, and it stays unrouted until a
    routing row is minted from it."

    Design: Corner/errors/unsupported_stream_type_rejection
    """
    channel = create_approved_channel(channel_name="Stream Type OK Channel",
                                      country_code="US", lifetime_watch_hours=4000,
                                      subscriber_count=1000)

    event = validate_success(api.create_revenue_event(
        channel["id"], {"stream_type": "SUPER_CHAT", "amount_cents": 500},
        TEST_USERS["platform_admin_headers"]), 201)

    assert event["stream_type"] == "SUPER_CHAT"
    assert event["amount_cents"] == 500
    assert event["routed"] is False