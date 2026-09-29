"""Priority conflicts inside the strictly ordered validation sequence.

Validation is strictly ordered: the first violated check decides the whole
response and no side effect of any kind is applied. These tests build requests
that violate two checks at once and pin the error the earlier check owns, then
repeat the same request with only the earlier violation removed so that the
later check's own error is shown to have been genuinely reachable.
"""

from typing import Any, Dict

from prd_bench_local_runner.testing import validate_error

from test_helpers import (
    ApiErrorId,
    REVENUE_MANAGER_HEADERS,
    assert_fields,
    assert_instant_equals,
    assert_inventory_day,
    factories,
    filter_by,
    fixtures,
)

# KING holds ten physical rooms at the property's 1000 bp allowance:
# 10 + floor(10 x 1000 / 10000) = 11 units of nightly ceiling.
CEILING_UNITS = fixtures.KING_CEILING

# The clock sits at 2026-08-25 and the property sells 365 days out, so
# 2026-08-25 + 365 = 2027-08-25 is the last date inside the booking horizon.
LAST_IN_HORIZON_DATE = "2027-08-25"


def _exhaust_the_nightly_ceiling(api: Any, world: Dict[str, Any]) -> Dict[str, Any]:
    """Open one night and hold every unit of its ceiling for the direct channel.

    The night ends up with allocated_units 11, committed_units 0 and
    shared_pool_units 0, so any booking that has to draw from the shared pool is
    over the ceiling. committed_units stays at 0, which keeps the night
    EXHAUSTED rather than OVERSOLD and so leaves the automatic overbooking guard
    out of the picture.
    """
    fixtures.open_inventory_day(api, world["room_type_id"], fixtures.STAY_DATE)
    brand = fixtures.create_brand_channel(api, world["property_id"])
    fixtures.create_allocation(
        api,
        world["room_type_id"],
        brand["channel"]["id"],
        CEILING_UNITS,
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(
        day,
        capacity=fixtures.KING_CAPACITY,
        ceiling=CEILING_UNITS,
        allocated=CEILING_UNITS,
        committed=0,
        shared=0,
        pooled_state="EXHAUSTED",
    )
    return brand


def _ota_booking_payload(world: Dict[str, Any]) -> Dict[str, Any]:
    """A one-night stay on the OTA, which serves only the US-CA market."""
    return factories.reservation_payload(
        channel_id=world["channel_id"],
        rate_plan_id=world["rate_plan_id"],
        room_type_id=world["room_type_id"],
        arrival_date=fixtures.STAY_DATE,
        nights=1,
        geo_market_code=fixtures.OTA_GEO_MARKET,
    )


def _restriction_batches(api: Any) -> int:
    """How many restriction distribution batches exist right now."""
    return len(filter_by(fixtures.list_batches(api), payload_kind="RESTRICTION"))


def test_unsellable_connection_outranks_the_exhausted_ceiling(api, world) -> None:
    """A booking on a suspended connection reports the sellability failure.

    The connection check precedes the capacity check, so a stay booked on a
    suspended connection into a night that is already at its overbooking ceiling
    reports ERR_CONNECTION_NOT_SELLABLE rather than
    ERR_OVERBOOKING_CEILING_EXCEEDED, and nothing is committed.

    Design: Difficulty/priority_pair_validation_conflict/unsellable_connection_beats_overbooking_ceiling_on_booking
    """
    _exhaust_the_nightly_ceiling(api, world)
    suspended = fixtures.suspend_connection(api, world["connection_id"])
    assert_fields(
        suspended,
        {"connection_state": "SUSPENDED", "consecutive_failures": 3},
        entity_name="connection",
    )

    response = api.create_reservation(_ota_booking_payload(world), REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.CONNECTION_NOT_SELLABLE.value, 409)
    assert fixtures.list_reservations(api) == [], "a refused booking must create no reservation"
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(day, allocated=CEILING_UNITS, committed=0, shared=0, pooled_state="EXHAUSTED")


def test_revalidated_connection_lets_the_ceiling_error_surface(api, world) -> None:
    """With the connection sellable again, the capacity check does bite.

    Revalidation returns a suspended connection to DEGRADED, which is sellable,
    so the very same booking now reaches the capacity check and is refused with
    ERR_OVERBOOKING_CEILING_EXCEEDED because the night has no shared pool left.

    Design: Difficulty/priority_pair_validation_conflict/unsellable_connection_beats_overbooking_ceiling_on_booking
    """
    _exhaust_the_nightly_ceiling(api, world)
    fixtures.suspend_connection(api, world["connection_id"])
    revalidated = fixtures.revalidate_connection(api, world["connection_id"])
    assert_fields(
        revalidated,
        {"connection_state": "DEGRADED", "consecutive_failures": 2},
        entity_name="connection",
    )

    response = api.create_reservation(_ota_booking_payload(world), REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.OVERBOOKING_CEILING_EXCEEDED.value, 409)
    assert fixtures.list_reservations(api) == [], "a refused booking must create no reservation"
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(day, allocated=CEILING_UNITS, committed=0, shared=0, pooled_state="EXHAUSTED")


def test_horizon_failure_outranks_the_overlapping_restriction_window(api, world) -> None:
    """A placement both outside the horizon and overlapping reports the horizon.

    The horizon check precedes the uniqueness-and-overlap check, so a minimum
    stay whose range runs past the property's booking horizon and also overlaps
    an existing active window of the same scope reports
    ERR_WINDOW_OUTSIDE_HORIZON, not ERR_RESTRICTION_WINDOW_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/window_outside_horizon_beats_restriction_window_overlap
    """
    fixtures.create_restriction(
        api,
        world["room_type_id"],
        "MIN_STAY",
        fixtures.STAY_DATE,
        "2027-08-20",
        value_nights=2,
    )
    assert _restriction_batches(api) == 1

    # 2027-08-20 sits inside the existing window, and 2027-09-30 is past
    # 2026-08-25 + 365 = 2027-08-25, so both checks are violated at once.
    payload = factories.min_stay_payload(
        room_type_id=world["room_type_id"],
        start_date="2027-08-20",
        end_date="2027-09-30",
        value_nights=3,
    )
    response = api.create_restriction(payload, REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.WINDOW_OUTSIDE_HORIZON.value, 422)
    restrictions = fixtures.list_restrictions(api, room_type_id=world["room_type_id"])
    assert len(restrictions) == 1, "a refused placement must create no restriction"
    assert _restriction_batches(api) == 1, "a refused placement must queue no batch"


def test_restriction_inside_the_horizon_surfaces_the_overlap_error(api, world) -> None:
    """Pulled back inside the horizon, the same placement reports the overlap.

    2027-08-25 is the clock's date plus the property's 365-day horizon and is
    therefore still inside it, so the only surviving violation is the overlap
    with the existing active minimum stay, reported as
    ERR_RESTRICTION_WINDOW_OVERLAP.

    Design: Difficulty/priority_pair_validation_conflict/window_outside_horizon_beats_restriction_window_overlap
    """
    fixtures.create_restriction(
        api,
        world["room_type_id"],
        "MIN_STAY",
        fixtures.STAY_DATE,
        "2027-08-20",
        value_nights=2,
    )

    payload = factories.min_stay_payload(
        room_type_id=world["room_type_id"],
        start_date="2027-08-20",
        end_date=LAST_IN_HORIZON_DATE,
        value_nights=3,
    )
    response = api.create_restriction(payload, REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.RESTRICTION_WINDOW_OVERLAP.value, 409)
    restrictions = fixtures.list_restrictions(api, room_type_id=world["room_type_id"])
    assert len(restrictions) == 1, "a refused placement must create no restriction"
    assert _restriction_batches(api) == 1, "a refused placement must queue no batch"


def test_stop_sell_outranks_the_exhausted_ceiling(api, world) -> None:
    """A stay that is both stop-sold and over capacity reports the stop-sell.

    The sell-restriction check precedes the capacity check, so a night carrying
    an active stop-sell whose shared pool is also empty reports
    ERR_STOP_SELL_ACTIVE rather than ERR_OVERBOOKING_CEILING_EXCEEDED.

    Design: Difficulty/priority_pair_validation_conflict/stop_sell_beats_overbooking_ceiling_on_booking
    """
    _exhaust_the_nightly_ceiling(api, world)
    restriction = fixtures.create_restriction(
        api,
        world["room_type_id"],
        "STOP_SELL",
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    assert_fields(
        restriction,
        {"origin": "MANUAL", "restriction_state": "ACTIVE", "rate_plan_id": None},
        entity_name="restriction",
    )

    response = api.create_reservation(_ota_booking_payload(world), REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.STOP_SELL_ACTIVE.value, 422)
    assert fixtures.list_reservations(api) == [], "a refused booking must create no reservation"
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(day, allocated=CEILING_UNITS, committed=0, shared=0, pooled_state="EXHAUSTED")
    assert _restriction_batches(api) == 1, "the placement queued one batch and the booking none"


def test_lifting_the_stop_sell_lets_the_ceiling_error_surface(api, world) -> None:
    """With the stop-sell lifted, the capacity check does bite.

    A lifted restriction never applies to a booking, so the same stay reaches
    the capacity check and is refused with ERR_OVERBOOKING_CEILING_EXCEEDED
    because the night's shared pool is empty.

    Design: Difficulty/priority_pair_validation_conflict/stop_sell_beats_overbooking_ceiling_on_booking
    """
    _exhaust_the_nightly_ceiling(api, world)
    restriction = fixtures.create_restriction(
        api,
        world["room_type_id"],
        "STOP_SELL",
        fixtures.STAY_DATE,
        fixtures.STAY_DATE,
    )
    lifted = fixtures.lift_restriction(api, restriction["id"])
    assert_fields(
        lifted,
        {"restriction_state": "LIFTED", "lift_reason": "MANUAL_LIFT"},
        entity_name="restriction",
    )
    assert_instant_equals(lifted["lifted_at"], fixtures.FIXTURE_CLOCK, "restriction.lifted_at")
    assert _restriction_batches(api) == 2, "placement and lift each queue one batch"

    response = api.create_reservation(_ota_booking_payload(world), REVENUE_MANAGER_HEADERS)

    validate_error(response, ApiErrorId.OVERBOOKING_CEILING_EXCEEDED.value, 409)
    assert fixtures.list_reservations(api) == [], "a refused booking must create no reservation"
    day = fixtures.inventory_day_on(api, world["room_type_id"], fixtures.STAY_DATE)
    assert_inventory_day(day, allocated=CEILING_UNITS, committed=0, shared=0, pooled_state="EXHAUSTED")
