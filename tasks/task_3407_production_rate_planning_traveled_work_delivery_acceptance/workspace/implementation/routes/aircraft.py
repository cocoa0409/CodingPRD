"""Aircraft units and their station work packages (PRD 3.1, 3.4)."""
from flask import Blueprint

import svc
from core import (
    ALL_ROLES,
    ApiError,
    body,
    db,
    endpoint,
    f_date,
    f_int,
    f_str,
    new_row,
    paginate,
    q_enum,
    raw_int,
    respond_object,
    sort_created,
    touch,
)

bp = Blueprint("aircraft", __name__, url_prefix="/api")

PRODUCTION_STATUSES = ("IN_PRODUCTION", "ASSEMBLY_COMPLETE", "IN_STORAGE", "DELIVERED")
WORK_PACKAGE_STATUSES = ("OPEN", "COMPLETE", "TRAVELED")


# ---------------------------------------------------------------------------
# Aircraft units
# ---------------------------------------------------------------------------
@bp.post("/programs/<program_id>/aircraft-units")
@endpoint("ProductionPlanner")
def create_aircraft(program_id):
    program = svc.need_program(program_id)
    payload = body()
    # Body-referenced FK existence: customer_id must resolve.
    referenced = payload.get("customer_id")
    if isinstance(referenced, str):
        svc.need_customer(referenced)
    # rung 8 -- line_number unique within the program
    line = payload.get("line_number")
    if raw_int(line) and any(
        a["program_id"] == program["id"] and a["line_number"] == line
        for a in db.aircraft.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    # rung 10 -- body shape
    customer_id = f_str(payload, "customer_id")
    line_number = f_int(payload, "line_number", minimum=1)
    configuration_code = f_str(payload, "configuration_code")
    ordered_configuration_code = f_str(payload, "ordered_configuration_code")
    contract_price_cents = f_int(payload, "contract_price_cents", minimum=1)
    contracted_delivery_date = f_date(payload, "contracted_delivery_date")
    aircraft = new_row(
        "AircraftUnit",
        program_id=program["id"],
        customer_id=customer_id,
        line_number=line_number,
        configuration_code=configuration_code,
        ordered_configuration_code=ordered_configuration_code,
        contract_price_cents=contract_price_cents,
        contracted_delivery_date=contracted_delivery_date.isoformat(),
        production_status="IN_PRODUCTION",
        quality_status="CLEAR",
        delivery_status="NOT_STARTED",
        scheduled_delivery_date=None,
    )
    db.aircraft[aircraft["id"]] = aircraft
    return respond_object(svc.dump_aircraft(aircraft), 201)


@bp.get("/aircraft-units/<aircraft_id>")
@endpoint(*ALL_ROLES)
def get_aircraft(aircraft_id):
    return respond_object(svc.dump_aircraft(svc.need_aircraft(aircraft_id)))


@bp.get("/programs/<program_id>/aircraft-units")
@endpoint("ProgramAdmin", "ProductionPlanner", "LineManager", "QualityInspector", "DeliveryManager")
def list_program_aircraft(program_id):
    svc.need_program(program_id)
    production_status = q_enum("production_status", PRODUCTION_STATUSES)
    rows = [a for a in db.aircraft.values() if a["program_id"] == program_id]
    if production_status is not None:
        rows = [a for a in rows if a["production_status"] == production_status]
    return paginate(sort_created(rows), svc.dump_aircraft)


@bp.get("/customers/<customer_id>/aircraft-units")
@endpoint("ProgramAdmin", "DeliveryManager", "Customer")
def list_customer_aircraft(customer_id):
    svc.need_customer(customer_id)
    production_status = q_enum("production_status", PRODUCTION_STATUSES)
    rows = [a for a in db.aircraft.values() if a["customer_id"] == customer_id]
    if production_status is not None:
        rows = [a for a in rows if a["production_status"] == production_status]
    return paginate(sort_created(rows), svc.dump_aircraft)


# ---------------------------------------------------------------------------
# Work packages
# ---------------------------------------------------------------------------
@bp.post("/aircraft-units/<aircraft_id>/work-packages")
@endpoint("LineManager")
def create_work_package(aircraft_id):
    aircraft = svc.need_aircraft(aircraft_id)
    payload = body()
    # rung 8 -- station_sequence unique per aircraft
    seq = payload.get("station_sequence")
    if raw_int(seq) and any(
        wp["aircraft_id"] == aircraft["id"] and wp["station_sequence"] == seq
        for wp in db.work_packages.values()
    ):
        raise ApiError("ERR_DUPLICATE_CODE")
    # rung 10 -- body shape
    station_sequence = f_int(payload, "station_sequence", minimum=1)
    description = f_str(payload, "description")
    planned_hours = f_int(payload, "planned_hours", minimum=1)
    package = new_row(
        "WorkPackage",
        aircraft_id=aircraft["id"],
        station_sequence=station_sequence,
        description=description,
        planned_hours=planned_hours,
        traveled_hours=None,
        status="OPEN",
    )
    db.work_packages[package["id"]] = package
    return respond_object(svc.dump_work_package(package), 201)


@bp.get("/aircraft-units/<aircraft_id>/work-packages")
@endpoint("ProgramAdmin", "ProductionPlanner", "LineManager")
def list_work_packages(aircraft_id):
    svc.need_aircraft(aircraft_id)
    status = q_enum("status", WORK_PACKAGE_STATUSES)
    rows = [wp for wp in db.work_packages.values() if wp["aircraft_id"] == aircraft_id]
    if status is not None:
        rows = [wp for wp in rows if wp["status"] == status]
    return paginate(sort_created(rows), svc.dump_work_package)


@bp.get("/work-packages/<package_id>")
@endpoint("ProgramAdmin", "ProductionPlanner", "LineManager")
def get_work_package(package_id):
    return respond_object(svc.dump_work_package(svc.need_work_package(package_id)))


@bp.post("/work-packages/<package_id>/complete")
@endpoint("LineManager")
def complete_work_package(package_id):
    package = svc.need_work_package(package_id)
    if package["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    package["status"] = "COMPLETE"
    touch(package)
    svc.bubble_up_assembly(svc.need_aircraft(package["aircraft_id"]))
    return respond_object(svc.dump_work_package(package))


@bp.post("/work-packages/<package_id>/travel")
@endpoint("LineManager")
def travel_work_package(package_id):
    package = svc.need_work_package(package_id)
    payload = body()
    if package["status"] != "OPEN":
        raise ApiError("ERR_INVALID_TRANSITION")
    # rung 10 -- traveled_hours payload of at least one (PRD 3.4)
    traveled_hours = f_int(payload, "traveled_hours", minimum=1)
    package["traveled_hours"] = traveled_hours
    package["status"] = "TRAVELED"
    touch(package)
    # Cascade link 1: provisional TRAVELED_WORK rework order (PRD 3.4/3.5).
    svc.create_rework_order(
        package["aircraft_id"],
        "TRAVELED_WORK",
        traveled_hours,
        work_package_id=package["id"],
    )
    # Cascade link 2: program.traveled_work_open_hours recomputes live.
    svc.bubble_up_assembly(svc.need_aircraft(package["aircraft_id"]))
    return respond_object(svc.dump_work_package(package))
