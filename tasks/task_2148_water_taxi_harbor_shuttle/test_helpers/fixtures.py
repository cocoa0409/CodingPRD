"""Composite setup helpers.

Most interesting claims in this PRD need a harbor that already exists: two docks
with fare-zone stops, a vessel with a current annual inspection, a licensed
master, an operating day with its weather observations, and a logical clock
parked somewhere sensible. `setup_harbor_world` builds exactly that in one call
and every later helper threads its ids through.
"""

from prd_bench_local_runner.testing import get_success_data

from .api_client import api_client
from .constants import TEST_DEFAULTS
from .factories import (
    approve_claim_payload,
    board_payload,
    clock_payload,
    confirm_payload,
    create_booking_payload,
    create_crew_member_payload,
    create_dock_payload,
    create_dock_slot_payload,
    create_inspection_payload,
    create_interruption_payload,
    create_ride_pass_payload,
    create_service_day_payload,
    create_stop_payload,
    create_trip_payload,
    create_vessel_payload,
    refund_pass_payload,
)
from .test_users import (
    TEST_USERS,
    make_rider_headers,
    make_vessel_master_headers,
)

ADMIN = TEST_USERS["harbor_admin_headers"]
DISPATCHER = TEST_USERS["dispatcher_headers"]
INSPECTOR = TEST_USERS["marine_inspector_headers"]
AUDITOR = TEST_USERS["fare_auditor_headers"]


# --- Tier 1: the standing harbor estate -----------------------------------

def set_clock(to_iso8601: str) -> dict:
    """Move the logical harbor clock."""
    return get_success_data(api_client.set_clock(clock_payload(to_iso8601), ADMIN))


def setup_harbor_world(
    dock_a=None,
    stop1=None,
    dock_b=None,
    stop2=None,
    vessel=None,
    crew=None,
    annual_inspection=True,
    inspection=None,
    service_day=None,
    clock=TEST_DEFAULTS["CLOCK_UTC"],
    extra_stops_on_dock_b=None,
):
    """Build the standing harbor estate plus one operating day.

    Creates 'Pier One' (dock A) carrying the zone-1 stop 'Ferry Landing',
    'Pier Two' (dock B) carrying the zone-2 stop 'Quay Two', a vessel, a master,
    optionally a passing ANNUAL inspection, one operating day, and finally moves
    the logical clock.

    Every argument accepts a dict of payload overrides. Returns a dict of the
    created rows and their ids.
    """
    world = {}

    dock_a_row = get_success_data(
        api_client.create_dock(create_dock_payload(**(dock_a or {})), ADMIN)
    )
    world["dock_a"] = dock_a_row
    world["dock_a_id"] = dock_a_row["id"]

    stop1_row = get_success_data(
        api_client.create_stop(dock_a_row["id"],
                               create_stop_payload(**(stop1 or {})), ADMIN)
    )
    world["stop1"] = stop1_row
    world["stop1_id"] = stop1_row["id"]

    dock_b_defaults = {
        "name": "Pier Two",
        "berth_count": 1,
        "min_turnaround_minutes": 0,
        "landing_fee_per_pax_cents": 200,
        "berth_minute_rate_cents": 60,
        "monthly_fee_cap_cents": 1_000_000,
    }
    dock_b_defaults.update(dock_b or {})
    dock_b_row = get_success_data(
        api_client.create_dock(create_dock_payload(**dock_b_defaults), ADMIN)
    )
    world["dock_b"] = dock_b_row
    world["dock_b_id"] = dock_b_row["id"]

    stop2_defaults = {"name": "Quay Two", "zone_index": 2, "charted_depth_m": 4.00}
    stop2_defaults.update(stop2 or {})
    stop2_row = get_success_data(
        api_client.create_stop(dock_b_row["id"],
                               create_stop_payload(**stop2_defaults), ADMIN)
    )
    world["stop2"] = stop2_row
    world["stop2_id"] = stop2_row["id"]

    world["extra_stops"] = []
    for extra in (extra_stops_on_dock_b or []):
        row = get_success_data(
            api_client.create_stop(dock_b_row["id"], create_stop_payload(**extra), ADMIN)
        )
        world["extra_stops"].append(row)

    vessel_row = get_success_data(
        api_client.create_vessel(create_vessel_payload(**(vessel or {})), ADMIN)
    )
    world["vessel"] = vessel_row
    world["vessel_id"] = vessel_row["id"]

    crew_row = get_success_data(
        api_client.create_crew_member(create_crew_member_payload(**(crew or {})), ADMIN)
    )
    world["crew"] = crew_row
    world["crew_id"] = crew_row["id"]
    world["master_headers"] = make_vessel_master_headers(crew_row["id"])

    if annual_inspection:
        world["annual_inspection"] = get_success_data(
            api_client.create_inspection(
                vessel_row["id"], create_inspection_payload(**(inspection or {})),
                INSPECTOR,
            )
        )

    day_row = get_success_data(
        api_client.create_service_day(create_service_day_payload(**(service_day or {})),
                                      ADMIN)
    )
    world["day"] = day_row
    world["day_id"] = day_row["id"]

    if clock:
        set_clock(clock)

    return world


