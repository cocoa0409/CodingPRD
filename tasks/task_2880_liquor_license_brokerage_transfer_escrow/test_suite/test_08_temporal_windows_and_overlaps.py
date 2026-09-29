"""Two reservations of one resource: the license's half-open contract window and
the premises' closed posting window widened by a statutory quiet buffer.
"""

from test_helpers import (
    ApiErrorId,
    add_parallel_transfer,
    api_client,
    assert_instant_equals,
    create_purchase_agreement_payload,
    draft_agreement,
    post_notice,
    read_application,
    read_listing,
    set_clock,
    setup_scenario,
    validate_error,
    validate_paginated,
)


def _active_listing():
    """An ACTIVE listing on a license whose reserved-window set is empty."""
    return setup_scenario(
        stage="listing_active",
        county_overrides={"quota_licenses_total": 100},
    )


def test_two_contract_windows_that_merely_touch_are_both_accepted():
    """The interval is half-open, so the exclusive end is free to be reused.

    PRD: "Before the draft is accepted, the proposed half-open interval running
    from `closing_window_start` up to but not including `contingency_deadline_at`
    is compared against the same interval of every other agreement on the same
    `license_id` whose `agreement_status` is `DRAFT` or `EXECUTED`."

    PRD: "Because the intervals are half-open, two windows that merely touch — one
    ending at the exact instant the next begins — do not intersect and are both
    accepted."

    The first window runs from 2026-09-01 up to but not including 2026-10-01; the
    second starts exactly on that excluded instant and runs to 2026-10-31.

    Design: Difficulty/resource_temporal_overlap/license_closing_window_half_open_adjacency
    """
    scenario = _active_listing()
    listing_id = scenario["listing_id"]

    first = draft_agreement(
        listing_id, scenario["buyer_id"], scenario["premises_id"],
        scenario["listing"]["version"], scenario["brokerage_id"],
        closing_window_start="2026-09-01T00:00:00Z", contingency_days=30,
    )
    assert_instant_equals(
        first["contingency_deadline_at"], "2026-10-01T00:00:00Z",
        "contingency_deadline_at",
    )

    second = draft_agreement(
        listing_id, scenario["buyer_id"], scenario["premises_id"],
        read_listing(listing_id)["version"], scenario["brokerage_id"],
        closing_window_start="2026-10-01T00:00:00Z", contingency_days=30,
    )
    assert_instant_equals(
        second["contingency_deadline_at"], "2026-10-31T00:00:00Z",
        "contingency_deadline_at",
    )
    assert second["agreement_status"] == "DRAFT"
    assert read_listing(listing_id)["open_offer_count"] == 2


def test_a_window_overlapping_a_live_reservation_by_one_day_is_refused():
    """An intersecting window is refused and leaves no trace.

    PRD: "Competing draft offers on one listing are legitimate, but competing
    *reservations of the same license window* are not."

    PRD: "Any intersection is refused with `ERR_LICENSE_CONTRACT_OVERLAP`."

    A window starting 2026-09-30 intersects the first agreement's
    [2026-09-01, 2026-10-01) reservation by a single day, so the create is refused
    and the listing's open-offer counter still reflects only the two accepted
    offers.

    Design: Difficulty/resource_temporal_overlap/license_closing_window_half_open_adjacency
    """
    scenario = _active_listing()
    listing_id = scenario["listing_id"]

    draft_agreement(
        listing_id, scenario["buyer_id"], scenario["premises_id"],
        scenario["listing"]["version"], scenario["brokerage_id"],
        closing_window_start="2026-09-01T00:00:00Z", contingency_days=30,
    )
    draft_agreement(
        listing_id, scenario["buyer_id"], scenario["premises_id"],
        read_listing(listing_id)["version"], scenario["brokerage_id"],
        closing_window_start="2026-10-01T00:00:00Z", contingency_days=30,
    )

    refused = api_client.create_purchase_agreement(
        create_purchase_agreement_payload(
            listing_id, scenario["buyer_id"], scenario["premises_id"],
            read_listing(listing_id)["version"],
            closing_window_start="2026-09-30T00:00:00Z", contingency_days=30,
        ),
        scenario["broker_headers"],
    )
    validate_error(refused, ApiErrorId.ERR_LICENSE_CONTRACT_OVERLAP.value, 409)

    assert read_listing(listing_id)["open_offer_count"] == 2
    rows, meta = validate_paginated(
        api_client.list_purchase_agreements(
            scenario["admin_headers"], {"listing_id": listing_id}
        )
    )
    assert meta["total_count"] == 2
    assert len(rows) == 2


