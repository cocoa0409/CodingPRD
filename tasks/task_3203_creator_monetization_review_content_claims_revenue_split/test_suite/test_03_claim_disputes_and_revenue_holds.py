"""Claim filing, the revenue lock, disputes and the dispute window.

Covers a claim's initial derived bookkeeping and the money-parking consequence
of a dispute, plus the compensating release that restores it.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    api_client,
    assert_claim,
    assert_share_conservation,
    create_channel_payload,
    create_claim_payload,
    create_content_item_payload,
    create_reference_file_payload,
    get_success_data,
    make_creator_headers,
    make_rights_holder_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _approved_channel(name, **overrides):
    payload = create_channel_payload(channel_name=name, country_code="US",
                                     lifetime_watch_hours=8000,
                                     subscriber_count=1500,
                                     token="unused")
    payload.pop("token", None)
    payload.update(overrides)
    channel = get_success_data(api_client.create_channel(payload,
                                                         TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    validate_success(api_client.apply_monetization(channel["id"], creator), 200)
    return validate_success(api_client.review_monetization(
        channel["id"], {"decision": "APPROVE"},
        TEST_USERS["monetization_reviewer_headers"]), 200)


def _reviewed_item_with_claim(channel, rights_holder_id, fingerprint, title="Source"):
    ref = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(
            rights_holder_name=f"Rights {rights_holder_id}",
            reference_fingerprint=fingerprint),
        make_rights_holder_headers(rights_holder_id)))
    creator = make_creator_headers(channel["id"])
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title=title), creator))
    item = validate_success(api_client.request_review(channel["id"], item["id"], creator), 200)
    data, _meta = validate_paginated(api_client.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item["id"]}))
    return ref, item, data[0]


def _item_routing(item_id):
    data, _meta = validate_paginated(api_client.list_item_routings(
        item_id, TEST_USERS["any_headers"]))
    assert data, f"expected a routing record on item {item_id}"
    return data[0]


# ─── Claim creation ──────────────────────────────────

def test_claim_initial_state_is_active_and_dispute_window_is_preserved(api):
    """PRD §3.4: "When the owning channel's posture is `OPEN`, a manual claim
    starts `ACTIVE` with `lock_reason` set to `PENDING_RETRO`, and it runs the
    same claim-revenue-lock cascade as an automatic claim."
    PRD §3.4: "A manually filed claim records `source` as `MANUAL`."
    PRD §3.4: "Its `taken_down_at` timestamp stays null until the claim reaches
    `TAKEN_DOWN`."
    PRD §3.4: "Its `dispute_deadline_at` is null until the claim first becomes
    `DISPUTED`, at which point it is set to thirty days after the claim's
    `created_at`."

    Design: Corner/state_machines/claim_initial_state_is_active_and_dispute_window_is_preserved
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Init Claim Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    ref = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(reference_fingerprint="fp-initclaim-1"),
        make_rights_holder_headers("rh-initclaim-1")))
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title="Init Claim Item"),
        make_creator_headers(channel["id"])))
    validate_success(api_client.request_review(channel["id"], item["id"],
                                               make_creator_headers(channel["id"])), 200)

    claim = validate_success(api_client.create_claim(
        create_claim_payload(item["id"], ref["id"], match_confidence=0.820,
                             claim_level="HIGH"),
        make_rights_holder_headers(ref["id"])), 201)

    assert_claim(claim)
    assert claim["status"] == "ACTIVE"
    assert claim["source"] == "MANUAL"
    assert claim["lock_reason"] == "PENDING_RETRO"
    assert claim["revenue_locked"] is True
    assert claim["match_confidence"] == 0.820
    assert claim["claim_level"] == "HIGH"
    assert claim["taken_down_at"] is None
    assert claim["dispute_deadline_at"] is None


