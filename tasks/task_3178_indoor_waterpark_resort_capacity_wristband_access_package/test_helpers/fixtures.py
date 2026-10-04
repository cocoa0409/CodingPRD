"""Composite setup helpers.

Every helper here builds its preconditions from scratch, because each test runs
against a freshly restarted server with an empty database. Helpers validate
setup calls with ``get_success_data`` so a broken precondition surfaces as a
clear "Setup failed" message rather than as a confusing assertion in the test
body.

Group-owned operations always use ``make_group_headers`` with the real
``GroupBooking`` id, because ``Group`` is the one entity-backed role and the
server compares the caller's ``X-User-ID`` to the group booking it mutates.
Group bookings themselves are created by ``FrontDesk``, which is permitted to
create a group booking on a group's behalf and is not subject to the identity
comparison.
"""
from prd_bench_local_runner.testing import get_success_data

from . import factories as f
from .api_client import api_client
from .constants import DEFAULT_CURRENT_UTC, DEFAULT_SERVICE_DATE, TEST_DEFAULTS
from .test_users import TEST_USERS, make_group_headers
from .test_users import make_group_headers as group_headers_for

PLATFORM_OPS = TEST_USERS["platform_ops_headers"]
FRONT_DESK = TEST_USERS["front_desk_headers"]
AQUATICS_MANAGER = TEST_USERS["aquatics_manager_headers"]
GATE_ATTENDANT = TEST_USERS["gate_attendant_headers"]
ANONYMOUS = TEST_USERS["anonymous_headers"]

# Mirrors the per-resort logical clock the fixtures have advanced (PRD 2.6).
_clock_dates: dict = {}


def _setup(response, label: str) -> dict:
    assert response.status_code < 400, (
        f"Setup failed: {label} returned {response.status_code} — {getattr(response, 'text', '')}"
    )
    return get_success_data(response)


def _setup_data(response, label: str):
    return _setup(response, label)


def _setup_list(response, label: str) -> list:
    data = _setup(response, label)
    assert isinstance(data, list), f"Setup failed: {label} did not return an array"
    return data


# ---------------------------------------------------------------------------
# Primitive builders
# ---------------------------------------------------------------------------


def create_resort(**overrides) -> dict:
    """Create a property. Returns the Resort representation."""
    return _setup_data(
        api_client.create_resort(f.create_resort_payload(**overrides), PLATFORM_OPS),
        "POST /resorts",
    )


def refresh_resort(resort_id: str) -> dict:
    """Read the property back, for a current ``version``."""
    return _setup_data(api_client.get_resort(resort_id, PLATFORM_OPS), "GET /resorts/{id}")


def set_clock(resort_id: str, to_iso8601: str) -> dict:
    """Advance the property's logical clock."""
    _clock_dates[resort_id] = to_iso8601[:10]
    return _setup_data(
        api_client.set_current_utc(resort_id, f.set_clock_payload(to_iso8601), PLATFORM_OPS),
        "POST /_clock/set_current_utc",
    )


def create_room_type(resort_id: str, **overrides) -> dict:
    return _setup_data(
        api_client.create_room_type(resort_id, f.create_room_type_payload(**overrides), PLATFORM_OPS),
        "POST /room-types",
    )


def create_reservation(resort_id: str, room_type_id: str, **overrides) -> dict:
    return _setup_data(
        api_client.create_reservation(
            resort_id, f.create_reservation_payload(room_type_id, **overrides), FRONT_DESK
        ),
        "POST /reservations",
    )


def check_in_reservation(resort_id: str, reservation_id: str) -> dict:
    return _setup_data(
        api_client.check_in_reservation(resort_id, reservation_id, FRONT_DESK),
        "POST /reservations/{id}/check_in",
    )


def create_wristband(resort_id: str, holder_type: str, owner_name: str, **overrides) -> dict:
    payload = f.create_wristband_payload(holder_type, owner_name, **overrides)
    return _setup_data(api_client.create_wristband(resort_id, payload, FRONT_DESK), "POST /wristbands")


def activate_wristband(resort_id: str, wristband_id: str) -> dict:
    return _setup_data(
        api_client.activate_wristband(resort_id, wristband_id, FRONT_DESK),
        "POST /wristbands/{id}/activate",
    )


def create_day_pass(resort_id: str, **overrides) -> dict:
    """Sell a day pass, reading a fresh property version for the OCC field."""
    version = refresh_resort(resort_id)["version"]
    overrides.setdefault("expected_resort_version", version)
    return _setup_data(
        api_client.create_day_pass(resort_id, f.create_day_pass_payload(**overrides), FRONT_DESK),
        "POST /day-passes",
    )


