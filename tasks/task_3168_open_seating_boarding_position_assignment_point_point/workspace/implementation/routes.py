"""Route handlers for all endpoint groups."""
from __future__ import annotations

from datetime import datetime, timedelta

from db import db
from errors import ApiError, err_not_found, err_validation
from middleware import require_owner, require_roles
from services import (
    BAG_FEE_CENTS,
    DELAY_FLOOR_MINUTES,
    GROUP_RANK,
    MAX_BAGS_PER_JOURNEY,
    MAX_CONNECTION_MINUTES,
    MAX_DUTY_MINUTES,
    active_assignment_for_journey,
    active_ub_upgrades_on_leg,
    active_upgrades_for_journey,
    aircraft_for_leg,
    apply_delay_to_leg,
    assign_for_new_checkin,
    boarding_order_sort,
    break_pairings_for_leg,
    break_routings_for_leg,
    cancel_journey_cascade,
    cancel_leg_cascade,
    clock_now,
    clock_now_iso,
    compute_mint_amount,
    compute_upgrade_price,
    grant_ub_position,
    maybe_cancel_booking,
    mint_travel_credit,
    no_show_journey,
    post_disruption_event,
    projected_bags,
    recompute_routing_slack,
    refresh_booking_journeys,
    staffing_adequacy,
    turn_projection,
    upgrade_pool_cap,
    void_journey_redemptions_compensate,
)
from utils import (
    get_body,
    new_row,
    opt_bool,
    opt_enum,
    opt_int,
    opt_str,
    paginate,
    parse_date,
    parse_dt,
    parse_pagination,
    req_enum,
    req_int,
    req_str,
    success_list,
    success_object,
    touch,
)

ALL_GET = ("OpsController", "GateAgent", "Passenger")


def _list_response(rows, filters=None, sort=None):
    if filters:
        for key, val in filters.items():
            if val is not None:
                rows = [r for r in rows if r.get(key) == val]
    rows.sort(key=sort or (lambda r: (r["created_at"], r["id"])))
    limit, offset = parse_pagination()
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


def _get_or_404(table, rid):
    row = table.get(rid)
    if not row:
        raise err_not_found()
    return row


# ---------------- Stations ----------------

def create_station():
    require_roles("OpsController")
    body = get_body()
    iata = req_str(body, "iata_code")
    row = new_row()
    row.update(
        {
            "iata_code": iata,
            "bag_weight_limit_lbs": opt_int(body, "bag_weight_limit_lbs", 50),
            "min_connection_minutes": opt_int(body, "min_connection_minutes", 40),
            "time_zone_offset_minutes": opt_int(body, "time_zone_offset_minutes"),
            "station_status": "ACTIVE",
        }
    )
    db.stations[row["id"]] = row
    return success_object(row, 201)


def get_station(station_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.stations, station_id))


def list_stations():
    require_roles(*ALL_GET)
    status = opt_str_args("station_status")
    return _list_response(list(db.stations.values()), {"station_status": status})


def opt_str_args(name):
    from flask import request

    v = request.args.get(name)
    return v if v is not None else None


def station_status(station_id):
    require_roles("OpsController")
    st = _get_or_404(db.stations, station_id)
    body = get_body()
    action = req_enum(body, "action", {"CLOSE", "REOPEN"})
    st["station_status"] = "CLOSED" if action == "CLOSE" else "ACTIVE"
    touch(st)
    return success_object(st)


# ---------------- Fare classes ----------------

def create_fare_class():
    require_roles("OpsController")
    body = get_body()
    row = new_row()
    row.update(
        {
            "code": req_str(body, "code"),
            "included_bags": opt_int(body, "included_bags", 2, minimum=0),
            "change_fee_cents": opt_int(body, "change_fee_cents", 0, minimum=0),
            "upgrade_discount_pct": opt_int(body, "upgrade_discount_pct", 0, 0, 100),
            "credit_validity_days": opt_int(body, "credit_validity_days", 365),
            "preboard_eligible": opt_bool(body, "preboard_eligible", False),
            "is_active": opt_bool(body, "is_active", True),
        }
    )
    db.fare_classes[row["id"]] = row
    return success_object(row, 201)


def get_fare_class(fare_class_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.fare_classes, fare_class_id))


def list_fare_classes():
    require_roles(*ALL_GET)
    raw = opt_str_args("is_active")
    val = None
    if raw is not None:
        val = raw.lower() == "true"
    return _list_response(list(db.fare_classes.values()), {"is_active": val})


# ---------------- Passengers ----------------

def create_passenger():
    require_roles("Passenger")
    body = get_body()
    row = new_row()
    row.update(
        {
            "full_name": req_str(body, "full_name"),
            "status_tier": opt_enum(
                body, "status_tier", {"NONE", "A_LIST", "A_LIST_PREFERRED"}, "NONE"
            ),
            "is_min_eligible": opt_bool(body, "is_min_eligible", True),
            "date_of_birth": req_str(body, "date_of_birth"),
            "standing": "GOOD",
            "no_show_count": 0,
        }
    )
    db.passengers[row["id"]] = row
    return success_object(row, 201)


def get_passenger(passenger_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.passengers, passenger_id))


# ---------------- Aircraft ----------------

def create_aircraft():
    require_roles("OpsController")
    body = get_body()
    fleet = req_enum(body, "fleet_type", {"SINGLE_FLEET"})
    row = new_row()
    row.update(
        {
            "tail_number": req_str(body, "tail_number"),
            "seat_count": req_int(body, "seat_count", minimum=1),
            "fleet_type": fleet,
            "maintenance_state": "SERVICEABLE",
            "home_station_code": req_str(body, "home_station_code"),
        }
    )
    db.aircraft[row["id"]] = row
    return success_object(row, 201)


def get_aircraft(aircraft_id):
    require_roles("OpsController", "GateAgent")
    return success_object(_get_or_404(db.aircraft, aircraft_id))


def list_aircraft():
    require_roles("OpsController", "GateAgent")
    return _list_response(
        list(db.aircraft.values()),
        {"maintenance_state": opt_str_args("maintenance_state")},
    )