def add_service_day(**overrides) -> dict:
    """Open one more operating day in an existing world."""
    return get_success_data(
        api_client.create_service_day(create_service_day_payload(**overrides), ADMIN)
    )


def add_vessel(**overrides) -> dict:
    return get_success_data(
        api_client.create_vessel(create_vessel_payload(**overrides), ADMIN)
    )


def add_crew_member(**overrides) -> dict:
    return get_success_data(
        api_client.create_crew_member(create_crew_member_payload(**overrides), ADMIN)
    )


def add_dock(**overrides) -> dict:
    return get_success_data(api_client.create_dock(create_dock_payload(**overrides), ADMIN))


def add_stop(dock_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_stop(dock_id, create_stop_payload(**overrides), ADMIN)
    )


def file_inspection(vessel_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_inspection(vessel_id, create_inspection_payload(**overrides),
                                     INSPECTOR)
    )


# --- Tier 2: sailings, berths, bookings ------------------------------------

def create_trip(world, origin_stop_id=None, destination_stop_id=None,
                vessel_id=None, master_crew_id=None, service_day_id=None,
                **overrides) -> dict:
    """Plan one sailing in the given world. Overrides carry the timetable."""
    payload = create_trip_payload(
        service_day_id or world["day_id"],
        vessel_id or world["vessel_id"],
        master_crew_id or world["crew_id"],
        origin_stop_id or world["stop1_id"],
        destination_stop_id or world["stop2_id"],
        **overrides,
    )
    return get_success_data(api_client.create_trip(payload, DISPATCHER))


def current_dock_version(dock_id) -> int:
    return get_success_data(api_client.get_dock(dock_id, DISPATCHER))["version"]


def current_trip_version(trip_id) -> int:
    return get_success_data(api_client.get_trip(trip_id, DISPATCHER))["version"]


def reserve_dock_slot(trip_id, dock_id, start_utc, end_utc, purpose="LANDING",
                      expected_dock_version=None) -> dict:
    """Reserve a berth window, reading the dock's live version unless one is given."""
    version = (expected_dock_version if expected_dock_version is not None
               else current_dock_version(dock_id))
    payload = create_dock_slot_payload(dock_id, version, purpose=purpose,
                                       start_utc=start_utc, end_utc=end_utc)
    return get_success_data(api_client.create_dock_slot(trip_id, payload, DISPATCHER))


def buy_ride_pass(rider_user_id, **overrides) -> dict:
    return get_success_data(
        api_client.create_ride_pass(create_ride_pass_payload(**overrides),
                                    make_rider_headers(rider_user_id))
    )


def request_booking(world, rider_user_id, origin_stop_id=None,
                    destination_stop_id=None, **overrides) -> dict:
    payload = create_booking_payload(
        origin_stop_id or world["stop1_id"],
        destination_stop_id or world["stop2_id"],
        **overrides,
    )
    return get_success_data(
        api_client.create_booking(payload, make_rider_headers(rider_user_id))
    )


def dispatch_booking(booking_id) -> dict:
    return get_success_data(api_client.dispatch_booking(booking_id, DISPATCHER))


def confirm_booking(booking_id, rider_user_id, expected_trip_version=None,
                    trip_id=None) -> dict:
    """Confirm an offered booking, reading the offered trip's live version unless
    an explicit (possibly stale) one is given."""
    if expected_trip_version is None:
        if trip_id is None:
            booking = get_success_data(
                api_client.get_booking(booking_id, make_rider_headers(rider_user_id))
            )
            trip_id = booking["trip_id"]
        expected_trip_version = current_trip_version(trip_id)
    return get_success_data(
        api_client.confirm_booking(booking_id, confirm_payload(expected_trip_version),
                                   make_rider_headers(rider_user_id))
    )


def decline_booking(booking_id, rider_user_id) -> dict:
    return get_success_data(
        api_client.decline_booking(booking_id, make_rider_headers(rider_user_id))
    )


def create_confirmed_booking(world, rider_user_id, party_size=1, ride_pass_id=None,
                             origin_stop_id=None, destination_stop_id=None,
                             **overrides) -> dict:
    """Request -> dispatch -> confirm, in one call. Returns the confirmed booking."""
    payload_overrides = dict(overrides)
    payload_overrides["party_size"] = party_size
    if ride_pass_id is not None:
        payload_overrides["ride_pass_id"] = ride_pass_id
    booking = request_booking(world, rider_user_id,
                              origin_stop_id=origin_stop_id,
                              destination_stop_id=destination_stop_id,
                              **payload_overrides)
    dispatch_booking(booking["id"])
    return confirm_booking(booking["id"], rider_user_id)