def create_attraction(resort_id: str, **overrides) -> dict:
    return _setup_data(
        api_client.create_attraction(resort_id, f.create_attraction_payload(**overrides), AQUATICS_MANAGER),
        "POST /attractions",
    )


def add_manager(resort_id: str, name: str, role: str = "AquaticsManager") -> dict:
    return _setup_data(
        api_client.add_manager(resort_id, f.create_manager_payload(role, name), PLATFORM_OPS),
        "POST /managers",
    )


def create_shift(resort_id: str, attraction_id: str, staffer_name: str, **overrides) -> dict:
    overrides.setdefault("shift_date", current_service_date(resort_id))
    payload = f.create_lifeguard_shift_payload(attraction_id, staffer_name, **overrides)
    return _setup_data(
        api_client.create_lifeguard_shift(resort_id, payload, AQUATICS_MANAGER), "POST /lifeguard-shifts"
    )


def create_cabana(resort_id: str, **overrides) -> dict:
    return _setup_data(
        api_client.create_cabana(resort_id, f.create_cabana_payload(**overrides), PLATFORM_OPS),
        "POST /cabanas",
    )


def create_group_booking(resort_id: str, **overrides) -> dict:
    """Create a group booking as FrontDesk, which acts on a group's behalf."""
    return _setup_data(
        api_client.create_group_booking(resort_id, f.create_group_booking_payload(**overrides), FRONT_DESK),
        "POST /group-bookings",
    )


def confirm_group_booking(resort_id: str, group_booking_id: str) -> dict:
    return _setup_data(
        api_client.confirm_group_booking(resort_id, group_booking_id, make_group_headers(group_booking_id)),
        "POST /group-bookings/{id}/confirm",
    )


def create_group_member(resort_id: str, group_booking_id: str, member_name: str, **overrides) -> dict:
    payload = f.create_group_member_payload(group_booking_id, member_name, **overrides)
    return _setup_data(
        api_client.create_group_member(resort_id, payload, make_group_headers(group_booking_id)),
        "POST /group-members",
    )


def create_activity_session(resort_id: str, **overrides) -> dict:
    """Create a session under a property that already has an OPEN attraction.

    PRD §3.9 / §2.4: session creation inherits the attraction-readiness check,
    so the PRD precondition for this flow is "the property's attractions must be
    in a state that supports programming".  Without a staffed attraction the
    faithful server correctly answers ERR_ATTRACTION_NOT_OPEN, so the fixture
    opens one first.
    """
    _ensure_open_attraction(resort_id)
    return _setup_data(
        api_client.create_activity_session(
            resort_id, f.create_activity_session_payload(**overrides), PLATFORM_OPS
        ),
        "POST /activities",
    )


def _ensure_open_attraction(resort_id: str) -> None:
    """Post a rostered staffer on a shift so the property has an OPEN attraction.

    The shift is booked short enough to satisfy PRD 3.6's rotation rule
    (duration at most ``rotation_minutes`` plus two hours) and starts on the
    property's current service date.
    """
    if any(
        a.get("resort_id") == resort_id and a.get("attraction_status") == "OPEN"
        for a in _setup_data(
            api_client.list_attractions(resort_id, PLATFORM_OPS), "GET /attractions"
        )
    ):
        return
    staffer = "Session Keeper"
    add_manager(resort_id, staffer)
    attraction = create_attraction(
        resort_id, min_occupancy_units=1, required_certification="NONE"
    )
    shift = create_shift(
        resort_id, attraction["id"], staffer,
        shift_date=current_service_date(resort_id), start_minute=540, end_minute=660,
        rotation_minutes=120,
    )
    _setup_data(
        api_client.start_lifeguard_shift(resort_id, shift["id"], AQUATICS_MANAGER),
        "POST /lifeguard-shifts/{id}/start",
    )


def create_activity_booking(resort_id: str, activity_session_id: str, group_booking_id: str, **overrides) -> dict:
    # PRD 3.9: a booking names "the reservation_id of the folio the charge will
    # settle against", so the fixture always supplies one.
    overrides.setdefault("reservation_id", reservation_for_group(resort_id, group_booking_id))
    payload = f.create_activity_booking_payload(activity_session_id, group_booking_id, **overrides)
    return _setup_data(
        api_client.create_activity_booking(resort_id, payload, make_group_headers(group_booking_id)),
        "POST /activity-bookings",
    )


