"""Breadth coverage of computed fields, input filtering and parent links."""
import pytest

from test_helpers import (
    TEST_USERS,
    build_catalog_scenario,
    create_entry,
    create_region,
    create_subscriber,
    create_tier,
    create_title,
    publish_entry,
    scenario_with_published_entry,
    set_clock,
    sign_deal,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]
ANALYST = TEST_USERS["analyst_headers"]


def test_weighted_engagement_score_tracks_the_titles_live_entries(api):
    """PRD §3.7: "A title's `weighted_engagement_score` is recomputed on every
    publish and on every retirement, over the title's entries in status `ADDED`
    or `REMOVING` only; `PLANNED` and `DELISTED` entries contribute nothing."
    PRD §3.7: "with `ESSENTIAL` weighted 1.00, `PREMIUM` weighted 1.50 and
    `ULTIMATE` weighted 2.00".

    Design: Corner/entities/title_weighted_engagement_score_is_recomputed_on_publish_and_retire
    """
    sc = scenario_with_published_entry(
        api,
        entry_overrides={"removal_date": "2026-11-30T00:00:00Z",
                         "release_class": "CATALOG_ADD",
                         "popularity_index_cents": 6000,
                         "popularity_index_cents_30d_avg": 3000},
    )
    assert sc.title["weighted_engagement_score"] == pytest.approx(90.00, abs=0.01), \
        "6000 / 100 * 1.50, the PREMIUM tier weight"
    assert sc.title["status"] == "RELEASED"

    validate_success(api.retire_catalog_entry(sc.entry["id"], ADMIN))
    retired = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert retired["weighted_engagement_score"] == pytest.approx(0.00, abs=0.01), \
        "no ADDED entry contributes any longer"
    assert retired["status"] == "RETIRED"


def test_weighted_engagement_score_starts_at_zero_before_any_publish(api):
    """PRD §3.7: "A title that loses its last live entry has its score
    recomputed to 0.00, since it then contributes no entries at all."

    Design: Corner/entities/title_weighted_engagement_score_is_recomputed_on_publish_and_retire
    """
    sc = build_catalog_scenario(api)
    before = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert before["weighted_engagement_score"] == pytest.approx(0.00, abs=0.01)

    entry = create_entry(api, sc.title["id"], removal_date="2026-11-30T00:00:00Z",
                         release_class="CATALOG_ADD", popularity_index_cents=6000,
                         popularity_index_cents_30d_avg=3000)
    planned = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert planned["weighted_engagement_score"] == pytest.approx(0.00, abs=0.01), \
        "a PLANNED entry contributes nothing while it is still planned"

    publish_entry(api, entry["id"])
    after = validate_success(api.get_title(sc.title["id"], ADMIN))
    assert after["weighted_engagement_score"] == pytest.approx(90.00, abs=0.01)
    assert after["status"] == "RELEASED"


def test_creation_refuses_client_supplied_system_fields(api):
    """PRD §2.11: "a permitted-role request with a missing or undeclared body
    field is rejected with `ERR_INVALID_REQUEST` (400) before any identifier is
    resolved".
    PRD §3.3: "a new entry starts in `PLANNED` status."
    PRD §2.5: the system-managed fields `actual_add_date` (entry), `status` and
    `version` are never client-supplied, so naming them is an undeclared field.

    Design: Corner/entities/catalog_entry_create_extra_field_status_is_ignored_input
    """
    sc = build_catalog_scenario(api)
    validate_error(
        api.create_catalog_entry(
            {
                "title_id": sc.title["id"],
                "region_code": "NA",
                "tiers": ["PREMIUM"],
                "announced_add_date": "2026-09-02T00:00:00Z",
                "removal_date": "2026-11-30T00:00:00Z",
                "release_class": "CATALOG_ADD",
                "popularity_index_cents": 6000,
                "popularity_index_cents_30d_avg": 3000,
                "actual_add_date": "2026-09-02T00:00:00Z",
                "status": "ADDED",
                "version": 7,
            },
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
    )

    rows, meta = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"title_id": sc.title["id"]})
    )
    assert rows == []
    assert meta["total_count"] == 0, "the rejected create persisted nothing"


def test_system_field_ignoring_is_visible_through_the_listing_filter(api):
    """PRD §3.3: "The system resolves the entry's
    `deal_id` from the title's binding deal and computes `removal_notice_days` as a whole-day count between
    `announced_add_date` and `removal_date`, truncating rather than rounding".

    Design: Corner/entities/catalog_entry_create_extra_field_status_is_ignored_input
    """
    sc = build_catalog_scenario(api)
    entry = create_entry(api, sc.title["id"], removal_date="2026-11-30T00:00:00Z",
                         release_class="CATALOG_ADD", popularity_index_cents=6000,
                         popularity_index_cents_30d_avg=3000)
    planned, meta_planned = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"status": "PLANNED"})
    )
    assert len(planned) == 1 and meta_planned["total_count"] == 1

    added, meta_added = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"status": "ADDED"})
    )
    assert added == [] and meta_added["total_count"] == 0

    reread = validate_success(api.get_catalog_entry(entry["id"], ADMIN))
    assert reread["status"] == "PLANNED"
    assert reread["actual_add_date"] is None


