"""Cascade tests: channel suspension chain, publisher termination chain, and
asymmetric reinstatement."""
from test_helpers import (
    api_client,
    validate_success,
    validate_error,
    get_success_data,
    ApiErrorId,
    create_publisher,
    create_published_channel,
    create_active_campaign,
    create_placement_booking,
    create_viewer,
    create_subscription,
    make_publisher_headers,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
ADOPS = TEST_USERS["adops_headers"]


def _suspend_setup():
    """Two publishers each with a PUBLISHED channel and an ACTIVE campaign;
    publisher 1 additionally has a CONFIRMED booking on HOME_ROW_1."""
    p1 = create_publisher(legal_name="P1")
    p2 = create_publisher(legal_name="P2")
    c1 = create_published_channel(p1)
    c2 = create_published_channel(p2)
    k1 = create_active_campaign(p1, c1["id"])
    k2 = create_active_campaign(p2, c2["id"])
    b1 = create_placement_booking(
        k1["id"], p1["id"], slot_code="HOME_ROW_1",
        window_start="2026-09-10T09:00:00Z",
        window_end="2026-09-10T12:00:00Z",
    )
    get_success_data(api_client.confirm_placement_booking(b1["id"], ADOPS))
    return p1, p2, c1, c2, k1, k2, b1


def test_channel_suspension_cascade_chain():
    """PRD §3.3: "Suspension by a `PlatformAdmin` moves a `PUBLISHED` channel
    to `SUSPENDED` and fires the cascade of §2.9: every campaign of this
    channel in `ACTIVE` or `PAUSED` becomes `PAUSED`, and each campaign so
    paused releases its own `HELD` and `CONFIRMED` placement bookings to
    `RELEASED`."

    Design: Difficulty/transitive_cascade/channel_suspension_pauses_campaign_releases_booking_frees_slot
    """
    p1, p2, c1, c2, k1, k2, b1 = _suspend_setup()

    get_success_data(
        api_client.suspend_channel(c1["id"], {"reason": "OPS"}, ADMIN)
    )

    assert get_success_data(api_client.get_channel(c1["id"], ADMIN))[
        "status"] == "SUSPENDED"
    assert get_success_data(api_client.get_campaign(k1["id"], ADMIN))[
        "status"] == "PAUSED"
    assert get_success_data(api_client.get_placement_booking(b1["id"], ADMIN))[
        "status"] == "RELEASED"
    # Unrelated subtree untouched.
    assert get_success_data(api_client.get_campaign(k2["id"], ADMIN))[
        "status"] == "ACTIVE"


def test_channel_suspension_frees_slot_window_for_rebooking():
    """PRD §3.5: "`RELEASED` and `EXPIRED` bookings never block anything."

    Design: Difficulty/transitive_cascade/channel_suspension_pauses_campaign_releases_booking_frees_slot
    """
    p1, p2, c1, c2, k1, k2, b1 = _suspend_setup()
    get_success_data(
        api_client.suspend_channel(c1["id"], {"reason": "OPS"}, ADMIN)
    )

    resp = api_client.create_placement_booking(
        {
            "campaign_id": k2["id"],
            "slot_code": "HOME_ROW_1",
            "window_start": "2026-09-10T09:00:00Z",
            "window_end": "2026-09-10T12:00:00Z",
        },
        make_publisher_headers(p2["id"]),
    )
    probe = validate_success(resp, expected_status=201)
    assert probe["status"] == "HELD", (
        "the released booking's window must be free for an identical rebooking"
    )


def test_publisher_termination_cascade_removes_channel_and_cancels_subscription():
    """PRD §3.1: "termination to `TERMINATED` is final and fires the cascade
    described in §2.9 — every channel of the publisher not already `REMOVED`
    is removed (each recording its own removal rationale and firing its own
    removal side effects), each channel's `ACTIVE` subscriptions are cancelled
    with entitlements revoked, and no refunds are issued automatically."

    Design: Difficulty/transitive_cascade/publisher_termination_removes_channels_cancels_subscriptions
    """
    publisher = create_publisher(legal_name="Term Pub")
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="tv@x.com")
    subscription = create_subscription(channel["id"], viewer["id"],
                                       price_cents=2500)

    get_success_data(api_client.set_publisher_standing(
        publisher["id"],
        {"to_standing": "TERMINATED", "reason": "contract breach"},
        ADMIN,
    ))

    assert get_success_data(api_client.get_publisher(publisher["id"], ADMIN))[
        "standing"] == "TERMINATED"
    assert get_success_data(api_client.get_channel(channel["id"], ADMIN))[
        "status"] == "REMOVED"
    sub = get_success_data(
        api_client.get_subscription(subscription["id"], ADMIN)
    )
    assert sub["billing_status"] == "CANCELLED"
    assert sub["entitlement_status"] == "REVOKED"


def test_publisher_termination_issues_no_refunds():
    """PRD §3.1: "termination to `TERMINATED` is final and fires the cascade
    described in §2.9 — every channel of the publisher not already `REMOVED`
    is removed (each recording its own removal rationale and firing its own
    removal side effects), each channel's `ACTIVE` subscriptions are cancelled
    with entitlements revoked, and no refunds are issued automatically."

    Design: Difficulty/transitive_cascade/publisher_termination_removes_channels_cancels_subscriptions
    """
    publisher = create_publisher(legal_name="Term Pub 2")
    channel = create_published_channel(publisher)
    viewer = create_viewer(email="tv2@x.com")
    subscription = create_subscription(channel["id"], viewer["id"],
                                       price_cents=2500)

    get_success_data(api_client.set_publisher_standing(
        publisher["id"],
        {"to_standing": "TERMINATED", "reason": "contract breach"},
        ADMIN,
    ))

    sub = get_success_data(
        api_client.get_subscription(subscription["id"], ADMIN)
    )
    assert sub["billing_status"] == "CANCELLED", (
        "termination cancels, not refunds, active subscriptions"
    )
    assert sub.get("refunded_at") is None, (
        "no refund timestamp may be stamped by the termination cascade"
    )


def test_suspend_then_reinstate_does_not_restore_campaign_or_booking():
    """PRD §3.3: "Reinstatement moves a `SUSPENDED` channel back to
    `PUBLISHED`, requires the publisher to be in `GOOD` or `PROBATION`, clears
    `policy_hold` to false — and deliberately does nothing else: campaigns
    stay paused, bookings stay released."

    Design: Corner/cross_cutting_complexity_layers/cascading_side_effects_suspend_then_reinstate_does_not_restore
    """
    publisher = create_publisher(legal_name="Asym Pub")
    channel = create_published_channel(publisher)
    campaign = create_active_campaign(publisher, channel["id"],
                                      budget_cents=50000)
    booking = create_placement_booking(
        campaign["id"], publisher["id"], slot_code="HOME_ROW_5",
        window_start="2026-09-15T09:00:00Z",
        window_end="2026-09-15T12:00:00Z",
    )
    get_success_data(api_client.confirm_placement_booking(booking["id"], ADOPS))
    get_success_data(
        api_client.suspend_channel(channel["id"], {"reason": "OPS"}, ADMIN)
    )

    reinstated = get_success_data(
        api_client.reinstate_channel(channel["id"], ADMIN)
    )
    assert reinstated["status"] == "PUBLISHED"
    assert reinstated["policy_hold"] is False
    assert get_success_data(api_client.get_campaign(campaign["id"], ADMIN))[
        "status"] == "PAUSED"
    assert get_success_data(
        api_client.get_placement_booking(booking["id"], ADMIN)
    )["status"] == "RELEASED"
