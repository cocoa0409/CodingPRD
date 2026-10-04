"""Role permissions, listing surfaces and resource existence rules.

Covers the exclusive operations of each role, the unauthenticated surface, and
the fingerprint uniqueness constraint on reference registration.
"""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    TEST_USERS,
    api_client,
    create_channel_payload,
    create_claim_payload,
    create_content_item_payload,
    create_membership_payload,
    create_reference_file_payload,
    get_success_data,
    make_creator_headers,
    make_no_role_headers,
    make_rights_holder_headers,
    make_unknown_role_headers,
    validate_error,
    validate_paginated,
    validate_success,
)


def _pending_channel(name):
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name=name, country_code="US", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    validate_success(api_client.apply_monetization(channel["id"], creator), 200)
    return channel


# ─── Role exclusivity ────────────────────────────────

def test_creator_cannot_review_its_own_monetization_application(api):
    """PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation, or whose principal is acting on a resource it does not
    own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/creator_cannot_review_its_own_monetization_application
    """
    channel = _pending_channel("Self Review Channel")

    res = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                  make_creator_headers(channel["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_creator_cannot_file_a_claim_on_its_own_item(api):
    """PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation, or whose principal is acting on a resource it does not
    own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/creator_cannot_file_a_claim_on_its_own_item
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Self Claim Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    ref = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(reference_fingerprint="fp-selfclaim-1"),
        make_rights_holder_headers("rh-selfclaim-1")))
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title="Self Claim Item"), creator))
    validate_success(api.request_review(channel["id"], item["id"], creator), 200)

    res = api.create_claim(create_claim_payload(item["id"], ref["id"], match_confidence=0.800),
                           make_creator_headers(channel["id"]))
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)


def test_reviewer_cannot_issue_a_community_strike(api):
    """PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation, or whose principal is acting on a resource it does not
    own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."

    Design: Corner/rbac/reviewer_cannot_issue_a_community_strike
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Strike Authz Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))

    res = api.issue_strike(channel["id"], {"kind": "COMMUNITY", "reason_code": "HATE_SPEECH"},
                           TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    allowed = validate_success(api.issue_strike(
        channel["id"], {"kind": "COMMUNITY", "reason_code": "HATE_SPEECH"},
        TEST_USERS["moderator_headers"]), 201)
    assert allowed["status"] == "ACTIVE"


def test_clock_control_is_refused_for_a_non_admin_role(api):
    """PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation, or whose principal is acting on a resource it does not
    own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.9: "The clock is advanced only by a `PlatformAdmin`-only test-driving
    capability, which accepts a `to_iso8601` instant and moves the logical clock
    to that value."

    Design: Corner/rbac/platform_admin_cannot_be_denied_the_clock_control
    """
    res = api.set_clock("2026-12-01T00:00:00Z",
                        TEST_USERS["monetization_reviewer_headers"])
    validate_error(res, "ERR_FORBIDDEN_ROLE", expected_status=403)

    advanced = validate_success(api.set_clock("2026-12-01T00:00:00Z",
                                              TEST_USERS["platform_admin_headers"]), 200)
    assert advanced == {} or isinstance(advanced, dict)


def test_unauthorized_role_is_rejected(api):
    """PRD §2.1: "A request whose declared role is not permitted to perform the
    requested operation, or whose principal is acting on a resource it does not
    own, is rejected with `ERR_FORBIDDEN_ROLE` (HTTP 403)."
    PRD §2.1: "A request that omits `X-User-Role`, or supplies a value that is not
    one of the roles named below, is rejected with `ERR_UNAUTHENTICATED` (HTTP
    401)."

    Design: Corner/errors/unauthorized_role_is_rejected
    """
    channel = _pending_channel("Authz Channel")

    forbidden = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                        make_creator_headers(channel["id"]))
    validate_error(forbidden, "ERR_FORBIDDEN_ROLE", expected_status=403)

    missing_role = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                           make_no_role_headers())
    validate_error(missing_role, "ERR_UNAUTHENTICATED", expected_status=401)

    unknown_role = api.review_monetization(channel["id"], {"decision": "APPROVE"},
                                           make_unknown_role_headers())
    validate_error(unknown_role, "ERR_UNAUTHENTICATED", expected_status=401)

    allowed = validate_success(api.review_monetization(
        channel["id"], {"decision": "APPROVE"},
        TEST_USERS["monetization_reviewer_headers"]), 200)
    assert allowed["monetization_status"] == "MONETIZATION_APPROVED"


# ─── Listing surfaces ────────────────────────────────

def test_channel_listing_paginates_with_total_count_and_has_more(api):
    """PRD §2.3: "`limit` caps the number of rows returned, defaults to 10 when
    omitted, and must be at least 1 and at most 100."
    PRD §2.3: "Every list response carries `limit`, `offset`, `total_count` and
    `has_more` inside the envelope's `meta` object."

    Design: Corner/entities/channel_listing_paginates_with_total_count_and_has_more
    """
    for name, country in [("Page One", "US"), ("Page Two", "GB")]:
        validate_success(api.create_channel(create_channel_payload(
            channel_name=name, country_code=country, lifetime_watch_hours=1000,
            subscriber_count=10), TEST_USERS["anonymous_headers"]), 201)

    first, meta = validate_paginated(api.list_channels(TEST_USERS["any_headers"],
                                                       params={"limit": 1, "offset": 0}))
    assert len(first) == 1
    assert meta["total_count"] == 2
    assert meta["has_more"] is True

    second, meta_second = validate_paginated(api.list_channels(
        TEST_USERS["any_headers"], params={"limit": 1, "offset": 1}))
    assert len(second) == 1
    assert meta_second["has_more"] is False
    assert second[0]["id"] != first[0]["id"]