def reservation_for_group(resort_id: str, group_booking_id: str) -> str:
    """A booking whose stay spans the group's service date."""
    group = _setup_data(
        api_client.get_group_booking(resort_id, group_booking_id, PLATFORM_OPS),
        "GET /group-bookings/{id}",
    )
    room_types = _setup_data(
        api_client.list_room_types(resort_id, PLATFORM_OPS), "GET /room-types"
    )
    room_type = room_types[0] if room_types else create_room_type(resort_id, max_occupancy=8)
    arrival = group["service_date"]
    departure = date_from_service_date_plus_one(arrival)
    reservation = create_reservation(
        resort_id, room_type["id"], guest_count=2,
        arrival_date=arrival, departure_date=departure,
    )
    return reservation["id"]


def date_from_service_date_plus_one(service_date: str) -> str:
    from datetime import date, timedelta

    year, month, day = (int(part) for part in service_date.split("-"))
    return (date(year, month, day) + timedelta(days=1)).isoformat()


def hold_cabana(resort_id: str, cabana_id: str, group_booking_id: str, **overrides) -> dict:
    """Place a hold and return the provisional ``CabanaBooking`` row."""
    version = overrides.pop("expected_cabana_version", None)
    if version is None:
        version = _setup_data(
            api_client.get_cabana(resort_id, cabana_id, PLATFORM_OPS), "GET /cabanas/{id}"
        )["version"]
    payload = f.create_cabana_booking_payload(cabana_id, group_booking_id, version, **overrides)
    rows = _setup_list(
        api_client.create_cabana_booking(resort_id, payload, make_group_headers(group_booking_id)),
        "POST /cabana-bookings",
    )
    assert rows, "Setup failed: cabana hold returned no rows"
    return rows[0]


def confirm_cabana_booking(resort_id: str, cabana_booking_id: str, group_booking_id: str) -> dict:
    return _setup_data(
        api_client.confirm_cabana_booking(
            resort_id, cabana_booking_id, make_group_headers(group_booking_id)
        ),
        "POST /cabana-bookings/{id}/confirm",
    )


def create_water_quality_log(resort_id: str, attraction_id: str, **overrides) -> dict:
    payload = f.create_water_quality_log_payload(attraction_id, **overrides)
    return _setup_data(
        api_client.create_water_quality_log(resort_id, payload, AQUATICS_MANAGER),
        "POST /water-quality-logs",
    )


def current_service_date(resort_id: str) -> str:
    """The property's current logical service date, tracked locally.

    PRD 2.6: the clock starts at 2026-09-01 and only ever moves through the
    test-driving endpoint, so the fixtures' own bookkeeping is exact.
    """
    return _clock_dates.get(resort_id, DEFAULT_SERVICE_DATE)


def get_capacity(resort_id: str, service_date: str) -> dict:
    return _setup_data(
        api_client.get_capacity(resort_id, FRONT_DESK, params={"service_date": service_date}),
        "GET /capacity",
    )


# ---------------------------------------------------------------------------
# Tier 1/2 — hierarchy builders
# ---------------------------------------------------------------------------


def setup_resort_with_room_type(**resort_overrides):
    """Resort plus one sleeping room type. Returns (resort, room_type)."""
    resort = create_resort(**resort_overrides)
    room_type = create_room_type(resort["id"])
    return resort, room_type


def setup_resort_room_booking(guest_count: int = 2, **resort_overrides):
    """Resort + room type + one RESERVED booking. Returns (resort, room_type, reservation)."""
    resort, room_type = setup_resort_with_room_type(**resort_overrides)
    reservation = create_reservation(resort["id"], room_type["id"], guest_count=guest_count)
    return resort, room_type, reservation


# ---------------------------------------------------------------------------
# Tier 3 — lifecycle shortcuts
# ---------------------------------------------------------------------------


def setup_checked_in_reservation(guest_count: int = 2, clock_iso: str = None, **resort_overrides):
    """Resort + room type + booking in IN_HOUSE.

    Returns (resort, room_type, reservation).
    """
    resort, room_type = setup_resort_with_room_type(**resort_overrides)
    if clock_iso:
        set_clock(resort["id"], clock_iso)
    reservation = create_reservation(resort["id"], room_type["id"], guest_count=guest_count)
    reservation = check_in_reservation(resort["id"], reservation["id"])
    return resort, room_type, reservation


