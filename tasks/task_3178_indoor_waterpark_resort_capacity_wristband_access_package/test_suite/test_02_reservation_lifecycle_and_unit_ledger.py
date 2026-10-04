"""Room-package lifecycle, the room contribution to the ledger, and derived reads."""
import pytest

from test_helpers import ApiErrorId, assert_reservation, validate_error, validate_success
from test_helpers import fixtures as fx


def test_issued_reservation_band_starts_pending_with_room_charge_enabled(api):
    """PRD §3.3: "A newly issued band starts in `ISSUED` wristband status with `PENDING` access status, and its `valid_on_service_date` defaults to the holder's own operative date — the linked reservation's `arrival_date` for a reservation guest, or the linked day pass's `service_date` for a day-pass guest — unless the caller supplies `valid_on_service_date` explicitly."
    PRD §3.3: "When `holder_type` is `RESERVATION_GUEST` *and* the linked booking's
    `stay_status` is already `IN_HOUSE`, the band is issued with
    `room_charge_enabled` true and `arcade_credit_limit_cents` equal to the
    property's `arcade_credit_rate_cents_per_unit` multiplied by the linked
    booking's `waterpark_included_units`."

    Design: Corner/state_machines/wristband_starts_issued_and_pending
    """
    resort, _room_type, _reservation, wristband = fx.setup_issued_guest_band(guest_count=2)
    assert wristband["wristband_status"] == "ISSUED"
    assert wristband["access_status"] == "PENDING"
    assert wristband["room_charge_enabled"] is True
    assert wristband["arcade_credit_limit_cents"] == 500


def test_activating_an_issued_band_grants_access_without_double_counting_units(api, front_desk_headers):
    """PRD §3.3: "A successful activation moves the band to `ACTIVE` with
    `access_status` `GRANTED`, recomputes the room contribution for the band's
    `valid_on_service_date`, recomputes `pool_posture` from the property's current
    non-terminal water readings, and increments the band's `version`."
    PRD §3.2: "Each reservation's `reserved_units` equals its
    `waterpark_included_units` on every service date in the half-open span from
    `arrival_date` inclusive to `departure_date` exclusive."

    Design: Corner/state_machines/activate_issued_band_grants_access_and_reserves_units
    """
    resort, _room_type, _reservation, wristband = fx.setup_issued_guest_band(
        guest_count=2, clock_iso="2026-09-03T08:00:00Z"
    )
    activated = validate_success(
        api.activate_wristband(resort["id"], wristband["id"], front_desk_headers)
    )
    assert activated["wristband_status"] == "ACTIVE"
    assert activated["access_status"] == "GRANTED"
    ledger = fx.get_capacity(resort["id"], "2026-09-03")
    assert ledger["room_units_reserved"] == 2, "the party is counted once, not once per band"


def test_two_night_booking_contributes_to_arrival_and_middle_dates_only(api):
    """PRD §3.2: "Each reservation's `reserved_units` equals its
    `waterpark_included_units` on every service date in the half-open span from
    `arrival_date` inclusive to `departure_date` exclusive."

    Design: Corner/calculations/room_units_reserved_span_is_checkout_exclusive
    """
    resort, room_type = fx.setup_resort_with_room_type(park_capacity_occupancy_units=40)
    fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    departure_ledger = fx.get_capacity(resort["id"], "2026-09-05")
    assert departure_ledger["room_units_reserved"] == 0
    assert departure_ledger["occupancy_units"] == 0
    assert fx.get_capacity(resort["id"], "2026-09-04")["room_units_reserved"] == 4


def test_a_cancelled_booking_consumes_zero_units_on_every_date(api, front_desk_headers):
    """PRD §3.2: "A booking that has been cancelled consumes zero units on every
    date; a booking that has been checked out consumes zero units on its
    `departure_date`."

    Design: Corner/calculations/room_units_reserved_span_is_checkout_exclusive
    """
    resort, room_type = fx.setup_resort_with_room_type(park_capacity_occupancy_units=40)
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    validate_success(
        api.cancel_reservation(resort["id"], reservation["id"], front_desk_headers)
    )
    assert fx.get_capacity(resort["id"], "2026-09-03")["room_units_reserved"] == 0
    assert fx.get_capacity(resort["id"], "2026-09-04")["room_units_reserved"] == 0


def test_check_out_zeroes_the_departure_date_contribution(api, front_desk_headers):
    """PRD §3.2: "A booking that has been cancelled consumes zero units on every
    date; a booking that has been checked out consumes zero units on its
    `departure_date`."

    Design: Corner/cross_cutting_complexity_layers/check_out_stops_counting_departure_date_units
    """
    resort, _room_type, reservation = fx.setup_checked_in_reservation(guest_count=4)
    checked_out = validate_success(
        api.check_out_reservation(resort["id"], reservation["id"], front_desk_headers)
    )
    assert checked_out["booking_status"] == "CHECKED_OUT"
    assert fx.get_capacity(resort["id"], "2026-09-05")["room_units_reserved"] == 0
    assert fx.get_capacity(resort["id"], "2026-09-04")["room_units_reserved"] == 4


