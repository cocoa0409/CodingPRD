"""Pricing, seasons, and quoting: quoted vs frozen variants, season bucketing,
long-rental discount boundary, and the PATCH recompute behavior."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    api_client,
    create_confirmed_reservation,
    create_lane_rate_payload,
    create_quoted_reservation,
    make_customer_headers,
    setup_active_rate,
    setup_customer,
    setup_dealer,
    setup_two_locations,
    setup_unit,
    validate_error,
    validate_success,
)


def test_quoted_vs_frozen_price_when_lane_rate_changes_quoted_snapshot():
    """PRD §3.5: "the quote reflects the rate active at quote time, the frozen
    snapshot reflects the rate active at the confirm instant, and when the two
    rows differ the frozen value governs everything downstream, including
    settlement."

    Design: Difficulty/dual_variant_calc/quoted_vs_frozen_price_when_lane_rate_changes
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    rate_1 = setup_active_rate(loc_a, loc_b, base_rate_cents=5000)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    assert rsv["price_snapshot"]["quoted_rate_cents_per_day"] == 5000
    assert rsv["price_snapshot"]["total_quoted_cents"] == 10000
    # Replace the ACTIVE rate between quote and confirm.
    rate_2 = validate_success(api_client.create_lane_rate(
        create_lane_rate_payload(
            origin_location_id=loc_a["id"], dest_location_id=loc_b["id"],
            base_rate_cents=8000), TEST_USERS["pricing"]), expected_status=201)
    validate_success(api_client.activate_lane_rate(rate_2["id"], TEST_USERS["pricing"]))
    confirmed = validate_success(api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"])))
    assert confirmed["status"] == "CONFIRMED"
    assert confirmed["price_snapshot"]["quoted_rate_cents_per_day"] == 8000
    assert confirmed["price_snapshot"]["total_quoted_cents"] == 16000


def test_quoted_vs_frozen_price_incumbent_rate_superseded():
    """PRD §3.2: "Activation moves a row `DRAFT → ACTIVE` and, in the same act,
    any other row with the identical lane key — same origin, destination,
    equipment type, and season — that was `ACTIVE` becomes `SUPERSEDED`;
    uniqueness of the active rate per lane key is enforced here and nowhere
    else."

    Design: Difficulty/dual_variant_calc/quoted_vs_frozen_price_when_lane_rate_changes
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_unit(dealer_a)
    rate_1 = setup_active_rate(loc_a, loc_b, base_rate_cents=5000)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    rate_2 = validate_success(api_client.create_lane_rate(
        create_lane_rate_payload(
            origin_location_id=loc_a["id"], dest_location_id=loc_b["id"],
            base_rate_cents=8000), TEST_USERS["pricing"]), expected_status=201)
    validate_success(api_client.activate_lane_rate(rate_2["id"], TEST_USERS["pricing"]))
    # The incumbent row moved to SUPERSEDED in the same act as activation.
    incumbent = validate_success(api_client.get_lane_rate(rate_1["id"], TEST_USERS["pricing"]))
    assert incumbent["status"] == "SUPERSEDED"
    challenger = validate_success(api_client.get_lane_rate(rate_2["id"], TEST_USERS["pricing"]))
    assert challenger["status"] == "ACTIVE"
    # Confirm still succeeds against the new active row and freezes its price.
    confirmed = validate_success(api_client.confirm_reservation(
        rsv["id"], {"expected_reservation_version": rsv["version"]},
        make_customer_headers(customer["id"])))
    assert confirmed["status"] == "CONFIRMED"


def test_long_rental_discount_applies_at_exactly_seven_days():
    """PRD §3.5: "When the rental runs at least 7 days, the daily rate is then
    discounted by 10 percent and rounded half-up to the nearest integer cent —
    the day rate is rounded first, before any multiplication. The quoted total
    is the rounded daily rate multiplied by `rental_days`."

    Design: Corner/calculations/long_rental_discount_applies_at_exactly_seven_days
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b, base_rate_cents=10000)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    r6 = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-16T10:00:00Z")
    r7 = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-17T10:00:00Z")
    # 6 days: no discount.
    assert r6["rental_days"] == 6
    assert r6["price_snapshot"]["total_quoted_cents"] == 60000
    # 7 days: discounted day rate 9000 (round_half_up(10000 * 0.9)), total 63000.
    assert r7["rental_days"] == 7
    assert r7["price_snapshot"]["quoted_rate_cents_per_day"] == 9000
    assert r7["price_snapshot"]["total_quoted_cents"] == 63000


