"""Routes: bus units."""
from datetime import timedelta
from flask import Blueprint, request
from db import DB, stamp_new, touch, _fmt_logical
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_referential,
    err_accessibility, err_certificate_missing, err_domestic_threshold,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import recompute_zev, recompute_kit, kit_completeness_pct

bp = Blueprint("buses", __name__)

ASSEMBLY_LOCATIONS = {"US_MAIN", "US_ANNEX"}


def get_bus_or_404(bid):
    b = DB.buses.get(bid)
    if b is None:
        raise err_not_found("BusUnit not found")
    return b


@bp.post("/api/bus-units")
def create_bus():
    require_roles("ProductionPlanner")
    body = get_body()
    contract_id = body.get("contract_id")
    config_id = body.get("bus_configuration_id")
    assembly_location = body.get("assembly_location")
    option_order_id = body.get("option_order_id")
    if contract_id is None:
        raise err_invalid_request("Missing required field: contract_id")
    if config_id is None:
        raise err_invalid_request("Missing required field: bus_configuration_id")
    if assembly_location is None:
        raise err_invalid_request("Missing required field: assembly_location")
    if assembly_location not in ASSEMBLY_LOCATIONS:
        raise err_invalid_request("Unknown assembly_location")
    contract = DB.contracts.get(contract_id)
    if contract is None:
        raise err_not_found("Contract not found")
    cfg = DB.configurations.get(config_id)
    if cfg is None:
        raise err_not_found("BusConfiguration not found")
    if option_order_id is not None:
        o = DB.option_orders.get(option_order_id)
        if o is None:
            raise err_not_found("OptionOrder not found")
    if contract["status"] != "ACTIVE":
        raise err_invalid_state("Contract is not ACTIVE")
    rec = {
        "contract_id": contract_id,
        "bus_configuration_id": config_id,
        "option_order_id": option_order_id,
        "serial_number": DB.next_serial(),
        "assembly_location": assembly_location,
        "payment_status": "UNPAID",
        "status": "ORDERED",
        "delivered_at": None,
        "acceptance_deadline": None,
    }
    stamp_new(rec)
    DB.buses[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/bus-units")
def list_buses():
    require_roles(
        "PlatformAdmin", "ProductionPlanner", "ProcurementOfficer",
        "AgencyInspector", "Auditor", "WarrantyAdmin", "ComplianceOfficer",
    )
    limit, offset = parse_pagination(request.args)
    contract_id = request.args.get("contract_id")
    config_id = request.args.get("bus_configuration_id")
    option_order_id = request.args.get("option_order_id")
    status = request.args.get("status")
    items = list(DB.buses.values())
    if contract_id is not None:
        items = [b for b in items if b["contract_id"] == contract_id]
    if config_id is not None:
        items = [b for b in items if b["bus_configuration_id"] == config_id]
    if option_order_id is not None:
        items = [b for b in items if b.get("option_order_id") == option_order_id]
    if status is not None:
        items = [b for b in items if b["status"] == status]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(b) for b in window], limit, offset, total)


@bp.get("/api/bus-units/<busUnitId>")
def get_bus(busUnitId):
    require_roles(
        "PlatformAdmin", "ProductionPlanner", "ProcurementOfficer",
        "AgencyInspector", "Auditor", "WarrantyAdmin", "ComplianceOfficer",
    )
    b = get_bus_or_404(busUnitId)
    from services.core import lazy_bus_check
    lazy_bus_check(b)
    return success_obj(public(b))


@bp.post("/api/bus-units/<busUnitId>/engineer")
def engineer_bus(busUnitId):
    require_roles("ConfigEngineer")
    b = get_bus_or_404(busUnitId)
    if b["status"] != "ORDERED":
        raise err_invalid_state("Bus is not ORDERED")
    cfg = DB.configurations.get(b["bus_configuration_id"])
    if cfg is None:
        raise err_not_found("BusConfiguration not found")
    contract = DB.contracts.get(b["contract_id"])
    if contract is None:
        raise err_not_found("Contract not found")
    # safety gate (priority 6) before referential (priority 10)
    agency = DB.agencies.get(contract["agency_id"])
    if agency is not None and agency.get("federally_funded", True):
        if "WHEELCHAIR_LIFT" not in (cfg["accessibility_features"] or []):
            raise err_accessibility()
    if cfg["status"] != "FROZEN":
        raise err_referential("BusConfiguration is not FROZEN")
    if contract["status"] != "ACTIVE":
        raise err_invalid_state("Contract is not ACTIVE")
    b["status"] = "ENGINEERED"
    touch(b)
    kit = {
        "bus_unit_id": b["id"],
        "component_ids": list(cfg["component_ids"] or []),
        "completeness_pct": 0.0,
        "status": "STAGING",
    }
    stamp_new(kit)
    kit["completeness_pct"] = kit_completeness_pct(kit)
    if kit["completeness_pct"] == 100.0:
        kit["status"] = "COMPLETE"
    DB.kits[kit["id"]] = kit
    return success_obj(public(b))


@bp.post("/api/bus-units/<busUnitId>/submit-plant-inspection")
def submit_plant_inspection(busUnitId):
    require_roles("ProductionPlanner")
    b = get_bus_or_404(busUnitId)
    if b["status"] != "BUILT":
        raise err_invalid_state("Bus is not BUILT")
    contract = DB.contracts.get(b["contract_id"])
    agency = DB.agencies.get(contract["agency_id"]) if contract else None
    cert = None
    for c in DB.certificates.values():
        if c["bus_unit_id"] == b["id"] and c["status"] == "ISSUED":
            cert = c
            break
    if cert is None:
        raise err_certificate_missing()
    if agency is not None and agency.get("federally_funded", True):
        if cert["domestic_content_pct"] < cert["threshold_pct"]:
            raise err_domestic_threshold()
    b["status"] = "PLANT_INSPECTION"
    touch(b)
    return success_obj(public(b))


@bp.post("/api/bus-units/<busUnitId>/deliver")
def deliver_bus(busUnitId):
    require_roles("ProductionPlanner")
    b = get_bus_or_404(busUnitId)
    if b["status"] != "IN_TRANSIT":
        raise err_invalid_state("Bus is not IN_TRANSIT")
    now = DB.clock.now()
    b["status"] = "DELIVERED"
    b["delivered_at"] = _fmt_logical(now)
    b["acceptance_deadline"] = _fmt_logical(now + timedelta(days=30))
    touch(b)
    return success_obj(public(b))


@bp.post("/api/bus-units/<busUnitId>/accept")
def accept_bus(busUnitId):
    require_roles("AgencyInspector")
    b = get_bus_or_404(busUnitId)
    if b["status"] != "DELIVERED":
        raise err_invalid_state("Bus is not DELIVERED")
    b["status"] = "ACCEPTED"
    if b["payment_status"] == "UNPAID":
        b["payment_status"] = "INVOICED"
    touch(b)
    contract = DB.contracts.get(b["contract_id"])
    if contract is not None:
        recompute_zev(contract["agency_id"])
    return success_obj(public(b))


@bp.post("/api/bus-units/<busUnitId>/record-payment")
def record_payment(busUnitId):
    require_roles("ProcurementOfficer")
    b = get_bus_or_404(busUnitId)
    if b["payment_status"] != "INVOICED":
        raise err_invalid_state("Bus payment_status is not INVOICED")
    b["payment_status"] = "PAID"
    touch(b)
    return success_obj(public(b))
