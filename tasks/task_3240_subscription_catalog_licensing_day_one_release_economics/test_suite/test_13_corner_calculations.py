"""Breadth coverage of the derived-figure calculations: engagement scoring,
removal notice, pricing precision and capacity input filtering."""
import pytest

from test_helpers import (
    TEST_USERS,
    build_catalog_scenario,
    create_entry,
    create_region,
    create_tier,
    create_subscriber,
    publish_entry,
    open_subscription,
    pay_subscription,
    record_event,
    scenario_with_published_entry,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]

BACK_CATALOG_ENTRY = {
    "removal_date": "2026-12-30T00:00:00Z",
    "release_class": "BACK_CATALOG",
    "popularity_index_cents": 8000,
    "popularity_index_cents_30d_avg": 8000,
}


def test_engagement_score_is_the_mean_of_this_months_normalized_hours(api):
    """PRD §3.6: "A new event's `normalized_hours` is the product of its
    `session_hours` and its `engagement_multiplier`, rounded half up to four
    decimal places".
    PRD §3.6: "The average is the sum of the window's `normalized_hours` divided
    by the number of events in the window, held exactly and without rounding".

    Design: Corner/calculations/engagement_score_is_the_rounded_mean_of_this_months_events
    """
    set_clock(api, "2026-09-10T00:00:00Z")
    sc = build_catalog_scenario(api, advance_to="2026-09-10T00:00:00Z")
    subscriber = create_subscriber(api, email="eng@example.com", display_name="Eng")
    subscription = open_subscription(api, subscriber["id"], tier_code="PREMIUM")
    pay_subscription(api, subscription["id"], subscriber["id"])

    first = record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                         session_hours=60.0, channel="CONSOLE", engagement_multiplier=1.5)
    second = record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                          session_hours=80.0, channel="PC", engagement_multiplier=1.5)
    assert first["normalized_hours"] == pytest.approx(90.0000, abs=0.0001)
    assert second["normalized_hours"] == pytest.approx(120.0000, abs=0.0001)
    assert "updated_at" not in first, "an EngagementEvent carries no updated_at field"

    read = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert read["monthly_engaged_hours_avg"] == pytest.approx(105.00, abs=0.01), \
        "the exact unrounded mean of the two normalized values"


def test_engagement_score_is_clamped_at_the_ceiling(api):
    """PRD §3.6: "The `engagement_score` is that exact average rounded half up to
    two decimal places and then clamped at a ceiling of 100, so no subscriber's
    score can exceed one hundred index points."

    Design: Corner/calculations/engagement_score_is_the_rounded_mean_of_this_months_events
    """
    set_clock(api, "2026-09-10T00:00:00Z")
    sc = build_catalog_scenario(api, advance_to="2026-09-10T00:00:00Z")
    subscriber = create_subscriber(api, email="eng@example.com", display_name="Eng")
    subscription = open_subscription(api, subscriber["id"], tier_code="PREMIUM")
    pay_subscription(api, subscription["id"], subscriber["id"])

    record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                 session_hours=60.0, channel="CONSOLE", engagement_multiplier=1.5)
    record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                 session_hours=80.0, channel="PC", engagement_multiplier=1.5)

    read = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert read["engagement_score"] == pytest.approx(100.00, abs=0.01), \
        "the ceiling bites, so the score is not the 105.00 mean"
    assert read["monthly_engaged_hours_avg"] == pytest.approx(105.00, abs=0.01)

    events, meta = validate_paginated(
        api.list_engagement_events(ADMIN, params={"subscription_id": subscription["id"]})
    )
    assert len(events) == 2 and meta["total_count"] == 2


