"""Depth-3 cascades.

Retiring an entry fans out across the title's North American entries and then
sweeps the entitlements naming each delisted entry; cancelling a subscription
revokes its entitlements directly and recomputes the counts that name them.
"""
import pytest

from test_helpers import (
    BACK_CATALOG_ENTRY_B,
    CATALOG_ADD_ENTRY_A,
    TEST_USERS,
    list_entitlements,
    make_subscriber_headers,
    scenario_with_two_subscribers_and_two_entries,
    set_clock,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_retiring_one_entry_delists_the_titles_other_north_american_entries(api):
    """PRD §3.4: "**Hop two** is the delisting fan-out. Every other
    `CatalogEntry` belonging to the same `Title` in region `NA` that is
    currently in status `ADDED` or `REMOVING` is also moved to `DELISTED`."
    PRD §3.4: "the title moves to `RETIRED` only when it holds no entry at all,
    in any region, in status `ADDED` or `REMOVING`."

    Design: Difficulty/transitive_cascade/entry_retire_cascades_through_title_entries_to_entitlements
    """
    sc = scenario_with_two_subscribers_and_two_entries(api)

    validate_success(api.retire_catalog_entry(sc.entry_a["id"], ADMIN))

    hop_one = validate_success(api.get_catalog_entry(sc.entry_a["id"], ADMIN))
    assert hop_one["status"] == "DELISTED"

    hop_two = validate_success(api.get_catalog_entry(sc.entry_b["id"], ADMIN))
    assert hop_two["status"] == "DELISTED", \
        "nothing was called on entry_b, yet the fan-out delisted it"

    title = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert title["status"] == "RETIRED", \
        "the title now holds no entry in status ADDED or REMOVING"
    assert title["weighted_engagement_score"] == pytest.approx(0.00, abs=0.01), \
        "no ADDED entry contributes to the score any longer"


def test_retire_cascade_revokes_entitlements_unless_the_retention_clause_holds(api):
    """PRD §3.4: "For each such entry, every `Entitlement` whose `entry_id`
    points at it and whose `status` is `ACTIVE` or `GRACE` is revoked — with
    one retention clause that is evaluated before any revocation."
    PRD §3.4: "A `BACK_CATALOG` entry always retains. If the delisted entry's
    `release_class` is `BACK_CATALOG`, the entitlement is never revoked, no
    matter how much time has passed."
    PRD §3.4: "The entitlement survives if the logical clock is at or before
    the instant formed by adding the owning tier's `discount_retention_days` to
    the entry's `removal_date` and then subtracting one second. ... Once the
    clock passes that instant, the delayed revocation fires and the row becomes
    `REVOKED`."

    PRD §2.8 fixes the entitlement at one row per (subscription, title, region)
    triple, so the single subscription below resolves exactly one row, naming
    the entry the selector policy prefers.

    Design: Difficulty/transitive_cascade/entry_retire_cascades_through_title_entries_to_entitlements
    """
    # --- the revocation arm: a CATALOG_ADD entitlement past its retention ----
    sc = scenario_with_two_subscribers_and_two_entries(api, advance_to=None)
    set_clock(api, "2027-01-15T00:00:00Z")

    rows = list_entitlements(api, subscription_id=sc.subscription_a["id"])
    assert len(rows) == 1, "one row per (subscription, title, region) triple"
    assert rows[0]["entry_id"] == sc.entry_a["id"], \
        "entry_a was published first, so the selector policy prefers it"

    validate_success(api.retire_catalog_entry(sc.entry_a["id"], ADMIN))

    swept = list_entitlements(api, subscription_id=sc.subscription_a["id"])
    assert len(swept) == 1
    assert swept[0]["status"] == "REVOKED", \
        "entry_a is CATALOG_ADD and the clock is past removal_date plus the " \
        "tier's 30 retention days, so the delayed revocation fires"

    entry_a = validate_success(api.get_catalog_entry(sc.entry_a["id"], ADMIN))
    assert entry_a["subscriber_impact_count"] == 0, \
        "no entitlement resolves to the delisted CATALOG_ADD entry any more"


def test_back_catalog_entitlement_survives_the_retire_sweep(api):
    """PRD §3.4: "A `BACK_CATALOG` entry always retains. If the delisted
    entry's `release_class` is `BACK_CATALOG`, the entitlement is never revoked,
    no matter how much time has passed."

    Design: Difficulty/transitive_cascade/entry_retire_cascades_through_title_entries_to_entitlements
    """
    # Publish the BACK_CATALOG entry first so the selector policy prefers it and
    # the (subscription, title, region) triple's single row names it.
    sc = scenario_with_two_subscribers_and_two_entries(
        api,
        entry_a_overrides=dict(BACK_CATALOG_ENTRY_B),
        entry_b_overrides=dict(CATALOG_ADD_ENTRY_A),
        advance_to=None,
    )
    set_clock(api, "2027-01-15T00:00:00Z")

    rows = list_entitlements(api, subscription_id=sc.subscription_a["id"])
    assert len(rows) == 1
    assert rows[0]["entry_id"] == sc.entry_a["id"]

    validate_success(api.retire_catalog_entry(sc.entry_a["id"], ADMIN))

    swept = list_entitlements(api, subscription_id=sc.subscription_a["id"])
    assert len(swept) == 1
    assert swept[0]["status"] != "REVOKED", \
        "entry_a is BACK_CATALOG, so the retention clause never revokes the " \
        "row however much time has passed"

    entry_a = validate_success(api.get_catalog_entry(sc.entry_a["id"], ADMIN))
    assert entry_a["subscriber_impact_count"] == 2, \
        "the retained BACK_CATALOG entitlements of both subscribers still count"


def test_cancelling_a_subscription_revokes_every_entitlement_it_holds(api):
    """PRD §3.5: "Cancellation carries no retention clause and makes no time
    comparison: every entitlement of that subscription becomes `REVOKED`
    immediately, all channels close including any retained purchase access for
    catalogue titles"."

    Design: Difficulty/transitive_cascade/subscription_cancel_cascades_to_entitlements_and_impact_counts
    """
    sc = scenario_with_two_subscribers_and_two_entries(api)

    cancelled = validate_success(
        api.cancel_subscription(sc.subscription_a["id"],
                                make_subscriber_headers(sc.subscriber_a["id"]))
    )
    assert cancelled["lifecycle_status"] == "CANCELLED"

    ana_rows = list_entitlements(api, subscription_id=sc.subscription_a["id"])
    assert len(ana_rows) == 1, "no entitlement row was deleted"
    assert ana_rows[0]["status"] == "REVOKED", \
        "the row is revoked even though it names a BACK_CATALOG entry, which " \
        "retention would otherwise spare"

    bo_rows = list_entitlements(api, subscription_id=sc.subscription_b["id"])
    assert len(bo_rows) == 1
    assert bo_rows[0]["status"] == "ACTIVE"


def test_cancel_cascade_recomputes_impact_counts_and_the_tier_population(api):
    """PRD §3.5: "the `subscriber_impact_count` of every entry those
    entitlements named is recomputed, and the tier's `current_subscriber_count` is refreshed."
    PRD §3.8: "it counts the tier's `Subscription` rows whose lifecycle
    dimension is `ACTIVE` or `GRACE`".

    Design: Difficulty/transitive_cascade/subscription_cancel_cascades_to_entitlements_and_impact_counts
    """
    sc = scenario_with_two_subscribers_and_two_entries(api)

    tier_before = validate_success(api.get_tier("PREMIUM", ADMIN))
    assert tier_before["current_subscriber_count"] == 2

    validate_success(
        api.cancel_subscription(sc.subscription_a["id"],
                                make_subscriber_headers(sc.subscriber_a["id"]))
    )

    # Both subscribers' rows name the same winning entry (the selector policy's
    # first ADDED candidate), so the cancel drops that entry's impact count by
    # one and leaves the other entry untouched.
    named = sc.entry_a["id"]
    entry_a = validate_success(api.get_catalog_entry(named, ADMIN))
    assert entry_a["subscriber_impact_count"] == 1, \
        "the cancelled subscription left the entry its one row named"

    tier_after = validate_success(api.get_tier("PREMIUM", ADMIN))
    assert tier_after["current_subscriber_count"] == 1, \
        "the cancelled subscription left the tier's live population"