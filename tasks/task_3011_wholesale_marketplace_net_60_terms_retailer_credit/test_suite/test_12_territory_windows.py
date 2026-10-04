"""Resource temporal overlap (queue A): grant-interval half-open semantics and
the time-window territory conflict."""

from test_helpers import (
    ADMIN,
    ApiErrorId,
    active_brand,
    create_grant,
    exclusivity_grant_payload,
    get_success_data,
    make_brand_headers,
    make_retailer_headers,
    open_credit_account,
    order_payload,
    read_brand,
    set_clock,
    validate_error,
    validate_success,
    verified_retailer,
)


def test_touching_grant_intervals_do_not_overlap(api):
    """PRD §3.8: "The window must be well-formed: `ends_at` must fall after
    `starts_at`, and no two grants for the same brand and the same retailer may
    have overlapping half-open intervals while both are `ACTIVE` — intervals
    that merely touch at an endpoint do not overlap."

    Design: Difficulty/resource_temporal_overlap/grant_interval_overlap_same_pair
    """
    retailer = verified_retailer(api)
    brand = active_brand(api, lead_time_days=0)
    create_grant(
        api, brand["id"], retailer["id"],
        starts_at="2026-08-01T00:00:00Z", ends_at="2027-08-01T00:00:00Z",
    )
    second = create_grant(
        api, brand["id"], retailer["id"],
        starts_at="2027-08-01T00:00:00Z", ends_at="2028-08-01T00:00:00Z",
    )
    assert second["status"] == "ACTIVE"


def test_overlapping_grant_interval_rejected(api):
    """PRD §3.8: "A malformed or overlapping interval is rejected with
    `ERR_GRANT_OVERLAP` (HTTP 422). New grants begin `ACTIVE`."

    Design: Difficulty/resource_temporal_overlap/grant_interval_overlap_same_pair
    """
    retailer = verified_retailer(api)
    brand = active_brand(api, lead_time_days=0)
    create_grant(
        api, brand["id"], retailer["id"],
        starts_at="2026-08-01T00:00:00Z", ends_at="2027-08-01T00:00:00Z",
    )
    fresh = read_brand(api, brand["id"])
    response = api.create_exclusivity_grant(
        exclusivity_grant_payload(
            brand["id"], retailer["id"], fresh["version"],
            starts_at="2027-07-31T23:59:59Z", ends_at="2028-06-01T00:00:00Z",
        ),
        make_brand_headers(brand["id"]),
    )
    validate_error(response, ApiErrorId.ERR_GRANT_OVERLAP, 422)


def test_expired_grant_no_longer_blocks(api):
    """PRD §3.8: "the grant is `ACTIVE` at evaluation time — grants whose
    `ends_at` has been reached are first flipped to `EXPIRED` by lazy
    evaluation and no longer block"
    PRD §3.8: "When any grant satisfies all five conditions, the placement
    fails with `ERR_TERRITORY_CONFLICT` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/territory_time_window_conflict
    """
    holder = verified_retailer(api, lat=55.0, lng=-120.0)
    brand = active_brand(api, lead_time_days=0)
    grant = create_grant(
        api, brand["id"], holder["id"],
        center_lat=55.0, center_lng=-120.0, radius_km=5.0,
        starts_at="2026-08-01T00:00:00Z", ends_at="2026-10-01T00:00:00Z",
    )

    challenger = verified_retailer(api, lat=55.001, lng=-120.0)
    open_credit_account(api, challenger["id"])

    blocked = api.create_order(
        order_payload(challenger["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(challenger["id"]),
    )
    validate_error(blocked, ApiErrorId.ERR_TERRITORY_CONFLICT, 422)

    # Reach ends_at: the grant lazy-flips to EXPIRED and stops blocking.
    set_clock(api, "2026-10-01T00:00:00Z")
    assert get_success_data(api.get_exclusivity_grant(grant["id"], ADMIN))["status"] == (
        "EXPIRED"
    )

    allowed = api.create_order(
        order_payload(challenger["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(challenger["id"]),
    )
    validate_success(allowed, 201)


def test_grant_holder_is_never_blocked_by_own_grant(api):
    """PRD §3.8: "A grant blocks competing order placements when every one of
    the following holds: the grant's brand is the order's brand; the grant is
    `ACTIVE` at evaluation time — grants whose `ends_at` has been reached are
    first flipped to `EXPIRED` by lazy evaluation and no longer block; the
    logical-clock now falls within the window, at or after `starts_at` and
    strictly before `ends_at`; the ordering retailer is not the grant's
    protected retailer; and the great-circle distance between the grant's
    center and the retailer's storefront `lat`/`lng` — computed with the
    haversine formula using an earth radius of 6,371.0 kilometers — is strictly
    less than `radius_km`."

    Design: Difficulty/resource_temporal_overlap/territory_time_window_conflict
    """
    holder = verified_retailer(api, lat=55.0, lng=-120.0)
    open_credit_account(api, holder["id"])
    brand = active_brand(api, lead_time_days=0)
    create_grant(
        api, brand["id"], holder["id"],
        center_lat=55.0, center_lng=-120.0, radius_km=5.0,
        starts_at="2026-08-01T00:00:00Z", ends_at="2026-10-01T00:00:00Z",
    )

    response = api.create_order(
        order_payload(holder["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(holder["id"]),
    )
    validate_success(response, 201)
