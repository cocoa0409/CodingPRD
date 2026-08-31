"""Riders, multi-ride passes and the fare frozen at request time."""

from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    assert_booking,
    assert_ride_pass,
    buy_ride_pass,
    create_booking_payload,
    create_confirmed_booking,
    create_trip,
    refund_ride_pass,
    setup_harbor_world,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
RIDER = TEST_USERS["rider_headers"]

MISSING_UUID = "00000000-0000-4000-8000-000000000009"


def test_new_booking_starts_requested_with_the_fare_frozen(api):
    """PRD §3.5: "A new booking is stamped with `rider_user_id` from `X-User-ID`,
    starts in `REQUESTED` with `trip_id` null, `offer_round` at 0, an empty
    `declined_trip_ids` list, `redemption_status` `NONE`, `interrupted_from_status`
    null, and `fare_charged_cents`, `fare_refunded_cents`, and `credit_refunded_cents`
    all at 0."
    PRD §3.5: "Begin with a per-seat base of 450 cents plus 275 cents for each zone
    crossed, where the number of zones crossed is the absolute difference of the
    destination stop's `zone_index` and the origin stop's `zone_index`; when both
    stops share a zone that difference is zero and the base is simply 450 cents."

    Design: Corner/state_machines/new_booking_starts_in_requested_with_no_trip_and_zero_offer_round
    """
    world = setup_harbor_world()

    booking = validate_success(
        api.create_booking(
            create_booking_payload(world["stop1_id"], world["stop2_id"],
                                   requested_date="2026-09-12",
                                   service_mode="SCHEDULED", party_size=2),
            RIDER,
        ),
        201,
    )

    assert_booking(booking)
    assert booking["status"] == "REQUESTED"
    assert booking["trip_id"] is None
    assert booking["offer_round"] == 0
    assert booking["declined_trip_ids"] == []
    assert booking["redemption_status"] == "NONE"
    assert booking["interrupted_from_status"] is None
    assert booking["fare_quoted_cents"] == 1450, (
        f"(450 + 275) x 1.0 mode x 1.0 surge x 2 seats must be 1450, got "
        f"{booking['fare_quoted_cents']}"
    )
    assert booking["fare_charged_cents"] == 0
    assert booking["version"] == 1


def test_booking_between_the_same_two_stops_is_rejected(api):
    """PRD §3.5: "The rider supplies `origin_stop_id` and `destination_stop_id` (which
    must differ), a `requested_date` naming the calendar date of travel, a
    `service_mode` of `SCHEDULED` or `ON_DEMAND`, and a `party_size` between 1 and 12
    inclusive."
    PRD §2.8: "**Distinct endpoints.** `origin_stop_id` differs from
    `destination_stop_id` — otherwise `ERR_SAME_ORIGIN_DESTINATION` (422)."

    Design: Corner/validations/booking_with_identical_origin_and_destination_is_rejected
    """
    world = setup_harbor_world()

    response = api.create_booking(
        create_booking_payload(world["stop1_id"], world["stop1_id"],
                               requested_date="2026-09-12", party_size=2),
        RIDER,
    )
    validate_error(response, ApiErrorId.ERR_SAME_ORIGIN_DESTINATION.value, 422)

    _rows, meta = validate_paginated(
        api.list_bookings(RIDER, params={"rider_user_id": "rider-ann"})
    )
    assert meta["total_count"] == 0, (
        f"A rejected booking must not be persisted, got {meta['total_count']}"
    )


def test_booking_for_a_date_with_no_operating_day_is_rejected(api):
    """PRD §3.5: "The travel date is resolved to the operating day whose
    `service_date` equals it, and if no such day has been opened the request fails
    with `ERR_SERVICE_DAY_NOT_FOUND`."

    Design: Corner/errors/booking_for_a_date_that_has_no_service_day_returns_service_day_not_found
    """
    world = setup_harbor_world()

    response = api.create_booking(
        create_booking_payload(world["stop1_id"], world["stop2_id"],
                               requested_date="2026-09-19", party_size=2),
        RIDER,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DAY_NOT_FOUND.value, 404)

    _rows, meta = validate_paginated(
        api.list_bookings(RIDER, params={"rider_user_id": "rider-ann"})
    )
    assert meta["total_count"] == 0


def test_booking_naming_an_unknown_stop_is_rejected(api):
    """PRD §2.8: "**Body foreign-key resolution.** Every foreign key supplied in the
    request body resolves, validated in the order the fields are listed for that
    endpoint in §3, yielding `ERR_STOP_NOT_FOUND`, `ERR_VESSEL_NOT_FOUND`,
    `ERR_CREW_NOT_FOUND`, `ERR_SERVICE_DAY_NOT_FOUND`, `ERR_DOCK_NOT_FOUND`, or
    `ERR_RIDE_PASS_NOT_FOUND` (all 404)."

    Design: Corner/errors/unknown_stop_reference_on_a_booking_returns_stop_not_found
    """
    world = setup_harbor_world()

    response = api.create_booking(
        create_booking_payload(world["stop1_id"], MISSING_UUID,
                               requested_date="2026-09-12", party_size=2),
        RIDER,
    )
    validate_error(response, ApiErrorId.ERR_STOP_NOT_FOUND.value, 404)