def test_engagement_score_window_is_the_current_calendar_month_only(api):
    """PRD §3.6: "The window is the calendar month of the logical clock: from the
    first instant of the current UTC calendar month up to, but not including,
    the first instant of the next."
    PRD §3.6: "events from earlier months leave the window but are never deleted.
    The average is the sum of the window's `normalized_hours` divided by the
    number of events in the window, held exactly and without rounding; the mean
    of an empty window is zero rather than an error."

    Design: Corner/calculations/engagement_score_excludes_events_from_earlier_months
    """
    set_clock(api, "2026-09-10T00:00:00Z")
    sc = build_catalog_scenario(api, advance_to="2026-09-10T00:00:00Z")
    subscriber = create_subscriber(api, email="win@example.com", display_name="Win")
    subscription = open_subscription(api, subscriber["id"], tier_code="PREMIUM")
    pay_subscription(api, subscription["id"], subscriber["id"])
    record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                 session_hours=200.0, channel="PC", engagement_multiplier=1.0)

    in_september = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert in_september["monthly_engaged_hours_avg"] == pytest.approx(200.00, abs=0.01)
    assert in_september["engagement_score"] == pytest.approx(100.00, abs=0.01), \
        "the exact 200.00 is clamped at the ceiling"

    set_clock(api, "2026-10-05T00:00:00Z")
    in_october = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert in_october["monthly_engaged_hours_avg"] == pytest.approx(0.00, abs=0.01), \
        "the September event left the window"
    assert in_october["engagement_score"] == pytest.approx(0.00, abs=0.01), \
        "the mean of an empty window is zero rather than an error"

    record_event(api, subscription["id"], subscriber["id"], sc.title["id"],
                 session_hours=20.0, channel="PC", engagement_multiplier=1.0)
    after_july_event = validate_success(api.get_subscription(subscription["id"], ADMIN))
    assert after_july_event["engagement_score"] == pytest.approx(20.00, abs=0.01), \
        "the July-only mean"

    events, meta = validate_paginated(
        api.list_engagement_events(ADMIN, params={"subscription_id": subscription["id"]})
    )
    assert len(events) == 2 and meta["total_count"] == 2, \
        "the earlier event was filtered out of the aggregate, not deleted"


def test_the_day_one_notice_minimum_is_inclusive_at_the_boundary(api):
    """PRD §3.4: "The minimum is fourteen days for `DAY_ONE`, seven days for
    `CATALOG_ADD` and zero for `BACK_CATALOG`, and the comparison is inclusive at
    the boundary, so a notice count exactly equal to the minimum is accepted."
    PRD §3.4: "Announcing is done by a `CatalogAdmin` and moves the entry from
    `ADDED` to `REMOVING`; it requires ... that the computed
    `removal_notice_days` meet the minimum for the entry's release class."

    The notice minimum is a rule about *announcing* (§3.4), so the boundary is
    read at the announce transition rather than at the plan.

    Design: Corner/calculations/catalog_removal_notice_minimum_is_inclusive_at_the_day_one_boundary
    """
    sc = build_catalog_scenario(api)
    at_boundary = create_entry(api, sc.title["id"], removal_date="2026-09-16T00:00:00Z",
                               release_class="DAY_ONE", popularity_index_cents=6000,
                               popularity_index_cents_30d_avg=3000)
    assert at_boundary["removal_notice_days"] == 14, \
        "a notice count exactly equal to the minimum is accepted"
    publish_entry(api, at_boundary["id"])
    announced = validate_success(api.announce_entry_removal(at_boundary["id"], ADMIN))
    assert announced["status"] == "REMOVING", \
        "a notice count exactly equal to the minimum clears the inclusive boundary"

    one_day_short = create_entry(api, sc.title["id"], removal_date="2026-09-15T00:00:00Z",
                                 release_class="DAY_ONE", popularity_index_cents=6000,
                                 popularity_index_cents_30d_avg=3000)
    assert one_day_short["removal_notice_days"] == 13
    publish_entry(api, one_day_short["id"])
    validate_error(api.announce_entry_removal(one_day_short["id"], ADMIN),
                   "ERR_INSUFFICIENT_REMOVAL_NOTICE")

    rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"title_id": sc.title["id"]})
    )
    assert len(rows) == 2 and meta["total_count"] == 2, \
        "the refused announce left both planned rows in place"


def test_a_thirteen_day_window_is_fine_for_a_later_addition(api):
    """PRD §3.4: "The notice count is the whole number of days between
    `announced_add_date` and `removal_date`, computed as the difference in
    seconds divided by 86,400 and truncated toward zero — which means a 13.99-day
    notice fails the `DAY_ONE` minimum rather than rounding up to fourteen."

    Design: Corner/calculations/catalog_removal_notice_minimum_is_inclusive_at_the_day_one_boundary
    """
    sc = build_catalog_scenario(api)
    entry = create_entry(api, sc.title["id"], removal_date="2026-09-15T00:00:00Z",
                         release_class="CATALOG_ADD", popularity_index_cents=6000,
                         popularity_index_cents_30d_avg=3000)
    assert entry["removal_notice_days"] == 13, \
        "the same thirteen-day window clears the CATALOG_ADD minimum of seven"
    assert entry["status"] == "PLANNED"


