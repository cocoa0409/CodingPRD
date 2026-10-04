"""Composite setup helpers for multi-step test prerequisites.

Every helper builds its preconditions from scratch through PRD-declared
endpoints, because the harness restarts the server (empty database) before each
test.  Setup calls use ``get_success_data()`` so a broken precondition raises a
clear "Setup failed" error rather than a confusing assertion failure.
"""
from prd_bench_local_runner.testing import get_success_data, validate_paginated

from .api_client import api_client
from .constants import LOGICAL_CLOCK_START, PERIOD_END, PERIOD_START, TEST_DEFAULTS
from .factories import (
    create_channel_payload,
    create_claim_payload,
    create_classification_payload,
    create_content_item_payload,
    create_dispute_payload,
    create_membership_payload,
    create_payout_lock_payload,
    create_reference_file_payload,
    create_revenue_routing_payload,
    create_strike_payload,
)
from .test_users import (
    TEST_USERS,
    make_creator_headers,
    make_rights_holder_headers,
)


def _ok(response):
    return get_success_data(response)


def reset_clock(to_iso8601=LOGICAL_CLOCK_START):
    """Move the logical clock to a known instant (PRD §2.9)."""
    return _ok(api_client.set_clock(to_iso8601, TEST_USERS["platform_admin_headers"]))


# ─── Tier 1: Single-entity creation ──────────────────

def create_channel(headers=None, **overrides):
    """Create a channel as Anonymous (the unauthenticated creation surface)."""
    return _ok(api_client.create_channel(
        create_channel_payload(**overrides),
        headers or TEST_USERS["anonymous_headers"]))


def create_content_item(channel_id, **overrides):
    """Upload a content item owned by ``channel_id``."""
    return _ok(api_client.create_content_item(
        channel_id, create_content_item_payload(**overrides),
        make_creator_headers(channel_id)))


def create_reference_file(rights_holder_id="rh-test-1", **overrides):
    """Register a rights-holder reference file."""
    return _ok(api_client.create_reference_file(
        create_reference_file_payload(**overrides),
        make_rights_holder_headers(rights_holder_id)))


def issue_strike(channel_id, **overrides):
    """Issue one ACTIVE community strike on the channel (PRD §3.7)."""
    return _ok(api_client.issue_strike(
        channel_id, create_strike_payload(**overrides),
        TEST_USERS["moderator_headers"]))


def create_claim(content_item_id, reference_file_id, **overrides):
    """File a manual claim as the reference file's own rights holder."""
    return _ok(api_client.create_claim(
        create_claim_payload(content_item_id, reference_file_id, **overrides),
        make_rights_holder_headers(reference_file_id)))


# ─── Tier 2: State progression ───────────────────────

def apply_for_monetization(channel_id):
    """MONETIZATION_NOT_APPLIED/REJECTED -> MONETIZATION_PENDING (PRD §3.1)."""
    return _ok(api_client.apply_monetization(channel_id, make_creator_headers(channel_id)))


def approve_channel(channel_id):
    """Drive a pending application to MONETIZATION_APPROVED (PRD §3.2)."""
    return _ok(api_client.review_monetization(
        channel_id, {"decision": "APPROVE"},
        TEST_USERS["monetization_reviewer_headers"]))


def reject_channel(channel_id, note="Insufficient original content."):
    """Drive a pending application to MONETIZATION_REJECTED (PRD §3.2)."""
    return _ok(api_client.review_monetization(
        channel_id, {"decision": "REJECT", "note": note},
        TEST_USERS["monetization_reviewer_headers"]))


def create_approved_channel(**overrides):
    """Create a channel and walk it all the way to MONETIZATION_APPROVED.

    Because posture is OPEN throughout, and no reference file exists, the
    approval cascade settles nothing.
    """
    channel = create_channel(**overrides)
    apply_for_monetization(channel["id"])
    return approve_channel(channel["id"])


def create_approved_channel_with_item(approve=True, item_overrides=None, **overrides):
    """Channel + one content item driven through its rights scan.

    With ``approve=True`` the channel is approved first, so the item resolves to
    CLAIM_SCAN_COMPLETE only if a reference file matches it — otherwise it rests
    at CLASSIFIED.  Returns (channel, item, upload_status_before_review).
    """
    channel = create_channel(**overrides)
    item = create_content_item(channel["id"], **(item_overrides or {}))
    before_status = item["upload_status"]
    item = _ok(api_client.request_review(channel["id"], item["id"],
                                         make_creator_headers(channel["id"])))
    if approve:
        apply_for_monetization(channel["id"])
        channel = approve_channel(channel["id"])
    return channel, item, before_status