def setup_active_guest_band(guest_count: int = 2, owner_name: str = "Ava", clock_iso: str = None,
                            **resort_overrides):
    """Resort + checked-in booking + one ACTIVE RESERVATION_GUEST band.

    Returns (resort, room_type, reservation, wristband).
    """
    resort, room_type, reservation = setup_checked_in_reservation(
        guest_count=guest_count, clock_iso=clock_iso, **resort_overrides
    )
    wristband = create_wristband(
        resort["id"], "RESERVATION_GUEST", owner_name, reservation_id=reservation["id"]
    )
    wristband = activate_wristband(resort["id"], wristband["id"])
    return resort, room_type, reservation, wristband


def setup_issued_guest_band(guest_count: int = 2, owner_name: str = "Ava", **resort_overrides):
    """Resort + checked-in booking + one ISSUED guest band. Returns the same quartet."""
    resort, room_type, reservation = setup_checked_in_reservation(
        guest_count=guest_count, **resort_overrides
    )
    wristband = create_wristband(
        resort["id"], "RESERVATION_GUEST", owner_name, reservation_id=reservation["id"]
    )
    return resort, room_type, reservation, wristband


def setup_day_pass_with_band(units_requested: int = 2, **resort_overrides):
    """Resort + a RESERVED day pass + its ISSUED day-pass band.

    Returns (resort, day_pass, room_type, wristband).
    """
    resort = create_resort(**resort_overrides)
    room_type = create_room_type(resort["id"])
    day_pass = create_day_pass(resort["id"], units_requested=units_requested)
    wristband = create_wristband(
        resort["id"],
        "DAY_PASS_GUEST",
        "Hana",
        day_pass_id=day_pass["id"],
        valid_on_service_date=day_pass["service_date"],
    )
    return resort, day_pass, room_type, wristband


# ---------------------------------------------------------------------------
# Tier 3/5 — group, cabana and activity lifecycles
# ---------------------------------------------------------------------------


def setup_confirmed_group(member_count: int = 2, member_names=("Cleo", "Dev"), **overrides):
    """Resort + a CONFIRMED group booking with its members registered.

    Returns (resort, group_booking, members).
    """
    overrides.setdefault("deposit_paid_cents", member_count * 500)
    resort = create_resort()
    group_booking = create_group_booking(resort["id"], member_count=member_count, **overrides)
    group_booking = confirm_group_booking(resort["id"], group_booking["id"])
    members = [
        create_group_member(resort["id"], group_booking["id"], name) for name in member_names
    ]
    return resort, group_booking, members


def setup_confirmed_group_with_booked_cabana(member_units: int = 2, cabana_units: int = 4,
                                             start_minute: int = 600, end_minute: int = 720,
                                             cabana_kind: str = "CABANA",
                                             cabana_label: str = "CAB-5", **overrides):
    """Resort + CONFIRMED group + a cabana occupied through confirm.

    Returns (resort, group_booking, members, cabana, cabana_booking).
    """
    resort, group_booking, members = setup_confirmed_group(**overrides)
    cabana = create_cabana(
        resort["id"], capacity_units=cabana_units, cabana_kind=cabana_kind,
        cabana_label=cabana_label,
    )
    hold = hold_cabana(
        resort["id"], cabana["id"], group_booking["id"],
        member_units=member_units, start_minute=start_minute, end_minute=end_minute,
    )
    hold = confirm_cabana_booking(resort["id"], hold["id"], group_booking["id"])
    return resort, group_booking, members, cabana, hold


def setup_confirmed_group_with_activity(session_overrides=None, attendees: int = 2, **overrides):
    """Resort + CONFIRMED group + an activity booking on a session.

    Returns (resort, group_booking, session, activity_booking).
    """
    resort, group_booking, _members = setup_confirmed_group(**overrides)
    session = create_activity_session(resort["id"], **(session_overrides or {}))
    booking = create_activity_booking(
        resort["id"], session["id"], group_booking["id"], attendees=attendees
    )
    return resort, group_booking, session, booking


# ---------------------------------------------------------------------------
# Tier 4 — accumulation / threshold targeting
# ---------------------------------------------------------------------------


def setup_resort_at_clock(clock_iso: str = "2026-09-03T08:00:00Z", **resort_overrides) -> dict:
    """Resort whose logical clock has been advanced to ``clock_iso``."""
    resort = create_resort(**resort_overrides)
    set_clock(resort["id"], clock_iso)
    return resort