def aircraft_maintenance(aircraft_id):
    require_roles("OpsController")
    ac = _get_or_404(db.aircraft, aircraft_id)
    body = get_body()
    action = req_enum(body, "action", {"TAKE_OUT_OF_SERVICE", "RETURN_TO_SERVICE"})
    if action == "TAKE_OUT_OF_SERVICE":
        if ac["maintenance_state"] != "SERVICEABLE":
            raise ApiError("ERR_INVALID_STATE", 409, "aircraft already out of service")
        # precondition: no DEPARTED-but-not-ARRIVED legs on this tail
        for r in db.aircraft_routings.values():
            if r["aircraft_id"] != aircraft_id or r["routing_status"] != "ACTIVE":
                continue
            for lid in r["leg_ids"]:
                leg = db.flight_legs.get(lid)
                if leg and leg["leg_status"] == "DEPARTED":
                    raise ApiError(
                        "ERR_INVALID_STATE",
                        409,
                        "aircraft has a departed-not-arrived leg",
                    )
        ac["maintenance_state"] = "OUT_OF_SERVICE"
        touch(ac)
        # break ACTIVE routings + propagate MAINTENANCE downstream
        for r in list(db.aircraft_routings.values()):
            if r["aircraft_id"] != aircraft_id or r["routing_status"] != "ACTIVE":
                continue
            r["routing_status"] = "BROKEN"
            touch(r)
            # downstream legs receive propagated delay when slack exhausted
            for i, lid in enumerate(r["leg_ids"][:-1]):
                leg = db.flight_legs.get(lid)
                nxt = db.flight_legs.get(r["leg_ids"][i + 1])
                if not leg or not nxt or nxt["leg_status"] != "SCHEDULED":
                    continue
                gap = int(
                    (
                        parse_dt(nxt["scheduled_departure_utc"])
                        - parse_dt(leg["scheduled_arrival_utc"])
                    ).total_seconds()
                    // 60
                )
                slack = gap - nxt["turn_target_minutes"]
                if slack < 0:
                    apply_delay_to_leg(nxt, -slack, "MAINTENANCE", True, 1)
    else:
        ac["maintenance_state"] = "SERVICEABLE"
        touch(ac)
    return success_object(ac)


# ---------------- Crew members ----------------

def create_crew_member():
    require_roles("OpsController")
    body = get_body()
    row = new_row()
    row.update(
        {
            "employee_ref": req_str(body, "employee_ref"),
            "crew_role": req_enum(
                body, "crew_role", {"CAPTAIN", "FIRST_OFFICER", "FLIGHT_ATTENDANT"}
            ),
            "qualified_fleet": req_enum(body, "qualified_fleet", {"SINGLE_FLEET"}),
            "crew_status": "AVAILABLE",
            "base_station_code": req_str(body, "base_station_code"),
        }
    )
    db.crew_members[row["id"]] = row
    return success_object(row, 201)


def get_crew_member(crew_member_id):
    require_roles("OpsController", "GateAgent")
    return success_object(_get_or_404(db.crew_members, crew_member_id))


def crew_availability(crew_member_id):
    require_roles("OpsController")
    cm = _get_or_404(db.crew_members, crew_member_id)
    body = get_body()
    action = req_enum(body, "action", {"MARK_UNAVAILABLE", "MARK_AVAILABLE"})
    if action == "MARK_UNAVAILABLE":
        cm["crew_status"] = "UNAVAILABLE"
        touch(cm)
        # break ACTIVE pairings + CREW propagation to the NEXT covered leg
        # (PRD §3.7: "with crew-cause propagation to the next covered leg").
        # The current leg of the pairing is the earliest one not yet
        # DEPARTED/ARRIVED; the next covered leg is the first SCHEDULED leg
        # after it. A pairing whose current leg is the last one has no next
        # leg, so nothing is propagated.
        for p in list(db.crew_pairings.values()):
            if p["pairing_status"] != "ACTIVE" or p["crew_member_id"] != crew_member_id:
                continue
            p["pairing_status"] = "BROKEN"
            touch(p)
            cur = 0
            for i, lid in enumerate(p["leg_ids"]):
                leg = db.flight_legs.get(lid)
                if leg and leg["leg_status"] not in ("DEPARTED", "ARRIVED"):
                    cur = i
                    break
            for lid in p["leg_ids"][cur + 1:]:
                leg = db.flight_legs.get(lid)
                if leg and leg["leg_status"] == "SCHEDULED":
                    apply_delay_to_leg(leg, DELAY_FLOOR_MINUTES, "CREW", True, 1)
                    break
    else:
        cm["crew_status"] = "AVAILABLE"
        touch(cm)
    return success_object(cm)


# ---------------- Flight legs ----------------

def create_flight_leg():
    require_roles("OpsController")
    body = get_body()
    origin_id = req_str(body, "origin_station_id")
    dest_id = req_str(body, "destination_station_id")
    origin = db.stations.get(origin_id)
    dest = db.stations.get(dest_id)
    if not origin or not dest:
        raise err_not_found("station not found")
    std = parse_dt(req_str(body, "scheduled_departure_utc"), "scheduled_departure_utc")
    sta = parse_dt(req_str(body, "scheduled_arrival_utc"), "scheduled_arrival_utc")
    if sta <= std:
        raise err_validation("scheduled_arrival_utc must be after scheduled_departure_utc")
    for st in (origin, dest):
        if st["station_status"] == "CLOSED":
            raise ApiError("ERR_STATION_CLOSED", 409, "station is CLOSED")
    row = new_row()
    row.update(
        {
            "flight_number": req_str(body, "flight_number"),
            "origin_station_id": origin_id,
            "destination_station_id": dest_id,
            "scheduled_departure_utc": _iso(std),
            "scheduled_arrival_utc": _iso(sta),
            "turn_target_minutes": opt_int(body, "turn_target_minutes", 35),
            "gate_agent_count": opt_int(body, "gate_agent_count", 2),
            "ramp_agent_count": opt_int(body, "ramp_agent_count", 4),
            "capacity_seats": req_int(body, "capacity_seats", minimum=1),
            "leg_status": "SCHEDULED",
            "delay_minutes": 0,
            "delay_cause": "NONE",
            "delay_propagated": False,
            "boarding_start_utc": None,
            "actual_departure_utc": None,
            "actual_arrival_utc": None,
        }
    )
    db.flight_legs[row["id"]] = row
    return success_object(row, 201)


def _iso(dt):
    from utils import iso_out

    return iso_out(dt)


def get_flight_leg(leg_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.flight_legs, leg_id))


def list_flight_legs():
    require_roles(*ALL_GET)
    return _list_response(
        list(db.flight_legs.values()),
        {
            "leg_status": opt_str_args("leg_status"),
            "origin_station_id": opt_str_args("origin_station_id"),
            "destination_station_id": opt_str_args("destination_station_id"),
        },
    )


def leg_journeys(leg_id):
    require_roles("OpsController", "GateAgent")
    _get_or_404(db.flight_legs, leg_id)
    rows = [j for j in db.journeys.values() if j["flight_leg_id"] == leg_id]
    return _list_response(rows, {"journey_status": opt_str_args("journey_status")})


