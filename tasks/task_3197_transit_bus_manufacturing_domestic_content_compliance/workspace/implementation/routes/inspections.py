"""Routes: inspection records."""
from flask import Blueprint, request
from db import DB, stamp_new
from errors import (
    err_not_found, err_invalid_request, err_invalid_state,
    err_inspection_defects,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import recompute_zev

bp = Blueprint("inspections", __name__)

INSPECTION_TYPES = {"PLANT", "DELIVERY"}
RESULTS = {"PASS", "FAIL"}


@bp.post("/api/inspection-records")
def create_inspection():
    require_roles("AgencyInspector")
    body = get_body()
    bus_unit_id = body.get("bus_unit_id")
    inspection_type = body.get("inspection_type")
    inspector_id = body.get("inspector_id")
    result = body.get("result")
    defects = body.get("defects", [])
    if bus_unit_id is None:
        raise err_invalid_request("Missing required field: bus_unit_id")
    if inspection_type is None:
        raise err_invalid_request("Missing required field: inspection_type")
    if inspection_type not in INSPECTION_TYPES:
        raise err_invalid_request("Unknown inspection_type")
    if inspector_id is None:
        raise err_invalid_request("Missing required field: inspector_id")
    if result is None:
        raise err_invalid_request("Missing required field: result")
    if result not in RESULTS:
        raise err_invalid_request("Unknown result")
    if defects is None:
        defects = []
    if not isinstance(defects, list):
        raise err_invalid_request("defects must be an array")
    bus = DB.buses.get(bus_unit_id)
    if bus is None:
        raise err_not_found("BusUnit not found")
    # State-machine legality (priority 4) before defects rule.
    if inspection_type == "PLANT":
        if bus["status"] != "PLANT_INSPECTION":
            raise err_invalid_state("Bus is not PLANT_INSPECTION")
    else:  # DELIVERY
        if bus["status"] != "DELIVERED":
            raise err_invalid_state("Bus is not DELIVERED")
    if result == "FAIL" and len(defects) == 0:
        raise err_inspection_defects()
    rec = {
        "bus_unit_id": bus_unit_id,
        "inspection_type": inspection_type,
        "inspector_id": inspector_id,
        "result": result,
        "defects": defects,
    }
    stamp_new(rec, common=False)
    DB.inspections[rec["id"]] = rec
    # Drive bus transition.
    from db import touch
    if inspection_type == "PLANT":
        if result == "PASS":
            bus["status"] = "IN_TRANSIT"
            touch(bus)
        else:
            bus["status"] = "BUILT"
            touch(bus)
    else:  # DELIVERY
        contract = DB.contracts.get(bus["contract_id"])
        if result == "PASS":
            bus["status"] = "ACCEPTED"
            if bus["payment_status"] == "UNPAID":
                bus["payment_status"] = "INVOICED"
            touch(bus)
            if contract is not None:
                recompute_zev(contract["agency_id"])
        else:
            bus["status"] = "REJECTED"
            touch(bus)
            if contract is not None:
                recompute_zev(contract["agency_id"])
    return success_obj(public(rec), 201)


@bp.get("/api/inspection-records/<inspectionRecordId>")
def get_inspection(inspectionRecordId):
    require_roles("PlatformAdmin", "AgencyInspector", "Auditor")
    r = DB.inspections.get(inspectionRecordId)
    if r is None:
        raise err_not_found("InspectionRecord not found")
    return success_obj(public(r))


@bp.get("/api/bus-units/<busUnitId>/inspection-records")
def bus_inspections(busUnitId):
    require_roles("PlatformAdmin", "AgencyInspector", "Auditor", "ProductionPlanner")
    if busUnitId not in DB.buses:
        raise err_not_found("BusUnit not found")
    limit, offset = parse_pagination(request.args)
    inspection_type = request.args.get("inspection_type")
    items = [r for r in DB.inspections.values() if r["bus_unit_id"] == busUnitId]
    if inspection_type is not None:
        items = [r for r in items if r["inspection_type"] == inspection_type]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(r) for r in window], limit, offset, total)