def create_offered_booking(world, rider_user_id, party_size=1, ride_pass_id=None,
                           origin_stop_id=None, destination_stop_id=None,
                           **overrides) -> dict:
    """Request -> dispatch. Returns the offered booking."""
    payload_overrides = dict(overrides)
    payload_overrides["party_size"] = party_size
    if ride_pass_id is not None:
        payload_overrides["ride_pass_id"] = ride_pass_id
    booking = request_booking(world, rider_user_id,
                              origin_stop_id=origin_stop_id,
                              destination_stop_id=destination_stop_id,
                              **payload_overrides)
    return dispatch_booking(booking["id"])


# --- Tier 3: the movement lifecycle ----------------------------------------

def board_trip(world, trip_id, booking_ids=(), master_headers=None) -> dict:
    headers = master_headers or world["master_headers"]
    return get_success_data(
        api_client.board_trip(trip_id, board_payload(booking_ids), headers)
    )


def depart_trip(world, trip_id, master_headers=None) -> dict:
    headers = master_headers or world["master_headers"]
    return get_success_data(api_client.depart_trip(trip_id, headers))


def complete_trip(world, trip_id, master_headers=None) -> dict:
    headers = master_headers or world["master_headers"]
    return get_success_data(api_client.complete_trip(trip_id, headers))


def setup_boarded_trip(world, booking_ids=(), trip=None, **trip_overrides):
    """Plan a sailing (unless one is passed) and open boarding on it."""
    trip = trip or create_trip(world, **trip_overrides)
    board_trip(world, trip["id"], booking_ids)
    return trip


def setup_departed_trip(world, booking_ids=(), trip=None, depart_at=None,
                        **trip_overrides):
    """Plan -> board -> (move the clock) -> depart. Returns the departed trip."""
    trip = setup_boarded_trip(world, booking_ids=booking_ids, trip=trip,
                              **trip_overrides)
    if depart_at:
        set_clock(depart_at)
    return depart_trip(world, trip["id"])


def setup_completed_trip(world, booking_ids=(), trip=None, depart_at=None,
                         complete_at=None, **trip_overrides):
    """Plan -> board -> depart -> complete. Returns the completed trip."""
    departed = setup_departed_trip(world, booking_ids=booking_ids, trip=trip,
                                   depart_at=depart_at, **trip_overrides)
    if complete_at:
        set_clock(complete_at)
    return complete_trip(world, departed["id"])


# --- Tier 4: suspension, interruption and refund claims --------------------

def suspend_day(service_day_id, **patch) -> dict:
    """Recompute the day's posture to SUSPENDED. Defaults to the manual override."""
    payload = patch or {"manual_suspension": True}
    return get_success_data(api_client.update_service_day(service_day_id, payload, ADMIN))


def patch_service_day(service_day_id, **patch) -> dict:
    return get_success_data(api_client.update_service_day(service_day_id, patch, ADMIN))


def declare_interruption(service_day_id, cause="WEATHER", dispatcher_headers=None) -> dict:
    return get_success_data(
        api_client.create_interruption(service_day_id, create_interruption_payload(cause=cause),
                                       dispatcher_headers or DISPATCHER)
    )


def claims_for_interruption(interruption_id, headers=None):
    """Every refund claim the interruption opened, in listing order."""
    response = api_client.list_refund_claims(
        headers or AUDITOR,
        params={"service_interruption_id": interruption_id, "limit": 100},
    )
    body = response.json()
    assert response.status_code == 200, f"Setup step failed: {response.text}"
    return body["data"]


def claim_for_booking(booking_id, headers=None):
    response = api_client.list_refund_claims(
        headers or AUDITOR, params={"booking_id": booking_id, "limit": 100}
    )
    assert response.status_code == 200, f"Setup step failed: {response.text}"
    rows = response.json()["data"]
    assert rows, f"No refund claim was opened for booking {booking_id}"
    return rows[0]


def decide_claim(refund_claim_id, decision="APPROVE", auditor_headers=None) -> dict:
    return get_success_data(
        api_client.approve_refund_claim(refund_claim_id, approve_claim_payload(decision),
                                        auditor_headers or AUDITOR)
    )


def setup_interrupted_booking_with_claim(world, rider_user_id="rider-bob", party_size=2,
                                         trip=None, board_before_suspension=False,
                                         ride_pass_id=None, **trip_overrides):
    """Confirm a booking on a sailing, suspend the day so Cascade A interrupts it,
    then declare the interruption that opens its refund claim.

    Returns (trip, booking, interruption, claim).
    """
    trip = trip or create_trip(world, **trip_overrides)
    booking = create_confirmed_booking(world, rider_user_id, party_size=party_size,
                                       ride_pass_id=ride_pass_id)
    if board_before_suspension:
        board_trip(world, trip["id"], [booking["id"]])
    suspend_day(world["day_id"])
    interruption = declare_interruption(world["day_id"])
    claim = claim_for_booking(booking["id"])
    return trip, booking, interruption, claim


def refund_ride_pass(ride_pass_id, rider_user_id, settlement_basis="PRO_RATA") -> dict:
    return get_success_data(
        api_client.refund_ride_pass(ride_pass_id, refund_pass_payload(settlement_basis),
                                    make_rider_headers(rider_user_id))
    )
