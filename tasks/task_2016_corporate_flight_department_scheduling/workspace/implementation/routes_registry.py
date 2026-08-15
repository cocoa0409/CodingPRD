"""Registry endpoints: clock, Aircraft, DocumentPermit, CrewMember,
BusinessUnit, PassengerProfile, SiflRatePeriod."""

from flask import Blueprint, request

from httpkit import (
    authenticate, err, err_constraint, err_unauthorized, err_validation,
    get_body, ignore_body, paginate, require_roles, respond_object,
    sorted_items,
)
from serializers import (
    aircraft_json, business_unit_json, crew_member_json, document_json,
    passenger_json, sifl_rate_period_json,
)
from services import (
    AIRCRAFT_TYPES, DOC_KINDS, PRIORITY_TIERS, REQUIRED_DOC_KINDS,
    SEAT_QUALIFICATIONS, advance_clock, aircraft_posture,
    cascade_aircraft_grounded, document_status, documents_of_aircraft,
    get_aircraft, get_business_unit, get_crew_member, get_passenger,
    get_rate_period, new_common, touch, windows_of_aircraft,
)
from store import db
from util import fmt_ts

bp = Blueprint("registry", __name__)

MGR = "FlightDeptManager"
DISP = "Dispatcher"
MAINT = "MaintenancePlanner"
FIN = "FinanceAdmin"
EXEC = "ExecutiveRequester"


# ---------------------------------------------------------------------------
# Logical clock
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/_clock/set_current_utc")
def set_clock():
    authenticate()
    require_roles(MGR)
    data = get_body([
        {"name": "to_iso8601", "type": "datetime", "required": True},
    ])
    advance_clock(data["to_iso8601"])
    return respond_object({"now_utc": fmt_ts(db.now())})


# ---------------------------------------------------------------------------
# Aircraft
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/aircraft")
def create_aircraft():
    authenticate()
    require_roles(MGR)
    data = get_body([
        {"name": "tail_number", "type": "string", "required": True},
        {"name": "aircraft_type", "type": "enum", "values": AIRCRAFT_TYPES, "required": True},
        {"name": "passenger_capacity", "type": "integer", "required": True},
        {"name": "home_base_icao", "type": "string", "required": True},
    ])
    if data["passenger_capacity"] < 1:
        raise err_validation("passenger_capacity must be >= 1")
    for a in db.aircraft.values():
        if a["tail_number"] == data["tail_number"]:
            raise err_validation("tail_number must be unique across the fleet")
    a = new_common()
    a.update({
        "tail_number": data["tail_number"],
        "aircraft_type": data["aircraft_type"],
        "passenger_capacity": data["passenger_capacity"],
        "home_base_icao": data["home_base_icao"],
        "status": "ACTIVE",
    })
    db.aircraft[a["id"]] = a
    return respond_object(aircraft_json(a), 201)


@bp.get("/flight-ops/aircraft")
def list_aircraft():
    authenticate()
    require_roles(MGR, DISP, MAINT, FIN)
    items = sorted_items(db.aircraft.values())
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [a for a in items if a["status"] == flt_status]
    flt_posture = request.args.get("posture")
    if flt_posture is not None:
        items = [a for a in items if aircraft_posture(a)[0] == flt_posture]
    return paginate([aircraft_json(a) for a in items])


@bp.get("/flight-ops/aircraft/<aircraft_id>")
def read_aircraft(aircraft_id):
    authenticate()
    require_roles(MGR, DISP, MAINT, FIN)
    return respond_object(aircraft_json(get_aircraft(aircraft_id)))


@bp.post("/flight-ops/aircraft/<aircraft_id>/ground")
def ground_aircraft(aircraft_id):
    authenticate()
    require_roles(MAINT)
    ignore_body()
    a = get_aircraft(aircraft_id)
    if a["status"] != "ACTIVE":
        raise err("ERR_INVALID_STATE", 409,
                  "Only an ACTIVE aircraft can be grounded")
    a["status"] = "GROUNDED"
    touch(a)
    cascade_aircraft_grounded(a)
    return respond_object(aircraft_json(a))


@bp.post("/flight-ops/aircraft/<aircraft_id>/return-to-service")
def return_to_service(aircraft_id):
    authenticate()
    require_roles(MAINT)
    ignore_body()
    a = get_aircraft(aircraft_id)
    if a["status"] != "GROUNDED":
        raise err("ERR_INVALID_STATE", 409,
                  "Only a GROUNDED aircraft can return to service")
    now = db.now()
    for w in windows_of_aircraft(a["id"]):
        if (w["status"] in ("PLANNED", "IN_PROGRESS")
                and w["window_start_utc"] <= now < w["window_end_utc"]):
            raise err("ERR_INVALID_STATE", 409,
                      "A maintenance window overlaps the current clock")
    for d in documents_of_aircraft(a["id"]):
        if d["doc_kind"] in REQUIRED_DOC_KINDS and document_status(d) != "CURRENT":
            raise err("ERR_INVALID_STATE", 409,
                      f"Required document {d['doc_kind']} is not CURRENT")
    a["status"] = "ACTIVE"
    touch(a)
    return respond_object(aircraft_json(a))


