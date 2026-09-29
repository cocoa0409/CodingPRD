"""Programme configuration: planning areas, plan formulas, hearing rooms, clock, applicants."""

from flask import Blueprint

import auth
import clock
import envelope
import shape
import store
from errors import ApiError

bp = Blueprint("config", __name__)

READ_ROLES_ALL = auth.STAFF_AND_PARTIES
READ_ROLES_NO_PUBLIC = ["ProgramAdmin", "IntakeAnalyst", "ReviewAnalyst", "DecisionOfficer",
                        "AppealBoardMember", "Applicant"]
FORMULA_STATUSES = ("DRAFT", "ACTIVE", "SUPERSEDED")
ROOM_STATUSES = ("AVAILABLE", "OUT_OF_SERVICE")
AREA_STATUSES = ("ACTIVE", "RETIRED")
ORG_TYPES = ("HOSPITAL", "NURSING_FACILITY", "PHYSICIAN_GROUP", "OTHER")


# --- planning areas ----------------------------------------------------------

@bp.post("/health-service-areas")
def create_area():
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    code = shape.hsa_code_field(body, "code")
    name = shape.string_field(body, "name")
    population = shape.int_field(body, "population_projection", minimum=1)
    existing = shape.int_field(body, "existing_licensed_beds", required=False, default=0,
                               minimum=0)
    status = shape.enum_field(body, "status", AREA_STATUSES, required=False, default="ACTIVE")
    for row in store.rows("health_service_areas"):
        if row["code"] == code:
            raise ApiError("ERR_DUPLICATE_LOI", "A planning area with this code already exists.")
    record = store.create("health_service_areas", {
        "code": code,
        "name": name,
        "population_projection": population,
        "existing_licensed_beds": existing,
        "approved_unimplemented_beds": 0,
        "capital_authorization_committed_cents": 0,
        "status": status,
    })
    return envelope.ok(record, 201)


@bp.get("/health-service-areas/<record_id>")
def read_area(record_id):
    auth.identity(READ_ROLES_ALL)
    record = store.get("health_service_areas", record_id)
    if record is None:
        raise ApiError("ERR_HSA_NOT_FOUND")
    return envelope.ok(record)


# --- state plan formulas -----------------------------------------------------

@bp.post("/state-plan-formulas")
def create_formula():
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    service_type = shape.enum_field(body, "service_type", shape.SERVICE_TYPES)
    effective_from = shape.date_field(body, "effective_from_date")
    use_rate = shape.number_field(body, "use_rate_per_1000", exclusive_min=0)
    alos = shape.number_field(body, "average_length_of_stay_days", exclusive_min=0)
    base_rate = shape.number_field(body, "base_target_occupancy_rate",
                                   exclusive_min=0, exclusive_max=1)
    high_rate = shape.number_field(body, "high_volume_target_occupancy_rate",
                                   exclusive_min=0, exclusive_max=1)
    threshold = shape.int_field(body, "high_volume_bed_threshold", minimum=1)
    status = shape.enum_field(body, "status", FORMULA_STATUSES, required=False, default="ACTIVE")
    record = store.create("state_plan_formulas", {
        "service_type": service_type,
        "effective_from_date": effective_from,
        "use_rate_per_1000": use_rate,
        "average_length_of_stay_days": alos,
        "base_target_occupancy_rate": base_rate,
        "high_volume_target_occupancy_rate": high_rate,
        "high_volume_bed_threshold": threshold,
        "status": status,
    })
    return envelope.ok(record, 201)


@bp.patch("/state-plan-formulas/<record_id>")
def amend_formula(record_id):
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    use_rate = shape.number_field(body, "use_rate_per_1000", required=False,
                                 default=None, exclusive_min=0)
    alos = shape.number_field(body, "average_length_of_stay_days", required=False,
                              default=None, exclusive_min=0)
    base_rate = shape.number_field(body, "base_target_occupancy_rate", required=False,
                                   default=None, exclusive_min=0, exclusive_max=1)
    high_rate = shape.number_field(body, "high_volume_target_occupancy_rate", required=False,
                                   default=None, exclusive_min=0, exclusive_max=1)
    threshold = shape.int_field(body, "high_volume_bed_threshold", required=False,
                                default=None, minimum=1)
    status = shape.enum_field(body, "status", FORMULA_STATUSES, required=False, default=None)
    record = store.get("state_plan_formulas", record_id)
    if record is None:
        raise ApiError("ERR_FORMULA_NOT_FOUND")
    if use_rate is not None:
        record["use_rate_per_1000"] = use_rate
    if alos is not None:
        record["average_length_of_stay_days"] = alos
    if base_rate is not None:
        record["base_target_occupancy_rate"] = base_rate
    if high_rate is not None:
        record["high_volume_target_occupancy_rate"] = high_rate
    if threshold is not None:
        record["high_volume_bed_threshold"] = threshold
    if status is not None:
        record["status"] = status
    store.touch(record)
    return envelope.ok(record)


# --- hearing rooms -----------------------------------------------------------

@bp.post("/hearing-rooms")
def create_room():
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    name = shape.string_field(body, "name")
    seating = shape.int_field(body, "seating_capacity", minimum=1)
    buffer_minutes = shape.int_field(body, "setup_buffer_minutes", required=False,
                                     default=60, minimum=0)
    status = shape.enum_field(body, "status", ROOM_STATUSES, required=False, default="AVAILABLE")
    for row in store.rows("hearing_rooms"):
        if row["name"] == name:
            raise ApiError("ERR_DUPLICATE_LOI", "A hearing room with this name already exists.")
    record = store.create("hearing_rooms", {
        "name": name,
        "seating_capacity": seating,
        "setup_buffer_minutes": buffer_minutes,
        "status": status,
    })
    return envelope.ok(record, 201)


# --- logical clock -----------------------------------------------------------

@bp.post("/_clock/set_current_utc")
def set_clock():
    auth.clock_identity()
    body = shape.body()
    _raw, parsed = shape.instant_field(body, "to_iso8601")
    clock.set_now(parsed)
    return envelope.ok({})


# --- applicants --------------------------------------------------------------

@bp.post("/applicants")
def create_applicant():
    auth.identity(["ProgramAdmin"])
    body = shape.body()
    legal_name = shape.string_field(body, "legal_name")
    org_type = shape.enum_field(body, "organization_type", ORG_TYPES)
    email = shape.string_field(body, "contact_email")
    for row in store.rows("applicants"):
        if row["legal_name"] == legal_name:
            raise ApiError("ERR_DUPLICATE_LOI", "An applicant with this legal name exists.")
    record = store.create("applicants", {
        "legal_name": legal_name,
        "organization_type": org_type,
        "contact_email": email,
        "standing": "GOOD",
        "compliance_strike_count": 0,
    })
    return envelope.ok(record, 201)


@bp.get("/applicants/<record_id>")
def read_applicant(record_id):
    auth.identity(READ_ROLES_NO_PUBLIC)
    record = store.get("applicants", record_id)
    if record is None:
        raise ApiError("ERR_APPLICANT_NOT_FOUND")
    return envelope.ok(record)