def _two_sales_on_one_premises():
    """Two separate license sales pointed at the same premises, the first of them
    already published on 2026-08-10."""
    scenario = setup_scenario(
        stage="application_posted",
        county_overrides={
            "quota_licenses_total": 100,
            "posting_period_days": 30,
            "protest_window_days": 15,
        },
        application_fee=173250,
        post_notice_at="2026-08-10T00:00:00Z",
    )
    second = add_parallel_transfer(scenario, closing_window_start="2026-09-01T00:00:00Z")
    return scenario, second


def test_a_second_posting_exactly_on_the_buffered_boundary_collides():
    """The comparison is strictly greater, so the boundary instant is a conflict.

    PRD: "And the proposed publication must not collide with another live
    publication on the same premises: for every other application on the same
    `premises_id` whose `status` is `POSTED`, `PROTESTED` or `APPROVED`, the current
    logical instant must be strictly later than that other application's
    `posting_ends_at` advanced by a statutory quiet buffer of 30 days."

    PRD: "The intervals here are closed and the buffer is additive, so equality
    collides — an instant exactly on the buffered boundary is a conflict, refused
    with `ERR_POSTING_WINDOW_CONFLICT`."

    The first publication runs 2026-08-10 to 2026-09-09, so its quiet buffer ends
    at 2026-10-09; a second publication attempted at exactly that instant is not
    strictly later and is refused.

    Design: Difficulty/resource_temporal_overlap/premises_posting_window_closed_plus_quiet_buffer
    """
    scenario, second = _two_sales_on_one_premises()
    first_application = read_application(scenario["application_id"])
    assert_instant_equals(
        first_application["posting_started_at"], "2026-08-10T00:00:00Z",
        "posting_started_at",
    )
    assert_instant_equals(
        first_application["posting_ends_at"], "2026-09-09T00:00:00Z",
        "posting_ends_at",
    )
    assert_instant_equals(
        first_application["protest_deadline_at"], "2026-08-25T00:00:00Z",
        "protest_deadline_at",
    )

    set_clock("2026-10-09T00:00:00Z")
    refused = api_client.post_notice(
        second["application_id"], scenario["analyst_headers"]
    )
    validate_error(refused, ApiErrorId.ERR_POSTING_WINDOW_CONFLICT.value, 409)

    blocked = read_application(second["application_id"])
    assert blocked["status"] == "UNDER_REVIEW"
    assert blocked["posting_started_at"] is None


def test_a_second_posting_one_day_past_the_buffer_is_accepted():
    """One day later the instant is strictly later and publication proceeds.

    PRD: "Publication then writes three instants. `posting_started_at` is the
    current logical instant. `posting_ends_at` is `posting_started_at` advanced by
    the county's `posting_period_days`."

    PRD: "And the proposed publication must not collide with another live
    publication on the same premises: for every other application on the same
    `premises_id` whose `status` is `POSTED`, `PROTESTED` or `APPROVED`, the current
    logical instant must be strictly later than that other application's
    `posting_ends_at` advanced by a statutory quiet buffer of 30 days."

    The buffer is read off the first application rather than rewritten onto it, so
    that application is still `POSTED` with its own instants untouched.

    Design: Difficulty/resource_temporal_overlap/premises_posting_window_closed_plus_quiet_buffer
    """
    scenario, second = _two_sales_on_one_premises()

    set_clock("2026-10-09T00:00:00Z")
    early = api_client.post_notice(
        second["application_id"], scenario["analyst_headers"]
    )
    validate_error(early, ApiErrorId.ERR_POSTING_WINDOW_CONFLICT.value, 409)

    set_clock("2026-10-10T00:00:00Z")
    posted = post_notice(second["application_id"])
    assert posted["status"] == "POSTED"
    assert_instant_equals(
        posted["posting_started_at"], "2026-10-10T00:00:00Z", "posting_started_at"
    )
    assert_instant_equals(
        posted["posting_ends_at"], "2026-11-09T00:00:00Z", "posting_ends_at"
    )

    first_application = read_application(scenario["application_id"])
    assert first_application["status"] == "POSTED"
    assert_instant_equals(
        first_application["posting_ends_at"], "2026-09-09T00:00:00Z",
        "posting_ends_at",
    )