def test_pro_rata_unit_price_rounds_half_up_before_multiplying(api):
    """PRD §3.5: "Under `PRO_RATA` the operator pays back the rides not taken at the
    average price the rider actually paid: divide `purchase_price_cents` by
    `rides_purchased`, round half up to whole cents to get a unit price, then multiply
    that unit price by `rides_remaining`."
    PRD §3.5: "The chosen basis is recorded in `refund_basis`, the payout in
    `refund_amount_cents`; `rides_remaining` is set to 0, the pass moves
    `ACTIVE → REFUNDED` or `EXHAUSTED → REFUNDED`, and its `version` increments by 1."

    Design: Corner/calculations/pro_rata_unit_price_rounds_half_up_and_can_exceed_the_purchase_price
    """
    ride_pass = buy_ride_pass("rider-ann", zone_tier="OUTER", rides_purchased=10,
                              purchase_price_cents=9995, valid_until="2026-12-31")

    refunded = refund_ride_pass(ride_pass["id"], "rider-ann", "PRO_RATA")

    assert_ride_pass(refunded)
    assert refunded["refund_amount_cents"] == 10000, (
        f"9995 / 10 rounds half up to 1000, x 10 rides = 10000, got "
        f"{refunded['refund_amount_cents']}"
    )
    assert refunded["refund_basis"] == "PRO_RATA"
    assert refunded["rides_remaining"] == 0
    assert refunded["status"] == "REFUNDED"


def test_refunding_an_already_refunded_pass_is_rejected(api):
    """PRD §3.5: "Only the pass's owner may do so, and only while the pass is `ACTIVE`
    or `EXHAUSTED`; a pass already `REFUNDED` or `EXPIRED` is rejected with
    `ERR_PASS_NOT_ACTIVE`."

    Design: Corner/errors/refunding_a_pass_that_is_already_refunded_returns_pass_not_active
    """
    ride_pass = buy_ride_pass("rider-ann", zone_tier="INNER", rides_purchased=4,
                              purchase_price_cents=4000, valid_until="2026-12-31")
    refund_ride_pass(ride_pass["id"], "rider-ann", "PRO_RATA")

    response = api.refund_ride_pass(ride_pass["id"], {"settlement_basis": "DIFFERENTIAL"},
                                    RIDER)
    validate_error(response, ApiErrorId.ERR_PASS_NOT_ACTIVE.value, 409)

    unchanged = validate_success(api.get_ride_pass(ride_pass["id"], RIDER))
    assert unchanged["status"] == "REFUNDED"
    assert unchanged["refund_basis"] == "PRO_RATA", (
        f"The rejected second refund must not overwrite the basis, got "
        f"{unchanged['refund_basis']}"
    )
    assert unchanged["refund_amount_cents"] == 4000


def _surge_fare_world():
    """A zone-1 to zone-2 hop on an ELEVATED event day."""
    return setup_harbor_world(
        annual_inspection=False,
        service_day={"service_date": "2026-09-12", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10,
                     "event_name": "Harbor Bowl", "expected_attendance": 18000},
        clock="2026-09-12T13:00:00Z",
    )


def test_fare_rounds_per_seat_after_each_multiplier_then_multiplies_by_party(api):
    """PRD §3.5: "The mode multiplier is 14000 basis points for an `ON_DEMAND` booking
    and 10000 basis points for a `SCHEDULED` one: multiply the base by it, divide by
    10000, and round half up to whole cents."
    PRD §3.5: "The surge multiplier is the operating day's `surge_multiplier_bp`:
    multiply the rounded per-seat amount by it, divide by 10000, and round half up to
    whole cents again."
    PRD §3.5: "This ordering is normative — rounding once at the end, after
    multiplying the base by both multipliers and by the party size, yields a different
    number of cents and is incorrect."

    Design: Difficulty/combinatorial_formula/fare_quote_rounds_per_seat_after_each_multiplier_then_multiplies_by_party
    """
    world = _surge_fare_world()

    booking = validate_success(
        api.create_booking(
            create_booking_payload(world["stop1_id"], world["stop2_id"],
                                   requested_date="2026-09-12",
                                   service_mode="ON_DEMAND", party_size=3),
            RIDER,
        ),
        201,
    )

    assert booking["fare_quoted_cents"] == 3807, (
        f"725 -> 1015 -> 1269 per seat, x 3 seats = 3807, got "
        f"{booking['fare_quoted_cents']}"
    )
    assert booking["fare_quoted_cents"] != 3806, (
        "Rounding only once at the end yields 3806 and is incorrect"
    )


