"""Half-open delegation windows and the per-product price-hold cooldown."""
from test_helpers import (
    ApiErrorId,
    add_price_hold_term,
    assert_instant_equals,
    assert_paginated_list,
    create_grant,
    delegation_grant_payload,
    ids_of,
    nonstandard_term_payload,
    read_term,
    setup_single_line_quote,
    validate_error,
    USER_IDS,
)


def test_a_second_grant_from_the_same_grantor_and_tier_may_not_overlap(
    api, base, director_headers, vp_headers, analyst_headers
):
    """PRD §2.10: "Creating a grant whose half-open window from inclusive `starts_at` to
    exclusive `ends_at` intersects the window of an existing `ACTIVE` grant with the same
    `grantor_user_id` and the same `tier_level` is refused with
    `ERR_DELEGATION_WINDOW_OVERLAP` (HTTP 409)."
    PRD §2.10: "Two grants that merely touch — where one's `ends_at` equals the other's
    `starts_at` — do not overlap, because the interval is half-open at its upper end."

    Design: Difficulty/resource_temporal_overlap/delegation_grant_windows_overlap_rejected_adjacent_and_other_grantor_allowed
    """
    first = create_grant(
        api, USER_IDS["grantee_a"], 2, 0.20, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
        headers=director_headers,
    )
    assert first["status"] == "ACTIVE"
    assert first["grantor_user_id"] == USER_IDS["director"]

    overlapping = api.create_delegation_grant(
        delegation_grant_payload(
            USER_IDS["grantee_b"], 2, 0.20, "2026-08-19T00:00:00Z", "2026-08-25T00:00:00Z"
        ),
        director_headers,
    )
    validate_error(overlapping, ApiErrorId.ERR_DELEGATION_WINDOW_OVERLAP.value, 409)

    touching = create_grant(
        api, USER_IDS["grantee_b"], 2, 0.20, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z",
        headers=director_headers,
    )
    assert touching["status"] == "ACTIVE", "an end that equals a start is not an intersection"
    assert_instant_equals(touching["starts_at"], "2026-08-20T00:00:00.000Z", "starts_at")

    other_grantor = create_grant(
        api, USER_IDS["grantee_b"], 2, 0.20, "2026-08-19T00:00:00Z", "2026-08-25T00:00:00Z",
        headers=vp_headers,
    )
    assert other_grantor["status"] == "ACTIVE", "the calendar is kept per grantor"
    assert other_grantor["grantor_user_id"] == USER_IDS["vp"]


def test_delegation_grants_come_back_ordered_by_their_window_start(
    api, base, director_headers, vp_headers, analyst_headers
):
    """PRD §2.3: "Four endpoints do name a different ordering, and those orderings are part
    of their contract: a policy's approval matrix rows come back sorted by `tier_level`
    ascending, a product's quantity bands by `min_quantity` ascending, a product's price
    holds by `hold_start_date` ascending, and delegation grants by `starts_at` ascending."
    PRD §2.3: "`total_count` is the number of records matching the request's filters before
    the page window is applied, and `has_more` is true exactly when records matching the
    filters remain beyond the current window."

    Design: Difficulty/resource_temporal_overlap/delegation_grant_windows_overlap_rejected_adjacent_and_other_grantor_allowed
    """
    first = create_grant(
        api, USER_IDS["grantee_a"], 2, 0.20, "2026-08-10T00:00:00Z", "2026-08-20T00:00:00Z",
        headers=director_headers,
    )
    later = create_grant(
        api, USER_IDS["grantee_b"], 2, 0.20, "2026-08-20T00:00:00Z", "2026-08-25T00:00:00Z",
        headers=director_headers,
    )
    middle = create_grant(
        api, USER_IDS["grantee_b"], 2, 0.20, "2026-08-19T00:00:00Z", "2026-08-25T00:00:00Z",
        headers=vp_headers,
    )

    grants, _ = assert_paginated_list(
        api.list_delegation_grants(analyst_headers, params={"tier_level": 2}),
        expected_total=3, expected_page_size=3,
    )
    assert ids_of(grants) == [first["id"], middle["id"], later["id"]]


