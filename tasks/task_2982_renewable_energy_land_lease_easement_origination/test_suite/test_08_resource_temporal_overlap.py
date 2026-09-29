"""Contended resources: a linear corridor in two dimensions, a parcel's crews in one."""

from prd_bench_local_runner.testing import validate_error

from test_helpers.api_errors import (
    ERR_CORRIDOR_STATION_CONFLICT,
    ERR_CREW_CAPACITY_EXCEEDED,
)
from test_helpers.assertions import (
    assert_cents_equals,
    assert_instant_equals,
    assert_status,
)
from test_helpers.factories import booking_payload, crossing_payload
from test_helpers.fixtures import (
    book_site_access,
    cancel_booking,
    caprock_qualified_parcel,
    client,
    crossings_on_corridor,
    plan_corridor,
    propose_crossing,
    read_booking,
    read_corridor,
)
from test_helpers.test_users import LAND_AGENT, TITLE_COUNSEL


def _corridor_with_one_crossing():
    """A buffered corridor already occupied over stations 1000-1500 for September."""
    setup = caprock_qualified_parcel()
    corridor = plan_corridor(voltage_class="GENTIE_345KV", buffer_m=50)
    first = propose_crossing(corridor["id"], setup["parcel"]["id"])
    assert_cents_equals(first["compensation_cents"], 900000, "X1 compensation_cents")
    return corridor["id"], setup["parcel"]["id"], first


def _parcel_at_the_crew_cap():
    """A parcel whose overlapping bookings already occupy all three crews."""
    setup = caprock_qualified_parcel()
    parcel_id = setup["parcel"]["id"]
    first = book_site_access(
        parcel_id,
        TITLE_COUNSEL,
        purpose="TITLE_SURVEY",
        window_start="2026-08-10T08:00:00Z",
        window_end="2026-08-10T16:00:00Z",
        crew_count=1,
    )
    second = book_site_access(
        parcel_id,
        LAND_AGENT,
        purpose="GEOTECH",
        window_start="2026-08-10T12:00:00Z",
        window_end="2026-08-10T20:00:00Z",
        crew_count=2,
    )
    assert_status(first, "BOOKED", "B1")
    assert_status(second, "BOOKED", "B2")
    return parcel_id, first, second


def _third_booking_payload(parcel_id):
    """The request that asks for one crew over 14:00-18:00."""
    return booking_payload(
        parcel_id,
        purpose="ENV_SURVEY",
        window_start="2026-08-10T14:00:00Z",
        window_end="2026-08-10T18:00:00Z",
        crew_count=1,
    )


def test_touching_the_buffer_edge_exactly_is_not_a_station_conflict():
    """
    A crossing starting one buffer-width past the occupied span is admitted, while
    one metre further back inside the buffer is refused. The refusal is
    attributable to the original crossing alone, since the admitted one's window
    does not overlap it.

    PRD: "Touching at exactly the buffer edge does not conflict, and windows that
    merely abut — one ending at the instant the other begins — do not conflict
    either."

    Design: Difficulty/resource_temporal_overlap/corridor_station_buffer_and_window_double_overlap
    """
    corridor_id, parcel_id, _first = _corridor_with_one_crossing()

    clear_of_buffer = propose_crossing(
        corridor_id,
        parcel_id,
        crossing_kind="INTERCONNECTION_ROUTE",
        station_start_m=1550,
        station_end_m=1700,
        occupancy_window_start="2026-09-15T00:00:00Z",
        occupancy_window_end="2026-09-20T00:00:00Z",
    )
    assert clear_of_buffer["occupied_m"] == 150
    assert clear_of_buffer["duration_days"] == 5
    assert_cents_equals(clear_of_buffer["compensation_cents"], 510000, "X2 compensation")
    assert_status(clear_of_buffer, "PROPOSED", "X2")

    inside_buffer = client().create_crossing_agreement(
        crossing_payload(
            corridor_id,
            parcel_id,
            crossing_kind="INTERCONNECTION_ROUTE",
            station_start_m=1549,
            station_end_m=1700,
            occupancy_window_start="2026-09-05T00:00:00Z",
            occupancy_window_end="2026-09-10T00:00:00Z",
        ),
        LAND_AGENT,
    )

    validate_error(inside_buffer, ERR_CORRIDOR_STATION_CONFLICT, 409)