@bp.post("/flight-ops/aircraft/<aircraft_id>/retire")
def retire_aircraft(aircraft_id):
    authenticate()
    require_roles(MGR)
    ignore_body()
    a = get_aircraft(aircraft_id)
    if a["status"] not in ("ACTIVE", "GROUNDED"):
        raise err("ERR_INVALID_STATE", 409,
                  "Only an ACTIVE or GROUNDED aircraft can be retired")
    for lg in db.flight_legs.values():
        if lg["aircraft_id"] == a["id"] and lg["status"] in (
                "AIRCRAFT_ASSIGNED", "CREWED", "RELEASED"):
            raise err("ERR_INVALID_STATE", 409,
                      "A flight leg currently holds this tail")
    a["status"] = "RETIRED"
    touch(a)
    return respond_object(aircraft_json(a))


# ---------------------------------------------------------------------------
# DocumentPermit (child of Aircraft)
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/aircraft/<aircraft_id>/documents")
def create_document(aircraft_id):
    authenticate()
    require_roles(MAINT)
    a = get_aircraft(aircraft_id)
    data = get_body([
        {"name": "doc_kind", "type": "enum", "values": DOC_KINDS, "required": True},
        {"name": "identifier", "type": "string", "required": True},
        {"name": "issued_at", "type": "datetime", "required": True},
        {"name": "expires_at", "type": "datetime", "required": True},
    ])
    d = new_common()
    d.update({
        "aircraft_id": a["id"],
        "doc_kind": data["doc_kind"],
        "identifier": data["identifier"],
        "issued_at": data["issued_at"],
        "expires_at": data["expires_at"],
    })
    db.documents[d["id"]] = d
    # Parent posture is derived on read; the recomputation is implicit.
    return respond_object(document_json(d), 201)


@bp.get("/flight-ops/aircraft/<aircraft_id>/documents")
def list_documents(aircraft_id):
    authenticate()
    require_roles(MGR, DISP, MAINT)
    a = get_aircraft(aircraft_id)
    items = sorted_items(documents_of_aircraft(a["id"]))
    return paginate([document_json(d) for d in items])


# ---------------------------------------------------------------------------
# CrewMember
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/crew-members")
def create_crew_member():
    authenticate()
    require_roles(MGR)
    data = get_body([
        {"name": "employee_number", "type": "string", "required": True},
        {"name": "full_name", "type": "string", "required": True},
        {"name": "seat_qualification", "type": "enum",
         "values": SEAT_QUALIFICATIONS, "required": True},
        {"name": "type_ratings", "type": "enum_array",
         "values": AIRCRAFT_TYPES, "required": True},
        {"name": "training_valid_until", "type": "datetime", "required": True},
    ])
    for c in db.crew_members.values():
        if c["employee_number"] == data["employee_number"]:
            raise err_validation("employee_number must be unique")
    c = new_common()
    c.update({
        "employee_number": data["employee_number"],
        "full_name": data["full_name"],
        "seat_qualification": data["seat_qualification"],
        "type_ratings": list(data["type_ratings"]),
        "training_valid_until": data["training_valid_until"],
        "duty_window_start_utc": None,
        "duty_minutes_used": 0,
        "status": "ACTIVE",
    })
    db.crew_members[c["id"]] = c
    return respond_object(crew_member_json(c), 201)


@bp.get("/flight-ops/crew-members")
def list_crew_members():
    authenticate()
    require_roles(MGR, DISP, FIN)
    items = sorted_items(db.crew_members.values())
    flt_status = request.args.get("status")
    if flt_status is not None:
        items = [c for c in items if c["status"] == flt_status]
    flt_seat = request.args.get("seat_qualification")
    if flt_seat is not None:
        items = [c for c in items if c["seat_qualification"] == flt_seat]
    return paginate([crew_member_json(c) for c in items])


@bp.get("/flight-ops/crew-members/<crew_id>")
def read_crew_member(crew_id):
    authenticate()
    require_roles(MGR, DISP, FIN)
    return respond_object(crew_member_json(get_crew_member(crew_id)))


# ---------------------------------------------------------------------------
# BusinessUnit
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/business-units")
def create_business_unit():
    authenticate()
    require_roles(FIN)
    data = get_body([
        {"name": "bu_code", "type": "string", "required": True},
        {"name": "name", "type": "string", "required": True},
        {"name": "annual_flight_budget_cents", "type": "integer", "required": True},
    ])
    if data["annual_flight_budget_cents"] < 0:
        raise err_validation("annual_flight_budget_cents must be >= 0")
    for b in db.business_units.values():
        if b["bu_code"] == data["bu_code"]:
            raise err_validation("bu_code must be unique")
    b = new_common()
    b.update({
        "bu_code": data["bu_code"],
        "name": data["name"],
        "annual_flight_budget_cents": data["annual_flight_budget_cents"],
        "allocated_cents": 0,
    })
    db.business_units[b["id"]] = b
    return respond_object(business_unit_json(b), 201)