def test_season_of_bucket_boundaries():
    """PRD §3.5: "the season is `PEAK` for pickup months June through August,
    `SHOULDER` for April, May, September, and October, and `OFF_PEAK` in every
    other month, judged by the calendar month of the pickup instant in UTC."

    Design: Corner/calculations/season_of_bucket_boundaries
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b, season="PEAK", base_rate_cents=9000)
    setup_active_rate(loc_a, loc_b, season="SHOULDER", base_rate_cents=7000)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    r_peak = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2027-06-01T10:00:00Z", dropoff_date="2027-06-02T10:00:00Z")
    r_shoulder = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2027-05-31T10:00:00Z", dropoff_date="2027-06-01T10:00:00Z")
    assert r_peak["season"] == "PEAK"
    assert r_peak["price_snapshot"]["quoted_rate_cents_per_day"] == 9000
    # May 31 is SHOULDER even though dropoff lands in June.
    assert r_shoulder["season"] == "SHOULDER"
    assert r_shoulder["price_snapshot"]["quoted_rate_cents_per_day"] == 7000


def test_reservation_patch_recomputes_quote_and_bumps_version():
    """PRD §3.3: "While a reservation is still `QUOTED`, the customer may amend
    the `pickup_date` or `dropoff_date`; doing so recomputes the season and the
    quoted snapshot and bumps the reservation's `version` by 1."

    Design: Corner/endpoints/reservation_patch_recomputes_quote_and_bumps_version
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b, base_rate_cents=5000)
    customer, _ = setup_customer(verify_dealer=dealer_a)
    rsv = create_quoted_reservation(
        customer, dealer_a, loc_b,
        pickup_date="2026-11-10T10:00:00Z", dropoff_date="2026-11-12T10:00:00Z")
    patched = validate_success(api_client.patch_reservation(
        rsv["id"], {"dropoff_date": "2026-11-18T10:00:00Z"},
        make_customer_headers(customer["id"])))
    assert patched["version"] == rsv["version"] + 1
    assert patched["rental_days"] == 8
    # 8 days triggers the long-rental discount: round_half_up(5000 * 0.9) = 4500.
    assert patched["price_snapshot"]["quoted_rate_cents_per_day"] == 4500
    assert patched["price_snapshot"]["total_quoted_cents"] == 36000


def test_clock_default_is_fixed_2026_09_01():
    """PRD §2.5: "Before any administrative call adjusts it, the logical clock
    reads exactly 2026-09-01T00:00:00Z — the server startup default — and it
    must never fall back to wall-clock time."
    PRD §3.3: "The drop-off must fall strictly after the pickup, and the pickup
    must not lie in the past relative to the logical clock — a violation is
    `ERR_INVALID_DATE_RANGE` (HTTP 400)."

    Design: Corner/endpoints/clock_default_is_fixed_2026_09_01
    """
    loc_a, loc_b = setup_two_locations()
    dealer_a = setup_dealer(loc_a)
    setup_active_rate(loc_a, loc_b)
    customer, _ = setup_customer(verify_dealer=dealer_a, verify=False)
    # Pickup 2026-08-15 is before the default logical clock 2026-09-01.
    resp = api_client.create_reservation(
        {
            "customer_id": customer["id"],
            "origin_dealer_id": dealer_a["id"],
            "dest_location_id": loc_b["id"],
            "equipment_type": "TRUCK_10FT",
            "rental_kind": "ONE_WAY",
            "pickup_date": "2026-08-15T10:00:00Z",
            "dropoff_date": "2026-08-16T10:00:00Z",
        },
        make_customer_headers(customer["id"]),
    )
    validate_error(resp, ApiErrorId.ERR_INVALID_DATE_RANGE, expected_status=400)
