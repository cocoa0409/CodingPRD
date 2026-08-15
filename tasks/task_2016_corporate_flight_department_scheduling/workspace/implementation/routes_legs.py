"""FlightLeg endpoints plus per-leg services (CateringOrder, GroundTransport)."""

from flask import Blueprint, g, request

from httpkit import (
    authenticate, err, err_constraint, err_invalid_state, err_unauthorized,
    err_validation, get_body, ignore_body, paginate, require_roles,
    respond_object, sorted_items,
)
from serializers import catering_order_json, flight_leg_json, ground_transport_json
from services import (
    accepted_charter_for_trip, catering_of_leg, crew_interval_conflict,
    duty_check_passes, get_catering_order, get_crew_member, get_ground_transport,
    get_leg, get_trip, legs_of_trip, maintenance_conflict, new_common, touch,
    transports_of_leg, cascade_leg_cancelled,
)
from store import db

bp = Blueprint("legs", __name__)

MGR = "FlightDeptManager"
DISP = "Dispatcher"
FIN = "FinanceAdmin"
EXEC = "ExecutiveRequester"

LEG_READ_ROLES = (MGR, DISP, FIN, EXEC)


# ---------------------------------------------------------------------------
# FlightLeg create / read
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/trip-requests/<trip_id>/flight-legs")
def create_leg(trip_id):
    authenticate()
    require_roles(EXEC, DISP)
    t = get_trip(trip_id)
    if g.role == EXEC and t["requester_id"] != g.user_id:
        raise err_unauthorized(
            "An ExecutiveRequester may add legs only to their own trip requests")
    data = get_body([
        {"name": "leg_sequence", "type": "integer", "required": True},
        {"name": "origin_icao", "type": "string", "required": True},
        {"name": "destination_icao", "type": "string", "required": True},
        {"name": "scheduled_departure_utc", "type": "datetime", "required": True},
        {"name": "scheduled_arrival_utc", "type": "datetime", "required": True},
        {"name": "distance_statute_miles", "type": "integer", "required": True},
    ])
    if data["distance_statute_miles"] < 0:
        raise err_validation("distance_statute_miles must be >= 0")
    for lg in legs_of_trip(t["id"]):
        if lg["leg_sequence"] == data["leg_sequence"]:
            raise err_constraint("leg_sequence must be unique within the trip")
    if not data["scheduled_arrival_utc"] > data["scheduled_departure_utc"]:
        raise err_constraint(
            "scheduled_arrival_utc must be strictly after scheduled_departure_utc")
    lg = new_common()
    delta = data["scheduled_arrival_utc"] - data["scheduled_departure_utc"]
    lg.update({
        "trip_request_id": t["id"],
        "leg_sequence": data["leg_sequence"],
        "origin_icao": data["origin_icao"],
        "destination_icao": data["destination_icao"],
        "scheduled_departure_utc": data["scheduled_departure_utc"],
        "scheduled_arrival_utc": data["scheduled_arrival_utc"],
        "distance_statute_miles": data["distance_statute_miles"],
        "aircraft_id": None,
        "pic_crew_id": None,
        "sic_crew_id": None,
        "block_minutes": int(delta.total_seconds() // 60),
        "status": "PLANNED",
    })
    db.flight_legs[lg["id"]] = lg
    # A leg insertion on a trip past DRAFT modifies the trip itself for OCC
    # purposes (PRD 2.9 lists "a leg insertion" as a version advancer); while
    # DRAFT the roster is still being built and the trip version is untouched.
    if t["approval_status"] != "DRAFT":
        touch(t)
    return respond_object(flight_leg_json(lg), 201)


@bp.get("/flight-ops/trip-requests/<trip_id>/flight-legs")
def list_trip_legs(trip_id):
    authenticate()
    require_roles(*LEG_READ_ROLES)
    t = get_trip(trip_id)
    items = sorted_items(legs_of_trip(t["id"]))
    return paginate([flight_leg_json(lg) for lg in items])


@bp.get("/flight-ops/flight-legs")
def list_legs():
    authenticate()
    require_roles(*LEG_READ_ROLES)
    items = sorted_items(db.flight_legs.values())
    for param in ("aircraft_id", "pic_crew_id", "sic_crew_id", "status",
                  "trip_request_id"):
        val = request.args.get(param)
        if val is not None:
            items = [lg for lg in items if lg[param] == val]
    return paginate([flight_leg_json(lg) for lg in items])


@bp.get("/flight-ops/flight-legs/<leg_id>")
def read_leg(leg_id):
    authenticate()
    require_roles(*LEG_READ_ROLES)
    return respond_object(flight_leg_json(get_leg(leg_id)))


# ---------------------------------------------------------------------------
# FlightLeg pipeline actions
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/flight-legs/<leg_id>/assign-crew")
def assign_crew(leg_id):
    authenticate()
    require_roles(DISP)
    lg = get_leg(leg_id)
    data = get_body([
        {"name": "pic_crew_id", "type": "string", "required": True},
        {"name": "sic_crew_id", "type": "string", "required": True},
    ])
    # Body FK resolution (priority 4) precedes the state gate (priority 5).
    pic = get_crew_member(data["pic_crew_id"], fk=True)
    sic = get_crew_member(data["sic_crew_id"], fk=True)
    if lg["status"] != "AIRCRAFT_ASSIGNED":
        raise err_invalid_state("Only an AIRCRAFT_ASSIGNED leg can be crewed")
    aircraft = db.aircraft.get(lg["aircraft_id"])
    # Crew legality (priority 7): distinct seats, ACTIVE, type-rated,
    # training strictly beyond departure, duty limit with inclusive boundary.
    if pic["id"] == sic["id"]:
        raise err("ERR_CREW_ILLEGAL", 422,
                  "PIC and SIC seats must be filled by different crew members")
    for crew in (pic, sic):
        if crew["status"] != "ACTIVE":
            raise err("ERR_CREW_ILLEGAL", 422, "Crew member is not ACTIVE")
        if aircraft is not None and aircraft["aircraft_type"] not in crew["type_ratings"]:
            raise err("ERR_CREW_ILLEGAL", 422,
                      "Crew member is not type-rated for the assigned aircraft type")
        if not crew["training_valid_until"] > lg["scheduled_departure_utc"]:
            raise err("ERR_CREW_ILLEGAL", 422,
                      "Crew training expires at or before the leg departure")
        if not duty_check_passes(crew, lg):
            raise err("ERR_CREW_ILLEGAL", 422,
                      "Duty-time limit of 840 minutes would be exceeded")
    # Crew interval conflict (priority 10): unbuffered half-open.
    for crew in (pic, sic):
        if crew_interval_conflict(crew["id"], lg):
            raise err("ERR_CREW_INTERVAL_CONFLICT", 422,
                      "Crew member is committed to an overlapping leg")
    # Maintenance / training conflict gate (priority 11).
    if lg["aircraft_id"] and maintenance_conflict(lg["aircraft_id"], lg):
        raise err("ERR_MAINTENANCE_CONFLICT", 422,
                  "A maintenance window intersects the leg interval")
    lg["pic_crew_id"] = pic["id"]
    lg["sic_crew_id"] = sic["id"]
    lg["status"] = "CREWED"
    touch(lg)
    return respond_object(flight_leg_json(lg))


@bp.post("/flight-ops/flight-legs/<leg_id>/release")
def release_leg(leg_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    lg = get_leg(leg_id)
    if lg["status"] != "CREWED":
        raise err_invalid_state("Only a CREWED leg can be released")
    t = db.trips.get(lg["trip_request_id"])
    if t is None or t["approval_status"] != "APPROVED":
        raise err_invalid_state("Release requires the parent trip to be APPROVED")
    for o in catering_of_leg(lg["id"]):
        if o["status"] == "REQUESTED":
            raise err("ERR_SERVICE_NOT_READY", 422,
                      "A catering order is still REQUESTED")
    for gt in transports_of_leg(lg["id"]):
        if gt["status"] == "REQUESTED":
            raise err("ERR_SERVICE_NOT_READY", 422,
                      "A ground transport is still REQUESTED")
    lg["status"] = "RELEASED"
    touch(lg)
    return respond_object(flight_leg_json(lg))


@bp.post("/flight-ops/flight-legs/<leg_id>/complete")
def complete_leg(leg_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    lg = get_leg(leg_id)
    t = db.trips.get(lg["trip_request_id"])
    charter_covered = t is not None and accepted_charter_for_trip(t["id"]) is not None
    if lg["status"] == "RELEASED":
        pass
    elif lg["status"] == "PLANNED" and charter_covered:
        # A charter-operated trip flies outside the fleet: its legs complete
        # directly once the charter vendor has flown them.
        pass
    else:
        raise err("ERR_LEG_NOT_RELEASED", 422,
                  "Complete requires the leg to be in RELEASED")
    if not db.now() >= lg["scheduled_arrival_utc"]:
        raise err_invalid_state(
            "The logical clock has not reached the leg's scheduled arrival")
    lg["status"] = "COMPLETED"
    touch(lg)
    # System transition: when every sibling leg is COMPLETED the parent trip
    # advances DISPATCHED -> COMPLETED; settlement stays UNSETTLED.
    if t is not None and t["assignment_status"] == "DISPATCHED":
        if all(s["status"] == "COMPLETED" for s in legs_of_trip(t["id"])):
            t["assignment_status"] = "COMPLETED"
            touch(t)
    return respond_object(flight_leg_json(lg))


@bp.post("/flight-ops/flight-legs/<leg_id>/cancel")
def cancel_leg(leg_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    lg = get_leg(leg_id)
    if lg["status"] not in ("PLANNED", "AIRCRAFT_ASSIGNED", "CREWED"):
        raise err_invalid_state(
            "Only a PLANNED, AIRCRAFT_ASSIGNED, or CREWED leg can be cancelled")
    lg["status"] = "CANCELLED"
    touch(lg)
    cascade_leg_cancelled(lg)
    return respond_object(flight_leg_json(lg))


# ---------------------------------------------------------------------------
# CateringOrder (child of FlightLeg)
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/flight-legs/<leg_id>/catering-orders")
def create_catering(leg_id):
    authenticate()
    require_roles(DISP)
    lg = get_leg(leg_id)
    data = get_body([
        {"name": "vendor_name", "type": "string", "required": True},
        {"name": "menu_code", "type": "string", "required": True},
        {"name": "headcount", "type": "integer", "required": True},
        {"name": "quoted_cost_cents", "type": "integer", "required": True},
    ])
    if data["headcount"] < 1:
        raise err_validation("headcount must be >= 1")
    if data["quoted_cost_cents"] < 0:
        raise err_validation("quoted_cost_cents must be >= 0")
    o = new_common()
    o.update({
        "flight_leg_id": lg["id"],
        "vendor_name": data["vendor_name"],
        "menu_code": data["menu_code"],
        "headcount": data["headcount"],
        "quoted_cost_cents": data["quoted_cost_cents"],
        "status": "REQUESTED",
    })
    db.catering_orders[o["id"]] = o
    return respond_object(catering_order_json(o), 201)


@bp.get("/flight-ops/flight-legs/<leg_id>/catering-orders")
def list_catering(leg_id):
    authenticate()
    require_roles(DISP, MGR)
    lg = get_leg(leg_id)
    items = sorted_items(catering_of_leg(lg["id"]))
    return paginate([catering_order_json(o) for o in items])


@bp.post("/flight-ops/catering-orders/<order_id>/confirm")
def confirm_catering(order_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    o = get_catering_order(order_id)
    if o["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED catering order can be confirmed")
    o["status"] = "CONFIRMED"
    touch(o)
    return respond_object(catering_order_json(o))


@bp.post("/flight-ops/catering-orders/<order_id>/deliver")
def deliver_catering(order_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    o = get_catering_order(order_id)
    if o["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED catering order can be delivered")
    lg = db.flight_legs.get(o["flight_leg_id"])
    if lg is None or lg["status"] not in ("CREWED", "RELEASED"):
        raise err_invalid_state(
            "Catering can be delivered only once the leg is CREWED or RELEASED")
    o["status"] = "DELIVERED"
    touch(o)
    return respond_object(catering_order_json(o))


@bp.post("/flight-ops/catering-orders/<order_id>/cancel")
def cancel_catering(order_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    o = get_catering_order(order_id)
    if o["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err_invalid_state(
            "Only a REQUESTED or CONFIRMED catering order can be cancelled")
    o["status"] = "CANCELLED"
    touch(o)
    return respond_object(catering_order_json(o))


# ---------------------------------------------------------------------------
# GroundTransport (child of FlightLeg)
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/flight-legs/<leg_id>/ground-transports")
def create_ground_transport(leg_id):
    authenticate()
    require_roles(DISP)
    lg = get_leg(leg_id)
    data = get_body([
        {"name": "provider_name", "type": "string", "required": True},
        {"name": "pickup_minutes_after_arrival", "type": "integer", "required": True},
        {"name": "quoted_cost_cents", "type": "integer", "required": True},
    ])
    if data["pickup_minutes_after_arrival"] < 0:
        raise err_validation("pickup_minutes_after_arrival must be >= 0")
    if data["quoted_cost_cents"] < 0:
        raise err_validation("quoted_cost_cents must be >= 0")
    t = new_common()
    t.update({
        "flight_leg_id": lg["id"],
        "provider_name": data["provider_name"],
        "pickup_minutes_after_arrival": data["pickup_minutes_after_arrival"],
        "quoted_cost_cents": data["quoted_cost_cents"],
        "status": "REQUESTED",
    })
    db.ground_transports[t["id"]] = t
    return respond_object(ground_transport_json(t), 201)


@bp.get("/flight-ops/flight-legs/<leg_id>/ground-transports")
def list_ground_transports(leg_id):
    authenticate()
    require_roles(DISP, MGR)
    lg = get_leg(leg_id)
    items = sorted_items(transports_of_leg(lg["id"]))
    return paginate([ground_transport_json(t) for t in items])


@bp.post("/flight-ops/ground-transports/<transport_id>/confirm")
def confirm_ground_transport(transport_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    t = get_ground_transport(transport_id)
    if t["status"] != "REQUESTED":
        raise err_invalid_state("Only a REQUESTED ground transport can be confirmed")
    t["status"] = "CONFIRMED"
    touch(t)
    return respond_object(ground_transport_json(t))


@bp.post("/flight-ops/ground-transports/<transport_id>/complete")
def complete_ground_transport(transport_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    t = get_ground_transport(transport_id)
    if t["status"] != "CONFIRMED":
        raise err_invalid_state("Only a CONFIRMED ground transport can be completed")
    lg = db.flight_legs.get(t["flight_leg_id"])
    if lg is None or lg["status"] != "COMPLETED":
        raise err_invalid_state(
            "Ground transport completes only after the parent leg has completed")
    t["status"] = "COMPLETED"
    touch(t)
    return respond_object(ground_transport_json(t))


@bp.post("/flight-ops/ground-transports/<transport_id>/cancel")
def cancel_ground_transport(transport_id):
    authenticate()
    require_roles(DISP)
    ignore_body()
    t = get_ground_transport(transport_id)
    if t["status"] not in ("REQUESTED", "CONFIRMED"):
        raise err_invalid_state(
            "Only a REQUESTED or CONFIRMED ground transport can be cancelled")
    t["status"] = "CANCELLED"
    touch(t)
    return respond_object(ground_transport_json(t))