def setup_attraction_with_completed_shift(shift_date: str = "2026-09-03", start_minute: int = 540,
                                          end_minute: int = 660, rotation_minutes: int = 60,
                                          staffer_name: str = "Iris", min_occupancy_units: int = 1,
                                          required_certification: str = "NONE", **resort_overrides):
    """Resort + rostered staffer + attraction + a COMPLETED shift for that staffer.

    Returns (resort, attraction, shift).
    """
    resort = create_resort(**resort_overrides)
    add_manager(resort["id"], staffer_name)
    attraction = create_attraction(
        resort["id"], min_occupancy_units=min_occupancy_units,
        required_certification=required_certification,
    )
    shift = create_shift(
        resort["id"], attraction["id"], staffer_name,
        shift_date=shift_date, start_minute=start_minute, end_minute=end_minute,
        rotation_minutes=rotation_minutes,
    )
    shift = _setup_data(
        api_client.start_lifeguard_shift(resort["id"], shift["id"], AQUATICS_MANAGER),
        "POST /lifeguard-shifts/{id}/start",
    )
    shift = _setup_data(
        api_client.complete_lifeguard_shift(resort["id"], shift["id"], AQUATICS_MANAGER),
        "POST /lifeguard-shifts/{id}/complete",
    )
    return resort, attraction, shift


def setup_occupancy_filled(park_capacity: int, booking_units: int, day_pass_units: int,
                           service_date: str = "2026-09-03", day_pass_cap_units: int = 20,
                           clock_iso: str = "2026-09-03T08:00:00Z"):
    """Resort whose room and day-pass contributions exactly fill ``park_capacity``.

    Returns (resort, reservation, day_pass, room_type).
    """
    resort = create_resort(
        park_capacity_occupancy_units=park_capacity,
        # PRD 2.5 keeps day_pass_cap_units at or below the park ceiling.
        day_pass_cap_units=min(day_pass_cap_units, park_capacity),
    )
    set_clock(resort["id"], clock_iso)
    room_type = create_room_type(resort["id"], max_occupancy=8)
    reservation = create_reservation(
        resort["id"], room_type["id"], guest_count=booking_units,
        arrival_date=service_date, departure_date="2026-09-05",
    )
    day_pass = create_day_pass(
        resort["id"], service_date=service_date, units_requested=day_pass_units
    )
    return resort, reservation, day_pass, room_type


# ---------------------------------------------------------------------------
# Tier 5 — terminal / closure states
# ---------------------------------------------------------------------------


def setup_pool_closure_with_active_band(**resort_overrides):
    """Resort + attraction + checked-in booking + ACTIVE band + a standing FAIL reading.

    Returns (resort, attraction, reservation, wristband).
    """
    resort = create_resort(**resort_overrides)
    set_clock(resort["id"], "2026-09-03T10:00:00Z")
    attraction = create_attraction(resort["id"], required_certification="NONE")
    room_type = create_room_type(resort["id"])
    reservation = create_reservation(resort["id"], room_type["id"], guest_count=2)
    reservation = check_in_reservation(resort["id"], reservation["id"])
    wristband = create_wristband(
        resort["id"], "RESERVATION_GUEST", "Eve", reservation_id=reservation["id"]
    )
    wristband = activate_wristband(resort["id"], wristband["id"])
    # A succeeded grant is what the closure cascade has to decline.
    _setup_data(
        api_client.post_arcade_grant(
            resort["id"], wristband["id"], f.create_arcade_grant_payload(500), ANONYMOUS
        ),
        "POST /wristbands/{id}/arcade-grants",
    )
    create_water_quality_log(
        resort["id"], attraction["id"], sampled_at="2026-09-03T11:00:00Z", ph_reading=6.1
    )
    return resort, attraction, reservation, wristband


def setup_attraction_with_staffer(required_certification: str = "NONE", min_occupancy_units: int = 2,
                                  staffer_name: str = "Dana", shift_date: str = "2026-09-03",
                                  start_minute: int = 540, end_minute: int = 660,
                                  rotation_minutes: int = 120, **resort_overrides):
    """Resort + rostered staffer + attraction + a SCHEDULED shift.

    Returns (resort, attraction, shift).
    """
    resort = create_resort(**resort_overrides)
    add_manager(resort["id"], staffer_name)
    attraction = create_attraction(
        resort["id"], min_occupancy_units=min_occupancy_units,
        required_certification=required_certification,
    )
    shift = create_shift(
        resort["id"], attraction["id"], staffer_name,
        shift_date=shift_date, start_minute=start_minute, end_minute=end_minute,
        rotation_minutes=rotation_minutes,
    )
    return resort, attraction, shift