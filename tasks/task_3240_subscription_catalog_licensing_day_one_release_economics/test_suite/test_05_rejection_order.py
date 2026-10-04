"""Order of rejection where two rules are live at the same instant.

The PRD fixes the order in §2.11 and names the layers explicitly, so a request
that trips two layers reports the earlier one and only the earlier one.
"""
import pytest

from test_helpers import (
    TEST_USERS,
    create_entry,
    create_licensing_deal_payload,
    create_publisher,
    create_title,
    build_catalog_scenario,
    publish_entry,
    sign_deal,
    set_clock,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["admin_headers"]


def test_republishing_an_added_entry_reports_the_state_error_not_the_ceiling(api):
    """PRD §3.3: "attempting to publish an entry that is already `ADDED`,
    `REMOVING` or `DELISTED` is rejected with `ERR_ENTRY_NOT_PUBLISHABLE`."
    PRD §2.11: "a target in the wrong state is reported before any window,
    eligibility or quota rule is reached."

    Design: Difficulty/priority_pair_validation_conflict/already_added_entry_beats_region_ceiling
    """
    sc = build_catalog_scenario(api, ceiling=2)
    entry_a = create_entry(api, sc.title["id"], removal_date="2027-02-27T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=6000,
                           popularity_index_cents_30d_avg=3000)
    entry_b = create_entry(api, sc.title["id"], removal_date="2026-12-30T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=4000,
                           popularity_index_cents_30d_avg=4000)
    validate_success(api.publish_catalog_entry(entry_a["id"], ADMIN))
    validate_success(api.publish_catalog_entry(entry_b["id"], ADMIN))

    # Now the region sits at its ceiling of two ADDED entries, so the fiscal
    # rule ERR_REGION_CATALOG_CEILING_REACHED is live as well.
    validate_error(api.publish_catalog_entry(entry_a["id"], ADMIN),
                   "ERR_ENTRY_NOT_PUBLISHABLE")


def test_the_region_ceiling_error_fires_on_a_fresh_entry_at_the_same_instant(api):
    """PRD §2.7: "an attempt to publish an entry into a region that already
    holds that many entries in status `ADDED` or `REMOVING` is rejected with
    `ERR_REGION_CATALOG_CEILING_REACHED` (409)."

    Design: Difficulty/priority_pair_validation_conflict/already_added_entry_beats_region_ceiling
    """
    sc = build_catalog_scenario(api, ceiling=2)
    entry_a = create_entry(api, sc.title["id"], removal_date="2027-02-27T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=6000,
                           popularity_index_cents_30d_avg=3000)
    entry_b = create_entry(api, sc.title["id"], removal_date="2026-12-30T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=4000,
                           popularity_index_cents_30d_avg=4000)
    entry_c = create_entry(api, sc.title["id"], removal_date="2027-01-30T00:00:00Z",
                           release_class="CATALOG_ADD", popularity_index_cents=1000,
                           popularity_index_cents_30d_avg=1000)
    validate_success(api.publish_catalog_entry(entry_a["id"], ADMIN))
    validate_success(api.publish_catalog_entry(entry_b["id"], ADMIN))

    validate_error(api.publish_catalog_entry(entry_c["id"], ADMIN),
                   "ERR_REGION_CATALOG_CEILING_REACHED")

    rows, _meta = validate_paginated(
        api.list_catalog_entries(ADMIN, params={"region_code": "NA", "status": "ADDED"})
    )
    assert len(rows) == 2, "the rejected publish persisted nothing"


def test_short_day_one_notice_is_reported_as_the_temporal_layer_error(api):
    """PRD §3.4: "The notice count is the whole number of days between
    `announced_add_date` and `removal_date`, computed as the difference in
    seconds divided by 86,400 and truncated toward zero"
    PRD §3.4: "a notice count exactly equal to the minimum is accepted ... one
    whose notice falls short of its class minimum is rejected with
    `ERR_INSUFFICIENT_REMOVAL_NOTICE`."
    PRD §2.11: "the temporal layer collects ... `ERR_INSUFFICIENT_REMOVAL_NOTICE`".

    Design: Difficulty/priority_pair_validation_conflict/insufficient_notice_beats_day_one_ineligibility
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    region = build_catalog_scenario(api, advance_to="2026-09-02T00:00:00Z")
    publisher = create_publisher(api, name="Halcyon Works",
                                 home_region_code=region.region_code)
    title = create_title(api, publisher["id"], name="Static Vale",
                         platform_set=["CONSOLE", "PC", "CLOUD"],
                         day_one_eligible=True, list_price_cents=4000, unit_sales_30d=8000)
    deal = create_deal_for(api, publisher["id"], title["id"])
    sign_deal(api, deal["id"], title["version"])

    # A five-day notice fails the DAY_ONE minimum of fourteen; the announce
    # transition is where PRD §3.4 evaluates it.
    short = create_entry(api, title["id"], removal_date="2026-09-07T00:00:00Z",
                         release_class="DAY_ONE", popularity_index_cents=5000,
                         popularity_index_cents_30d_avg=5000)
    assert short["removal_notice_days"] == 5
    publish_entry(api, short["id"])
    validate_error(api.announce_entry_removal(short["id"], ADMIN),
                   "ERR_INSUFFICIENT_REMOVAL_NOTICE")

    # A fourteen-day notice clears the same boundary and is accepted.
    ok = create_entry(api, title["id"], removal_date="2026-09-16T00:00:00Z",
                      release_class="DAY_ONE", popularity_index_cents=5000,
                      popularity_index_cents_30d_avg=5000)
    assert ok["removal_notice_days"] == 14
    publish_entry(api, ok["id"])
    announced = validate_success(api.announce_entry_removal(ok["id"], ADMIN))
    assert announced["status"] == "REMOVING"


def test_a_day_one_entry_for_an_ineligible_title_is_refused_at_publish(api):
    """PRD §3.3: "and that a `DAY_ONE` entry's title actually be day-one
    eligible, otherwise `ERR_DAY_ONE_NOT_ELIGIBLE`."
    PRD §2.11: "the eligibility layer collects ... `ERR_DAY_ONE_NOT_ELIGIBLE`".

    Design: Difficulty/priority_pair_validation_conflict/insufficient_notice_beats_day_one_ineligibility
    """
    set_clock(api, "2026-09-01T00:00:00Z")
    region = build_catalog_scenario(api, advance_to="2026-09-02T00:00:00Z")
    publisher = create_publisher(api, name="Halcyon Works",
                                 home_region_code=region.region_code)
    # The title ships on CONSOLE and CLOUD, so the platform rules do not preempt
    # the day-one eligibility check.
    title = create_title(api, publisher["id"], name="Static Vale",
                         platform_set=["CONSOLE", "CLOUD"],
                         day_one_eligible=False, list_price_cents=4000, unit_sales_30d=8000)
    deal = create_deal_for(api, publisher["id"], title["id"])
    sign_deal(api, deal["id"], title["version"])

    entry = create_entry(api, title["id"], removal_date="2026-09-20T00:00:00Z",
                         release_class="DAY_ONE", popularity_index_cents=5000,
                         popularity_index_cents_30d_avg=5000)
    assert entry["removal_notice_days"] == 18, \
        "the eighteen-day notice clears the DAY_ONE minimum of fourteen"

    validate_error(api.publish_catalog_entry(entry["id"], ADMIN),
                   "ERR_DAY_ONE_NOT_ELIGIBLE")

    after = validate_success(api.get_catalog_entry(entry["id"], ADMIN))
    assert after["status"] == "PLANNED", "the rejected publish persisted nothing"


def create_deal_for(api, publisher_id, title_id):
    """A live HYBRID deal for the title, mirroring the standard scenario terms."""
    payload = create_licensing_deal_payload(publisher_id=publisher_id, title_id=title_id)
    return validate_success(api.create_licensing_deal(payload, ADMIN), expected_status=201)