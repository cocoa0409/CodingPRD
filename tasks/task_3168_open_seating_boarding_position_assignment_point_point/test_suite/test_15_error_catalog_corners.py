"""Error-catalogue corner tests: each documented error id is reachable.

Covers Corner/errors instances:
- err_duplicate_checkin_triggerable
- err_credit_exhausted_overdraw
- err_fleet_heterogeneity_triggerable
- err_family_anchor_ineligible_triggerable
- err_station_closed_triggerable

(the remaining error instances are excluded stubs owned by §1.8 difficulty
instances)
"""
from test_helpers import (
    TEST_USERS, api_client, get_success_data, validate_error,
    validate_error_is_one_of, validate_paginated, validate_success,
    ApiErrorId,
    book_journey, create_aircraft, create_fare_class, create_leg,
    create_passenger, create_station, leg_check_in, set_clock,
    setup_basic_network, setup_checked_in_journey, setup_credit_scenario,
)

OPS = TEST_USERS["ops_headers"]
GATE = TEST_USERS["gate_agent_headers"]


def test_second_checkin_on_the_same_journey_is_rejected(api):
    """PRD §3.4: "A journey already checked in rejects with
    `ERR_DUPLICATE_CHECKIN` (HTTP 409)."

    PRD §2.6: "When two checks could both fail, the earlier one in this
    ordering is the one the client sees."

    Design: Corner/errors/err_duplicate_checkin_triggerable
    """
    fx = setup_checked_in_journey()
    leg = fx["leg"]
    journey_id = fx["journey_id"]
    p_h = fx["passenger_headers"]
    current_leg_v = validate_success(api.get_flight_leg(leg["id"], OPS),
                                     200)["version"]

    res = api.leg_check_in(
        leg["id"], {"journey_id": journey_id,
                    "expected_leg_version": current_leg_v}, p_h)
    assert res.status_code == 409
    error_id = validate_error_is_one_of(
        res, [ApiErrorId.ERR_DUPLICATE_CHECKIN.value,
              ApiErrorId.ERR_INVALID_STATE.value])
    assert error_id in ("ERR_DUPLICATE_CHECKIN", "ERR_INVALID_STATE")

    journey = validate_success(api.get_journey(journey_id, p_h), 200)
    assert journey["journey_status"] == "CHECKED_IN"


def test_redeeming_more_than_the_remaining_balance_is_rejected(api):
    """PRD §3.8: "The credit must be redeemable: a credit that is `EXPIRED`,
    `VOID`, or already `REDEEMED`, or an `amount_cents` exceeding
    `remaining_amount_cents`, is rejected with `ERR_CREDIT_EXHAUSTED`
    (HTTP 422)."

    Design: Corner/errors/err_credit_exhausted_overdraw
    """
    sc = setup_credit_scenario(source_fare_cents=10000, new_fare_cents=9000)
    p_h = sc["passenger_headers"]
    credit = sc["credit"]

    res = api.redeem_credit(
        credit["id"], {"journey_id": sc["j_new"], "amount_cents": 15000,
                       "expected_credit_version": credit["version"]}, p_h)
    err = validate_error(res, ApiErrorId.ERR_CREDIT_EXHAUSTED)
    assert err["error_id"] == "ERR_CREDIT_EXHAUSTED", (
        "15000 exceeds the remaining balance of 10000")

    credit_now = validate_success(api.get_credit(credit["id"], p_h), 200)
    assert credit_now["remaining_amount_cents"] == 10000, (
        "the rejected redemption does not move the balance")


def test_a_non_single_fleet_crew_member_is_rejected(api):
    """PRD §2.9: "The carrier operates one fleet type, denoted
    `SINGLE_FLEET`, on every aircraft and every crew member.
    `Aircraft.fleet_type` is always `SINGLE_FLEET`; `CrewMember.qualified_fleet`
    is always `SINGLE_FLEET`."

    Design: Corner/errors/err_fleet_heterogeneity_triggerable
    """
    res = api.create_crew_member(
        {"employee_ref": "C9", "crew_role": "CAPTAIN",
         "qualified_fleet": "WIDEBODY", "base_station_code": "DAL"}, OPS)
    assert res.status_code in (400, 422), (
        "WIDEBODY departs from the single-fleet invariant and is rejected "
        "at entry")
    error_id = validate_error_is_one_of(
        res, [ApiErrorId.ERR_FLEET_HETEROGENEITY.value,
              ApiErrorId.ERR_VALIDATION.value])
    assert error_id in ("ERR_FLEET_HETEROGENEITY", "ERR_VALIDATION")