def test_surge_multiplier_of_the_day_feeds_the_frozen_quote(api):
    """PRD §3.2: "The tier then fixes two derived fields outright:
    `surge_multiplier_bp` is 10000 basis points at `NONE`, 12500 at `ELEVATED`, and
    15000 at `PEAK`; and `planned_extra_vessels` — the operator's capacity plan for
    the event — is 0 at `NONE`, 1 at `ELEVATED`, and 2 at `PEAK`."
    PRD §3.5: "The fare is quoted once, at request time, and frozen into
    `fare_quoted_cents`; it is never re-quoted, whatever happens to the booking
    afterwards, and the trip eventually offered or confirmed never influences it."

    Design: Difficulty/combinatorial_formula/fare_quote_rounds_per_seat_after_each_multiplier_then_multiplies_by_party
    """
    world = _surge_fare_world()

    assert world["day"]["surge_tier"] == "ELEVATED"
    assert world["day"]["surge_multiplier_bp"] == 12500

    booking = validate_success(
        api.create_booking(
            create_booking_payload(world["stop1_id"], world["stop2_id"],
                                   requested_date="2026-09-12",
                                   service_mode="ON_DEMAND", party_size=3),
            RIDER,
        ),
        201,
    )

    assert booking["status"] == "REQUESTED"
    assert booking["fare_charged_cents"] == 0, (
        f"Nothing is charged before confirmation, got {booking['fare_charged_cents']}"
    )
    assert booking["fare_quoted_cents"] == 3807


def _twin_pass_world():
    """Two byte-identical INNER passes, each with four rides already redeemed."""
    world = setup_harbor_world(
        annual_inspection=False,
        service_day={"service_date": "2026-09-12", "wind_knots": 10.0,
                     "wave_height_m": 0.30, "low_water_m": 2.10,
                     "event_name": "Harbor Bowl", "expected_attendance": 18000},
        clock="2026-09-12T13:00:00Z",
    )
    create_trip(world)
    pass_ann = buy_ride_pass("rider-ann", zone_tier="INNER", rides_purchased=10,
                             purchase_price_cents=9000, valid_until="2026-12-31")
    pass_bob = buy_ride_pass("rider-bob", zone_tier="INNER", rides_purchased=10,
                             purchase_price_cents=9000, valid_until="2026-12-31")
    create_confirmed_booking(world, "rider-ann", party_size=4,
                             ride_pass_id=pass_ann["id"])
    create_confirmed_booking(world, "rider-bob", party_size=4,
                             ride_pass_id=pass_bob["id"])
    return world, pass_ann, pass_bob


def test_pro_rata_settlement_pays_for_the_rides_not_taken(api):
    """PRD §3.5: "Under `PRO_RATA` the operator pays back the rides not taken at the
    average price the rider actually paid: divide `purchase_price_cents` by
    `rides_purchased`, round half up to whole cents to get a unit price, then multiply
    that unit price by `rides_remaining`."
    PRD §3.5: "The chosen basis is recorded in `refund_basis`, the payout in
    `refund_amount_cents`; `rides_remaining` is set to 0, the pass moves
    `ACTIVE → REFUNDED` or `EXHAUSTED → REFUNDED`, and its `version` increments by 1."

    Design: Difficulty/dual_variant_calc/ride_pass_residual_pro_rata_versus_differential_on_identical_passes
    """
    _world, pass_ann, _pass_bob = _twin_pass_world()

    refunded = refund_ride_pass(pass_ann["id"], "rider-ann", "PRO_RATA")

    assert refunded["refund_amount_cents"] == 5400, (
        f"900 per ride x 6 rides remaining = 5400, got {refunded['refund_amount_cents']}"
    )
    assert refunded["refund_basis"] == "PRO_RATA"
    assert refunded["status"] == "REFUNDED"


def test_differential_settlement_claws_back_the_retail_value_already_travelled(api):
    """PRD §3.5: "Under `DIFFERENTIAL` the operator instead claws back the retail
    value of the rides already taken: multiply `rides_consumed` by the retail per-ride
    price of the pass's tier — 1100 cents for `INNER`, 1800 cents for `OUTER`, 2600
    cents for `ALL_ZONE` — subtract that from `purchase_price_cents`, and take zero if
    the subtraction would go negative."
    PRD §3.5: "Because a multi-ride pass is sold at a discount to retail,
    `DIFFERENTIAL` returns strictly less than `PRO_RATA` once any ride has been used,
    while a `PRO_RATA` settlement of a fully exhausted pass pays exactly 0."

    Design: Difficulty/dual_variant_calc/ride_pass_residual_pro_rata_versus_differential_on_identical_passes
    """
    _world, pass_ann, pass_bob = _twin_pass_world()

    pro_rata = refund_ride_pass(pass_ann["id"], "rider-ann", "PRO_RATA")
    differential = refund_ride_pass(pass_bob["id"], "rider-bob", "DIFFERENTIAL")

    assert differential["refund_amount_cents"] == 4600, (
        f"9000 - 4 rides x 1100 retail = 4600, got {differential['refund_amount_cents']}"
    )
    assert differential["refund_basis"] == "DIFFERENTIAL"
    assert differential["rides_remaining"] == 0
    assert differential["refund_amount_cents"] < pro_rata["refund_amount_cents"], (
        f"DIFFERENTIAL must return strictly less than PRO_RATA on identical passes: "
        f"{differential['refund_amount_cents']} vs {pro_rata['refund_amount_cents']}"
    )