def leg_boarding_assignments(leg_id):
    require_roles(*ALL_GET)
    _get_or_404(db.flight_legs, leg_id)
    rows = [a for a in db.boarding_assignments.values() if a["flight_leg_id"] == leg_id]
    filters = {
        "assignment_status": opt_str_args("assignment_status"),
        "boarding_group": opt_str_args("boarding_group"),
    }
    for k, v in filters.items():
        if v is not None:
            rows = [r for r in rows if r.get(k) == v]
    rows.sort(key=boarding_order_sort)
    limit, offset = parse_pagination()
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


def leg_disruptions(leg_id):
    require_roles("OpsController", "GateAgent")
    _get_or_404(db.flight_legs, leg_id)
    rows = [e for e in db.disruption_events.values() if e["flight_leg_id"] == leg_id]
    rows.sort(key=lambda e: (e["posted_utc"], e["created_at"]))
    limit, offset = parse_pagination()
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


def post_disruption(leg_id):
    require_roles("OpsController")
    leg = _get_or_404(db.flight_legs, leg_id)
    body = get_body()
    dtype = req_enum(body, "disruption_type", {"DELAY", "CANCELLATION"})
    cause = req_enum(body, "cause", {"WEATHER", "INBOUND_DELAY", "CREW", "MAINTENANCE"})
    if leg["leg_status"] in ("DEPARTED", "ARRIVED", "CANCELLED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg already departed/cancelled")
    if dtype == "DELAY":
        delay = req_int(body, "delay_minutes")
        if delay < DELAY_FLOOR_MINUTES:
            raise ApiError("ERR_DELAY_BELOW_FLOOR", 422, "delay below floor")
        if leg["leg_status"] == "DELAYED" and delay <= leg["delay_minutes"]:
            raise ApiError(
                "ERR_DELAY_BELOW_FLOOR", 422, "delay must be strictly greater"
            )
        event = apply_delay_to_leg(leg, delay, cause, False, 0)
        return success_object(event, 201)
    # CANCELLATION
    event = post_disruption_event(leg, "CANCELLATION", cause, None, 0)
    leg["leg_status"] = "CANCELLED"
    touch(leg)
    cancel_leg_cascade(leg)
    return success_object(event, 201)


