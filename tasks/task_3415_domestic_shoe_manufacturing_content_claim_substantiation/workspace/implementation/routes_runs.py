"""ProductionRun creation and reads (PRD 3.5). Lifecycle transitions live in
routes_runs_lifecycle.py; content reports in routes_reports.py."""
from flask import Blueprint, request

import constants
import serializers
from errors import ApiError
from middleware import require_roles
from response import ok_obj, list_response
from state import DB, base_fields, sorted_items
from validation import body, req_str, req_enum, req_int, req_date, req_iso_week

bp = Blueprint("runs", __name__)


def get_run(rid):
    r = DB["runs"].get(rid)
    if r is None:
        raise ApiError("ERR_RUN_NOT_FOUND", "production run id does not resolve")
    return r


def find_allocation(factory_id, iso_week):
    for a in DB["allocations"].values():
        if a["factory_id"] == factory_id and a["iso_week"] == iso_week:
            return a
    return None


@bp.post("/footwear/production-runs")
@require_roles("ProductionPlanner")
def create_run(_uid, _role):
    b = body()
    # Family 4 (existence) precedes family 5 (schema).
    mid = b.get("model_id")
    if mid is not None and mid not in DB["models"]:
        raise ApiError("ERR_MODEL_NOT_FOUND", "model id does not resolve")
    fid = b.get("factory_id")
    if fid is not None and fid not in DB["factories"]:
        raise ApiError("ERR_FACTORY_NOT_FOUND", "factory id does not resolve")
    mid = req_str(b, "model_id")
    fid = req_str(b, "factory_id")
    rtype = req_enum(b, "run_type", constants.RUN_TYPES)
    units = req_int(b, "planned_units", min_v=1)
    line_index = req_int(b, "line_index")
    start_day = req_date(b, "start_day")
    end_day = req_date(b, "end_day")
    week = req_iso_week(b, "iso_week")
    if end_day <= start_day:
        raise ApiError("ERR_INVALID_REQUEST", "end_day must be strictly after start_day")
    model = DB["models"][mid]
    factory = DB["factories"][fid]
    if not 1 <= line_index <= factory["line_count"]:
        raise ApiError(
            "ERR_INVALID_REQUEST",
            "line_index must lie between 1 and the factory's line_count",
        )
    # Family 7 (regulatory), in the pinned order: government clearance first,
    # then production-policy direction.
    if rtype == "GOVERNMENT" and not (
        factory["location_type"] == "DOMESTIC" and factory["government_cleared"]
    ):
        raise ApiError(
            "ERR_GOV_RUN_REQUIRES_CLEARED_DOMESTIC_FACTORY",
            "GOVERNMENT runs may be created only on DOMESTIC government-cleared factories",
        )
    if model["production_policy"] == "DOMESTIC_ONLY" and factory["location_type"] == "OVERSEAS":
        raise ApiError(
            "ERR_POLICY_FORBIDS_IMPORT",
            "a DOMESTIC_ONLY model may not be produced at an OVERSEAS factory",
        )
    if model["production_policy"] == "IMPORT_ONLY" and factory["location_type"] == "DOMESTIC":
        raise ApiError(
            "ERR_POLICY_FORBIDS_DOMESTIC",
            "an IMPORT_ONLY model may not be produced at a DOMESTIC factory",
        )
    r = base_fields()
    r.update({
        "model_id": mid,
        "factory_id": fid,
        "run_type": rtype,
        "planned_units": units,
        "line_index": line_index,
        "start_day": start_day,
        "end_day": end_day,
        "iso_week": week,
        "actual_stitching_minutes": None,
        "actual_lasting_minutes": None,
        "actual_assembly_minutes": None,
        "consumed_lots": [],
        "certified_unit_cost_cents": None,
        "status": "PLANNED",
    })
    DB["runs"][r["id"]] = r
    return ok_obj(serializers.pub(r), 201)


@bp.get("/footwear/production-runs")
@require_roles(*constants.ALL_ROLES)
def list_runs(_uid, _role):
    items = sorted_items(DB["runs"])
    mid = request.args.get("model_id")
    fid = request.args.get("factory_id")
    status = request.args.get("status")
    week = request.args.get("iso_week")
    if mid is not None:
        items = [r for r in items if r["model_id"] == mid]
    if fid is not None:
        items = [r for r in items if r["factory_id"] == fid]
    if status is not None:
        items = [r for r in items if r["status"] == status]
    if week is not None:
        items = [r for r in items if r["iso_week"] == week]
    return list_response([serializers.pub(r) for r in items])


@bp.get("/footwear/production-runs/<rid>")
@require_roles(*constants.ALL_ROLES)
def get_one_run(rid, _uid, _role):
    return ok_obj(serializers.pub(get_run(rid)))