def test_abutting_windows_share_stations_without_competing_for_them():
    """
    A crossing whose stations sit squarely inside the occupied buffered span is
    still admitted, because its window begins at the instant the other's ends —
    one dimension of overlap is not enough.

    PRD: "A conflict exists against any other crossing on the **same** corridor in
    status `PROPOSED` or `GRANTED` when **both** a buffer-expanded station overlap
    and a half-open time overlap hold: the new crossing's `station_start_m` is less
    than the existing crossing's `station_end_m` plus the corridor's `buffer_m`,
    **and** the new crossing's `station_end_m` plus that same buffer is greater
    than the existing crossing's `station_start_m`, **and** the new
    `occupancy_window_start` is before the existing `occupancy_window_end`, **and**
    the new `occupancy_window_end` is after the existing `occupancy_window_start`."

    Design: Difficulty/resource_temporal_overlap/corridor_station_buffer_and_window_double_overlap
    """
    corridor_id, parcel_id, first = _corridor_with_one_crossing()
    clear_of_buffer = propose_crossing(
        corridor_id,
        parcel_id,
        crossing_kind="INTERCONNECTION_ROUTE",
        station_start_m=1550,
        station_end_m=1700,
        occupancy_window_start="2026-09-15T00:00:00Z",
        occupancy_window_end="2026-09-20T00:00:00Z",
    )

    later_window = propose_crossing(
        corridor_id,
        parcel_id,
        crossing_kind="COLLECTION_LINE",
        station_start_m=1200,
        station_end_m=1400,
        occupancy_window_start="2026-10-01T00:00:00Z",
        occupancy_window_end="2026-10-15T00:00:00Z",
    )

    assert later_window["occupied_m"] == 200
    assert later_window["duration_days"] == 14
    assert_cents_equals(later_window["compensation_cents"], 360000, "X4 compensation")
    admitted = {first["id"], clear_of_buffer["id"], later_window["id"]}
    rows = crossings_on_corridor(corridor_id)
    assert {row["id"] for row in rows} == admitted, (
        f"corridor should carry exactly the three admitted crossings, got {len(rows)}"
    )
    for row in rows:
        assert_status(row, "PROPOSED", "crossing")
    assert read_corridor(corridor_id)["granted_crossing_count"] == 0


def test_the_crew_cap_is_an_aggregate_over_intersecting_windows():
    """
    Both standing bookings are individually admissible and together sit exactly at
    the cap of three over their shared hours, so a fourth crew is refused on the
    collective sum rather than on anything about its own request.

    PRD: "Over every booking on the same parcel in status `BOOKED` or `COMPLETED`
    whose half-open window intersects the requested window, the sum of their
    `crew_count` plus the requested `crew_count` must not exceed 3; otherwise the
    booking is refused with `ERR_CREW_CAPACITY_EXCEEDED` (409)."

    Design: Difficulty/resource_temporal_overlap/parcel_crew_capacity_aggregate_half_open_windows
    """
    parcel_id, _first, _second = _parcel_at_the_crew_cap()

    response = client().create_site_access_booking(
        _third_booking_payload(parcel_id), LAND_AGENT
    )

    validate_error(response, ERR_CREW_CAPACITY_EXCEEDED, 409)


def test_a_back_to_back_window_takes_the_whole_capacity_unopposed():
    """
    A booking that starts at the instant the busiest standing booking ends may take
    all three crews, because half-open windows that merely abut never intersect.

    PRD: "Each individual booking may be perfectly admissible while the collective
    sum is not — three separate single-crew bookings fit, a fourth does not — and
    back-to-back windows, where one ends at the instant the next begins, never
    intersect and therefore never compete."

    Design: Difficulty/resource_temporal_overlap/parcel_crew_capacity_aggregate_half_open_windows
    """
    parcel_id, _first, _second = _parcel_at_the_crew_cap()

    back_to_back = book_site_access(
        parcel_id,
        LAND_AGENT,
        purpose="CONSTRUCTION_STAGING",
        window_start="2026-08-10T20:00:00Z",
        window_end="2026-08-11T04:00:00Z",
        crew_count=3,
    )

    assert_status(back_to_back, "BOOKED", "B4")
    assert back_to_back["crew_count"] == 3


def test_cancelling_a_booking_releases_its_crews_to_the_aggregate():
    """
    The refused request is retried unchanged after the two-crew booking is
    cancelled, and it now fits. The cancelled booking contributes nothing, and the
    later back-to-back booking's three crews are not counted either.

    PRD: "Cancelled bookings are excluded from the sum: cancelling a booking moves
    it `BOOKED → CANCELLED`, stamps `cancelled_at` from the logical clock, and its
    `crew_count` immediately stops counting against capacity for every overlapping
    window, which is the **crew-capacity conservation invariant**."

    Design: Difficulty/resource_temporal_overlap/parcel_crew_capacity_aggregate_half_open_windows
    """
    parcel_id, first, second = _parcel_at_the_crew_cap()
    refused = client().create_site_access_booking(
        _third_booking_payload(parcel_id), LAND_AGENT
    )
    validate_error(refused, ERR_CREW_CAPACITY_EXCEEDED, 409)
    back_to_back = book_site_access(
        parcel_id,
        LAND_AGENT,
        purpose="CONSTRUCTION_STAGING",
        window_start="2026-08-10T20:00:00Z",
        window_end="2026-08-11T04:00:00Z",
        crew_count=3,
    )

    cancelled = cancel_booking(second["id"])
    assert_status(cancelled, "CANCELLED", "B2")
    assert_instant_equals(
        cancelled["cancelled_at"], "2026-08-01T00:00:00Z", "cancelled_at"
    )

    retry = client().create_site_access_booking(
        _third_booking_payload(parcel_id), LAND_AGENT
    )

    assert retry.status_code in (200, 201), retry.text
    retried = retry.json()["data"]
    assert_status(retried, "BOOKED", "B3 retry")
    assert_status(read_booking(first["id"]), "BOOKED", "B1")
    assert_status(read_booking(second["id"]), "CANCELLED", "B2")
    assert_status(read_booking(back_to_back["id"]), "BOOKED", "B4")
