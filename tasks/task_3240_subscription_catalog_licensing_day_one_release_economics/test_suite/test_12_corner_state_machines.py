"""Breadth coverage of the state machines: idempotency, terminal lockdown, the
clock-driven maintenance progression and refused transitions."""
import pytest

from test_helpers import (
    TEST_USERS,
    create_region,
    create_subscriber,
    create_tier,
    list_entitlements,
    list_maintenances,
    make_subscriber_headers,
    open_subscription,
    pay_subscription,
    scenario_with_subscriber,
    scenario_with_published_entry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_repeating_a_publish_is_refused_and_mints_no_second_entitlement(api):
    """PRD §3.3: "attempting to publish an entry that is already `ADDED`,
    `REMOVING` or `DELISTED` is rejected with `ERR_ENTRY_NOT_PUBLISHABLE`."
    PRD §3.3: "at most one entitlement row may exist for a given
    (subscription, title, region) triple."

    Design: Corner/state_machines/entry_publish_repeat_is_refused_and_entitlement_rows_do_not_multiply
    """
    sc = scenario_with_subscriber(api)
    before = list_entitlements(api, subscription_id=sc.subscription["id"])
    assert len(before) == 1
    entry_id, channels = before[0]["id"], before[0]["access_channels"]

    validate_error(api.publish_catalog_entry(sc.entry["id"], ADMIN),
                   "ERR_ENTRY_NOT_PUBLISHABLE")

    after = list_entitlements(api, subscription_id=sc.subscription["id"])
    assert len(after) == 1, "the refused publish minted no duplicate entitlement"
    assert after[0]["id"] == entry_id
    assert after[0]["access_channels"] == channels
    assert set(channels) == {"CONSOLE", "PC", "CLOUD", "ONLINE_PLAY"}, \
        "the channel set derives from the PREMIUM tier flags"


def test_a_refused_publish_leaves_the_entry_untouched(api):
    """PRD §2.5: "`version` (integer): a counter starting at 1 and incremented by
    exactly one on every mutation of the resource".

    Design: Corner/state_machines/entry_publish_repeat_is_refused_and_entitlement_rows_do_not_multiply
    """
    sc = scenario_with_published_entry(api)
    published = validate_success(api.get_catalog_entry(sc.entry["id"], ADMIN))
    assert published["status"] == "ADDED"
    assert published["actual_add_date"] is not None

    validate_error(api.publish_catalog_entry(sc.entry["id"], ADMIN), "ERR_ENTRY_NOT_PUBLISHABLE")

    reread = validate_success(api.get_catalog_entry(sc.entry["id"], ADMIN))
    assert reread["status"] == "ADDED"
    assert reread["actual_add_date"] == published["actual_add_date"], \
        "the refused publish rewrote nothing"
    assert reread["version"] == published["version"]


def test_a_cancelled_subscription_refuses_pay_and_engagement(api):
    """PRD §3.5: "`CANCELLED` is terminal — a subscription that has been
    cancelled accepts no further transitions, and any attempt to pay it, cancel
    it again, or record engagement against it is rejected with
    `ERR_SUBSCRIPTION_TERMINAL`."

    Design: Corner/state_machines/canceled_subscription_is_locked_down_against_pay_and_engagement
    """
    sc = scenario_with_published_entry(api)
    subscriber = create_subscriber(api, email="cora@example.com", display_name="Cora")
    subscription = open_subscription(api, subscriber["id"], tier_code="PREMIUM")
    pay_subscription(api, subscription["id"], subscriber["id"])
    validate_success(
        api.cancel_subscription(subscription["id"], make_subscriber_headers(subscriber["id"]))
    )

    headers = make_subscriber_headers(subscriber["id"])
    validate_error(api.pay_subscription(subscription["id"], headers),
                   "ERR_SUBSCRIPTION_TERMINAL")
    validate_error(
        api.record_engagement_event(
            subscription["id"],
            {"title_id": sc.title["id"], "session_hours": 2.0, "channel": "PC",
             "engagement_multiplier": 1.0},
            headers,
        ),
        "ERR_SUBSCRIPTION_TERMINAL",
    )

    reread = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert reread["lifecycle_status"] == "CANCELLED"
    assert reread["cancellation_reason"] == "USER_INITIATED"

    events, meta = validate_paginated(
        api.list_engagement_events(ADMIN, params={"subscription_id": subscription["id"]})
    )
    assert events == [] and meta["total_count"] == 0

    subscriptions, sub_meta = validate_paginated(
        api.list_subscriptions(ADMIN, params={"subscriber_id": subscriber["id"]})
    )
    assert len(subscriptions) == 1 and sub_meta["total_count"] == 1, \
        "no Subscription row was deleted"


def test_maintenance_advances_with_the_clock_and_moves_the_capacity_figure(api):
    """PRD §2.12: "The transitions it drives are the licensing deal's
    `SIGNED → LIVE` activation, its `LIVE → EXPIRING` removal announcement and its `EXPIRING → COMPLETED`
    termination, the catalogue maintenance window's `SCHEDULED → ACTIVE → COMPLETED` progression".
    PRD §2.7: "While such a window is `ACTIVE` the region's usable slots are
    reduced by that fraction."

    Design: Corner/state_machines/catalog_maintenance_advances_scheduled_active_completed_with_the_clock
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(
        api,
        region_code="NA", currency_code="USD", price_multiplier=1.20,
        availability_ceiling_titles=4000,
        maintenance_windows=[
            {"maintenance_start": "2026-10-01T00:00:00Z",
             "maintenance_end": "2026-10-05T00:00:00Z",
             "capacity_reduction_pct": 0.25},
        ],
    )

    before = list_maintenances(api, region_code="NA", limit=10, offset=0)
    assert len(before) == 1
    assert before[0]["status"] == "SCHEDULED"

    set_clock(api, "2026-10-02T00:00:00Z")
    during = list_maintenances(api, region_code="NA", limit=10, offset=0)
    assert during[0]["status"] == "ACTIVE"

    reduced = validate_success(api.get_region("NA", ADMIN))
    assert reduced["capacity_usable_slots"] == pytest.approx(90000.00, abs=0.01), \
        "the 120000.00 base reduced by the window's 25 percent"

    set_clock(api, "2026-10-05T00:00:00Z")
    after = list_maintenances(api, region_code="NA", limit=10, offset=0)
    assert after[0]["status"] == "COMPLETED", \
        "the window's end is exclusive and the clock now equals it"

    restored = validate_success(api.get_region("NA", ADMIN))
    assert restored["capacity_usable_slots"] == pytest.approx(120000.00, abs=0.01)


def test_announcing_a_removal_twice_is_refused(api):
    """PRD §3.4: "already `REMOVING` is rejected with `ERR_REMOVAL_ALREADY_ANNOUNCED`. The transition publishes the
    removal notice to subscribers"."

    Design: Corner/state_machines/announce_removal_twice_is_refused
    """
    sc = scenario_with_subscriber(api)

    first = validate_success(api.announce_entry_removal(sc.entry["id"], ADMIN))
    assert first["status"] == "REMOVING"
    impact_first = first["subscriber_impact_count"]
    assert impact_first == 1, "the one paid subscription resolves to this entry"

    validate_error(api.announce_entry_removal(sc.entry["id"], ADMIN),
                   "ERR_REMOVAL_ALREADY_ANNOUNCED")

    after = validate_success(api.get_catalog_entry(sc.entry["id"], ADMIN))
    assert after["status"] == "REMOVING", "the first announcement's state stands"
    assert after["subscriber_impact_count"] == impact_first, \
        "the refused call changed no derived field"