def test_check_in_accrues_arcade_credit_as_rate_times_included_units(api):
    """PRD §3.2: "`credited_arcade_cents` is computed as an accrual: the property's
    `arcade_credit_rate_cents_per_unit` multiplied by the booking's
    `waterpark_included_units`, rounded half up to whole cents."

    Design: Corner/calculations/arcade_credit_accrual_matches_rate_times_included_units
    """
    resort = fx.create_resort(arcade_credit_rate_cents_per_unit=300)
    room_type = fx.create_room_type(resort["id"])
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=3)
    checked_in = fx.check_in_reservation(resort["id"], reservation["id"])
    assert checked_in["credited_arcade_cents"] == 900
    assert_reservation(checked_in)


def test_at_par_party_draws_no_room_fee_surcharge(api):
    """PRD §3.1: "When `waterpark_included_units` is at most the room type's
    `max_occupancy` minus 2, the party is at or below par and the surcharge is
    zero."
    PRD §3.1: "The two fields therefore differ by exactly the surcharge, and they
    coincide only when the party is at or below par — that is, only when
    `waterpark_included_units` is at most `max_occupancy` minus 2."

    Design: Corner/calculations/package_rate_applies_pinned_constants
    """
    resort, room_type = fx.setup_resort_with_room_type()
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=4)
    assert reservation["package_rate_total_cents"] == 113400
    assert reservation["package_rate_withheld_cents"] == 113400


def test_room_type_and_attraction_reads_carry_no_version_field(api, front_desk_headers):
    """PRD §2.7: "Those five resources have no `updated_at` field and no `version`
    field at all, and clients must not expect either to appear in their
    representations."

    Design: Corner/entities/room_type_rejects_update_and_carries_no_version
    """
    resort, room_type = fx.setup_resort_with_room_type()
    fetched = validate_success(
        api.get_room_type(resort["id"], room_type["id"], front_desk_headers)
    )
    assert "version" not in fetched
    assert "updated_at" not in fetched
    assert fetched["code"] == "WOLF"
    attraction = fx.create_attraction(resort["id"])
    fetched_attraction = validate_success(
        api.get_attraction(resort["id"], attraction["id"], front_desk_headers)
    )
    assert "version" not in fetched_attraction
    assert "updated_at" not in fetched_attraction


def test_client_supplied_computed_unit_fields_are_refused(api, front_desk_headers):
    """PRD §3.1: "A payload that omits a required field, that declares a field the
    booking operation does not accept, or that carries a `guest_count` outside its
    bounds is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/reservation_refuses_client_supplied_computed_units
    """
    resort, room_type = fx.setup_resort_with_room_type()
    response = api.create_reservation(
        resort["id"],
        {
            "room_type_id": room_type["id"],
            "guest_count": 3,
            "arrival_date": "2026-09-03",
            "departure_date": "2026-09-05",
            "reserved_units": 99,
        },
        front_desk_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)
    rows = validate_success(api.list_reservations(resort["id"], front_desk_headers))
    assert rows == [], "the refused booking must not have been created"


def test_omitting_the_party_size_is_refused(api, front_desk_headers):
    """PRD §3.1: "A payload that omits a required field, that declares a field the
    booking operation does not accept, or that carries a `guest_count` outside its
    bounds is refused with `ERR_INVALID_REQUEST` (HTTP 400)."

    Design: Corner/entities/reservation_missing_guest_count_rejected
    """
    resort, room_type = fx.setup_resort_with_room_type()
    response = api.create_reservation(
        resort["id"],
        {
            "room_type_id": room_type["id"],
            "arrival_date": "2026-09-03",
            "departure_date": "2026-09-05",
        },
        front_desk_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)


@pytest.mark.parametrize("bad_holder", ["STAFF", "GUEST", "RESERVATION"])
def test_wristband_holder_classification_is_closed(api, front_desk_headers, bad_holder):
    """PRD §3.3: "The holder classification is one of `RESERVATION_GUEST`, `DAY_PASS_GUEST`, or `GROUP_MEMBER`; a reservation guest's band names the owning booking through `reservation_id`, a day-pass guest's band names the owning pass through `day_pass_id`, and each of those two references is absent for the other classification."

    Design: Corner/entities/wristband_refuses_staff_holder_type
    """
    resort, _room_type, reservation = fx.setup_checked_in_reservation(guest_count=2)
    response = api.create_wristband(
        resort["id"],
        {"holder_type": bad_holder, "owner_name": "Uma"},
        front_desk_headers,
    )
    validate_error(response, ApiErrorId.ERR_INVALID_REQUEST.value)