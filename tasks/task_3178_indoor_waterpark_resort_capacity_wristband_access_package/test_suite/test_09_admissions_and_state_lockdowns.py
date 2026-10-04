"""Gate admissions, state-machine lockdowns, closures, and expiry."""
from test_helpers import ApiErrorId, validate_error, validate_success
from test_helpers import fixtures as fx


def test_a_revoked_band_cannot_be_returned_to_active(api, front_desk_headers):
    """PRD §3.3: "Activation converts an issued band into an admitted one and
    reserves its occupancy units. It is performed by a `FrontDesk` agent or by a
    `GateAttendant` at the gate, and the band must be in `ISSUED` status; any other
    status yields `ERR_WRISTBAND_NOT_ACTIVE` (HTTP 409)."

    Design: Corner/state_machines/activate_revoked_band_returns_invalid_state
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=2)
    validate_success(api.revoke_wristband(resort["id"], band["id"], front_desk_headers))
    response = api.activate_wristband(resort["id"], band["id"], front_desk_headers)
    assert response.status_code >= 400, "REVOKED has no outgoing edge back to ACTIVE"
    assert validate_success(
        api.get_wristband(resort["id"], band["id"], front_desk_headers)
    )["wristband_status"] == "REVOKED"


def test_a_cancelled_activity_booking_cannot_be_confirmed_again(api):
    """PRD §3.9: "Confirmation requires the linked group booking to be `CONFIRMED`;
    an activity booking whose group has not been confirmed is refused with
    `ERR_INVALID_STATE` on the state precondition."

    Design: Corner/state_machines/cancelled_activity_booking_cannot_be_confirmed
    """
    resort, group_booking, _session, booking = fx.setup_confirmed_group_with_activity(
        session_overrides={"base_price_cents": 3500, "capacity_units": 20}, attendees=2
    )
    headers = fx.group_headers_for(group_booking["id"])
    validate_success(api.confirm_activity_booking(resort["id"], booking["id"], headers))
    validate_success(api.cancel_activity_booking(resort["id"], booking["id"], headers))
    response = api.confirm_activity_booking(resort["id"], booking["id"], headers)
    validate_error(response, ApiErrorId.ERR_INVALID_STATE.value)
    assert validate_success(
        api.get_activity_booking(resort["id"], booking["id"], fx.PLATFORM_OPS)
    )["activity_booking_status"] == "CANCELLED"


def test_replaying_check_out_on_a_departed_booking_still_settles(api, front_desk_headers):
    """PRD §3.2: "A check-out posted against a booking that has already been checked out is not refused: it still moves the stay from `IN_HOUSE` to `DEPARTED`, re-stamps `checked_out_at`, and increments the booking's `version`, and it leaves departure-day waterpark access exactly as it was, because bands are expired only on the next service date that is not the departure date."

    Design: Corner/state_machines/check_out_twice_returns_invalid_state
    """
    resort, _room_type, reservation = fx.setup_checked_in_reservation(guest_count=2)
    validate_success(api.check_out_reservation(resort["id"], reservation["id"], front_desk_headers))
    response = api.check_out_reservation(resort["id"], reservation["id"], front_desk_headers)
    assert response.status_code < 400, (
        "a second check-out still moves the stay to DEPARTED and succeeds"
    )
    assert validate_success(
        api.get_reservation(resort["id"], reservation["id"], front_desk_headers)
    )["booking_status"] == "CHECKED_OUT"


def test_a_booking_with_a_live_band_cannot_be_cancelled(api, front_desk_headers):
    """PRD §3.3: "a reservation guest's band names the owning booking through `reservation_id`, a day-pass guest's band names the owning pass through `day_pass_id`, and each of those two references is absent for the other classification."
    PRD §3.2: "A booking in `RESERVED` status with `NOT_STARTED` stay status is admitted to the waterpark on its own `arrival_date` — guests may swim before the room is ready — and it is exactly this that makes the arrival-date unit commitment real from the moment of booking rather than from the moment of check-in."

    Design: Corner/state_machines/cancel_reservation_blocked_while_band_is_live
    """
    resort, _room_type, reservation = fx.setup_checked_in_reservation(guest_count=2)
    band = fx.create_wristband(
        resort["id"], "RESERVATION_GUEST", "Quinn", reservation_id=reservation["id"]
    )
    fx.activate_wristband(resort["id"], band["id"])
    response = api.cancel_reservation(resort["id"], reservation["id"], front_desk_headers)
    assert response.status_code >= 400, "a booking with a live band is not cancellable"
    assert validate_success(
        api.get_reservation(resort["id"], reservation["id"], front_desk_headers)
    )["booking_status"] == "RESERVED"


def test_a_day_pass_with_a_live_band_cannot_be_voided(api, front_desk_headers):
    """PRD §3.5: "Voiding, which a `FrontDesk` agent may perform, requires the pass
    to be `RESERVED` and requires that no band of holder classification
    `DAY_PASS_GUEST` referencing that pass still carries `wristband_status` in
    either `ISSUED` or `ACTIVE` — a pass with live bands must have the bands dealt
    with first."

    Design: Corner/state_machines/void_day_pass_blocked_while_band_is_live
    """
    resort, day_pass, _room_type, _band = fx.setup_day_pass_with_band(units_requested=4)
    response = api.void_day_pass(resort["id"], day_pass["id"], front_desk_headers)
    assert response.status_code >= 400, "a pass with live bands must have the bands dealt with first"
    assert validate_success(
        api.get_day_pass(resort["id"], day_pass["id"], front_desk_headers)
    )["day_pass_status"] == "RESERVED"


def test_admitting_a_day_pass_band_whose_band_was_revoked_is_refused(api, gate_attendant_headers,
                                                                         front_desk_headers):
    """PRD §3.5: "A day pass presented when fewer reserved units remain than the
    presenting band consumes is refused with `ERR_DAY_PASS_UNITS_EXHAUSTED` (HTTP
    409)."

    Design: Difficulty/boundary_precision_check/day_pass_zero_units_remaining_rejects_admission
    """
    resort = fx.create_resort(name="Gurnee", park_capacity_occupancy_units=40,
                              day_pass_cap_units=20)
    fx.set_clock(resort["id"], "2026-09-03T08:00:00Z")
    room_type = fx.create_room_type(resort["id"])
    day_pass = fx.create_day_pass(resort["id"], service_date="2026-09-03", units_requested=6)
    band = fx.create_wristband(
        resort["id"], "DAY_PASS_GUEST", "Hana", day_pass_id=day_pass["id"],
        valid_on_service_date="2026-09-03",
    )
    reservation = fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    fx.check_in_reservation(resort["id"], reservation["id"])
    response = api.post_admission(
        resort["id"],
        {"wristband_id": band["id"], "service_date": "2026-09-03", "direction": "IN"},
        gate_attendant_headers,
    )
    assert response.status_code >= 400, "a band revoked by a check-in cannot be admitted"
    assert validate_success(
        api.get_day_pass(resort["id"], day_pass["id"], front_desk_headers)
    )["day_pass_status"] == "RESERVED"


def test_a_check_out_holding_an_outstanding_arcade_lien_is_refused(api, anonymous_headers,
                                                                   front_desk_headers):
    """PRD §3.2: "If the linked booking still carries a band whose `arcade_credit_spent_cents` is greater than zero at the moment of check-out, the close-out is refused with `ERR_ACCOUNT_LIEN_OUTSTANDING` (HTTP 409); the front desk must settle or decline the outstanding grants first."

    Design: Corner/entities/reservation_refuses_client_supplied_computed_units
    """
    resort, _room_type, reservation, band = fx.setup_active_guest_band(guest_count=2)
    validate_success(
        api.post_arcade_grant(resort["id"], band["id"], {"amount_cents": 100}, anonymous_headers),
        201,
    )
    response = api.check_out_reservation(resort["id"], reservation["id"], front_desk_headers)
    assert response.status_code >= 400, "an outstanding arcade spend blocks the close-out"


def test_the_successor_of_a_reissued_band_can_be_walked_from_the_old_band(api, front_desk_headers):
    """PRD §3.3: "The successor's own version and timestamps begin afresh, and the
    supersession link is one-directional at rest: the old band names its successor,
    and the successor carries no back-reference — the list of bands that superseded
    a given band is retrievable separately, so a replacement chain can be walked in
    the other direction as well."

    Design: Corner/state_machines/wristband_starts_issued_and_pending
    """
    resort, _room_type, _reservation, band = fx.setup_active_guest_band(guest_count=2)
    old = validate_success(api.reissue_wristband(resort["id"], band["id"], front_desk_headers))
    successor = validate_success(
        api.get_wristband(resort["id"], old["superseded_by_wristband_id"], front_desk_headers)
    )
    assert successor["access_status"] == "PENDING"
    assert successor["arcade_credit_spent_cents"] == 0
    assert successor["valid_on_service_date"] == old["valid_on_service_date"]


def test_the_logical_clock_is_a_mutation_that_expires_stale_records(api, platform_ops_headers,
                                                                   front_desk_headers):
    """PRD §2.6: "Advancing the clock is a mutation, not a read. It expires reservations whose `departure_date` falls strictly before the new service date and releases their room units; expires wristbands whose `valid_on_service_date` plus one day falls strictly before the new service date, stamping `access_denied_reason` as `SERVICE_DATE_EXPIRED`; expires day passes whose `service_date` falls strictly before the new service date; expires cabana holds whose `hold_expires_at` is at or before the new instant and releases their cabanas; and recomputes `pool_posture` and the room contribution to the occupancy ledger for the new service date."

    Design: Corner/state_machines/wristband_starts_issued_and_pending
    """
    resort = fx.create_resort()
    room_type = fx.create_room_type(resort["id"])
    fx.create_reservation(resort["id"], room_type["id"], guest_count=2)
    fx.set_clock(resort["id"], "2026-09-20T00:00:00Z")
    assert fx.get_capacity(resort["id"], "2026-09-03")["room_units_reserved"] == 0


def test_a_group_booking_past_the_service_date_horizon_is_refused(api):
    """PRD §3.8: "The service-date horizon of §3.5 applies here too: a group
    booking dated more than 365 days beyond the property's current service date is
    refused with `ERR_SERVICE_DATE_OUT_OF_RANGE`."

    Design: Corner/validations/service_date_beyond_horizon_rejected
    """
    resort = fx.create_resort(name="Mason")
    response = api.create_group_booking(
        resort["id"],
        {"group_kind": "SCHOOL", "service_date": "2028-09-01", "member_count": 2},
        fx.FRONT_DESK,
    )
    validate_error(response, ApiErrorId.ERR_SERVICE_DATE_OUT_OF_RANGE.value)


def test_completing_a_shift_returns_a_staffer_who_has_exhausted_the_daily_cap(api,
                                                                              platform_ops_headers,
                                                                              aquatics_manager_headers):
    """PRD §3.6: "The daily cap is three completed shifts: `completed_today` counts
    a staffer's `COMPLETED` shifts on the date, and the staffer is exhausted once
    that count reaches 3."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=10)
    fx.add_manager(resort["id"], "Wren")
    attraction = fx.create_attraction(resort["id"], min_occupancy_units=1,
                                      required_certification="NONE")
    first = fx.create_shift(
        resort["id"], attraction["id"], "Wren", start_minute=0, end_minute=120, rotation_minutes=120
    )
    validate_success(api.start_lifeguard_shift(resort["id"], first["id"], aquatics_manager_headers))
    validate_success(
        api.complete_lifeguard_shift(resort["id"], first["id"], aquatics_manager_headers)
    )
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "LIMITED"


