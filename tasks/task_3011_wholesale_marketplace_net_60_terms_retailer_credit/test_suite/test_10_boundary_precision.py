"""Boundary precision (queue A): the credit gate's exact-equality edge and the
territory radius's strict-less-than edge."""

from test_helpers import (
    ApiErrorId,
    active_brand,
    create_grant,
    make_brand_headers,
    make_retailer_headers,
    open_credit_account,
    order_payload,
    validate_error,
    validate_success,
    verified_retailer,
    verified_retailer_with_account,
)


def test_subtotal_equal_to_available_credit_is_accepted(api):
    """PRD §3.4: "The credit check requires the retailer's credit account to be
    `ACTIVE` with `available_cents` at least equal to the `subtotal_cents`; a
    frozen account or insufficient headroom yields `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 422)."
    PRD §3.3: "Every retailer starts from a base by store type: 250,000 cents
    for `BRICK_AND_MORTAR`, 150,000 cents for `ONLINE`, and 200,000 cents for
    `HYBRID`."

    Design: Difficulty/boundary_precision_check/credit_available_exact_boundary
    """
    retailer, _ = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)
    response = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 150000, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    order = validate_success(response, 201)
    assert order["subtotal_cents"] == 150000


def test_subtotal_one_cent_over_available_credit_is_rejected(api):
    """PRD §3.4: "The credit check requires the retailer's credit account to be
    `ACTIVE` with `available_cents` at least equal to the `subtotal_cents`; a
    frozen account or insufficient headroom yields `ERR_CREDIT_LIMIT_EXCEEDED`
    (HTTP 422)."

    Design: Difficulty/boundary_precision_check/credit_available_exact_boundary
    """
    retailer, account = verified_retailer_with_account(api, store_type="ONLINE")
    brand = active_brand(api, lead_time_days=0)

    # First order, once shipped, puts a 150000-cent invoice on the books and
    # consumes the full headroom (available = limit - outstanding balances).
    first = validate_success(
        api.create_order(
            order_payload(retailer["id"], brand["id"],
                          [{"sku": "S1", "unit_price_cents": 150000, "qty": 1}]),
            make_retailer_headers(retailer["id"]),
        ),
        201,
    )
    validate_success(api.ship_order(first["id"], make_brand_headers(brand["id"])))

    # A further order at the brand's 1000-cent minimum has zero headroom left;
    # the credit check (which follows the minimum-order check in the ladder)
    # is the one that fires.
    response = api.create_order(
        order_payload(retailer["id"], brand["id"],
                      [{"sku": "S2", "unit_price_cents": 1000, "qty": 1}]),
        make_retailer_headers(retailer["id"]),
    )
    validate_error(response, ApiErrorId.ERR_CREDIT_LIMIT_EXCEEDED, 422)


def test_storefront_exactly_on_radius_circle_is_not_blocked(api):
    """PRD §3.8: "the great-circle distance between the grant's center and the
    retailer's storefront `lat`/`lng` — computed with the haversine formula
    using an earth radius of 6,371.0 kilometers — is strictly less than
    `radius_km`. A storefront sitting exactly on the boundary circle is not
    blocked."

    Design: Difficulty/boundary_precision_check/territory_distance_boundary
    """
    # Haversine((40,-105) -> (41,-105)) with R=6371.0, computed with the
    # standard double-precision formula; used verbatim as the grant radius.
    radius_km = 111.19492664455873

    holder = verified_retailer(api, lat=40.0, lng=-105.0)
    brand = active_brand(api, lead_time_days=0)
    create_grant(
        api, brand["id"], holder["id"],
        center_lat=40.0, center_lng=-105.0, radius_km=radius_km,
        starts_at="2026-08-01T00:00:00Z", ends_at="2027-08-01T00:00:00Z",
    )

    challenger = verified_retailer(api, lat=41.0, lng=-105.0)
    open_credit_account(api, challenger["id"])

    response = api.create_order(
        order_payload(challenger["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(challenger["id"]),
    )
    validate_success(response, 201)


def test_storefront_inside_radius_is_blocked(api):
    """PRD §3.8: "When any grant satisfies all five conditions, the placement
    fails with `ERR_TERRITORY_CONFLICT` (HTTP 422)."
    PRD §3.8: "the great-circle distance between the grant's center and the
    retailer's storefront `lat`/`lng` — computed with the haversine formula
    using an earth radius of 6,371.0 kilometers — is strictly less than
    `radius_km`."

    Design: Difficulty/boundary_precision_check/territory_distance_boundary
    """
    holder = verified_retailer(api, lat=40.0, lng=-105.0)
    brand = active_brand(api, lead_time_days=0)
    create_grant(
        api, brand["id"], holder["id"],
        center_lat=40.0, center_lng=-105.0, radius_km=5.0,
        starts_at="2026-08-01T00:00:00Z", ends_at="2027-08-01T00:00:00Z",
    )

    # 0.001 degrees of latitude ≈ 0.111 km inside the 5 km circle.
    challenger = verified_retailer(api, lat=40.001, lng=-105.0)
    open_credit_account(api, challenger["id"])

    response = api.create_order(
        order_payload(challenger["id"], brand["id"],
                      [{"sku": "S1", "unit_price_cents": 5000, "qty": 1}]),
        make_retailer_headers(challenger["id"]),
    )
    validate_error(response, ApiErrorId.ERR_TERRITORY_CONFLICT, 422)
