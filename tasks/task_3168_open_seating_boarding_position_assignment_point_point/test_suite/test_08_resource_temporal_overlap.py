"""Resource temporal overlap: half-open tail windows and crew duty-span cap.

Covers Difficulty/resource_temporal_overlap instances:
- aircraft_tail_half_open_overlap
- crew_pairing_duty_span_aggregate
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_success,
    ApiErrorId,
    create_aircraft, create_crew_member, create_leg, create_pairing,
    create_routing, create_station, set_clock,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def _tail_overlap_setup():
    """R1 = [L1, L2] covering 12:00-14:35; L3 starts at 14:35 (touching),
    L4 starts at 14:34 (overlapping)."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL", min_connection_minutes=30)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=30)
    station_aus = create_station(iata_code="AUS", min_connection_minutes=30)
    aircraft = create_aircraft(tail_number="N100", seat_count=143)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T12:00:00Z",
                    scheduled_arrival_utc="2026-10-01T13:00:00Z",
                    capacity_seats=143)
    l2 = create_leg(station_hou["id"], station_aus["id"],
                    scheduled_departure_utc="2026-10-01T13:35:00Z",
                    scheduled_arrival_utc="2026-10-01T14:35:00Z",
                    capacity_seats=143)
    l3 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T14:35:00Z",
                    scheduled_arrival_utc="2026-10-01T15:35:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    l4 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T14:34:00Z",
                    scheduled_arrival_utc="2026-10-01T15:34:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    r1 = create_routing("2026-10-01", aircraft["id"], [l1["id"], l2["id"]])
    return aircraft, l1, l2, l3, l4, r1


def test_touching_endpoint_windows_do_not_overlap(api):
    """PRD §3.2: "then a temporal-overlap check that no other `ACTIVE`
    routing already covers the same tail on the same date with overlapping
    leg windows — touching endpoints are again allowed, overlaps reject with
    `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/aircraft_tail_half_open_overlap
    """
    aircraft, _l1, _l2, l3, _l4, r1 = _tail_overlap_setup()

    r2 = validate_success(api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l3["id"]]}, OPS), 201)
    assert r2["routing_status"] == "ACTIVE", (
        "a window starting exactly at the prior routing's last arrival "
        "touches but does not overlap under half-open semantics")

    r1_now = validate_success(api.get_routing(r1["id"], OPS), 200)
    assert r1_now["routing_status"] == "ACTIVE"


def test_overlapping_window_is_rejected_as_double_booked(api):
    """PRD §3.2: "then a temporal-overlap check that no other `ACTIVE`
    routing already covers the same tail on the same date with overlapping
    leg windows — touching endpoints are again allowed, overlaps reject with
    `ERR_AIRCRAFT_DOUBLE_BOOKED` (HTTP 409)".

    Design: Difficulty/resource_temporal_overlap/aircraft_tail_half_open_overlap
    """
    aircraft, _l1, _l2, _l3, l4, _r1 = _tail_overlap_setup()

    res = api.create_routing(
        {"routing_date": "2026-10-01", "aircraft_id": aircraft["id"],
         "leg_ids": [l4["id"]]}, OPS)
    err = validate_error(res, ApiErrorId.ERR_AIRCRAFT_DOUBLE_BOOKED)
    assert err["error_id"] == "ERR_AIRCRAFT_DOUBLE_BOOKED", (
        "[12:00, 14:35) x [14:34, 15:34) intersects one minute before the "
        "touching boundary")


def _duty_span_setup():
    """Captain based at DAL; chain DAL->HOU 06:00-07:00, HOU->AUS 08:00-10:00
    (60-minute gaps: under the 120-minute per-leg connection cap and above
    the 30-minute station buffer); L3 11:00->19:59 yields a 839-minute duty
    span (06:00 -> 19:59), L4 11:00->20:01 yields 841."""
    set_clock("2026-09-30T12:00:00Z")
    station_dal = create_station(iata_code="DAL", min_connection_minutes=30)
    station_hou = create_station(iata_code="HOU", min_connection_minutes=30)
    station_aus = create_station(iata_code="AUS", min_connection_minutes=30)
    l1 = create_leg(station_dal["id"], station_hou["id"],
                    scheduled_departure_utc="2026-10-01T06:00:00Z",
                    scheduled_arrival_utc="2026-10-01T07:00:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    l2 = create_leg(station_hou["id"], station_aus["id"],
                    scheduled_departure_utc="2026-10-01T08:00:00Z",
                    scheduled_arrival_utc="2026-10-01T10:00:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    l3 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T11:00:00Z",
                    scheduled_arrival_utc="2026-10-01T19:59:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    l4 = create_leg(station_aus["id"], station_dal["id"],
                    scheduled_departure_utc="2026-10-01T11:00:00Z",
                    scheduled_arrival_utc="2026-10-01T20:01:00Z",
                    capacity_seats=143, turn_target_minutes=30)
    crew = create_crew_member(employee_ref="C100", crew_role="CAPTAIN",
                              base_station_code="DAL")
    return crew, l1, l2, l3, l4


def test_duty_span_at_839_minutes_is_within_the_cap(api):
    """PRD §3.2: "Crew legality is the gating rule, checked at creation: the
    pairing must begin at the crew member's base station, the legs must form
    a connected chain (consecutive legs share a station), no per-leg gap may
    exceed the `MAX_CONNECTION_MINUTES` cap of 120 minutes, the total duty
    span from first departure to last arrival may not exceed the
    `MAX_DUTY_MINUTES` cap of 840 minutes (fourteen hours), the crew member
    must be `AVAILABLE`, and they may not already hold a pairing on an
    overlapping window. A violation rejects creation with
    `ERR_CREW_LEGALITY_VIOLATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/crew_pairing_duty_span_aggregate
    """
    crew, l1, l2, l3, _l4 = _duty_span_setup()

    pairing = validate_success(api.create_pairing(
        {"pairing_date": "2026-10-01", "crew_member_id": crew["id"],
         "leg_ids": [l1["id"], l2["id"], l3["id"]]}, OPS), 201)
    assert pairing["pairing_status"] == "ACTIVE", (
        "06:00 first departure to 19:59 last arrival is 839 minutes: "
        "the 840-minute cap is inclusive")


def test_duty_span_at_841_minutes_violates_the_aggregate_cap(api):
    """PRD §3.2: "Crew legality is the gating rule, checked at creation: the
    pairing must begin at the crew member's base station, the legs must form
    a connected chain (consecutive legs share a station), no per-leg gap may
    exceed the `MAX_CONNECTION_MINUTES` cap of 120 minutes, the total duty
    span from first departure to last arrival may not exceed the
    `MAX_DUTY_MINUTES` cap of 840 minutes (fourteen hours), the crew member
    must be `AVAILABLE`, and they may not already hold a pairing on an
    overlapping window. A violation rejects creation with
    `ERR_CREW_LEGALITY_VIOLATION` (HTTP 422)."

    Design: Difficulty/resource_temporal_overlap/crew_pairing_duty_span_aggregate
    """
    crew, l1, l2, _l3, l4 = _duty_span_setup()

    res = api.create_pairing(
        {"pairing_date": "2026-10-01", "crew_member_id": crew["id"],
         "leg_ids": [l1["id"], l2["id"], l4["id"]]}, OPS)
    err = validate_error(res, ApiErrorId.ERR_CREW_LEGALITY_VIOLATION)
    assert err["error_id"] == "ERR_CREW_LEGALITY_VIOLATION", (
        "06:00 to 20:01 is 841 minutes: no two legs overlap, yet the "
        "aggregate window exceeds the 840-minute cap")
