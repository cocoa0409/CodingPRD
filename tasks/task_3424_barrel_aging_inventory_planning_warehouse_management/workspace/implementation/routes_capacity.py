"""Routes: capacity expansion projects, rickhouses, warehouse slots."""

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from flask import Blueprint

import calc
import envelope
import serializers
import store
import validation as v

bp = Blueprint("capacity", __name__)


@bp.route("/barrel-aging/expansion-projects", methods=["POST"])
def create_project():
    _, role = v.authenticate()
    v.require_role(role, ["DistilleryPlanner"])
    body = v.get_body()
    v.check_allowed_fields(body, {
        "name", "region_code", "floors", "rows_per_floor", "positions_per_row",
        "construction_lag_months", "planned_annual_distillation_liters",
    })
    name = v.req_str(body, "name")
    region_code = v.req_str(body, "region_code")
    floors = v.req_int(body, "floors", min_v=1)
    rows = v.req_int(body, "rows_per_floor", min_v=1)
    positions = v.req_int(body, "positions_per_row", min_v=1)
    lag = v.req_int(body, "construction_lag_months", min_v=1)
    planned = v.req_int(body, "planned_annual_distillation_liters", min_v=0)

    now = store.now()
    project = {
        "id": store.new_id(),
        "name": name,
        "region_code": region_code,
        "floors": floors,
        "rows_per_floor": rows,
        "positions_per_row": positions,
        "construction_lag_months": lag,
        "planned_annual_distillation_liters": planned,
        "state": "PROPOSED",
        "approved_at": None,
        "commissioned_at": None,
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.projects[project["id"]] = project
    return envelope.ok_object(serializers.serialize_project(project), status=201)


@bp.route("/barrel-aging/expansion-projects/<pid>", methods=["GET"])
def get_project(pid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    project = store.projects.get(pid)
    if project is None:
        raise envelope.err_not_found("Expansion project not found")
    return envelope.ok_object(serializers.serialize_project(project))


@bp.route("/barrel-aging/expansion-projects/<pid>/approve", methods=["POST"])
def approve_project(pid):
    _, role = v.authenticate()
    v.require_role(role, ["OperationsDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    project = store.projects.get(pid)
    if project is None:
        raise envelope.err_not_found("Expansion project not found")
    if project["state"] != "PROPOSED":
        raise envelope.err_invalid_state("Project is not PROPOSED")

    now = store.now()
    project["state"] = "APPROVED"
    project["approved_at"] = now
    project["updated_at"] = now
    project["version"] += 1

    # CASCADE link 1: create the PLANNED rickhouse, copying the spec.
    rickhouse = {
        "id": store.new_id(),
        "expansion_project_id": project["id"],
        "name": project["name"],
        "region_code": project["region_code"],
        "floors": project["floors"],
        "rows_per_floor": project["rows_per_floor"],
        "positions_per_row": project["positions_per_row"],
        "created_at": now,
        "updated_at": now,
        "version": 1,
        "_seq": store.next_seq(),
    }
    store.rickhouses[rickhouse["id"]] = rickhouse
    return envelope.ok_object(serializers.serialize_project(project))


@bp.route("/barrel-aging/expansion-projects/<pid>/commission", methods=["POST"])
def commission_project(pid):
    _, role = v.authenticate()
    v.require_role(role, ["OperationsDirector"])
    body = v.get_body()
    v.check_allowed_fields(body, set())
    project = store.projects.get(pid)
    if project is None:
        raise envelope.err_not_found("Expansion project not found")
    if project["state"] != "APPROVED":
        raise envelope.err_invalid_state("Project is not APPROVED")
    now = store.now()
    ready_at = project["approved_at"] + timedelta(days=30 * project["construction_lag_months"])
    if now < ready_at:
        raise envelope.err_construction_lag()

    project["state"] = "COMMISSIONED"
    project["commissioned_at"] = now
    project["updated_at"] = now
    project["version"] += 1

    # CASCADE links 2-4: activate the rickhouse and materialize the slot grid
    # in (floor_index, row_index, position_index) ascending order, 1-based.
    rickhouse = next(
        (r for r in store.rickhouses.values() if r["expansion_project_id"] == pid),
        None,
    )
    if rickhouse is not None:
        rickhouse["updated_at"] = now
        for floor in range(1, rickhouse["floors"] + 1):
            heat = (Decimal("1.0") + Decimal("0.05") * (floor - 1)).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            for row in range(1, rickhouse["rows_per_floor"] + 1):
                for pos in range(1, rickhouse["positions_per_row"] + 1):
                    slot = {
                        "id": store.new_id(),
                        "rickhouse_id": rickhouse["id"],
                        "floor_index": floor,
                        "row_index": row,
                        "position_index": pos,
                        "heat_factor": float(heat),
                        "created_at": now,
                        "updated_at": now,
                        "version": 1,
                        "_seq": store.next_seq(),
                    }
                    store.slots[slot["id"]] = slot
    return envelope.ok_object(serializers.serialize_project(project))


@bp.route("/barrel-aging/rickhouses/<rid>", methods=["GET"])
def get_rickhouse(rid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    rickhouse = store.rickhouses.get(rid)
    if rickhouse is None:
        raise envelope.err_not_found("Rickhouse not found")
    return envelope.ok_object(serializers.serialize_rickhouse(rickhouse))


@bp.route("/barrel-aging/rickhouses", methods=["GET"])
def list_rickhouses():
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    limit, offset = v.parse_pagination()
    project_filter = None
    posture_filter = None
    from flask import request
    if "expansion_project_id" in request.args:
        project_filter = request.args.get("expansion_project_id")
    if "posture" in request.args:
        posture_filter = request.args.get("posture")
    items = []
    for r in sorted(store.rickhouses.values(), key=lambda r: (r["created_at"], r["_seq"])):
        if project_filter is not None and r["expansion_project_id"] != project_filter:
            continue
        if posture_filter is not None and calc.posture(r) != posture_filter:
            continue
        items.append(serializers.serialize_rickhouse(r))
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/rickhouses/<rid>/slots", methods=["GET"])
def list_slots(rid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    rickhouse = store.rickhouses.get(rid)
    if rickhouse is None:
        raise envelope.err_not_found("Rickhouse not found")
    limit, offset = v.parse_pagination()
    slots = [s for s in store.slots.values() if s["rickhouse_id"] == rid]
    slots.sort(key=lambda s: (s["floor_index"], s["row_index"], s["position_index"]))
    items = [serializers.serialize_slot(s) for s in slots]
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)


@bp.route("/barrel-aging/warehouse-slots/<sid>", methods=["GET"])
def get_slot(sid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    slot = store.slots.get(sid)
    if slot is None:
        raise envelope.err_not_found("Warehouse slot not found")
    return envelope.ok_object(serializers.serialize_slot(slot))


@bp.route("/barrel-aging/warehouse-slots/<sid>/occupancies", methods=["GET"])
def list_slot_occupancies(sid):
    _, role = v.authenticate()
    v.require_role(role, v.ALL_ROLES)
    slot = store.slots.get(sid)
    if slot is None:
        raise envelope.err_not_found("Warehouse slot not found")
    limit, offset = v.parse_pagination()
    from flask import request
    status_filter = request.args.get("status")
    occs = calc.slot_occupancies(sid)
    occs.sort(key=lambda o: (o["start_at"], o["_seq"]))
    items = []
    for o in occs:
        ser = serializers.serialize_occupancy(o)
        if status_filter is not None and ser["status"] != status_filter:
            continue
        items.append(ser)
    page, total = v.paginate(items, limit, offset)
    return envelope.ok_list(page, limit, offset, total)