def test_dispute_stamps_the_deadline_and_parks_the_items_revenue(api):
    """PRD §3.5: "Every revenue routing row belonging to the claimed content item
    whose status is `PAID_CREATOR` is converted to `RETROACTIVE_OWED`, with its
    `creator_share_cents` zeroed and its `partner_share_cents` raised to the full
    `gross_revenue_cents` of that row."
    PRD §3.5: "The content item's `routed_revenue_cents` is then recomputed to
    zero, and its `holds_revenue` flag is recomputed to true."

    Design: Difficulty/compensating_invariant/dispute_then_release_restores_creator_share_cents_exactly
    """
    channel = _approved_channel("Invariant US", payment_threshold_cents=100)
    _ref, item, claim = _reviewed_item_with_claim(
        channel, "rh-invariant-1", "fp-invariant-1", "Invariant Source")
    routing = get_success_data(api_client.create_revenue_routing(
        {"content_item_id": item["id"], "stream_type": "AD", "gross_revenue_cents": 10000,
         "expected_content_item_version": get_success_data(api_client.get_content_item(
             item["id"], TEST_USERS["any_headers"]))["version"]},
        TEST_USERS["platform_admin_headers"]))
    assert routing["status"] == "PAID_CREATOR"
    assert routing["creator_share_cents"] == 5500

    disputed = validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "LICENSED"},
        make_creator_headers(channel["id"])), 200)
    assert disputed["status"] == "DISPUTED"
    assert disputed["dispute_deadline_at"] is not None

    after_dispute = get_success_data(api_client.get_content_item(
        item["id"], TEST_USERS["any_headers"]))
    assert after_dispute["routed_revenue_cents"] == 0
    assert after_dispute["holds_revenue"] is True

    parked = _item_routing(item["id"])
    assert parked["status"] == "RETROACTIVE_OWED"
    assert parked["creator_share_cents"] == 0
    assert parked["partner_share_cents"] == 10000
    assert_share_conservation(parked)


def test_release_restores_creator_share_cents_exactly(api):
    """PRD §3.5: "From the `DISPUTED` state that resolution closes the open
    `ClaimDispute` row to `RELEASED`, moves the claim to `RELEASED`, returns its
    `lock_reason` to `NONE`, and recomputes the content item's `holds_revenue` to
    false and its `routed_revenue_cents` to its restored figure."

    Design: Difficulty/compensating_invariant/dispute_then_release_restores_creator_share_cents_exactly
    """
    channel = _approved_channel("Invariant Release US", payment_threshold_cents=100)
    ref, item, claim = _reviewed_item_with_claim(
        channel, "rh-invariant-2", "fp-invariant-2", "Invariant Release")
    routing = get_success_data(api_client.create_revenue_routing(
        {"content_item_id": item["id"], "stream_type": "AD", "gross_revenue_cents": 10000,
         "expected_content_item_version": get_success_data(api_client.get_content_item(
             item["id"], TEST_USERS["any_headers"]))["version"]},
        TEST_USERS["platform_admin_headers"]))
    assert routing["creator_share_cents"] == 5500

    validate_success(api_client.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "LICENSED"},
        make_creator_headers(channel["id"])), 200)
    released = validate_success(api_client.resolve_dispute(
        claim["id"], {"resolution": "RELEASE"},
        make_rights_holder_headers(ref["id"])), 200)

    assert released["status"] == "RELEASED"
    assert released["lock_reason"] == "NONE"

    restored_item = get_success_data(api_client.get_content_item(
        item["id"], TEST_USERS["any_headers"]))
    assert restored_item["routed_revenue_cents"] == 5500
    assert restored_item["holds_revenue"] is False

    # The release restores the routing row the dispute had parked: PRD §3.5
    # recomputes `routed_revenue_cents` "to its restored figure", and §3.6 names
    # `RELEASED_TO_CREATOR` and the royalty_share_split values as the shape of
    # that restoration.
    rows, _meta = validate_paginated(api_client.list_item_routings(
        item["id"], TEST_USERS["any_headers"]))
    assert rows, "the release must leave the item's routing row in place"
    restored = rows[0]
    assert restored["gross_revenue_cents"] == routing["gross_revenue_cents"]
    assert restored["status"] == "RELEASED_TO_CREATOR"
    assert restored["creator_share_cents"] == 5500
    assert restored["partner_share_cents"] == 4500
    assert_share_conservation(restored)


def test_second_dispute_on_the_same_claim_is_rejected(api):
    """PRD §3.5: "a claim already sitting in `DISPUTED` cannot be disputed a
    second time and yields `ERR_CLAIM_ALREADY_DISPUTED` (HTTP 409)"

    Design: Corner/state_machines/second_dispute_on_the_same_claim_is_rejected
    """
    channel = _approved_channel("Idem Channel 2")
    _ref, _item, claim = _reviewed_item_with_claim(channel, "rh-idem-2", "fp-idem-2",
                                                   "Idem Item")
    creator = make_creator_headers(channel["id"])
    validate_success(api.dispute_claim(
        claim["id"], {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        creator), 200)

    current = get_success_data(api.get_claim(claim["id"], TEST_USERS["any_headers"]))
    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": current["version"], "reason_code": "MISMATCH"},
        creator)
    validate_error(res, "ERR_CLAIM_ALREADY_DISPUTED", expected_status=409)

    disputes, meta = validate_paginated(api.list_claim_disputes(
        claim["id"], TEST_USERS["any_headers"]))
    assert meta["total_count"] == 1, "the claim must carry exactly one dispute"
    assert disputes[0]["status"] == "FILED"


