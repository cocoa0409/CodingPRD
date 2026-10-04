"""A child resource's fate is decided by its parent's state.

A catalogue entry cannot be planned against a title whose deal is still a
draft, and the same publish call resolves two different entitlement states
because the two owning subscriptions sit on different billing dimensions.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    build_catalog_scenario,
    create_entry,
    create_subscriber,
    open_subscription,
    pay_subscription,
    make_subscriber_headers,
    list_entitlements,
    publish_entry,
    set_clock,
    sign_deal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

ENTRY_BODY = {
    "region_code": "NA",
    "tiers": ["PREMIUM"],
    "announced_add_date": "2026-09-02T00:00:00Z",
    "removal_date": "2027-02-27T00:00:00Z",
    "release_class": "CATALOG_ADD",
    "popularity_index_cents": 6000,
    "popularity_index_cents_30d_avg": 3000,
}


def test_entry_creation_is_refused_while_the_deal_is_still_a_draft(api):
    """PRD §3.3: "A title with no licensing deal in `LIVE` status for the region
    named cannot be published or projected at all, and the attempt is rejected
    with `ERR_NO_BINDING_DEAL`."
    PRD §3.2: "Once the logical clock reaches the term's start instant the deal
    advances from `SIGNED` to `LIVE`, and from that point catalogue entries may
    be created and published against it."

    Design: Difficulty/cross_entity_state_dependency/entry_readiness_depends_on_the_licensing_deal_state
    """
    sc = build_catalog_scenario(api, sign=False, advance_to=None)
    current = validate_success(api.get_licensing_deal(sc.deal["id"], ADMIN))
    assert current["status"] == "DRAFT"

    # Planning is not the gate the PRD names — publication is. A plan filed
    # against a draft deal resolves no deal_id, and the publish is refused.
    body = dict(ENTRY_BODY)
    body["title_id"] = sc.title["id"]
    entry = validate_success(api.create_catalog_entry(body, ADMIN), expected_status=201)
    assert entry["status"] == "PLANNED"

    validate_error(api.publish_catalog_entry(entry["id"], ADMIN), "ERR_NO_BINDING_DEAL")

    after = validate_success(api.get_catalog_entry(entry["id"], ADMIN))
    assert after["status"] == "PLANNED", "the refused publish persisted nothing"


def test_the_identical_body_is_accepted_once_the_deal_is_signed_and_live(api):
    """PRD §3.2: "Once the logical clock reaches the term's start instant the
    deal advances from `SIGNED` to `LIVE`, and from that point catalogue entries
    may be created and published against it."

    Design: Difficulty/cross_entity_state_dependency/entry_readiness_depends_on_the_licensing_deal_state
    """
    sc = build_catalog_scenario(api, sign=False, advance_to=None)
    body = dict(ENTRY_BODY)
    body["title_id"] = sc.title["id"]
    entry = validate_success(api.create_catalog_entry(body, ADMIN), expected_status=201)
    validate_error(api.publish_catalog_entry(entry["id"], ADMIN), "ERR_NO_BINDING_DEAL")

    signed = sign_deal(api, sc.deal["id"], sc.title["version"])
    assert signed["status"] == "SIGNED"
    set_clock(api, "2026-09-02T00:00:00Z")

    published = validate_success(api.publish_catalog_entry(entry["id"], ADMIN))
    assert published["status"] == "ADDED"
    assert published["deal_id"] == sc.deal["id"], \
        "the system resolves the entry's deal_id from the title's binding deal"

    rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"title_id": sc.title["id"]})
    )
    assert len(rows) == 1, "the rejected publish persisted nothing"
    assert meta["total_count"] == 1


def test_publishing_resolves_grace_for_a_failed_subscription_and_active_for_a_paid_one(api):
    """PRD §3.3: "Each such subscription receives an entitlement for the
    (subscription, title, region) triple, set to `ACTIVE`; a subscription whose
    tier grant is suspended because its billing has failed resolves to `GRACE`
    instead."

    Design: Difficulty/cross_entity_state_dependency/entitlement_access_narrowing_tracks_the_subscription_lifecycle_dimension
    """
    sc = build_catalog_scenario(api)

    # The failing subscription carries one outstanding month and is never paid.
    failing = create_subscriber(api, email="grace@example.com", display_name="Grace")
    failing_sub = open_subscription(api, failing["id"], tier_code="PREMIUM")

    # PRD §3.5: "Failure arrives from the clock, not from a request. When the
    # logical clock advances to a monthly renewal instant and the renewal charge
    # fails, a `PAID` monthly subscription moves to `FAILED`." Every monthly
    # subscription therefore fails at its own renewal instant, so the paid
    # subscriber is opened after the clock has passed the failing one's.
    set_clock(api, "2026-10-02T00:00:00Z")
    failing_now = validate_success(api.get_subscription(failing_sub["id"], ADMIN))
    assert failing_now["billing_status"] == "FAILED"
    assert failing_now["lifecycle_status"] == "GRACE"

    paid = create_subscriber(api, email="paid@example.com", display_name="Paid")
    paid_sub = open_subscription(api, paid["id"], tier_code="PREMIUM")
    pay_subscription(api, paid_sub["id"], paid["id"])
    assert validate_success(api.get_subscription(paid_sub["id"], ADMIN))[
        "lifecycle_status"] == "ACTIVE"

    entry = create_entry(api, sc.title["id"], announced_add_date="2026-10-02T00:00:00Z",
                         removal_date="2027-02-27T00:00:00Z", release_class="CATALOG_ADD",
                         popularity_index_cents=6000, popularity_index_cents_30d_avg=3000)
    publish_entry(api, entry["id"])

    grace_rows = list_entitlements(api, subscription_id=failing_sub["id"])
    paid_rows = list_entitlements(api, subscription_id=paid_sub["id"])
    assert len(grace_rows) == 1 and len(paid_rows) == 1
    assert grace_rows[0]["status"] == "GRACE", \
        "the same publish produced two different entitlement states"
    assert paid_rows[0]["status"] == "ACTIVE"

    all_rows = list_entitlements(api, entry_id=entry["id"])
    assert len(all_rows) == 2, "both entitlements name the same entry"
    assert {"CONSOLE", "PC", "CLOUD"} <= set(grace_rows[0]["access_channels"]), \
        "the channel set is derived from the tier flags; GRACE suspends rather than rewrites it"

    recovered = validate_success(
        api.pay_subscription(failing_sub["id"], make_subscriber_headers(failing["id"]))
    )
    assert recovered["lifecycle_status"] == "ACTIVE"
    after_pay = list_entitlements(api, subscription_id=failing_sub["id"])
    assert after_pay[0]["status"] == "ACTIVE"