def _two_quotes_with_one_live_hold(api, base):
    quote_a, _ = setup_single_line_quote(
        api, base, "support", 10, 0.00, term_months=12, title="Northwind Hold Quote A",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    hold = add_price_hold_term(
        api, quote_a["id"], base["support"]["id"], "2027-01-01", "2027-12-31",
        requested_numeric_value=12,
        requested_text="Hold FY27 support pricing for the renewal year",
    )
    quote_b, _ = setup_single_line_quote(
        api, base, "support", 10, 0.00, term_months=12, title="Northwind Hold Quote B",
        payment_terms_days=30, billing_frequency="ANNUAL",
    )
    return quote_a, hold, quote_b


def test_a_renewal_hold_inside_the_cooldown_is_refused_even_on_another_quote(
    api, base, rep_headers
):
    """PRD §3.4: "The proposal is refused with `ERR_PRICE_HOLD_WINDOW_CONFLICT` unless the
    two inclusive windows are separated by at least the pinned revision's
    `price_hold_cooldown_days` days."
    PRD §3.4: "The comparison considers only other `PRICE_HOLD_RENEWAL` terms whose
    `review_state` is `PENDING` or `APPROVED`, and only those registered against the same
    customer — reached through the quote's `account_id` — and the same `hold_product_id`."

    Design: Difficulty/resource_temporal_overlap/price_hold_windows_need_the_cooldown_gap_per_account_and_product
    """
    quote_a, hold, quote_b = _two_quotes_with_one_live_hold(api, base)
    assert hold["review_state"] == "PENDING"
    assert read_term(api, quote_a["id"], hold["id"])["hold_end_date"] == "2027-12-31"

    too_soon = api.create_nonstandard_term(
        nonstandard_term_payload(
            quote_b["id"], "PRICE_HOLD_RENEWAL", 12,
            requested_text="Second support hold, 30 days after the first",
            hold_product_id=base["support"]["id"],
            hold_start_date="2028-01-30", hold_end_date="2028-06-30",
        ),
        rep_headers,
    )
    validate_error(too_soon, ApiErrorId.ERR_PRICE_HOLD_WINDOW_CONFLICT.value, 409)

    clear_of_cooldown = add_price_hold_term(
        api, quote_b["id"], base["support"]["id"], "2028-01-31", "2028-06-30",
        requested_numeric_value=12,
        requested_text="Second support hold, 31 days after the first",
    )
    assert clear_of_cooldown["review_state"] == "PENDING"
    assert clear_of_cooldown["hold_start_date"] == "2028-01-31"


def test_the_cooldown_is_keyed_per_product_and_holds_list_by_start_date(
    api, base, analyst_headers
):
    """PRD §3.4: "Terms already `REJECTED` or `WITHDRAWN` impose no cooldown at all."
    PRD §2.3: "a product's price holds by `hold_start_date` ascending"

    Design: Difficulty/resource_temporal_overlap/price_hold_windows_need_the_cooldown_gap_per_account_and_product
    """
    _, _, quote_b = _two_quotes_with_one_live_hold(api, base)
    add_price_hold_term(
        api, quote_b["id"], base["support"]["id"], "2028-01-31", "2028-06-30",
        requested_numeric_value=12,
        requested_text="Second support hold, 31 days after the first",
    )
    other_product = add_price_hold_term(
        api, quote_b["id"], base["core"]["id"], "2028-01-30", "2028-06-30",
        requested_numeric_value=12,
        requested_text="Platform hold inside the support cooldown",
    )
    assert other_product["hold_product_id"] == base["core"]["id"]

    support_holds, _ = assert_paginated_list(
        api.list_product_price_holds(base["support"]["id"], analyst_headers),
        expected_total=2, expected_page_size=2,
    )
    assert [hold["hold_start_date"] for hold in support_holds] == ["2027-01-01", "2028-01-31"]

    core_holds, _ = assert_paginated_list(
        api.list_product_price_holds(base["core"]["id"], analyst_headers),
        expected_total=1, expected_page_size=1,
    )
    assert core_holds[0]["hold_start_date"] == "2028-01-30"