def boarding_open(leg_id):
    require_roles("GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    if leg["leg_status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg not boardable")
    leg["boarding_start_utc"] = clock_now_iso()
    touch(leg)
    return success_object(leg)


def no_show_sweep(leg_id):
    require_roles("GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    if leg["leg_status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg not sweepable")
    if not leg["boarding_start_utc"]:
        raise ApiError("ERR_INVALID_STATE", 409, "boarding not opened")
    now = clock_now()
    posted_dep = parse_dt(leg["scheduled_departure_utc"]) + timedelta(
        minutes=leg["delay_minutes"]
    )
    if now < posted_dep:
        raise ApiError(
            "ERR_INVALID_STATE", 409, "posted departure time not reached"
        )
    for j in list(db.journeys.values()):
        if j["flight_leg_id"] == leg_id and j["journey_status"] == "CHECKED_IN":
            no_show_journey(j)
    touch(leg)
    return success_object(leg)


def depart_leg(leg_id):
    require_roles("GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    if leg["leg_status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg cannot depart")
    if not leg["boarding_start_utc"]:
        raise ApiError("ERR_INVALID_STATE", 409, "boarding not opened")
    now = clock_now()
    if leg["leg_status"] == "DELAYED":
        dep = parse_dt(leg["scheduled_departure_utc"]) + timedelta(
            minutes=leg["delay_minutes"]
        )
        if now < dep:
            raise ApiError("ERR_INVALID_STATE", 409, "delayed departure time not reached")
    # checked-in journeys block departure
    for a in db.boarding_assignments.values():
        if a["flight_leg_id"] == leg_id and a["assignment_status"] == "ACTIVE":
            j = db.journeys.get(a["journey_id"])
            if j and j["journey_status"] == "CHECKED_IN":
                raise ApiError(
                    "ERR_INVALID_STATE",
                    409,
                    "checked-in journeys block departure; run no-show sweep",
                )
    for p in db.crew_pairings.values():
        if leg_id in p["leg_ids"] and p["pairing_status"] == "BROKEN":
            raise ApiError("ERR_INVALID_STATE", 409, "covering pairing is BROKEN")
    ac = aircraft_for_leg(leg)
    if ac and ac["maintenance_state"] != "SERVICEABLE":
        raise ApiError("ERR_INVALID_STATE", 409, "aircraft not serviceable")
    leg["leg_status"] = "DEPARTED"
    leg["actual_departure_utc"] = clock_now_iso()
    touch(leg)
    for b in list(db.bags.values()):
        j = db.journeys.get(b["journey_id"])
        if j and j["flight_leg_id"] == leg_id and b["bag_status"] == "ACCEPTED":
            b["bag_status"] = "LOADED"
            touch(b)
    return success_object(leg)


def arrive_leg(leg_id):
    require_roles("GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    if leg["leg_status"] != "DEPARTED":
        raise ApiError("ERR_INVALID_STATE", 409, "leg not departed")
    leg["leg_status"] = "ARRIVED"
    leg["actual_arrival_utc"] = clock_now_iso()
    touch(leg)
    for j in list(db.journeys.values()):
        if j["flight_leg_id"] == leg_id and j["journey_status"] == "BOARDED":
            j["journey_status"] = "COMPLETED"
            touch(j)
    for b in list(db.bags.values()):
        j = db.journeys.get(b["journey_id"])
        if j and j["flight_leg_id"] == leg_id and b["bag_status"] == "LOADED":
            b["bag_status"] = "DELIVERED"
            touch(b)
    for p in list(db.crew_pairings.values()):
        if p["pairing_status"] != "ACTIVE" or leg_id not in p["leg_ids"]:
            continue
        legs = [db.flight_legs.get(x) for x in p["leg_ids"]]
        if all(l and l["leg_status"] == "ARRIVED" for l in legs):
            p["pairing_status"] = "CLOSED"
            touch(p)
    return success_object(leg)


# ---------------- Check-in ----------------

def _check_in_window_ok(leg):
    now = clock_now()
    std = parse_dt(leg["scheduled_departure_utc"]) + timedelta(
        minutes=leg["delay_minutes"]
    )
    open_at = std - timedelta(hours=24)
    close_at = std - timedelta(minutes=30)
    return open_at <= now <= close_at


def _do_check_in(journey, leg):
    # State precondition (PRD §2.6) runs before the duplicate-check-in
    # business constraint: a journey no longer in BOOKED reports
    # ERR_INVALID_STATE even when it is CHECKED_IN specifically.
    if journey["journey_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "journey not in BOOKED")
    if leg["leg_status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg not open for check-in")
    fare = db.fare_classes.get(journey["fare_class_id"])
    if (
        journey.get("accommodation") == "PREBOARD"
        and fare
        and not fare.get("preboard_eligible", False)
    ):
        raise ApiError("ERR_PREBOARD_NOT_ELIGIBLE", 422, "fare not preboard eligible")
    if not _check_in_window_ok(leg):
        raise ApiError("ERR_CHECKIN_WINDOW_CLOSED", 409, "outside check-in window")
    active_count = sum(
        1
        for a in db.boarding_assignments.values()
        if a["flight_leg_id"] == leg["id"] and a["assignment_status"] == "ACTIVE"
    )
    if active_count >= leg["capacity_seats"]:
        raise ApiError(
            "ERR_BOARDING_CAPACITY_EXCEEDED", 409, "boarding capacity exceeded"
        )
    journey["checked_in_at"] = clock_now_iso()
    journey["journey_status"] = "CHECKED_IN"
    touch(journey)
    assign_for_new_checkin(journey, leg)
    touch(leg)
    return journey


def leg_check_in(leg_id):
    user_id, role = require_roles("Passenger")
    leg = _get_or_404(db.flight_legs, leg_id)
    body = get_body()
    journey_id = req_str(body, "journey_id")
    journey = db.journeys.get(journey_id)
    if not journey:
        raise err_not_found("journey not found")
    require_owner(user_id, journey["passenger_id"])
    expected = body.get("expected_leg_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err_validation("expected_leg_version must be an integer")
        if expected != leg["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale leg version")
    if journey["flight_leg_id"] != leg_id:
        raise err_validation("journey does not belong to this leg")
    _do_check_in(journey, leg)
    return success_object(journey, 201)


def journey_check_in(journey_id):
    user_id, role = require_roles("Passenger")
    journey = _get_or_404(db.journeys, journey_id)
    require_owner(user_id, journey["passenger_id"])
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    _do_check_in(journey, leg)
    return success_object(journey)


# ---------------- Upgrades ----------------

def leg_upgrade_purchase(leg_id):
    user_id, role = require_roles("Passenger")
    leg = _get_or_404(db.flight_legs, leg_id)
    body = get_body()
    journey_id = req_str(body, "journey_id")
    journey = db.journeys.get(journey_id)
    if not journey:
        raise err_not_found("journey not found")
    require_owner(user_id, journey["passenger_id"])
    expected = body.get("expected_leg_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err_validation("expected_leg_version must be an integer")
        if expected != leg["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale leg version")
    utype = req_enum(body, "upgrade_type", {"EARLY_BIRD", "UPGRADED_BOARDING"})
    if journey["flight_leg_id"] != leg_id:
        raise err_validation("journey does not belong to this leg")
    if journey["journey_status"] not in ("BOOKED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "journey not upgradeable")
    now = clock_now()
    std = parse_dt(leg["scheduled_departure_utc"]) + timedelta(
        minutes=leg["delay_minutes"]
    )
    if utype == "EARLY_BIRD":
        if now >= std - timedelta(hours=36):
            raise ApiError(
                "ERR_UPGRADE_WINDOW_CLOSED", 409, "early bird window closed"
            )
    else:
        if now < std - timedelta(hours=24):
            raise ApiError(
                "ERR_UPGRADE_WINDOW_CLOSED", 409, "upgraded boarding not yet open"
            )
        if len(active_ub_upgrades_on_leg(leg_id)) >= upgrade_pool_cap(leg):
            raise ApiError("ERR_UPGRADE_SOLD_OUT", 409, "A1-A15 pool exhausted")
    if active_upgrades_for_journey(journey_id, utype):
        raise ApiError("ERR_DUPLICATE_UPGRADE", 409, "duplicate upgrade type")
    fare = db.fare_classes.get(journey["fare_class_id"])
    pax = db.passengers.get(journey["passenger_id"])
    price = compute_upgrade_price(fare, pax, utype)
    row = new_row()
    row.update(
        {
            "journey_id": journey_id,
            "upgrade_type": utype,
            "price_cents": price,
            "position_granted": None,
            "upgrade_status": "ACTIVE",
        }
    )
    db.boarding_upgrades[row["id"]] = row
    if utype == "UPGRADED_BOARDING":
        grant_ub_position(leg, journey, row)
    touch(leg)
    return success_object(row, 201)


def get_upgrade(upgrade_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.boarding_upgrades, upgrade_id))


def list_upgrades():
    require_roles(*ALL_GET)
    return _list_response(
        list(db.boarding_upgrades.values()),
        {
            "journey_id": opt_str_args("journey_id"),
            "upgrade_type": opt_str_args("upgrade_type"),
            "upgrade_status": opt_str_args("upgrade_status"),
        },
    )


def journey_upgrades(journey_id):
    require_roles(*ALL_GET)
    _get_or_404(db.journeys, journey_id)
    rows = [u for u in db.boarding_upgrades.values() if u["journey_id"] == journey_id]
    return _list_response(rows)


def refund_upgrade(upgrade_id):
    user_id, role = require_roles("Passenger")
    up = _get_or_404(db.boarding_upgrades, upgrade_id)
    journey = _get_or_404(db.journeys, up["journey_id"])
    require_owner(user_id, journey["passenger_id"])
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    if up["upgrade_status"] != "ACTIVE":
        raise ApiError("ERR_INVALID_STATE", 409, "upgrade not ACTIVE")
    if up["upgrade_type"] == "EARLY_BIRD" or leg.get("boarding_start_utc"):
        raise ApiError(
            "ERR_UPGRADE_NOT_REFUNDABLE", 422, "upgrade not refundable"
        )
    up["upgrade_status"] = "REFUNDED"
    touch(up)
    # void granted assignment, re-issue original CHECKIN_TIME position
    if up["position_granted"] is not None:
        for a in db.boarding_assignments.values():
            if (
                a["journey_id"] == journey["id"]
                and a["assignment_status"] == "ACTIVE"
                and a["boarding_group"] == "A"
                and a["assignment_source"] in ("UPGRADE_PURCHASE", "RETIME")
            ):
                a["assignment_status"] = "VOIDED"
                a["release_reason"] = "UPGRADE"
                touch(a)
        if journey["journey_status"] == "CHECKED_IN":
            # re-issue at the end of A (or overflow) with CHECKIN_TIME source
            a_count = sum(
                1
                for a in db.boarding_assignments.values()
                if a["flight_leg_id"] == leg["id"]
                and a["assignment_status"] == "ACTIVE"
                and a["boarding_group"] == "A"
            )
            from services import _make_assignment

            if a_count < 60:
                _make_assignment(journey, leg, "A", a_count + 1, "CHECKIN_TIME")
            else:
                b_count = sum(
                    1
                    for a in db.boarding_assignments.values()
                    if a["flight_leg_id"] == leg["id"]
                    and a["assignment_status"] == "ACTIVE"
                    and a["boarding_group"] == "B"
                )
                _make_assignment(journey, leg, "B", b_count + 1, "CHECKIN_TIME")
    return success_object(up)


# ---------------- Routings ----------------

def create_routing():
    require_roles("OpsController")
    body = get_body()
    routing_date = req_str(body, "routing_date")
    aircraft_id = req_str(body, "aircraft_id")
    leg_ids = body.get("leg_ids")
    if not isinstance(leg_ids, list) or not leg_ids:
        raise err_validation("leg_ids must be a non-empty array")
    ac = db.aircraft.get(aircraft_id)
    if not ac:
        raise err_not_found("aircraft not found")
    legs = []
    for lid in leg_ids:
        leg = db.flight_legs.get(lid)
        if not leg:
            raise err_not_found("leg not found")
        legs.append(leg)
    # fleet homogeneity
    if ac["fleet_type"] != "SINGLE_FLEET":
        raise ApiError("ERR_FLEET_HETEROGENEITY", 422, "fleet heterogeneity")
    # chain
    for a, b in zip(legs, legs[1:]):
        if a["destination_station_id"] != b["origin_station_id"]:
            raise ApiError("ERR_ROUTING_CHAIN_BROKEN", 422, "routing chain broken")
        if parse_dt(a["scheduled_arrival_utc"]) >= parse_dt(b["scheduled_departure_utc"]):
            raise ApiError("ERR_ROUTING_CHAIN_BROKEN", 422, "legs out of time order")
    # turn buffer
    for a, b in zip(legs, legs[1:]):
        gap = int(
            (
                parse_dt(b["scheduled_departure_utc"])
                - parse_dt(a["scheduled_arrival_utc"])
            ).total_seconds()
            // 60
        )
        if gap < b["turn_target_minutes"]:
            raise ApiError(
                "ERR_ROUTING_TURN_VIOLATION", 422, "turn buffer violated"
            )
    # double-booked
    for r in db.aircraft_routings.values():
        if (
            r["aircraft_id"] != aircraft_id
            or r["routing_status"] != "ACTIVE"
            or r["routing_date"] != routing_date
        ):
            continue
        other = [db.flight_legs.get(x) for x in r["leg_ids"]]
        other = [o for o in other if o]
        if not other:
            continue
        o_start = min(parse_dt(o["scheduled_departure_utc"]) for o in other)
        o_end = max(parse_dt(o["scheduled_arrival_utc"]) for o in other)
        n_start = min(parse_dt(o["scheduled_departure_utc"]) for o in legs)
        n_end = max(parse_dt(o["scheduled_arrival_utc"]) for o in legs)
        if n_start < o_end and o_start < n_end:
            raise ApiError(
                "ERR_AIRCRAFT_DOUBLE_BOOKED", 409, "aircraft double booked"
            )
    # station connection
    for a, b in zip(legs, legs[1:]):
        conn = db.stations.get(a["destination_station_id"])
        buf = conn.get("min_connection_minutes", 40) if conn else 40
        gap = int(
            (
                parse_dt(b["scheduled_departure_utc"])
                - parse_dt(a["scheduled_arrival_utc"])
            ).total_seconds()
            // 60
        )
        if gap < buf:
            raise ApiError(
                "ERR_STATION_CONNECTION_VIOLATION", 422, "station connection violation"
            )
    row = new_row()
    row.update(
        {
            "routing_date": routing_date,
            "aircraft_id": aircraft_id,
            "leg_ids": list(leg_ids),
            "routing_status": "ACTIVE",
            "slack_minutes": 0,
        }
    )
    db.aircraft_routings[row["id"]] = row
    recompute_routing_slack(row)
    return success_object(row, 201)


def get_routing(routing_id):
    require_roles("OpsController", "GateAgent")
    return success_object(_get_or_404(db.aircraft_routings, routing_id))


def list_routings():
    require_roles("OpsController", "GateAgent")
    from flask import request

    leg_ids_filter = request.args.get("leg_ids")
    rows = list(db.aircraft_routings.values())
    filters = {
        "aircraft_id": opt_str_args("aircraft_id"),
        "routing_date": opt_str_args("routing_date"),
        "routing_status": opt_str_args("routing_status"),
    }
    for k, v in filters.items():
        if v is not None:
            rows = [r for r in rows if r.get(k) == v]
    if leg_ids_filter:
        rows = [r for r in rows if leg_ids_filter in r["leg_ids"]]
    return _list_response(rows)


# ---------------- Pairings ----------------

def create_pairing():
    require_roles("OpsController")
    body = get_body()
    pairing_date = req_str(body, "pairing_date")
    crew_id = req_str(body, "crew_member_id")
    leg_ids = body.get("leg_ids")
    if not isinstance(leg_ids, list) or not leg_ids:
        raise err_validation("leg_ids must be a non-empty array")
    cm = db.crew_members.get(crew_id)
    if not cm:
        raise err_not_found("crew member not found")
    legs = []
    for lid in leg_ids:
        leg = db.flight_legs.get(lid)
        if not leg:
            raise err_not_found("leg not found")
        legs.append(leg)
    if cm["qualified_fleet"] != "SINGLE_FLEET":
        raise ApiError("ERR_FLEET_HETEROGENEITY", 422, "fleet heterogeneity")
    # crew legality
    def legality_fail(msg):
        raise ApiError("ERR_CREW_LEGALITY_VIOLATION", 422, msg)

    origin_station = db.stations.get(legs[0]["origin_station_id"])
    if cm["base_station_code"] != (
        origin_station["iata_code"] if origin_station else None
    ):
        legality_fail("pairing must start at crew base")
    for a, b in zip(legs, legs[1:]):
        if a["destination_station_id"] != b["origin_station_id"]:
            legality_fail("pairing legs not connected")
        gap = int(
            (
                parse_dt(b["scheduled_departure_utc"])
                - parse_dt(a["scheduled_arrival_utc"])
            ).total_seconds()
            // 60
        )
        if gap >= MAX_CONNECTION_MINUTES:
            legality_fail("connection gap exceeds max")
    span = int(
        (
            parse_dt(legs[-1]["scheduled_arrival_utc"])
            - parse_dt(legs[0]["scheduled_departure_utc"])
        ).total_seconds()
        // 60
    )
    if span > MAX_DUTY_MINUTES:
        legality_fail("duty span exceeds max")
    if cm["crew_status"] != "AVAILABLE":
        legality_fail("crew not available")
    # overlapping pairing window
    n_start = parse_dt(legs[0]["scheduled_departure_utc"])
    n_end = parse_dt(legs[-1]["scheduled_arrival_utc"])
    for p in db.crew_pairings.values():
        if p["crew_member_id"] != crew_id or p["pairing_status"] != "ACTIVE":
            continue
        other = [db.flight_legs.get(x) for x in p["leg_ids"]]
        other = [o for o in other if o]
        if not other:
            continue
        o_start = parse_dt(other[0]["scheduled_departure_utc"])
        o_end = parse_dt(other[-1]["scheduled_arrival_utc"])
        if n_start < o_end and o_start < n_end:
            legality_fail("crew already paired on overlapping window")
    # station connection
    for a, b in zip(legs, legs[1:]):
        conn = db.stations.get(a["destination_station_id"])
        buf = conn.get("min_connection_minutes", 40) if conn else 40
        gap = int(
            (
                parse_dt(b["scheduled_departure_utc"])
                - parse_dt(a["scheduled_arrival_utc"])
            ).total_seconds()
            // 60
        )
        if gap < buf:
            raise ApiError(
                "ERR_STATION_CONNECTION_VIOLATION", 422, "station connection violation"
            )
    row = new_row()
    row.update(
        {
            "pairing_date": pairing_date,
            "crew_member_id": crew_id,
            "leg_ids": list(leg_ids),
            "pairing_status": "ACTIVE",
        }
    )
    db.crew_pairings[row["id"]] = row
    return success_object(row, 201)


def get_pairing(pairing_id):
    require_roles("OpsController", "GateAgent")
    return success_object(_get_or_404(db.crew_pairings, pairing_id))


def list_pairings():
    require_roles("OpsController", "GateAgent")
    from flask import request

    leg_ids_filter = request.args.get("leg_ids")
    rows = list(db.crew_pairings.values())
    filters = {
        "crew_member_id": opt_str_args("crew_member_id"),
        "pairing_date": opt_str_args("pairing_date"),
        "pairing_status": opt_str_args("pairing_status"),
    }
    for k, v in filters.items():
        if v is not None:
            rows = [r for r in rows if r.get(k) == v]
    if leg_ids_filter:
        rows = [r for r in rows if leg_ids_filter in r["leg_ids"]]
    return _list_response(rows)


# ---------------- Bookings & journeys ----------------

def create_booking():
    user_id, role = require_roles("Passenger")
    body = get_body()
    record_locator = req_str(body, "record_locator")
    channel = opt_enum(body, "channel", {"DIRECT", "AGENT"}, "DIRECT")
    journeys_in = body.get("journeys")
    if not isinstance(journeys_in, list) or not journeys_in:
        raise err_validation("journeys must be a non-empty array")
    # validate all before creating
    prepared = []
    for jspec in journeys_in:
        if not isinstance(jspec, dict):
            raise err_validation("journey entries must be objects")
        pid = req_str(jspec, "passenger_id")
        lid = req_str(jspec, "flight_leg_id")
        fid = req_str(jspec, "fare_class_id")
        fare = db.fare_classes.get(fid)
        leg = db.flight_legs.get(lid)
        pax = db.passengers.get(pid)
        if not pax or not leg or not fare:
            raise err_not_found("referenced resource not found")
        base_fare = req_int(jspec, "base_fare_cents", minimum=0)
        accommodation = opt_enum(
            jspec, "accommodation", {"NONE", "PREBOARD", "FAMILY"}, "NONE"
        )
        anchor = jspec.get("family_anchor_journey_id")
        prepared.append(
            {
                "passenger_id": pid,
                "flight_leg_id": lid,
                "fare_class_id": fid,
                "base_fare_cents": base_fare,
                "accommodation": accommodation,
                "family_anchor_journey_id": anchor,
                "fare": fare,
                "leg": leg,
                "pax": pax,
            }
        )
    # fiscal: fare active
    for p in prepared:
        if not p["fare"].get("is_active", True):
            raise ApiError("ERR_FARE_INACTIVE", 422, "fare class inactive")
    # safety: preboard eligible
    for p in prepared:
        if p["accommodation"] == "PREBOARD" and not p["fare"].get(
            "preboard_eligible", False
        ):
            raise ApiError(
                "ERR_PREBOARD_NOT_ELIGIBLE", 422, "fare not preboard eligible"
            )
    # create booking + journeys (anchors may reference journeys in same booking by index or id)
    booking = new_row()
    booking.update(
        {
            "record_locator": record_locator,
            "booking_status": "ACTIVE",
            "channel": channel,
            "journey_count": 0,
            "journey_ids": [],
        }
    )
    db.bookings[booking["id"]] = booking
    created = []
    for p in prepared:
        j = new_row()
        j.update(
            {
                "booking_id": booking["id"],
                "passenger_id": p["passenger_id"],
                "flight_leg_id": p["flight_leg_id"],
                "fare_class_id": p["fare_class_id"],
                "base_fare_cents": p["base_fare_cents"],
                "journey_status": "BOOKED",
                "accommodation": p["accommodation"],
                "family_anchor_journey_id": None,
                "checked_in_at": None,
                "no_show_penalty_cents": None,
            }
        )
        db.journeys[j["id"]] = j
        created.append((j, p))
    # resolve family anchors: anchor may be an existing journey id or an index into this booking
    for j, p in created:
        anchor = p["family_anchor_journey_id"]
        if anchor is None:
            continue
        anchor_j = db.journeys.get(anchor)
        if anchor_j is None and isinstance(anchor, int):
            if 0 <= anchor < len(created):
                anchor_j = created[anchor][0]
        if not anchor_j:
            raise err_not_found("family anchor journey not found")
        anchor_pax = db.passengers.get(anchor_j["passenger_id"])
        anchor_leg = db.flight_legs.get(anchor_j["flight_leg_id"])
        flight_date = parse_dt(anchor_leg["scheduled_departure_utc"]).date()
        try:
            dob = parse_date(anchor_pax["date_of_birth"], "date_of_birth")
        except ApiError:
            raise err_validation("anchor passenger date_of_birth invalid")
        age = flight_date.year - dob.year - (
            (flight_date.month, flight_date.day) < (dob.month, dob.day)
        )
        if age >= 6:
            raise ApiError(
                "ERR_FAMILY_ANCHOR_INELIGIBLE", 422, "anchor is not a child under 6"
            )
        if not p["pax"].get("is_min_eligible", True):
            raise ApiError(
                "ERR_FAMILY_ANCHOR_INELIGIBLE", 422, "accompanying adult not eligible"
            )
        j["family_anchor_journey_id"] = anchor_j["id"]
        if p["accommodation"] == "NONE":
            j["accommodation"] = "FAMILY"
        touch(j)
    refresh_booking_journeys(booking["id"])
    return success_object(booking, 201)


def get_booking(booking_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.bookings, booking_id))


def booking_journeys(booking_id):
    require_roles(*ALL_GET)
    _get_or_404(db.bookings, booking_id)
    rows = [j for j in db.journeys.values() if j["booking_id"] == booking_id]
    return _list_response(rows, {"journey_status": opt_str_args("journey_status")})


def get_journey_route(journey_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.journeys, journey_id))


def list_journeys():
    require_roles(*ALL_GET)
    return _list_response(
        list(db.journeys.values()),
        {
            "booking_id": opt_str_args("booking_id"),
            "passenger_id": opt_str_args("passenger_id"),
            "flight_leg_id": opt_str_args("flight_leg_id"),
            "fare_class_id": opt_str_args("fare_class_id"),
            "family_anchor_journey_id": opt_str_args("family_anchor_journey_id"),
            "journey_status": opt_str_args("journey_status"),
        },
    )


def journey_assignments(journey_id):
    require_roles(*ALL_GET)
    _get_or_404(db.journeys, journey_id)
    rows = [a for a in db.boarding_assignments.values() if a["journey_id"] == journey_id]
    rows.sort(key=lambda a: (a["created_at"], a["id"]), reverse=True)
    limit, offset = parse_pagination()
    page, total = paginate(rows, limit, offset)
    return success_list(page, limit, offset, total)


def cancel_journey_route(journey_id):
    user_id, role = require_roles("Passenger")
    journey = _get_or_404(db.journeys, journey_id)
    require_owner(user_id, journey["passenger_id"])
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    if journey["journey_status"] not in ("BOOKED", "CHECKED_IN"):
        raise ApiError("ERR_INVALID_STATE", 409, "journey not cancellable")
    if leg["leg_status"] in ("DEPARTED", "ARRIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg already departed")
    journey["journey_status"] = "CANCELLED"
    touch(journey)
    cancel_journey_cascade(journey, flight_cancelled=False)
    return success_object(journey)


def change_journey_route(journey_id):
    user_id, role = require_roles("Passenger")
    journey = _get_or_404(db.journeys, journey_id)
    require_owner(user_id, journey["passenger_id"])
    body = get_body()
    new_leg_id = req_str(body, "new_flight_leg_id")
    new_fare_id = req_str(body, "new_fare_class_id")
    new_fare_cents = req_int(body, "new_base_fare_cents", minimum=0)
    new_leg = db.flight_legs.get(new_leg_id)
    new_fare = db.fare_classes.get(new_fare_id)
    if not new_leg or not new_fare:
        raise err_not_found("new leg or fare not found")
    old_leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    old_fare = _get_or_404(db.fare_classes, journey["fare_class_id"])
    if journey["journey_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "journey not in BOOKED")
    if old_leg["leg_status"] in ("DEPARTED", "ARRIVED") or new_leg["leg_status"] in (
        "DEPARTED",
        "ARRIVED",
    ):
        raise ApiError("ERR_INVALID_STATE", 409, "leg already departed")
    fee = old_fare.get("change_fee_cents", 0)
    if fee > 0:
        # PRD §3.9: "a change attempted without satisfying the fee is
        # rejected with ERR_CHANGE_FEE_UNPAID" — a non-flexible change must
        # explicitly satisfy the fee; omitting payment does not satisfy it.
        paid = body.get("change_fee_paid_cents", 0)
        if not isinstance(paid, int) or isinstance(paid, bool) or paid < fee:
            raise ApiError("ERR_CHANGE_FEE_UNPAID", 422, "change fee unpaid")
    # compensation: void ACTIVE redemptions paying this journey
    void_journey_redemptions_compensate(journey)
    # downgrade residual
    residual = journey["base_fare_cents"] - new_fare_cents
    if residual > 0 and fee == 0:
        mint_travel_credit(
            journey["passenger_id"], journey, residual, old_fare, old_leg
        )
    journey["flight_leg_id"] = new_leg_id
    journey["fare_class_id"] = new_fare_id
    journey["base_fare_cents"] = new_fare_cents
    touch(journey)
    return success_object(journey)


# ---------------- Bags ----------------

def accept_bag(journey_id):
    require_roles("GateAgent")
    journey = _get_or_404(db.journeys, journey_id)
    body = get_body()
    weight = req_int(body, "weight_lbs", minimum=1)
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    origin = db.stations.get(leg["origin_station_id"])
    limit = origin.get("bag_weight_limit_lbs", 50) if origin else 50
    if weight > limit:
        raise ApiError("ERR_BAG_OVERWEIGHT", 422, "bag overweight")
    count = sum(
        1
        for b in db.bags.values()
        if b["journey_id"] == journey_id and b["bag_status"] in ("ACCEPTED", "LOADED")
    )
    if count >= MAX_BAGS_PER_JOURNEY:
        raise ApiError("ERR_BAG_LIMIT_EXCEEDED", 409, "bag limit exceeded")
    fare = db.fare_classes.get(journey["fare_class_id"])
    included = fare.get("included_bags", 2) if fare else 2
    k = count + 1
    fee = 0 if k <= included else BAG_FEE_CENTS
    row = new_row()
    row.update(
        {
            "journey_id": journey_id,
            "weight_lbs": weight,
            "bag_status": "ACCEPTED",
            "bag_fee_cents": fee,
        }
    )
    db.bags[row["id"]] = row
    return success_object(row, 201)


def offload_bag(bag_id):
    require_roles("GateAgent")
    bag = _get_or_404(db.bags, bag_id)
    journey = _get_or_404(db.journeys, bag["journey_id"])
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    if bag["bag_status"] != "ACCEPTED":
        raise ApiError("ERR_INVALID_STATE", 409, "bag not in ACCEPTED")
    if leg["leg_status"] in ("DEPARTED", "ARRIVED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg already departed")
    bag["bag_status"] = "OFFLOADED"
    touch(bag)
    return success_object(bag)


def get_bag(bag_id):
    require_roles("GateAgent", "OpsController")
    return success_object(_get_or_404(db.bags, bag_id))


def list_bags():
    require_roles("GateAgent", "OpsController")
    return _list_response(
        list(db.bags.values()),
        {
            "journey_id": opt_str_args("journey_id"),
            "bag_status": opt_str_args("bag_status"),
        },
    )


def journey_bags(journey_id):
    require_roles(*ALL_GET)
    _get_or_404(db.journeys, journey_id)
    rows = [b for b in db.bags.values() if b["journey_id"] == journey_id]
    return _list_response(rows)


# ---------------- Boarding scan ----------------

def boarding_scan():
    require_roles("GateAgent")
    body = get_body()
    jid = req_str(body, "journey_id")
    journey = db.journeys.get(jid)
    if not journey:
        raise err_not_found("journey not found")
    leg = _get_or_404(db.flight_legs, journey["flight_leg_id"])
    if not leg.get("boarding_start_utc"):
        raise ApiError("ERR_INVALID_STATE", 409, "boarding not open")
    if leg["leg_status"] not in ("SCHEDULED", "DELAYED"):
        raise ApiError("ERR_INVALID_STATE", 409, "leg not boardable")
    if journey["journey_status"] != "CHECKED_IN":
        raise ApiError("ERR_INVALID_STATE", 409, "journey not CHECKED_IN")
    asg = active_assignment_for_journey(jid)
    if not asg:
        raise ApiError("ERR_INVALID_STATE", 409, "no active boarding assignment")
    journey["journey_status"] = "BOARDED"
    touch(journey)
    return success_object(journey)


# ---------------- Credits ----------------

def get_credit(credit_id):
    require_roles("Passenger", "OpsController")
    return success_object(_get_or_404(db.travel_credits, credit_id))


def list_credits():
    require_roles("Passenger", "OpsController")
    return _list_response(
        list(db.travel_credits.values()),
        {
            "passenger_id": opt_str_args("passenger_id"),
            "credit_status": opt_str_args("credit_status"),
            "source_journey_id": opt_str_args("source_journey_id"),
        },
    )


def redeem_credit(credit_id):
    user_id, role = require_roles("Passenger")
    credit = _get_or_404(db.travel_credits, credit_id)
    body = get_body()
    journey_id = req_str(body, "journey_id")
    journey = db.journeys.get(journey_id)
    if not journey:
        raise err_not_found("journey not found")
    require_owner(user_id, credit["passenger_id"])
    expected = body.get("expected_credit_version")
    if expected is not None:
        if not isinstance(expected, int) or isinstance(expected, bool):
            raise err_validation("expected_credit_version must be an integer")
        if expected != credit["version"]:
            raise ApiError("ERR_STALE_VERSION", 412, "stale credit version")
    amount = req_int(body, "amount_cents", minimum=1)
    if journey["journey_status"] != "BOOKED":
        raise ApiError("ERR_INVALID_STATE", 409, "target journey not BOOKED")
    # Explicit date-based expiry check runs before status-based exhaustion
    # (PRD §3.8 introduces it with "Separately"), so a credit already swept
    # to EXPIRED by the logical clock reports ERR_CREDIT_EXPIRED (410).
    logical_date = clock_now().date()
    expires = parse_date(credit["expires_on"], "expires_on")
    if logical_date > expires:
        raise ApiError("ERR_CREDIT_EXPIRED", 410, "credit expired")
    if credit["credit_status"] in ("EXPIRED", "VOID", "REDEEMED"):
        raise ApiError("ERR_CREDIT_EXHAUSTED", 422, "credit not redeemable")
    if amount > credit["remaining_amount_cents"]:
        raise ApiError("ERR_CREDIT_EXHAUSTED", 422, "amount exceeds remaining")
    credit["remaining_amount_cents"] -= amount
    if credit["remaining_amount_cents"] == 0:
        credit["credit_status"] = "REDEEMED"
    else:
        credit["credit_status"] = "PARTIALLY_REDEEMED"
    touch(credit)
    row = new_row()
    row.update(
        {
            "credit_id": credit_id,
            "journey_id": journey_id,
            "amount_cents": amount,
            "redemption_status": "ACTIVE",
        }
    )
    db.credit_redemptions[row["id"]] = row
    return success_object(row, 201)


def void_credit(credit_id):
    require_roles("OpsController")
    credit = _get_or_404(db.travel_credits, credit_id)
    for r in db.credit_redemptions.values():
        if r["credit_id"] == credit_id and r["redemption_status"] == "ACTIVE":
            raise ApiError(
                "ERR_INVALID_STATE", 409, "credit has active redemptions"
            )
    if credit["credit_status"] not in ("OPEN", "PARTIALLY_REDEEMED"):
        raise ApiError("ERR_INVALID_STATE", 409, "credit not voidable")
    credit["credit_status"] = "VOID"
    touch(credit)
    return success_object(credit)


def credit_redemptions_list(credit_id):
    require_roles("Passenger", "OpsController")
    _get_or_404(db.travel_credits, credit_id)
    rows = [r for r in db.credit_redemptions.values() if r["credit_id"] == credit_id]
    return _list_response(rows)


def get_redemption(redemption_id):
    require_roles("Passenger", "OpsController")
    return success_object(_get_or_404(db.credit_redemptions, redemption_id))


def list_redemptions():
    require_roles("Passenger", "OpsController")
    return _list_response(
        list(db.credit_redemptions.values()),
        {
            "credit_id": opt_str_args("credit_id"),
            "journey_id": opt_str_args("journey_id"),
            "redemption_status": opt_str_args("redemption_status"),
        },
    )


# ---------------- Assignments / disruptions / clock / computed reads ----------------

def get_assignment(assignment_id):
    require_roles(*ALL_GET)
    return success_object(_get_or_404(db.boarding_assignments, assignment_id))


def list_assignments():
    require_roles(*ALL_GET)
    return _list_response(
        list(db.boarding_assignments.values()),
        {
            "journey_id": opt_str_args("journey_id"),
            "flight_leg_id": opt_str_args("flight_leg_id"),
            "assignment_status": opt_str_args("assignment_status"),
            "boarding_group": opt_str_args("boarding_group"),
        },
    )


def get_disruption_event(event_id):
    require_roles("OpsController", "GateAgent")
    return success_object(_get_or_404(db.disruption_events, event_id))


def list_disruption_events():
    require_roles("OpsController", "GateAgent")
    return _list_response(
        list(db.disruption_events.values()),
        {
            "flight_leg_id": opt_str_args("flight_leg_id"),
            "disruption_type": opt_str_args("disruption_type"),
        },
    )


def turn_projection_route(leg_id):
    require_roles("OpsController", "GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    proj = turn_projection(leg)
    staff = staffing_adequacy(leg, proj["projected_bags"])
    data = {
        "projected_turn_minutes": proj["projected_turn_minutes"],
        "projected_bags": proj["projected_bags"],
        "pax_minutes": proj["pax_minutes"],
        "turns_slip": proj["turns_slip"],
        "understaffed": staff["understaffed"],
        "load_factor": staff["load_factor"],
        "bags_per_ramp_agent": staff["bags_per_ramp_agent"],
    }
    return success_object(data)


def staffing_check_route(leg_id):
    require_roles("OpsController", "GateAgent")
    leg = _get_or_404(db.flight_legs, leg_id)
    staff = staffing_adequacy(leg, projected_bags(leg))
    return success_object(staff)


def set_clock():
    require_roles("OpsController")
    body = get_body()
    to = req_str(body, "to_iso8601")
    dt = parse_dt(to, "to_iso8601")
    db.clock_iso = _iso(dt)
    # credit expiry sweep
    new_date = dt.date()
    for c in db.travel_credits.values():
        if c["credit_status"] in ("OPEN", "PARTIALLY_REDEEMED"):
            exp = parse_date(c["expires_on"], "expires_on")
            if exp < new_date:
                c["credit_status"] = "EXPIRED"
                touch(c)
    return success_object({"current_utc": db.clock_iso})