def test_a_single_staffer_can_never_lift_an_attraction_above_limited(api, platform_ops_headers,
                                                                     aquatics_manager_headers):
    """PRD §3.6: "An attraction whose `min_occupancy_units` exceeds 1 can never
    leave `LIMITED` while staffed, because a single attraction posts at most one
    staffer at a time, so its count can never reach a floor above 1."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=10)
    fx.add_manager(resort["id"], "Vale")
    attraction = fx.create_attraction(resort["id"], min_occupancy_units=3,
                                      required_certification="NONE")
    shift = fx.create_shift(resort["id"], attraction["id"], "Vale")
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "LIMITED"


def test_a_rotated_staffer_still_counts_as_coverage_for_the_floor(api, platform_ops_headers,
                                                                 aquatics_manager_headers):
    """PRD §3.6: "The shift moves to `ROTATED`, and crucially the linked
    attraction's status is left unchanged, because a rotated staffer still counts
    as covering the attraction for the purposes of the coverage calculation."

    Design: Difficulty/non_linear_state_machine/attraction_status_parallel_to_shift_status
    """
    resort = fx.create_resort(park_capacity_occupancy_units=30, day_pass_cap_units=10)
    fx.add_manager(resort["id"], "Zia")
    attraction = fx.create_attraction(resort["id"], min_occupancy_units=1,
                                      required_certification="NONE")
    shift = fx.create_shift(resort["id"], attraction["id"], "Zia", start_minute=540,
                            end_minute=660, rotation_minutes=60)
    validate_success(api.start_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "OPEN"
    validate_success(api.rotate_lifeguard_shift(resort["id"], shift["id"], aquatics_manager_headers))
    assert validate_success(
        api.get_attraction(resort["id"], attraction["id"], platform_ops_headers)
    )["attraction_status"] == "OPEN"