def test_claim_reverse_list_filters_by_status(api):
    """PRD §2.3: "The claim listing accepts a `content_item_id` filter, a
    `reference_file_id` filter and a `status` filter, each narrowing the result
    set to rows matching the supplied value."

    Design: Corner/endpoints/claim_reverse_list_filters_by_status
    """
    channel = get_success_data(api_client.create_channel(create_channel_payload(
        channel_name="Claim Filter Channel", lifetime_watch_hours=4000,
        subscriber_count=1000), TEST_USERS["anonymous_headers"]))
    creator = make_creator_headers(channel["id"])
    # The first reference is registered before the item is uploaded, so the
    # item's own rights scan claims it; the second reference is registered only
    # afterwards, by which time the item has left CLASSIFIED and the retroactive
    # capture of PRD §3.4 no longer reaches it.
    ref_one = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name="Filter Rights One",
                                      reference_fingerprint="fp-clfilter-1"),
        make_rights_holder_headers("rh-clfilter-1")))
    item = get_success_data(api_client.create_content_item(
        channel["id"], create_content_item_payload(title="Claim Filter Item"), creator))
    scanned = validate_success(
        api.request_review(channel["id"], item["id"], creator), 200)
    assert scanned["upload_status"] == "CLAIM_SCAN_COMPLETE"

    ref_two = get_success_data(api_client.create_reference_file(
        create_reference_file_payload(rights_holder_name="Filter Rights Two",
                                      reference_fingerprint="fp-clfilter-2"),
        make_rights_holder_headers("rh-clfilter-2")))

    data, meta = validate_paginated(api.list_claims(
        TEST_USERS["any_headers"], params={"content_item_id": item["id"]}))
    assert meta["total_count"] == 1, "only the scan's own claim is in play"
    released = data[0]
    assert released["reference_file_id"] == ref_one["id"]

    # The claim the filter is meant to exclude is taken all the way to RELEASED:
    # PRD §3.5 only admits the release as a resolution of a DISPUTED (or
    # TAKEN_DOWN) claim, and the holder's RELEASE resolution is what leaves it in
    # the RELEASED status the filter drops.
    released = validate_success(api.dispute_claim(
        released["id"],
        {"expected_claim_version": released["version"], "reason_code": "LICENSED"},
        creator), 200)
    released = validate_success(api.resolve_dispute(
        released["id"], {"resolution": "RELEASE"},
        make_rights_holder_headers(ref_one["id"])), 200)
    assert released["status"] == "RELEASED"

    active = validate_success(api_client.create_claim(
        create_claim_payload(item["id"], ref_two["id"], match_confidence=0.700),
        make_rights_holder_headers(ref_two["id"])), 201)

    data, meta = validate_paginated(api.list_claims(
        TEST_USERS["any_headers"],
        params={"content_item_id": item["id"], "status": "ACTIVE"}))
    assert meta["total_count"] == 1
    assert data[0]["id"] == active["id"], "the released claim must be filtered out"


# ─── Reference fingerprint uniqueness ────────────────

def test_reference_file_fingerprint_must_be_globally_unique(api):
    """PRD §3.4: "The `reference_fingerprint` is a globally unique key across the
    entire platform: a registration that reuses an existing fingerprint is
    rejected outright with `ERR_DUPLICATE_REFERENCE_FINGERPRINT` (HTTP 409), and
    no two reference files may share one."

    Design: Corner/entities/reference_file_fingerprint_must_be_globally_unique
    """
    validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Uniq Rights",
                                      asset_kind="AUDIO",
                                      reference_fingerprint="fp-uniq-1",
                                      policy_mode="TRACK",
                                      claimed_segment_seconds=30),
        make_rights_holder_headers("rh-uniq-1")), 201)

    duplicate = api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Uniq Rights Two",
                                      asset_kind="VIDEO",
                                      reference_fingerprint="fp-uniq-1",
                                      policy_mode="TRACK",
                                      claimed_segment_seconds=30),
        make_rights_holder_headers("rh-uniq-2"))
    validate_error(duplicate, "ERR_DUPLICATE_REFERENCE_FINGERPRINT", expected_status=409)

    distinct = validate_success(api.create_reference_file(
        create_reference_file_payload(rights_holder_name="Uniq Rights Three",
                                      reference_fingerprint="fp-uniq-2"),
        make_rights_holder_headers("rh-uniq-3")), 201)
    assert distinct["reference_fingerprint"] == "fp-uniq-2"


# ─── Parent existence ────────────────────────────────

def test_channel_membership_requires_an_existing_parent_channel(api):
    """PRD §2.7: "an unknown channel yields `ERR_CHANNEL_NOT_FOUND`"
    PRD §2.7: "Before any business rule is evaluated, the server resolves these
    identifiers strictly left to right along the path and rejects the request at
    the first identifier that does not name an existing resource."

    Design: Corner/entities/channel_membership_requires_an_existing_parent_channel
    """
    res = api.create_membership(
        NON_EXISTENT_UUID,
        create_membership_payload(member_name="Ghost Member", monthly_fee_cents=499),
        TEST_USERS["platform_admin_headers"])
    validate_error(res, "ERR_CHANNEL_NOT_FOUND", expected_status=404)