def create_classified_item(channel_id, categories=None, like_count=10,
                           comment_count=5, **item_overrides):
    """Item resting at CLASSIFIED (or CLAIM_SCAN_COMPLETE) after its scan."""
    item = create_content_item(channel_id, **item_overrides)
    item = _ok(api_client.request_review(channel_id, item["id"],
                                         make_creator_headers(channel_id)))
    if categories:
        item = _ok(api_client.classify_item(
            item["id"], create_classification_payload(
                categories, like_count=like_count, comment_count=comment_count),
            TEST_USERS["reviewer_headers"]))
    return item


def create_item_with_claim(channel_id, reference_file_id, matched=True,
                           item_overrides=None, claim_overrides=None,
                           rights_holder_id="rh-claim-1", approve=False,
                           reference_overrides=None):
    """Channel + reference file + reviewed item + (optionally) one ACTIVE claim.

    The reference file is registered before the item's review when
    ``matched=True`` so the rights scan creates the claim automatically; this is
    the shape most claim-lifecycle tests need.
    """
    if matched:
        ref = create_reference_file(rights_holder_id, **(reference_overrides or {}))
    else:
        ref = None
    item = create_content_item(channel_id, **(item_overrides or {}))
    item = _ok(api_client.request_review(channel_id, item["id"],
                                         make_creator_headers(channel_id)))
    if approve:
        apply_for_monetization(channel_id)
        approve_channel(channel_id)
    claims, _ = validate_claim_list(api_client.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item["id"]}))
    if ref is not None and not claims:
        claim = create_claim(item["id"], ref["id"], **(claim_overrides or {}))
        claims = [claim]
    return ref, item, claims


def validate_claim_list(response):
    return validate_paginated(response)


def get_item(item_id):
    return _ok(api_client.get_content_item(item_id, TEST_USERS["any_headers"]))


def get_channel(channel_id):
    return _ok(api_client.get_channel(channel_id, TEST_USERS["any_headers"]))


def get_claim(claim_id):
    return _ok(api_client.get_claim(claim_id, TEST_USERS["any_headers"]))


def get_channel_version(channel_id):
    return get_channel(channel_id)["version"]


def get_item_version(item_id):
    return get_item(item_id)["version"]


def first_claim_of_item(item_id):
    """The single claim the rights scan materialised on an item."""
    claims, _ = validate_claim_list(api_client.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item_id}))
    assert claims, f"setup expected at least one claim on item {item_id}"
    return claims[0]


def route_revenue(item_id, stream_type="AD", gross_revenue_cents=TEST_DEFAULTS["AD_GROSS_CENTS"],
                  **overrides):
    """Create one routing record against the item's current version."""
    payload = create_revenue_routing_payload(
        item_id, get_item_version(item_id), stream_type=stream_type,
        gross_revenue_cents=gross_revenue_cents, **overrides)
    return _ok(api_client.create_revenue_routing(
        payload, TEST_USERS["platform_admin_headers"]))


def lock_payout(channel_id, period_start_at=PERIOD_START, period_end_at=PERIOD_END):
    """Assemble and lock a ROUTE-stage payout batch (PRD §3.11)."""
    return _ok(api_client.lock_payout(
        channel_id,
        create_payout_lock_payload(get_channel_version(channel_id),
                                   period_start_at=period_start_at,
                                   period_end_at=period_end_at),
        TEST_USERS["platform_admin_headers"]))


def release_payout(channel_id, batch_id, expected_version=None):
    """Release a locked batch, supplying its observed version (PRD §3.11)."""
    version = expected_version
    if version is None:
        version = _ok(api_client.get_channel_payout(
            channel_id, batch_id, TEST_USERS["any_headers"]))["version"]
    return api_client.release_payout(
        channel_id, batch_id, {"expected_payout_batch_version": version},
        TEST_USERS["platform_admin_headers"])


def enroll_member(channel_id, member_name="Test Member", monthly_fee_cents=499,
                  joined_at=None, headers=None):
    payload = {"member_name": member_name, "monthly_fee_cents": monthly_fee_cents}
    if joined_at is not None:
        payload["joined_at"] = joined_at
    return _ok(api_client.create_membership(
        channel_id, payload, headers or TEST_USERS["platform_admin_headers"]))


# ─── Tier 3: Claim ladder lifecycle ──────────────────