@bp.get("/flight-ops/business-units")
def list_business_units():
    authenticate()
    require_roles(FIN, MGR)
    items = sorted_items(db.business_units.values())
    return paginate([business_unit_json(b) for b in items])


@bp.get("/flight-ops/business-units/<bu_id>")
def read_business_unit(bu_id):
    authenticate()
    require_roles(FIN, MGR)
    return respond_object(business_unit_json(get_business_unit(bu_id)))


# ---------------------------------------------------------------------------
# PassengerProfile
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/passenger-profiles")
def create_passenger():
    authenticate()
    require_roles(MGR)
    data = get_body([
        {"name": "employee_number", "type": "string", "required": True},
        {"name": "full_name", "type": "string", "required": True},
        {"name": "priority_tier", "type": "enum", "values": PRIORITY_TIERS, "required": True},
        {"name": "home_bu_id", "type": "string", "required": True},
        {"name": "sifl_control_employee", "type": "boolean", "required": True},
    ])
    get_business_unit(data["home_bu_id"], fk=True)
    for p in db.passengers.values():
        if p["employee_number"] == data["employee_number"]:
            raise err_validation("employee_number must be unique")
    p = new_common()
    p.update({
        "employee_number": data["employee_number"],
        "full_name": data["full_name"],
        "priority_tier": data["priority_tier"],
        "home_bu_id": data["home_bu_id"],
        "sifl_control_employee": data["sifl_control_employee"],
    })
    db.passengers[p["id"]] = p
    return respond_object(passenger_json(p), 201)


@bp.get("/flight-ops/passenger-profiles")
def list_passengers():
    authenticate()
    require_roles(MGR, DISP, FIN)
    items = sorted_items(db.passengers.values())
    flt_bu = request.args.get("home_bu_id")
    if flt_bu is not None:
        items = [p for p in items if p["home_bu_id"] == flt_bu]
    return paginate([passenger_json(p) for p in items])


@bp.get("/flight-ops/passenger-profiles/<passenger_id>")
def read_passenger(passenger_id):
    authenticate()
    require_roles(MGR, DISP, FIN)
    return respond_object(passenger_json(get_passenger(passenger_id)))


# ---------------------------------------------------------------------------
# SiflRatePeriod
# ---------------------------------------------------------------------------

@bp.post("/flight-ops/sifl-rate-periods")
def create_rate_period():
    authenticate()
    require_roles(FIN)
    data = get_body([
        {"name": "period_start_utc", "type": "datetime", "required": True},
        {"name": "period_end_utc", "type": "datetime", "required": True},
        {"name": "terminal_charge_cents", "type": "integer", "required": True},
        {"name": "rate_band_1_cents_per_mile", "type": "integer", "required": True},
        {"name": "rate_band_2_cents_per_mile", "type": "integer", "required": True},
        {"name": "rate_band_3_cents_per_mile", "type": "integer", "required": True},
        {"name": "control_employee_multiplier_pct", "type": "integer", "required": True},
    ])
    if not data["period_end_utc"] > data["period_start_utc"]:
        raise err_validation("period_end_utc must be strictly after period_start_utc")
    for f in ("terminal_charge_cents", "rate_band_1_cents_per_mile",
              "rate_band_2_cents_per_mile", "rate_band_3_cents_per_mile"):
        if data[f] < 0:
            raise err_validation(f"{f} must be >= 0")
    # Half-open intersection against every existing period.
    ns, ne = data["period_start_utc"], data["period_end_utc"]
    for p in db.sifl_rate_periods.values():
        if ns < p["period_end_utc"] and p["period_start_utc"] < ne:
            raise err("ERR_OVERLAPPING_RATE_PERIOD", 422,
                      "New SiflRatePeriod overlaps an existing period")
    p = new_common()
    p.update({
        "period_start_utc": ns,
        "period_end_utc": ne,
        "terminal_charge_cents": data["terminal_charge_cents"],
        "rate_band_1_cents_per_mile": data["rate_band_1_cents_per_mile"],
        "rate_band_2_cents_per_mile": data["rate_band_2_cents_per_mile"],
        "rate_band_3_cents_per_mile": data["rate_band_3_cents_per_mile"],
        "control_employee_multiplier_pct": data["control_employee_multiplier_pct"],
    })
    db.sifl_rate_periods[p["id"]] = p
    return respond_object(sifl_rate_period_json(p), 201)


@bp.get("/flight-ops/sifl-rate-periods")
def list_rate_periods():
    authenticate()
    require_roles(FIN, MGR)
    items = sorted_items(db.sifl_rate_periods.values())
    return paginate([sifl_rate_period_json(p) for p in items])


@bp.get("/flight-ops/sifl-rate-periods/<period_id>")
def read_rate_period(period_id):
    authenticate()
    require_roles(FIN, MGR)
    return respond_object(sifl_rate_period_json(get_rate_period(period_id)))