def test_regional_price_precision_does_not_drift_on_read(api):
    """PRD §3.7: "the regional monthly price is the tier's global default
    multiplied by that final multiplier, rounded half up to two decimal places."
    PRD §3.7: "the tier's `monthly_price_cents` is read but never mutated by
    this calculation — the global default remains the global default".

    Design: Corner/calculations/regional_price_precision_never_drifts_on_read
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(api, region_code="EU", currency_code="EUR", price_multiplier=1.015)
    create_tier(api)
    first = create_subscriber(api, email="p1@example.com", display_name="P1",
                              home_region_code="EU")
    second = create_subscriber(api, email="p2@example.com", display_name="P2",
                               home_region_code="EU")

    first_sub = validate_success(
        api.create_subscription({"subscriber_id": first["id"], "tier_code": "PREMIUM",
                                 "billing_period": "MONTHLY"}, ADMIN),
        expected_status=201,
    )
    assert first_sub["monthly_bill_cents"] == pytest.approx(1826.00, abs=0.01), \
        "1799 * 1.015 rounded half up to the cent"

    reread = validate_success(api.get_subscription(first_sub["id"], ADMIN))
    assert reread["monthly_bill_cents"] == first_sub["monthly_bill_cents"]

    second_sub = validate_success(
        api.create_subscription({"subscriber_id": second["id"], "tier_code": "PREMIUM",
                                 "billing_period": "MONTHLY"}, ADMIN),
        expected_status=201,
    )
    assert second_sub["monthly_bill_cents"] == first_sub["monthly_bill_cents"], \
        "no accumulated rounding drift appears on a later subscription"

    region = validate_success(api.get_region("EU", ADMIN))
    assert region["price_multiplier"] == pytest.approx(1.015, abs=0.0001), \
        "the calculation never writes back to the region"
    tier = validate_success(api.get_tier("PREMIUM", ADMIN))
    assert tier["monthly_price_cents"] == pytest.approx(1799, abs=0.01)


def test_capacity_drops_when_an_entry_leaves_the_active_interval(api):
    """PRD §3.7: "The active entry set for a region is the entries whose
    `region_code` matches and for which the logical clock is at or after
    `actual_add_date` and strictly before `removal_date` — the same half-open
    predicate used throughout §3.4."

    Design: Corner/calculations/cloud_capacity_drops_when_an_entry_leaves_the_active_interval
    """
    sc = build_catalog_scenario(api)
    create_region(api, region_code="JP", currency_code="JPY", price_multiplier=1.10,
                  availability_ceiling_titles=400, catalog_tier_floor="ESSENTIAL")
    entry_a = create_entry(api, sc.title["id"], region_code="JP",
                           removal_date="2026-11-30T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=6000,
                           popularity_index_cents_30d_avg=3000)
    entry_b = create_entry(api, sc.title["id"], region_code="JP",
                           removal_date="2026-11-10T00:00:00Z", release_class="BACK_CATALOG",
                           popularity_index_cents=8000,
                           popularity_index_cents_30d_avg=8000)
    publish_entry(api, entry_a["id"])
    publish_entry(api, entry_b["id"])

    both = validate_success(api.get_region("JP", ADMIN))
    # Base slots: (6000 + 8000) * 0.5 == 7000. Launch spikes, both entries are
    # inside their fourteen-day window: (6000 + 8000) * 0.5 * 0.40 == 2800.
    # Region overhead: 200.
    assert both["capacity_required_slots"] == pytest.approx(10000.00, abs=0.01)
    assert both["capacity_status"] == "WITHIN_CAPACITY"

    set_clock(api, "2026-11-20T00:00:00Z")
    one = validate_success(api.get_region("JP", ADMIN))
    assert one["capacity_required_slots"] == pytest.approx(3200.00, abs=0.01), \
        "entry_b's interval closed and both launch windows expired"
    assert one["capacity_status"] == "WITHIN_CAPACITY"
    assert one["capacity_deficit_slots"] == pytest.approx(-8800.00, abs=0.01)

    reread = validate_success(api.get_catalog_entry(entry_b["id"], ADMIN))
    assert reread["status"] == "ADDED", \
        "the entry whose interval closed still exists"