def dispute_claim(claim_id, channel_id, reason_code="FAIR_USE", **overrides):
    """File a dispute as the owning creator (PRD §3.5)."""
    claim = get_claim(claim_id)
    payload = create_dispute_payload(claim["version"], reason_code=reason_code, **overrides)
    return _ok(api_client.dispute_claim(claim_id, payload, make_creator_headers(channel_id)))


def file_appeal(claim_id, reference_file_id, grounds_code="REVIEW_ERROR"):
    """File an appeal as the rights holder that owns the reference (PRD §3.6)."""
    return _ok(api_client.file_appeal(
        claim_id, {"grounds_code": grounds_code},
        make_rights_holder_headers(reference_file_id)))


def decide_appeal(claim_id, appeal_id, reference_file_id, decision):
    """Decide a pending appeal (PRD §3.6)."""
    return _ok(api_client.decide_appeal(
        claim_id, appeal_id, {"decision": decision},
        make_rights_holder_headers(reference_file_id)))


def claim_in_disputed_state(channel_id, reference_file_id=None, rights_holder_id="rh-ladder-1",
                            reason_code="FAIR_USE", item_overrides=None):
    """Channel+matching reference+reviewed item, then dispute the auto claim.

    Returns (reference_file, item, claim) with the claim in DISPUTED.
    """
    ref, item, claims = create_item_with_claim(
        channel_id, reference_file_id, rights_holder_id=rights_holder_id,
        item_overrides=item_overrides)
    claim = claims[0]
    claim = dispute_claim(claim["id"], channel_id, reason_code=reason_code)
    return ref, item, claim


def claim_at_second_appeal(channel_id, rights_holder_id="rh-second-1",
                           item_overrides=None, reference_overrides=None):
    """Walk a claim to a PENDING SECOND-level appeal.

    DISPUTED -> APPEALED (FIRST) -> DENIED -> DISPUTED -> APPEALED (SECOND).
    Returns (reference_file, item, claim, pending_second_appeal).
    """
    ref, item, claims = create_item_with_claim(
        channel_id, None, rights_holder_id=rights_holder_id,
        item_overrides=item_overrides, reference_overrides=reference_overrides)
    claim = claims[0]
    claim = dispute_claim(claim["id"], channel_id)
    first = file_appeal(claim["id"], ref["id"])
    decide_appeal(claim["id"], first["id"], ref["id"], "DENY")
    second = file_appeal(claim["id"], ref["id"], grounds_code="NEW_EVIDENCE")
    return ref, item, get_claim(claim["id"]), second


def claim_taken_down(channel_id, rights_holder_id="rh-takedown-1",
                     item_overrides=None, reference_overrides=None):
    """Full ladder through TAKEN_DOWN.

    Returns (reference_file, item, claim) with claim.status == TAKEN_DOWN.
    """
    ref, item, claim, _second = claim_at_second_appeal(
        channel_id, rights_holder_id=rights_holder_id,
        item_overrides=item_overrides, reference_overrides=reference_overrides)
    _ok(api_client.take_down_claim(claim["id"], make_rights_holder_headers(ref["id"])))
    return ref, item, get_claim(claim["id"])


def claim_taken_down_then_released(channel_id, rights_holder_id="rh-release-1",
                                  item_overrides=None, reference_overrides=None):
    """TAKEN_DOWN -> counter-notification -> RELEASE.

    Returns (reference_file, item, claim, routing_or_none).
    """
    ref, item, claim = claim_taken_down(
        channel_id, rights_holder_id=rights_holder_id,
        item_overrides=item_overrides, reference_overrides=reference_overrides)
    _ok(api_client.file_counter_notification(
        claim["id"], {"statement": "I own the master recording."},
        make_creator_headers(channel_id)))
    _ok(api_client.resolve_dispute(
        claim["id"], {"resolution": "RELEASE"},
        make_rights_holder_headers(ref["id"])))
    return ref, item, get_claim(claim["id"])


# ─── Tier 4: Accumulation / threshold targeting ──────

def channel_with_strikes(n=1, **overrides):
    """Create a channel already carrying ``n`` ACTIVE COMMUNITY strikes.

    History is written the declared way — one issuance at a time — so the
    cascading recomputation runs exactly as it would in production.
    """
    channel = create_channel(**overrides)
    for _ in range(n):
        issue_strike(channel["id"])
    return get_channel(channel["id"])


def channel_with_strikes_and_item(n=2, item_overrides=None, **overrides):
    """A struck channel plus one reviewed item, for posture-gate boundary tests."""
    channel = channel_with_strikes(n=n, **overrides)
    item = create_classified_item(channel["id"], **(item_overrides or {}))
    return channel, item