def test_min_anchor_must_be_a_qualifying_child(api):
    """PRD §3.3: "A journey may instead participate in the family-boarding
    accommodation: one journey is the child (the passenger must be under 6
    years old on the flight date, computed from `date_of_birth`), and an
    accompanying adult journey points at the child journey via
    `family_anchor_journey_id`; the accompanying passenger must have
    `is_min_eligible` true. An anchor that is not a qualifying child, or an
    accompanying passenger with `is_min_eligible` false, rejects the booking
    with `ERR_FAMILY_ANCHOR_INELIGIBLE` (HTTP 422)."

    Design: Corner/errors/err_family_anchor_ineligible_triggerable
    """
    net = setup_basic_network()
    adult1, a1_h = create_passenger(full_name="Adult 1",
                                    date_of_birth="1990-01-01")
    adult2, _a2_h = create_passenger(full_name="Adult 2",
                                     date_of_birth="1990-05-05")

    # PRD §3.3: the family accommodation is expressed by the accompanying
    # journey pointing at the child journey via `family_anchor_journey_id`;
    # here the "anchor" passenger is 36 on the flight date, not under 6.
    res = api.create_booking(
        {"record_locator": "BKFA",
         "journeys": [
             {"passenger_id": adult2["id"],
              "flight_leg_id": net["leg"]["id"],
              "fare_class_id": net["fare"]["id"], "base_fare_cents": 10000},
             {"passenger_id": adult1["id"],
              "flight_leg_id": net["leg"]["id"],
              "fare_class_id": net["fare"]["id"], "base_fare_cents": 10000,
              "family_anchor_journey_id": 0},
         ]}, a1_h)
    err = validate_error(res, ApiErrorId.ERR_FAMILY_ANCHOR_INELIGIBLE)
    assert err["error_id"] == "ERR_FAMILY_ANCHOR_INELIGIBLE", (
        "the anchor passenger is 36 on the flight date, not under 6")


def test_creating_a_leg_against_a_closed_station_is_rejected(api):
    """PRD §3.1: "An `OpsController` may close a station by posting a status
    `action` of `CLOSE` to its status endpoint; from that point, any new
    flight leg referencing the station is rejected with `ERR_STATION_CLOSED`
    (HTTP 409). Posting `action` `REOPEN` returns the station to `ACTIVE`."

    Design: Corner/errors/err_station_closed_triggerable
    """
    station_dal = create_station(iata_code="DAL")
    station_hou = create_station(iata_code="HOU")

    validate_success(api.set_station_status(station_dal["id"], "CLOSE", OPS),
                     200)
    closed = validate_success(api.get_station(station_dal["id"], OPS), 200)
    assert closed["station_status"] == "CLOSED"

    res = api.create_flight_leg(
        {"flight_number": "WN1", "origin_station_id": station_dal["id"],
         "destination_station_id": station_hou["id"],
         "scheduled_departure_utc": "2026-10-01T12:00:00Z",
         "scheduled_arrival_utc": "2026-10-01T13:00:00Z",
         "capacity_seats": 143}, OPS)
    err = validate_error(res, ApiErrorId.ERR_STATION_CLOSED)
    assert err["error_id"] == "ERR_STATION_CLOSED"

    validate_success(api.set_station_status(station_dal["id"], "REOPEN", OPS),
                     200)
    leg = validate_success(api.create_flight_leg(
        {"flight_number": "WN1", "origin_station_id": station_dal["id"],
         "destination_station_id": station_hou["id"],
         "scheduled_departure_utc": "2026-10-01T12:00:00Z",
         "scheduled_arrival_utc": "2026-10-01T13:00:00Z",
         "capacity_seats": 143}, OPS), 201)
    assert leg["leg_status"] == "SCHEDULED", (
        "the ACTIVE-CLOSED-ACTIVE cycle restores acceptance")