def test_dispute_is_refused_on_a_frozen_channel(api):
    """PRD §3.5: "And the owning channel's `monetization_posture` must not be
    `FROZEN`, or the filing is refused with `ERR_POSTURE_FROZEN`."
    PRD §2.4: "The consequence of `FROZEN` is that every operation which routes
    or pays out revenue is refused with `ERR_POSTURE_FROZEN` (HTTP 409). This
    covers four operations precisely: filing a dispute, requesting review of an
    upload (which drives an item into classification), and both the lock and the
    release stages of payout."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_closed_dispute_window
    """
    channel = _approved_channel("Frozen Dispute US")
    _ref, _item, claim = _reviewed_item_with_claim(channel, "rh-frozendispute-1",
                                                   "fp-frozendispute-1", "Frozen Source")
    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"]:
        validate_success(api.issue_strike(
            channel["id"],
            {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)

    frozen = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert frozen["monetization_posture"] == "FROZEN"

    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_POSTURE_FROZEN", expected_status=409)


def test_frozen_posture_refuses_a_dispute_whose_window_has_also_lapsed(api):
    """PRD §2.10: "5. **Posture gates** — a `FROZEN` posture rejects every
    revenue-generating or monetization write with `ERR_POSTURE_FROZEN`, and a
    `RESTRICTED` posture rejects new monetization applications, dispute filings,
    classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (both HTTP
    409)."
    PRD §2.10: "the server reports only the highest-priority failure"

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_closed_dispute_window
    """
    channel = _approved_channel("Conflict US")
    ref, _item, claim = _reviewed_item_with_claim(channel, "rh-conflict-1",
                                                  "fp-conflict-1", "Conflict Source")

    _, meta = validate_paginated(api.list_claim_disputes(claim["id"],
                                                         TEST_USERS["any_headers"]))
    assert meta["total_count"] == 0, "the setup must leave the claim undisputed"

    # The third ACTIVE community strike revokes the channel, pinning its posture
    # to FROZEN while the claim is still open.
    for reason in ["VIOLENT_CONTENT", "HATE_SPEECH", "SEXUAL_CONTENT"]:
        validate_success(api.issue_strike(
            channel["id"], {"kind": "COMMUNITY", "reason_code": reason},
            TEST_USERS["moderator_headers"]), 201)

    # Past the thirty-day window on a FROZEN channel: both the temporal rule and
    # the posture rule are violated, and the posture gate outranks the window.
    validate_success(api.set_clock("2026-10-15T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)
    frozen = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert frozen["monetization_posture"] == "FROZEN"

    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_POSTURE_FROZEN", expected_status=409)


def test_closed_dispute_window_is_reported_when_no_posture_rule_applies(api):
    """PRD §3.5: "once that window has lapsed the filing is refused with
    `ERR_DISPUTE_WINDOW_CLOSED` (HTTP 409)"

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_beats_closed_dispute_window
    """
    validate_success(api.set_clock("2026-09-01T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)
    channel = _approved_channel("Closed Window US")
    _ref, _item, claim = _reviewed_item_with_claim(channel, "rh-closedwin-1",
                                                   "fp-closedwin-1", "Closed Window Source")

    validate_success(api.set_clock("2026-10-15T00:00:00Z",
                                   TEST_USERS["platform_admin_headers"]), 200)
    open_posture = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert open_posture["monetization_posture"] == "OPEN"

    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_DISPUTE_WINDOW_CLOSED", expected_status=409)


def test_dispute_is_refused_on_a_restricted_channel(api):
    """PRD §2.4: "A `RESTRICTED` posture is narrower still: it refuses new
    monetization applications and re-applications, dispute filings,
    classification appeals and takedowns with `ERR_POSTURE_RESTRICTED` (HTTP
    409), while leaving the read surface and the majority of the earnings
    workflow intact."

    Design: Difficulty/boundary_precision_check/frozen_posture_blocks_routing_while_restricted_allows_it
    """
    channel = _approved_channel("Restricted Dispute US")
    _ref, _item, claim = _reviewed_item_with_claim(channel, "rh-restrdispute-1",
                                                   "fp-restrdispute-1", "Restricted Source")
    validate_success(api.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "HATE_SPEECH"},
        TEST_USERS["moderator_headers"]), 201)

    restricted = get_success_data(api.get_channel(channel["id"], TEST_USERS["any_headers"]))
    assert restricted["monetization_posture"] == "RESTRICTED"

    res = api.dispute_claim(
        claim["id"],
        {"expected_claim_version": claim["version"], "reason_code": "FAIR_USE"},
        make_creator_headers(channel["id"]))
    validate_error(res, "ERR_POSTURE_RESTRICTED", expected_status=409)