def channel_with_copyright_strikes(n=1, rights_holder_id="rh-cx-1",
                                   item_overrides=None, **overrides):
    """Create a channel already carrying ``n`` ACTIVE CopyrightStrike rows.

    Each one is produced by a real takedown of a freshly built claim, so the
    strike counters and the last_copyright_strike_activated_at field are
    recomputed by the declared cascade rather than seeded by hand.
    Returns (channel, item_of_last_takedown, claim_of_last_takedown).
    """
    channel = create_channel(**overrides)
    item = claim = None
    for i in range(n):
        ref, item, claim, _second = claim_at_second_appeal(
            channel["id"], rights_holder_id=f"{rights_holder_id}-{i}",
            item_overrides=item_overrides,
            reference_overrides={"reference_fingerprint": f"fp-cx-{i}"})
        _ok(api_client.take_down_claim(claim["id"], make_rights_holder_headers(ref["id"])))
        claim = get_claim(claim["id"])
    return get_channel(channel["id"]), item, claim


def approved_channel_routed(stream_type="AD",
                            gross_revenue_cents=TEST_DEFAULTS["AD_GROSS_CENTS"],
                            item_overrides=None, **overrides):
    """Approved channel + one reviewed item + one routing record.

    The item carries no claim, so the routing lands as PAID_CREATOR.
    Returns (channel, item, routing).
    """
    channel = create_approved_channel(**overrides)
    item = create_classified_item(channel["id"], **(item_overrides or {}))
    routing = route_revenue(item["id"], stream_type=stream_type,
                            gross_revenue_cents=gross_revenue_cents)
    return channel, item, routing


def approved_channel_with_three_ad_routings(gross_each=1001, **overrides):
    """The per-record rounding scenario: three AD routings of equal gross.

    Returns (channel, item, [routing_1, routing_2, routing_3]).
    """
    channel = create_approved_channel(**overrides)
    item = create_classified_item(channel["id"])
    routings = [route_revenue(item["id"], stream_type="AD", gross_revenue_cents=gross_each)
                for _ in range(3)]
    return channel, item, routings


def approved_channel_with_waterfall(channel_claims=1, gross_cents=3003, **overrides):
    """Approved channel + one item of ``gross_cents`` carrying ``channel_claims``
    ACTIVE claims of equal confidence, plus a reference file per claim.

    Returns (channel, item, [claims], [reference_files]).
    """
    channel = create_approved_channel(**overrides)
    refs = []
    for i in range(channel_claims):
        refs.append(create_reference_file(
            f"rh-waterfall-{i}",
            reference_fingerprint=f"fp-waterfall-{i}",
            rights_holder_name=f"Waterfall Rights {i}"))
    item = create_content_item(channel["id"], title="Waterfall Source",
                              duration_seconds=700)
    item = _ok(api_client.request_review(channel["id"], item["id"],
                                         make_creator_headers(channel["id"])))
    claims = []
    for ref in refs:
        claims.append(create_claim(item["id"], ref["id"], match_confidence=0.900))
    return channel, item, claims, refs


# ─── Tier 5: Finalization / terminal states ──────────

def revoked_channel_by_community_strikes(n=3, **overrides):
    """A channel pushed to MONETIZATION_REVOKED by ``n`` community strikes."""
    return channel_with_strikes(n=n, **overrides)


def revoked_channel_by_copyright_strikes(n=3, **overrides):
    """A channel pushed to MONETIZATION_REVOKED by copyright strikes alone."""
    channel, item, claim = channel_with_copyright_strikes(n=n, **overrides)
    return channel


def approved_channel_locked_batch(gross_cents=10000, stream_type="AD",
                                  channel_overrides=None, item_overrides=None,
                                  with_claim=False, rights_holder_id="rh-lock-1"):
    """Approved channel + reviewed item + one routing + a locked payout batch.

    With ``with_claim=True`` a matching reference file makes the routing land as
    ESCROW instead of PAID_CREATOR.
    Returns (channel, item, routing, batch).
    """
    overrides = dict(channel_overrides or {})
    channel = create_approved_channel(**overrides)
    ref = None
    if with_claim:
        ref = create_reference_file(rights_holder_id,
                                    reference_fingerprint=f"fp-{rights_holder_id}")
    item = create_content_item(channel["id"], **(item_overrides or {}))
    item = _ok(api_client.request_review(channel["id"], item["id"],
                                         make_creator_headers(channel["id"])))
    routing = route_revenue(item["id"], stream_type=stream_type,
                            gross_revenue_cents=gross_cents)
    batch = lock_payout(channel["id"])
    return channel, item, routing, batch