def test_annual_subscription_carries_zero_unpaid_months(api):
    """PRD §3.5: "`unpaid_months` initialised to one for a monthly cadence and
    to zero for an annual cadence".
    PRD §3.5: "The subscription's `monthly_bill_cents` is derived at creation by
    the regional pricing rule in §3.7."

    Design: Corner/entities/subscription_create_annual_carries_zero_unpaid_months
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(api)
    create_tier(api)
    subscriber = create_subscriber(api, email="ana@example.com", display_name="Ana")

    annual = validate_success(
        api.create_subscription(
            {"subscriber_id": subscriber["id"], "tier_code": "PREMIUM",
             "billing_period": "ANNUAL", "prepay_amount_cents": 18000},
            ADMIN,
        ),
        expected_status=201,
    )
    assert annual["unpaid_months"] == 0, "an ANNUAL subscription starts settled"
    assert annual["monthly_bill_cents"] == pytest.approx(2158.80, abs=0.01), \
        "1799 * 1.20, with no blend at a multiplier of 1.20"
    assert annual["billing_period"] == "ANNUAL"
    assert annual["prepay_amount_cents"] == pytest.approx(18000, abs=0.01)


def test_an_out_of_enum_billing_period_is_a_request_format_failure(api):
    """PRD §3.5: "The create supplies the `subscriber_id`, a `tier_code` of
    `ESSENTIAL`, `PREMIUM` or `ULTIMATE`, a `billing_period` of `MONTHLY` or
    `ANNUAL`".
    PRD §2.11: "a permitted-role request with a missing or undeclared body field
    is rejected with `ERR_INVALID_REQUEST` (400)".

    Design: Corner/entities/subscription_create_annual_carries_zero_unpaid_months
    """
    set_clock(api, "2026-09-02T00:00:00Z")
    create_region(api)
    create_tier(api)
    subscriber = create_subscriber(api, email="ana@example.com", display_name="Ana")

    validate_success(
        api.create_subscription(
            {"subscriber_id": subscriber["id"], "tier_code": "PREMIUM",
             "billing_period": "ANNUAL", "prepay_amount_cents": 18000},
            ADMIN,
        ),
        expected_status=201,
    )
    validate_error(
        api.create_subscription(
            {"subscriber_id": subscriber["id"], "tier_code": "PREMIUM",
             "billing_period": "LIFETIME", "prepay_amount_cents": 18000},
            ADMIN,
        ),
        "ERR_INVALID_REQUEST",
    )
    rows, meta = validate_paginated(
        api.list_subscriptions(ADMIN, params={"subscriber_id": subscriber["id"]})
    )
    assert len(rows) == 1 and meta["total_count"] == 1


def test_a_purchase_naming_another_titles_entry_is_refused(api):
    """PRD §3.8: "The named entry must belong to the named title; an entry that
    belongs to a different title is rejected with `ERR_ENTRY_TITLE_MISMATCH`."

    Design: Corner/entities/purchase_entry_must_belong_to_the_purchased_title
    """
    sc = scenario_with_published_entry(
        api,
        entry_overrides={"removal_date": "2026-11-30T00:00:00Z",
                         "release_class": "CATALOG_ADD",
                         "popularity_index_cents": 6000,
                         "popularity_index_cents_30d_avg": 3000},
    )
    other_title = create_title(api, sc.publisher["id"], name="Second Wind",
                               platform_set=["PC"], day_one_eligible=False,
                               list_price_cents=4000, unit_sales_30d=9000)
    other_deal = validate_success(
        api.create_licensing_deal(
            {
                "publisher_id": sc.publisher["id"],
                "title_id": other_title["id"],
                "compensation_model": "HYBRID",
                "guaranteed_compensation_cents": 150000,
                "monthly_engagement_cap_cents": 300000,
                "engagement_rate_cents_per_hour": 251,
                "term_start_date": "2026-09-01T00:00:00Z",
                "term_end_date": "2027-03-01T00:00:00Z",
                "add_effective_date": "2026-09-05T00:00:00Z",
            },
            ADMIN,
        )
    , expected_status=201)
    sign_deal(api, other_deal["id"], other_title["version"])

    buyer = create_subscriber(api, email="bo@example.com", display_name="Bo")
    validate_error(
        api.create_purchase(
            {"subscriber_id": buyer["id"], "title_id": other_title["id"],
             "entry_id": sc.entry["id"], "region_code": "NA", "quantity": 1},
            {"X-User-ID": buyer["id"], "X-User-Role": "Subscriber"},
        ),
        "ERR_ENTRY_TITLE_MISMATCH",
    )
    rows, meta = validate_paginated(
        api.list_purchases(ADMIN, params={"subscriber_id": buyer["id"]})
    )
    assert rows == [] and meta["total_count"] == 0

    subscribers, sub_meta = validate_paginated(api.list_subscribers(ADMIN))
    assert len(subscribers) == 1, "the subscriber itself was never the problem"
    assert sub_meta["total_count"] == 1