"""Routes: production slots and parts kits."""
from flask import Blueprint, request
from db import DB, stamp_new, touch, _parse_iso
from errors import (
    err_not_found, err_invalid_request, err_invalid_state, err_schedule_conflict,
    err_kit_incomplete, err_deadline, err_referential,
)
from middleware import require_roles, get_body
from response import success_obj, success_list, public, parse_pagination, paginate
from services.core import kit_completeness_pct, recompute_kit, update_stock_status

bp = Blueprint("production", __name__)

LINE_IDS = {"LINE_A", "LINE_B"}


def get_slot_or_404(sid):
    s = DB.slots.get(sid)
    if s is None:
        raise err_not_found("ProductionSlot not found")
    return s


def _overlaps(a_start, a_end, b_start, b_end):
    """Half-open interval overlap: [s,e) vs [s2,e2)."""
    return a_start < b_end and b_start < a_end


def _conflict_on_line(line_id, start, end, exclude_slot_id=None):
    for s in DB.slots.values():
        if s["line_id"] != line_id:
            continue
        if s["status"] not in ("OPEN", "ASSIGNED"):
            continue
        if exclude_slot_id is not None and s["id"] == exclude_slot_id:
            continue
        if _overlaps(start, end, _parse_iso(s["start_ts"]), _parse_iso(s["end_ts"])):
            return True
    return False


@bp.post("/api/production-slots")
def create_slot():
    require_roles("ProductionPlanner")
    body = get_body()
    line_id = body.get("line_id")
    start_ts = body.get("start_ts")
    end_ts = body.get("end_ts")
    if line_id is None:
        raise err_invalid_request("Missing required field: line_id")
    if line_id not in LINE_IDS:
        raise err_invalid_request("Unknown line_id")
    if start_ts is None:
        raise err_invalid_request("Missing required field: start_ts")
    if end_ts is None:
        raise err_invalid_request("Missing required field: end_ts")
    try:
        sdt = _parse_iso(start_ts)
        edt = _parse_iso(end_ts)
    except Exception:
        raise err_invalid_request("Malformed start_ts or end_ts")
    if not sdt < edt:
        raise err_invalid_request("start_ts must be before end_ts")
    if _conflict_on_line(line_id, sdt, edt):
        raise err_schedule_conflict("Slot interval overlaps another slot on the same line")
    rec = {
        "line_id": line_id,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "bus_unit_id": None,
        "kit_status": "NOT_KITTED",
        "status": "OPEN",
    }
    stamp_new(rec)
    DB.slots[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/production-slots")
def list_slots():
    require_roles("PlatformAdmin", "ProductionPlanner")
    limit, offset = parse_pagination(request.args)
    line_id = request.args.get("line_id")
    status = request.args.get("status")
    bus_unit_id = request.args.get("bus_unit_id")
    items = list(DB.slots.values())
    if line_id is not None:
        items = [s for s in items if s["line_id"] == line_id]
    if status is not None:
        items = [s for s in items if s["status"] == status]
    if bus_unit_id is not None:
        items = [s for s in items if s.get("bus_unit_id") == bus_unit_id]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(s) for s in window], limit, offset, total)


@bp.get("/api/production-slots/<productionSlotId>")
def get_slot(productionSlotId):
    require_roles("PlatformAdmin", "ProductionPlanner")
    s = get_slot_or_404(productionSlotId)
    return success_obj(public(s))


@bp.post("/api/production-slots/<productionSlotId>/assign")
def assign_slot(productionSlotId):
    require_roles("ProductionPlanner")
    s = get_slot_or_404(productionSlotId)
    if s["status"] != "OPEN":
        raise err_invalid_state("Slot is not OPEN")
    body = get_body()
    bus_unit_id = body.get("bus_unit_id")
    if bus_unit_id is None:
        raise err_invalid_request("Missing required field: bus_unit_id")
    bus = DB.buses.get(bus_unit_id)
    if bus is None:
        raise err_not_found("BusUnit not found")
    if bus["status"] != "ENGINEERED":
        raise err_invalid_state("BusUnit is not ENGINEERED")
    sdt = _parse_iso(s["start_ts"])
    edt = _parse_iso(s["end_ts"])
    if _conflict_on_line(s["line_id"], sdt, edt, exclude_slot_id=s["id"]):
        raise err_schedule_conflict("Slot interval overlaps another slot on the same line")
    s["bus_unit_id"] = bus_unit_id
    s["status"] = "ASSIGNED"
    kit = None
    for k in DB.kits.values():
        if k["bus_unit_id"] == bus_unit_id:
            kit = k
            break
    if kit is not None and kit["status"] == "COMPLETE" and s["kit_status"] == "NOT_KITTED":
        s["kit_status"] = "KITTED"
    touch(s)
    return success_obj(public(s))


@bp.post("/api/production-slots/<productionSlotId>/start-production")
def start_production(productionSlotId):
    require_roles("ProductionPlanner")
    s = get_slot_or_404(productionSlotId)
    if s["status"] != "ASSIGNED":
        raise err_invalid_state("Slot is not ASSIGNED")
    if s["kit_status"] != "KITTED":
        raise err_kit_incomplete()
    now = DB.clock.now()
    if now < _parse_iso(s["start_ts"]):
        raise err_deadline("Current logical time is before slot start_ts")
    bus = DB.buses.get(s["bus_unit_id"])
    if bus is None:
        raise err_not_found("BusUnit not found")
    kit = None
    for k in DB.kits.values():
        if k["bus_unit_id"] == bus["id"]:
            kit = k
            break
    s["status"] = "IN_PRODUCTION"
    touch(s)
    bus["status"] = "IN_PRODUCTION"
    touch(bus)
    if kit is not None and kit["status"] == "COMPLETE":
        kit["status"] = "CONSUMED"
        touch(kit)
        contract = DB.contracts.get(bus["contract_id"])
        agency_id = contract["agency_id"] if contract else None
        if agency_id is not None:
            for cid in kit["component_ids"]:
                for stock in DB.stocks.values():
                    if stock["agency_id"] == agency_id and stock["component_id"] == cid:
                        stock["quantity"] -= 1
                        update_stock_status(stock)
                        if stock.get("updated_at") is None:
                            touch(stock)
                        else:
                            # update_stock_status only touches on status flip; ensure quantity mutation is stamped.
                            pass
                        break
    return success_obj(public(s))


@bp.post("/api/production-slots/<productionSlotId>/complete-production")
def complete_production(productionSlotId):
    require_roles("ProductionPlanner")
    s = get_slot_or_404(productionSlotId)
    if s["status"] != "IN_PRODUCTION":
        raise err_invalid_state("Slot is not IN_PRODUCTION")
    bus = DB.buses.get(s.get("bus_unit_id"))
    s["status"] = "DONE"
    touch(s)
    if bus is not None and bus["status"] == "IN_PRODUCTION":
        bus["status"] = "BUILT"
        touch(bus)
    return success_obj(public(s))


@bp.post("/api/production-slots/<productionSlotId>/cancel")
def cancel_slot(productionSlotId):
    require_roles("ProductionPlanner")
    s = get_slot_or_404(productionSlotId)
    if s["status"] == "OPEN":
        s["status"] = "CANCELLED"
        touch(s)
        return success_obj(public(s))
    if s["status"] == "ASSIGNED":
        s["status"] = "CANCELLED"
        s["bus_unit_id"] = None
        touch(s)
        return success_obj(public(s))
    raise err_invalid_state("Slot cannot be cancelled from its current state")


@bp.post("/api/parts-kits")
def create_kit():
    require_roles("ProductionPlanner")
    body = get_body()
    bus_unit_id = body.get("bus_unit_id")
    component_ids = body.get("component_ids")
    if bus_unit_id is None:
        raise err_invalid_request("Missing required field: bus_unit_id")
    if component_ids is None:
        raise err_invalid_request("Missing required field: component_ids")
    if not isinstance(component_ids, list):
        raise err_invalid_request("component_ids must be an array")
    bus = DB.buses.get(bus_unit_id)
    if bus is None:
        raise err_not_found("BusUnit not found")
    for cid in component_ids:
        if cid not in DB.components:
            raise err_referential(f"Unknown component id: {cid}")
    rec = {
        "bus_unit_id": bus_unit_id,
        "component_ids": list(component_ids),
        "completeness_pct": 0.0,
        "status": "STAGING",
    }
    stamp_new(rec)
    rec["completeness_pct"] = kit_completeness_pct(rec)
    if rec["completeness_pct"] == 100.0:
        rec["status"] = "COMPLETE"
    DB.kits[rec["id"]] = rec
    return success_obj(public(rec), 201)


@bp.get("/api/parts-kits/<partsKitId>")
def get_kit(partsKitId):
    require_roles("PlatformAdmin", "ProductionPlanner", "ComplianceOfficer")
    k = DB.kits.get(partsKitId)
    if k is None:
        raise err_not_found("PartsKit not found")
    return success_obj(public(k))


@bp.get("/api/bus-units/<busUnitId>/parts-kits")
def bus_kits(busUnitId):
    require_roles("PlatformAdmin", "ProductionPlanner", "ComplianceOfficer")
    if busUnitId not in DB.buses:
        raise err_not_found("BusUnit not found")
    limit, offset = parse_pagination(request.args)
    items = [k for k in DB.kits.values() if k["bus_unit_id"] == busUnitId]
    items.sort(key=lambda r: r["_seq"])
    window, total = paginate(items, limit, offset)
    return success_list([public(k) for k in window], limit, offset, total)
